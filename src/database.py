"""Database connection and models for the application evaluation system - PostgreSQL."""

from typing import Optional, List, Dict, Any
from datetime import datetime
import psycopg
from .config import config
import json
import time
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse


class Database:
    """Database connection and operations manager for PostgreSQL."""
    
    def __init__(self):
        self.connection_params = None
        self.connection = None
        self._params_validated = False
        self._table_columns_cache = {}
        self._table_names_cache = None
        self._training_example_column = None
        self._test_data_column = None
        self._schema_probe_failed_at = None
        self._schema_probe_cooldown_seconds = 30

    def _schema_probe_allowed(self) -> bool:
        if self._schema_probe_failed_at is None:
            return True
        return (time.time() - self._schema_probe_failed_at) >= self._schema_probe_cooldown_seconds

    def _get_table_columns(self, table_name: str) -> set:
        """Return a cached set of column names for a table (lowercase)."""
        table_key = table_name.lower()
        if table_key in self._table_columns_cache:
            return self._table_columns_cache[table_key]

        if not self._schema_probe_allowed():
            return set()

        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                """,
                (table_key,)
            )
            columns = {row[0].lower() for row in cursor.fetchall()}
            cursor.close()
        except Exception:
            columns = set()
            self._schema_probe_failed_at = time.time()

        self._table_columns_cache[table_key] = columns
        return columns

    def _get_table_names(self) -> set:
        if self._table_names_cache is not None:
            return self._table_names_cache

        if not self._schema_probe_allowed():
            return set()

        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            )
            names = {row[0].lower() for row in cursor.fetchall()}
            cursor.close()
        except Exception:
            names = set()
            self._schema_probe_failed_at = time.time()

        self._table_names_cache = names
        return names

    def _resolve_table_name(self, candidates: List[str]) -> str:
        names = self._get_table_names()
        for candidate in candidates:
            if candidate.lower() in names:
                return candidate.lower()
        return candidates[0].lower() if candidates else None

    def has_table(self, table_name: str) -> bool:
        if not table_name:
            return False
        return table_name.lower() in self._get_table_names()

    def get_table_name(self, logical_name: str) -> Optional[str]:
        table_map = {
            "applications": ["applications", "Applications"],
            "merlin_evaluations": ["merlin_evaluations", "merlinevaluations", "MerlinEvaluations"],
            "tiana_applications": ["tiana_applications", "tianaapplications", "TianaApplications"],
            "mulan_recommendations": ["mulan_recommendations", "mulanrecommendations", "MulanRecommendations"],
            "student_school_context": ["student_school_context", "studentschoolcontext", "StudentSchoolContext"],
            "schools": ["schools", "Schools"],
            "aurora_evaluations": ["aurora_evaluations", "auroraevaluations", "AuroraEvaluations"],
            "ai_evaluations": ["ai_evaluations", "aievaluations", "AIEvaluations"],
            "agent_audit_logs": ["agent_audit_logs", "agentauditlogs", "AgentAuditLogs"],
            "test_submissions": ["test_submissions", "testsubmissions", "TestSubmissions"],
            "grade_records": ["grade_records", "graderecords", "GradeRecords", "grades", "Grades"],
            "rapunzel_grades": ["rapunzel_grades", "rapunzelgrades", "RapunzelGrades", "grade_records", "graderecords", "grades", "Grades"],
        }
        candidates = table_map.get(logical_name, [logical_name])
        return self._resolve_table_name(candidates)

    def resolve_table_column(self, table_logical: str, candidates: List[str]) -> Optional[str]:
        table_name = self.get_table_name(table_logical)
        return self._resolve_column(table_name, candidates)

    def get_applications_column(self, logical: str) -> Optional[str]:
        column_map = {
            "application_id": ["application_id", "applicationid"],
            "applicant_name": ["applicant_name", "applicantname"],
            "email": ["email"],
            "status": ["status"],
            "uploaded_date": ["uploaded_date", "uploadeddate"],
            "was_selected": ["was_selected", "wasselected"],
            "missing_fields": ["missing_fields", "missingfields"],
            "application_text": ["application_text", "applicationtext"],
            "transcript_text": ["transcript_text", "transcripttext"],
            "recommendation_text": ["recommendation_text", "recommendationtext"],
            "student_id": ["student_id", "studentid"],
        }
        return self.resolve_table_column("applications", column_map.get(logical, [logical]))

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        if not column_name:
            return False
        return column_name.lower() in self._get_table_columns(table_name)

    def _resolve_column(self, table_name: str, candidates: List[str]) -> Optional[str]:
        columns = self._get_table_columns(table_name)
        for candidate in candidates:
            if candidate.lower() in columns:
                return candidate.lower()
        return candidates[0].lower() if candidates else None

    def get_training_example_column(self) -> Optional[str]:
        if not self._training_example_column:
            self._training_example_column = self._resolve_column(
                "applications",
                ["is_training_example", "istrainingexample"],
            )
        return self._training_example_column

    def get_test_data_column(self) -> Optional[str]:
        if not self._test_data_column:
            self._test_data_column = self._resolve_column(
                "applications",
                ["is_test_data", "istestdata"],
            )
        return self._test_data_column

    def has_applications_column(self, column_name: str) -> bool:
        return self._column_exists("applications", column_name)
    
    def _build_connection_params(self) -> Dict[str, Any]:
        """Build PostgreSQL connection parameters from config."""
        if self._params_validated and self.connection_params:
            return self.connection_params
            
        # Try to get connection parameters from config (Key Vault secrets)
        postgres_url = config.postgres_url or config.get('DATABASE_URL')
        
        if postgres_url:
            # If a full connection URL is provided, ensure required params are set
            self.connection_params = {'conninfo': self._normalize_conninfo(postgres_url)}
            self._params_validated = True
            return self.connection_params
        
        # Otherwise, build from individual parameters
        host = config.postgres_host or config.get('POSTGRES_HOST')
        port = config.postgres_port or config.get('POSTGRES_PORT', '5432')
        database = config.postgres_database or config.get('POSTGRES_DB')
        username = config.postgres_username or config.get('POSTGRES_USER')
        password = config.postgres_password or config.get('POSTGRES_PASSWORD')
        
        if not all([host, database, username, password]):
            # Don't fail at init time - will fail on first actual database call
            return None
        
        self.connection_params = {
            'host': host,
            'port': int(port),
            'dbname': database,  # psycopg uses 'dbname' not 'database'
            'user': username,
            'password': password,
            'connect_timeout': 5,
            'sslmode': 'require',  # PostgreSQL Azure requires SSL
            'options': '-c statement_timeout=5000'
        }
        self._params_validated = True
        return self.connection_params

    def _normalize_conninfo(self, conninfo: str) -> str:
        """Ensure SSL and timeouts are set on URL-style connection strings."""
        parsed = urlparse(conninfo)
        if not parsed.scheme or not parsed.netloc:
            return conninfo

        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params.setdefault('sslmode', 'require')
        params.setdefault('connect_timeout', '5')
        # psycopg does not accept statement_timeout as a URL param; use options instead.
        statement_timeout = params.pop('statement_timeout', '5000')
        options_value = params.get('options', '')
        timeout_option = f"-c statement_timeout={statement_timeout}"
        if timeout_option not in options_value:
            options_value = f"{options_value} {timeout_option}".strip()
        if options_value:
            params['options'] = options_value

        updated_query = urlencode(params, doseq=True)
        return urlunparse(parsed._replace(query=updated_query))
    
    def connect(self):
        """Establish database connection."""
        if not self.connection or self.connection.closed:
            # Validate and build params if not done yet
            params = self._build_connection_params()
            
            if not params:
                raise ValueError(
                    "PostgreSQL configuration incomplete. Required: POSTGRES_HOST, POSTGRES_DB, "
                    "POSTGRES_USER, POSTGRES_PASSWORD (or DATABASE_URL) in Key Vault or environment"
                )
            
            try:
                if 'conninfo' in params:
                    self.connection = psycopg.connect(params['conninfo'])
                else:
                    self.connection = psycopg.connect(**params)
            except Exception as e:
                raise ConnectionError(f"Failed to connect to PostgreSQL: {e}")
        return self.connection
    
    def close(self):
        """Close database connection."""
        if self.connection and not self.connection.closed:
            self.connection.close()
            self.connection = None
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            # Get column names from cursor description
            columns = [column[0].lower() for column in cursor.description] if cursor.description else []
            results = []
            for row in cursor.fetchall():
                mapped = dict(zip(columns, row))
                alias_pairs = [
                    ("applicationid", "application_id"),
                    ("applicantname", "applicant_name"),
                    ("uploadeddate", "uploaded_date"),
                    ("wasselected", "was_selected"),
                    ("applicationtext", "application_text"),
                    ("transcripttext", "transcript_text"),
                    ("recommendationtext", "recommendation_text"),
                    ("originalfilename", "original_file_name"),
                    ("filetype", "file_type"),
                    ("blobstoragepath", "blob_storage_path"),
                    ("istrainingexample", "is_training_example"),
                    ("istestdata", "is_test_data"),
                ]
                for legacy, modern in alias_pairs:
                    if legacy in mapped and modern not in mapped:
                        mapped[modern] = mapped[legacy]
                    if modern in mapped and legacy not in mapped:
                        mapped[legacy] = mapped[modern]
                results.append(mapped)
            
            cursor.close()
            return results
        except Exception as e:
            if self.connection:
                try:
                    self.connection.rollback()
                except:
                    pass
                self.connection = None
            raise e
    
    def execute_non_query(self, query: str, params: tuple = None) -> int:
        """Execute INSERT, UPDATE, or DELETE and return affected rows."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            conn.commit()
            rowcount = cursor.rowcount
            cursor.close()
            return rowcount
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            self.connection = None
            raise e
    
    def execute_scalar(self, query: str, params: tuple = None) -> Any:
        """Execute a query and return a single value."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            result = cursor.fetchone()
            
            # For INSERT/UPDATE/DELETE, commit the transaction
            if any(keyword in query.upper() for keyword in ['INSERT', 'UPDATE', 'DELETE']):
                conn.commit()
            
            cursor.close()
            return result[0] if result else None
        except Exception as e:
            try:
                self.connection.rollback()
            except:
                pass
            self.connection = None
            raise e
    
    def create_application(self, applicant_name: str, email: str, application_text: str,
                          file_name: str, file_type: str, is_training: bool = False,
                          is_test_data: bool = False,
                          was_selected: Optional[bool] = None,
                          student_id: Optional[str] = None) -> int:
        """Create a new application record."""
        training_col = self.get_training_example_column()
        test_col = self.get_test_data_column()

        columns = [
            "applicant_name",
            "email",
            "application_text",
            "original_file_name",
            "file_type",
            training_col,
            "was_selected",
            "status",
        ]
        values = [
            applicant_name,
            email,
            application_text,
            file_name,
            file_type,
            is_training,
            was_selected,
            "Pending",
        ]

        if self.has_applications_column(test_col):
            columns.insert(6, test_col)
            values.insert(6, is_test_data)

        if self.has_applications_column("student_id"):
            columns.append("student_id")
            values.append(student_id)

        placeholders = ", ".join(["%s"] * len(columns))
        column_list = ", ".join(columns)
        query = f"""
            INSERT INTO Applications
            ({column_list})
            VALUES ({placeholders})
            RETURNING application_id
        """
        return self.execute_scalar(query, tuple(values))
    
    def get_application(self, application_id: int) -> Optional[Dict[str, Any]]:
        """Get application by ID."""
        applications_table = self.get_table_name("applications")
        app_id_col = self.get_applications_column("application_id")
        query = f"SELECT * FROM {applications_table} WHERE {app_id_col} = %s"
        results = self.execute_query(query, (application_id,))
        if not results:
            return None
        return results[0]
    
    def get_training_examples(self) -> List[Dict[str, Any]]:
        """Get all training examples."""
        training_col = self.get_training_example_column()
        query = """
            SELECT * FROM Applications 
            WHERE {training_col} = TRUE 
            ORDER BY uploaded_date DESC
        """
        return self.execute_query(query.format(training_col=training_col))
    
    def save_evaluation(self, application_id: int, agent_name: str, overall_score: float,
                       technical_score: float, communication_score: float,
                       experience_score: float, cultural_fit_score: float,
                       strengths: str, weaknesses: str, recommendation: str,
                       detailed_analysis: str, comparison: str, model_used: str,
                       processing_time_ms: int) -> int:
        """Save an AI evaluation."""
        query = """
            INSERT INTO ai_evaluations
            (application_id, agent_name, overall_score, technical_skills_score,
             communication_score, experience_score, cultural_fit_score,
             strengths, weaknesses, recommendation, detailed_analysis,
             comparison_to_excellence, model_used, processing_time_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING evaluation_id
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
        training_col = self.get_training_example_column()
        query = """
            SELECT * FROM Applications 
            WHERE status = 'Pending' AND {training_col} = FALSE
            ORDER BY uploaded_date DESC
        """
        return self.execute_query(query.format(training_col=training_col))
    
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
            INSERT INTO student_school_context
            (application_id, school_id, school_name, program_access_score,
             program_participation_score, relative_advantage_score,
             ap_courses_available, ap_courses_taken, ib_courses_available, ib_courses_taken,
             honors_courses_taken, stem_programs_available, stem_programs_accessed,
             school_ses_level, median_household_income, free_lunch_pct,
             percentage_of_peers_using_programs, comparison_notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING context_id
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
            INSERT INTO agent_audit_logs
            (application_id, agent_name, source_file_name)
            VALUES (%s, %s, %s)
            RETURNING audit_id
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
            INSERT INTO tiana_applications
            (application_id, agent_name, essay_summary, recommendation_texts, readiness_score, confidence, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING tiana_application_id
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
            INSERT INTO mulan_recommendations
            (application_id, agent_name, recommender_name, recommender_role,
             endorsement_strength, specificity_score, summary, raw_text, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING mulan_recommendation_id
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

    def save_rapunzel_grades(
        self,
        application_id: int,
        agent_name: str = 'Rapunzel',
        gpa: Optional[float] = None,
        academic_strength: Optional[str] = None,
        course_levels: Optional[Dict[str, Any]] = None,
        transcript_quality: Optional[str] = None,
        notable_patterns: Optional[List[str]] = None,
        confidence_level: Optional[str] = None,
        summary: Optional[str] = None,
        parsed_json: Optional[str] = None
    ) -> int:
        """Save Rapunzel grade analysis output."""
        def _truncate(value: Optional[str], max_len: int) -> Optional[str]:
            if value is None:
                return None
            return value if len(value) <= max_len else value[:max_len]

        query = """
            INSERT INTO rapunzel_grades
            (application_id, agent_name, gpa, academic_strength, course_levels,
             transcript_quality, notable_patterns, confidence_level, summary, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING rapunzel_grade_id
        """
        return self.execute_scalar(query, (
            application_id,
            agent_name,
            gpa,
            _truncate(academic_strength, 255),
            json.dumps(course_levels) if course_levels else None,
            _truncate(transcript_quality, 255),
            json.dumps(notable_patterns) if notable_patterns else None,
            _truncate(confidence_level, 50),
            summary,
            parsed_json or '{}'
        ))

    def save_moana_school_context(
        self,
        application_id: int,
        agent_name: str = 'Moana',
        school_name: Optional[str] = None,
        program_access_score: Optional[float] = None,
        program_participation_score: Optional[float] = None,
        relative_advantage_score: Optional[float] = None,
        ap_courses_available: Optional[int] = None,
        ap_courses_taken: Optional[int] = None,
        contextual_summary: Optional[str] = None,
        parsed_json: Optional[str] = None
    ) -> int:
        """Save Moana school context analysis output."""
        def _coerce_int(value: Any) -> Optional[int]:
            if value is None:
                return None
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, (int,)):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(value.strip())
                except ValueError:
                    return None
            return None

        ap_courses_available = _coerce_int(ap_courses_available)
        ap_courses_taken = _coerce_int(ap_courses_taken)
        columns = self.execute_query(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'student_school_context'"
        )
        column_names = {col.get('column_name') for col in columns} if columns else set()
        has_agent_name = 'agent_name' in column_names
        has_updated_at = 'updated_at' in column_names

        if has_agent_name:
            update_fields = """
                agent_name = %s,
                program_access_score = COALESCE(%s, program_access_score),
                program_participation_score = COALESCE(%s, program_participation_score),
                relative_advantage_score = COALESCE(%s, relative_advantage_score),
                ap_courses_available = COALESCE(%s, ap_courses_available),
                ap_courses_taken = COALESCE(%s, ap_courses_taken),
                comparison_notes = COALESCE(%s, comparison_notes),
                parsed_json = %s
            """
            if has_updated_at:
                update_fields += ",\n                    updated_at = CURRENT_TIMESTAMP"

            query = f"""
                UPDATE student_school_context
                SET {update_fields}
                WHERE application_id = %s
                RETURNING context_id
            """
            result = self.execute_scalar(query, (
                agent_name,
                program_access_score,
                program_participation_score,
                relative_advantage_score,
                ap_courses_available,
                ap_courses_taken,
                contextual_summary,
                parsed_json or '{}',
                application_id
            ))
        else:
            update_fields = """
                program_access_score = COALESCE(%s, program_access_score),
                program_participation_score = COALESCE(%s, program_participation_score),
                relative_advantage_score = COALESCE(%s, relative_advantage_score),
                ap_courses_available = COALESCE(%s, ap_courses_available),
                ap_courses_taken = COALESCE(%s, ap_courses_taken),
                comparison_notes = COALESCE(%s, comparison_notes),
                parsed_json = %s
            """
            if has_updated_at:
                update_fields += ",\n                    updated_at = CURRENT_TIMESTAMP"

            query = f"""
                UPDATE student_school_context
                SET {update_fields}
                WHERE application_id = %s
                RETURNING context_id
            """
            result = self.execute_scalar(query, (
                program_access_score,
                program_participation_score,
                relative_advantage_score,
                ap_courses_available,
                ap_courses_taken,
                contextual_summary,
                parsed_json or '{}',
                application_id
            ))
        
        # If no existing record, insert a new one
        if not result:
            if has_agent_name:
                insert_query = """
                INSERT INTO student_school_context
                (application_id, agent_name, school_name, program_access_score,
                 program_participation_score, relative_advantage_score,
                 ap_courses_available, ap_courses_taken, comparison_notes, parsed_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING context_id
                """
                return self.execute_scalar(insert_query, (
                    application_id,
                    agent_name,
                    school_name,
                    program_access_score,
                    program_participation_score,
                    relative_advantage_score,
                    ap_courses_available,
                    ap_courses_taken,
                    contextual_summary,
                    parsed_json or '{}'
                ))

            insert_query = """
            INSERT INTO student_school_context
            (application_id, school_name, program_access_score,
             program_participation_score, relative_advantage_score,
             ap_courses_available, ap_courses_taken, comparison_notes, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING context_id
            """
            return self.execute_scalar(insert_query, (
                application_id,
                school_name,
                program_access_score,
                program_participation_score,
                relative_advantage_score,
                ap_courses_available,
                ap_courses_taken,
                contextual_summary,
                parsed_json or '{}'
            ))
        return result

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
            INSERT INTO merlin_evaluations
            (application_id, agent_name, overall_score, recommendation, rationale, confidence, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING merlin_evaluation_id
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
        query = "SELECT * FROM student_school_context WHERE application_id = %s"
        results = self.execute_query(query, (application_id,))
        return results[0] if results else None
    
    def get_applications_with_evaluations(self) -> List[Dict[str, Any]]:
        """Get all applications (non-training examples)."""
        training_col = self.get_training_example_column()
        query = """
            SELECT * FROM Applications 
            WHERE {training_col} = FALSE
            ORDER BY uploaded_date DESC
        """
        return self.execute_query(query.format(training_col=training_col))

    def save_aurora_evaluation(
        self,
        application_id: int,
        formatted_evaluation: Dict[str, Any],
        merlin_score: Optional[float] = None,
        merlin_recommendation: Optional[str] = None,
        agents_completed: Optional[str] = None
    ) -> int:
        """Save Aurora's formatted evaluation for a student."""
        query = """
            INSERT INTO aurora_evaluations
            (application_id, agent_name, formatted_evaluation, merlin_score, merlin_recommendation, agents_completed, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING aurora_evaluation_id
        """
        return self.execute_scalar(query, (
            application_id,
            'Aurora',
            json.dumps(formatted_evaluation),
            merlin_score,
            merlin_recommendation,
            agents_completed or ''
        ))
    
    def get_aurora_evaluation(self, application_id: int) -> Optional[Dict[str, Any]]:
        """Get the most recent Aurora evaluation for a student."""
        query = """
            SELECT * FROM aurora_evaluations 
            WHERE application_id = %s 
            ORDER BY created_at DESC
            LIMIT 1
        """
        results = self.execute_query(query, (application_id,))
        if results:
            result = results[0]
            # Parse the formatted_evaluation JSON if it's a string
            formatted_eval_key = next((k for k in result.keys() if 'formatted' in k.lower()), None)
            if formatted_eval_key:
                val = result.get(formatted_eval_key)
                if isinstance(val, str):
                    try:
                        result[formatted_eval_key] = json.loads(val)
                    except:
                        pass
            return result
        return None
    
    def save_test_submission(self, session_id: str, student_count: int, application_ids: List[int]) -> str:
        """Save a test submission to database for persistence."""
        query = """
            INSERT INTO test_submissions
            (session_id, student_count, application_ids, status, created_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING session_id
        """
        return self.execute_scalar(query, (
            session_id,
            student_count,
            json.dumps(application_ids),
            'completed'
        ))
    
    def get_test_submission(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a test submission by session ID."""
        query = """
            SELECT * FROM test_submissions 
            WHERE session_id = %s
        """
        results = self.execute_query(query, (session_id,))
        if results:
            result = results[0]
            # Parse application IDs JSON - handle different key names
            app_ids_key = next((k for k in result.keys() if 'applicationids' in k.lower() or 'application_ids' in k.lower()), None)
            if app_ids_key:
                val = result.get(app_ids_key)
                if isinstance(val, str):
                    try:
                        result[app_ids_key] = json.loads(val)
                    except:
                        result[app_ids_key] = []
            return result
        return None
    
    def get_recent_test_submissions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent test submissions."""
        query = """
            SELECT * FROM test_submissions 
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = self.execute_query(query, (limit,))
        for result in results:
            # Parse application IDs JSON
            app_ids_key = next((k for k in result.keys() if 'applicationids' in k.lower() or 'application_ids' in k.lower()), None)
            if app_ids_key:
                val = result.get(app_ids_key)
                if isinstance(val, str):
                    try:
                        result[app_ids_key] = json.loads(val)
                    except:
                        result[app_ids_key] = []
        return results

    def clear_test_data(self) -> int:
        """Clear all test/training data from the database."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            training_col = self.get_training_example_column()
            
            # Get all test application IDs
            cursor.execute(
                f"SELECT application_id FROM Applications WHERE {training_col} = TRUE"
            )
            test_app_ids = [row[0] for row in cursor.fetchall()]
            
            if not test_app_ids:
                cursor.close()
                return 0
            
            # Build placeholder string for IN clause
            placeholders = ','.join(['%s'] * len(test_app_ids))
            
            # Delete in reverse dependency order
            tables_and_columns = [
                ('agent_audit_logs', 'application_id'),
                ('tiana_applications', 'application_id'),
                ('mulan_recommendations', 'application_id'),
                ('merlin_evaluations', 'application_id'),
                ('aurora_evaluations', 'application_id'),
                ('ai_evaluations', 'application_id'),
                ('student_school_context', 'application_id'),
                ('test_submissions', None),  # handled separately
                ('Applications', 'application_id'),
            ]
            
            total_deleted = 0
            
            for table, column in tables_and_columns:
                if column:
                    delete_query = f"DELETE FROM {table} WHERE {column} IN ({placeholders})"
                    cursor.execute(delete_query, test_app_ids)
                else:
                    # For test_submissions, delete by session_id patterns
                    cursor.execute("DELETE FROM test_submissions WHERE status = 'completed'")
                
                total_deleted += cursor.rowcount
            
            conn.commit()
            cursor.close()
            return total_deleted
            
        except Exception as e:
            try:
                conn.rollback()
            except:
                pass
            raise e

    def set_missing_fields(self, application_id: int, missing_fields: List[str]) -> None:
        """Set which fields/documents are missing for a student."""
        query = """
        UPDATE applications
        SET missing_fields = %s
        WHERE application_id = %s
        """
        self.execute_non_query(query, (json.dumps(missing_fields), application_id))

    def update_application_fields(self, application_id: int, fields: Dict[str, Any]) -> None:
        """Update allowed application fields with provided values."""
        if not fields:
            return

        allowed_fields = {
            'application_text',
            'transcript_text',
            'recommendation_text',
            'original_file_name',
            'file_type'
        }

        updates = []
        values = []
        for key, value in fields.items():
            if key in allowed_fields:
                column_name = self.get_applications_column(key)
                if not column_name:
                    continue
                updates.append(f"{column_name} = %s")
                values.append(value)

        if not updates:
            return

        query = f"UPDATE applications SET {', '.join(updates)} WHERE application_id = %s"
        values.append(application_id)
        self.execute_non_query(query, tuple(values))
    
    def add_missing_field(self, application_id: int, field_name: str) -> None:
        """Add a missing field to a student's missing_fields list."""
        # Get current missing fields
        query = "SELECT missing_fields FROM applications WHERE application_id = %s"
        result = self.execute_query(query, (application_id,))
        
        if result:
            current = result[0].get('missing_fields') or '[]'
            if isinstance(current, str):
                missing = json.loads(current)
            else:
                missing = current if isinstance(current, list) else []
            
            # Add field if not already present
            if field_name not in missing:
                missing.append(field_name)
                self.set_missing_fields(application_id, missing)
    
    def remove_missing_field(self, application_id: int, field_name: str) -> None:
        """Remove a field from a student's missing_fields list."""
        # Get current missing fields
        query = "SELECT missing_fields FROM applications WHERE application_id = %s"
        result = self.execute_query(query, (application_id,))
        
        if result:
            current = result[0].get('missing_fields') or '[]'
            if isinstance(current, str):
                missing = json.loads(current)
            else:
                missing = current if isinstance(current, list) else []
            
            # Remove field if present
            if field_name in missing:
                missing.remove(field_name)
                self.set_missing_fields(application_id, missing)
    
    def get_missing_fields(self, application_id: int) -> List[str]:
        """Get list of missing fields for a student."""
        query = "SELECT missing_fields FROM applications WHERE application_id = %s"
        result = self.execute_query(query, (application_id,))
        
        if result:
            current = result[0].get('missing_fields') or '[]'
            if isinstance(current, str):
                return json.loads(current)
            else:
                return current if isinstance(current, list) else []
        return []

    def get_formatted_student_list(self, is_training: bool = False, search_query: str = None):
        """
        Get a list of students with formatted data sorted by last name.
        
        Returns:
            List of dicts with: first_name, last_name, high_school, merlin_score, 
            application_id, email, status, uploaded_date, missing_fields
        """
        applications_table = self.get_table_name("applications")
        merlin_table = self.get_table_name("merlin_evaluations")
        context_table = self.get_table_name("student_school_context")
        schools_table = self.get_table_name("schools")

        app_id_col = self.get_applications_column("application_id")
        applicant_col = self.get_applications_column("applicant_name")
        email_col = self.get_applications_column("email")
        status_col = self.get_applications_column("status")
        uploaded_col = self.get_applications_column("uploaded_date")
        was_selected_col = self.get_applications_column("was_selected")
        missing_fields_col = self.get_applications_column("missing_fields")

        training_col = self.get_training_example_column()
        test_col = self.get_test_data_column()
        test_filter = ""
        if self.has_applications_column(test_col):
            test_filter = f" AND (a.{test_col} = FALSE OR a.{test_col} IS NULL)"

        merlin_score_col = None
        merlin_join = ""
        if self.has_table(merlin_table):
            merlin_score_col = self.resolve_table_column(
                "merlin_evaluations",
                ["overall_score", "overallscore"],
            )
            merlin_app_id_col = self.resolve_table_column(
                "merlin_evaluations",
                ["application_id", "applicationid"],
            )
            if merlin_score_col and merlin_app_id_col:
                merlin_join = f"LEFT JOIN {merlin_table} m ON a.{app_id_col} = m.{merlin_app_id_col}"

        context_join = ""
        school_join = ""
        school_select = "NULL as school_name"
        if self.has_table(context_table):
            context_app_id_col = self.resolve_table_column(
                "student_school_context",
                ["application_id", "applicationid"],
            )
            context_school_id_col = self.resolve_table_column(
                "student_school_context",
                ["school_id", "schoolid"],
            )
            context_school_name_col = self.resolve_table_column(
                "student_school_context",
                ["school_name", "schoolname"],
            )
            if context_app_id_col:
                context_join = f"LEFT JOIN {context_table} ssc ON a.{app_id_col} = ssc.{context_app_id_col}"
            if self.has_table(schools_table) and context_school_id_col:
                school_name_col = self.resolve_table_column(
                    "schools",
                    ["school_name", "schoolname"],
                )
                school_id_col = self.resolve_table_column(
                    "schools",
                    ["school_id", "schoolid"],
                )
                if school_name_col and school_id_col:
                    school_join = f"LEFT JOIN {schools_table} s ON ssc.{context_school_id_col} = s.{school_id_col}"
                    school_select = f"s.{school_name_col} as school_name"
            elif context_school_name_col:
                school_select = f"ssc.{context_school_name_col} as school_name"

        merlin_select = "NULL as merlin_score"
        if merlin_score_col and merlin_join:
            merlin_select = f"m.{merlin_score_col} as merlin_score"

        was_selected_select = "NULL as was_selected"
        if self.has_applications_column(was_selected_col):
            was_selected_select = f"a.{was_selected_col} as was_selected"

        missing_fields_select = "NULL as missing_fields"
        if self.has_applications_column(missing_fields_col):
            missing_fields_select = f"a.{missing_fields_col} as missing_fields"

        base_query = """
            SELECT
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date,
                {was_selected_select},
                {merlin_select},
                {school_select},
                {missing_fields_select}
            FROM {applications_table} a
            {merlin_join}
            {context_join}
            {school_join}
            WHERE a.{training_col} = {training_flag}{test_filter}
        """

        training_flag = "TRUE" if is_training else "FALSE"
        base_query = base_query.format(
            app_id_col=app_id_col,
            applicant_col=applicant_col,
            email_col=email_col,
            status_col=status_col,
            uploaded_col=uploaded_col,
            was_selected_select=was_selected_select,
            merlin_select=merlin_select,
            school_select=school_select,
            missing_fields_select=missing_fields_select,
            applications_table=applications_table,
            merlin_join=merlin_join,
            context_join=context_join,
            school_join=school_join,
            training_col=training_col,
            training_flag=training_flag,
            test_filter=test_filter,
        )
        
        # Add search filter if provided
        if search_query:
            base_query += f" AND (a.{applicant_col} ILIKE %s OR a.{email_col} ILIKE %s)"
            search_param = f"%{search_query}%"
            params = (search_param, search_param)
        else:
            params = None
        
        # Always sort by last name
        base_query += f" ORDER BY a.{applicant_col}"
        
        results = self.execute_query(base_query, params)
        
        # Format the results
        formatted = []
        for row in results:
            # Split applicant name into first and last
            parts = row.get('applicant_name', '').strip().split()
            first_name = parts[0] if len(parts) > 0 else ''
            last_name = parts[-1] if len(parts) > 1 else ''
            
            # Parse missing fields if present
            missing_fields = []
            if row.get('missing_fields'):
                try:
                    import json
                    missing_fields = json.loads(row.get('missing_fields')) if isinstance(row.get('missing_fields'), str) else row.get('missing_fields', [])
                except:
                    missing_fields = []
            
            formatted.append({
                'application_id': row.get('application_id'),
                'first_name': first_name,
                'last_name': last_name,
                'full_name': row.get('applicant_name'),
                'email': row.get('email'),
                'high_school': row.get('school_name') or 'Not specified',
                'merlin_score': row.get('merlin_score'),
                'status': row.get('status'),
                'uploaded_date': row.get('uploaded_date'),
                'was_selected': bool(row.get('was_selected')) if row.get('was_selected') is not None else None,
                'missing_fields': missing_fields
            })
        
        return formatted


# Global database instance
db = Database()
