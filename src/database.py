"""Database connection and models for the application evaluation system."""

import pyodbc
from typing import Optional, List, Dict, Any
from datetime import datetime
from .config import config


class Database:
    """Database connection and operations manager."""
    
    def __init__(self):
        self.connection_string = self._build_connection_string()
        self.connection = None
    
    def _build_connection_string(self) -> str:
        """Build Azure SQL connection string using configuration from Key Vault."""
        server = config.sql_server
        database = config.sql_database
        
        if not server or not database:
            raise ValueError(
                "SQL Server and Database must be configured in Key Vault or environment variables"
            )
        
        # Using Azure AD authentication
        connection_string = f"""
            Driver={{ODBC Driver 18 for SQL Server}};
            Server=tcp:{server},1433;
            Database={database};
            Authentication=ActiveDirectoryInteractive;
            Encrypt=yes;
            TrustServerCertificate=no;
        """
        return connection_string
    
    def connect(self):
        """Establish database connection."""
        if not self.connection:
            self.connection = pyodbc.connect(self.connection_string)
        return self.connection
    
    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results."""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
        finally:
            cursor.close()
    
    def execute_non_query(self, query: str, params: tuple = None) -> int:
        """Execute INSERT, UPDATE, or DELETE and return affected rows."""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
    
    def execute_scalar(self, query: str, params: tuple = None) -> Any:
        """Execute a query and return a single value."""
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            result = cursor.fetchone()
            return result[0] if result else None
        finally:
            cursor.close()
    
    def create_application(self, applicant_name: str, email: str, application_text: str,
                          file_name: str, file_type: str, is_training: bool = False,
                          was_selected: Optional[bool] = None) -> int:
        """Create a new application record."""
        query = """
            INSERT INTO Applications 
            (ApplicantName, Email, ApplicationText, OriginalFileName, FileType, 
             IsTrainingExample, WasSelected, Status)
            OUTPUT INSERTED.ApplicationID
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending')
        """
        return self.execute_scalar(query, (applicant_name, email, application_text,
                                           file_name, file_type, is_training, was_selected))
    
    def get_application(self, application_id: int) -> Optional[Dict[str, Any]]:
        """Get application by ID."""
        query = "SELECT * FROM Applications WHERE ApplicationID = ?"
        results = self.execute_query(query, (application_id,))
        return results[0] if results else None
    
    def get_training_examples(self) -> List[Dict[str, Any]]:
        """Get all training examples."""
        query = """
            SELECT * FROM Applications 
            WHERE IsTrainingExample = 1 
            ORDER BY UploadedDate DESC
        """
        return self.execute_query(query)
    
    def save_evaluation(self, application_id: int, agent_name: str, overall_score: float,
                       technical_score: float, communication_score: float,
                       experience_score: float, cultural_fit_score: float,
                       strengths: str, weaknesses: str, recommendation: str,
                       detailed_analysis: str, comparison: str, model_used: str,
                       processing_time_ms: int) -> int:
        """Save an AI evaluation."""
        query = """
            INSERT INTO AIEvaluations
            (ApplicationID, AgentName, OverallScore, TechnicalSkillsScore, 
             CommunicationScore, ExperienceScore, CulturalFitScore,
             Strengths, Weaknesses, Recommendation, DetailedAnalysis,
             ComparisonToExcellence, ModelUsed, ProcessingTimeMs)
            OUTPUT INSERTED.EvaluationID
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self.execute_scalar(query, (application_id, agent_name, overall_score,
                                           technical_score, communication_score,
                                           experience_score, cultural_fit_score,
                                           strengths, weaknesses, recommendation,
                                           detailed_analysis, comparison, model_used,
                                           processing_time_ms))
    
    def get_pending_applications(self) -> List[Dict[str, Any]]:
        """Get all pending applications."""
        query = """
            SELECT * FROM Applications 
            WHERE Status = 'Pending' AND IsTrainingExample = 0
            ORDER BY UploadedDate DESC
        """
        return self.execute_query(query)
    
    def get_applications_with_evaluations(self) -> List[Dict[str, Any]]:
        """Get applications with their AI evaluations."""
        query = """
            SELECT 
                a.*,
                e.EvaluationID,
                e.OverallScore,
                e.Recommendation,
                e.Strengths,
                e.Weaknesses,
                e.EvaluationDate
            FROM Applications a
            LEFT JOIN AIEvaluations e ON a.ApplicationID = e.ApplicationID
            WHERE a.IsTrainingExample = 0
            ORDER BY a.UploadedDate DESC, e.EvaluationDate DESC
        """
        return self.execute_query(query)


# Global database instance
db = Database()
