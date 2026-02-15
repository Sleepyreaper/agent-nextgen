"""Database connection and models for the application evaluation system."""

from typing import Optional, List, Dict, Any
from datetime import datetime
import psycopg
from psycopg.rows import tuple_row
from .config import config


class Database:
    """Database connection and operations manager."""
    
    def __init__(self):
        self.connection_string = self._build_connection_string()
        self.connection = None
    
    def _build_connection_string(self) -> str:
        """Build PostgreSQL connection string using configuration from Key Vault."""
        if config.postgres_url:
            return config.postgres_url

        host = config.postgres_host
        port = config.postgres_port
        database = config.postgres_database
        username = config.postgres_username
        password = config.postgres_password

        if not host or not database:
            raise ValueError(
                "Postgres host and database must be configured in Key Vault or environment variables"
            )
        if not username or not password:
            raise ValueError(
                "Postgres username and password must be configured in Key Vault or environment variables"
            )

        # For Azure Container Instances, SSL is not supported, use prefer instead of require
        return (
            f"host={host} port={port} dbname={database} user={username} "
            f"password={password} sslmode=prefer"
        )
    
    def connect(self):
        """Establish database connection."""
        if not self.connection:
            self.connection = psycopg.connect(self.connection_string, row_factory=tuple_row)
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending')
            RETURNING ApplicationID
        """
        return self.execute_scalar(
            query,
            (applicant_name, email, application_text, file_name, file_type, is_training, was_selected)
        )
    
    def get_application(self, application_id: int) -> Optional[Dict[str, Any]]:
        """Get application by ID."""
        query = "SELECT * FROM Applications WHERE ApplicationID = %s"
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING EvaluationID
        """
        return self.execute_scalar(
            query,
            (
                application_id, agent_name, overall_score,
                technical_score, communication_score,
                experience_score, cultural_fit_score,
                strengths, weaknesses, recommendation,
                detailed_analysis, comparison, model_used,
                processing_time_ms
            )
        )
    
    def get_pending_applications(self) -> List[Dict[str, Any]]:
        """Get all pending applications."""
        query = """
            SELECT * FROM Applications 
            WHERE Status = 'Pending' AND IsTrainingExample = FALSE
            ORDER BY UploadedDate DESC
        """
        return self.execute_query(query)
    
    def save_school_context(
        self,
        application_id: int,
        school_name: str,
        school_id: Optional[int] = None,
        program_access_score: float = 0,
        program_participation_score: float = 0,
        relative_advantage_score: float = 0,
        ap_courses_available: int = 0,
        ap_courses_taken: int = 0,
        ib_courses_available: int = 0,
        ib_courses_taken: int = 0,
        honors_courses_taken: int = 0,
        stem_programs_available: int = 0,
        stem_programs_accessed: int = 0,
        ses_level: str = '',
        median_household_income: Optional[float] = None,
        free_lunch_pct: Optional[float] = None,
        peers_using_programs_pct: Optional[float] = None,
        context_notes: str = ''
    ) -> int:
        """Save student school context analysis."""
        query = """
            INSERT INTO StudentSchoolContext
            (ApplicationID, SchoolID, SchoolName, ProgramAccessScore,
             ProgramParticipationScore, RelativeAdvantageScore,
             APCoursesAvailable, APCoursesTaken, IBCoursesAvailable, IBCoursesTaken,
             HonorsCoursesTaken, STEMProgramsAvailable, STEMProgramsAccessed,
             SchoolSESLevel, MedianHouseholdIncome, FreeLunchPct,
             PercentageOfPeersUsingPrograms, ComparisonNotes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING ContextID
        """
        return self.execute_scalar(query, (
            application_id, school_id, school_name,
            program_access_score, program_participation_score, relative_advantage_score,
            ap_courses_available, ap_courses_taken, ib_courses_available, ib_courses_taken,
            honors_courses_taken, stem_programs_available, stem_programs_accessed,
            ses_level, median_household_income, free_lunch_pct,
            peers_using_programs_pct, context_notes
        ))

    def save_agent_audit(
        self,
        application_id: int,
        agent_name: str,
        source_file_name: Optional[str] = None
    ) -> int:
        """Save an audit log entry for an agent write."""
        query = """
            INSERT INTO AgentAuditLogs
            (ApplicationID, AgentName, SourceFileName)
            VALUES (%s, %s, %s)
            RETURNING AuditID
        """
        return self.execute_scalar(query, (application_id, agent_name, source_file_name))

    def save_tiana_application(
        self,
        application_id: int,
        agent_name: str,
        essay_summary: Optional[str],
        recommendation_texts: Optional[str],
        readiness_score: Optional[float],
        confidence: Optional[str],
        parsed_json: str
    ) -> int:
        """Save Tiana application parsing output."""
        query = """
            INSERT INTO TianaApplications
            (ApplicationID, AgentName, EssaySummary, RecommendationTexts, ReadinessScore, Confidence, ParsedJson)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING TianaApplicationID
        """
        return self.execute_scalar(query, (
            application_id,
            agent_name,
            essay_summary,
            recommendation_texts,
            readiness_score,
            confidence,
            parsed_json
        ))

    def save_mulan_recommendation(
        self,
        application_id: int,
        agent_name: str,
        recommender_name: Optional[str],
        recommender_role: Optional[str],
        endorsement_strength: Optional[float],
        specificity_score: Optional[float],
        summary: Optional[str],
        raw_text: Optional[str],
        parsed_json: str
    ) -> int:
        """Save Mulan recommendation parsing output."""
        query = """
            INSERT INTO MulanRecommendations
            (ApplicationID, AgentName, RecommenderName, RecommenderRole,
             EndorsementStrength, SpecificityScore, Summary, RawText, ParsedJson)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING MulanRecommendationID
        """
        return self.execute_scalar(query, (
            application_id,
            agent_name,
            recommender_name,
            recommender_role,
            endorsement_strength,
            specificity_score,
            summary,
            raw_text,
            parsed_json
        ))

    def save_merlin_evaluation(
        self,
        application_id: int,
        agent_name: str,
        overall_score: Optional[float],
        recommendation: Optional[str],
        rationale: Optional[str],
        confidence: Optional[str],
        parsed_json: str
    ) -> int:
        """Save Merlin final evaluation output."""
        query = """
            INSERT INTO MerlinEvaluations
            (ApplicationID, AgentName, OverallScore, Recommendation, Rationale, Confidence, ParsedJson)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING MerlinEvaluationID
        """
        return self.execute_scalar(query, (
            application_id,
            agent_name,
            overall_score,
            recommendation,
            rationale,
            confidence,
            parsed_json
        ))
    
    def get_student_school_context(
        self,
        application_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get school context for a student."""
        query = "SELECT * FROM StudentSchoolContext WHERE ApplicationID = %s"
        results = self.execute_query(query, (application_id,))
        return results[0] if results else None
    
    def get_applications_with_evaluations(self) -> List[Dict[str, Any]]:
        """Get all applications (non-training examples)."""
        query = """
            SELECT * FROM Applications 
            WHERE IsTrainingExample = FALSE
            ORDER BY UploadedDate DESC
        """
        return self.execute_query(query)


# Global database instance
db = Database()
