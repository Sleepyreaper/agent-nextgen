"""Database connection and models for the application evaluation system - PostgreSQL."""

from typing import Optional, List, Dict, Any
from datetime import datetime
import psycopg
from .config import config
from .logger import app_logger as logger
import json
import time
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote


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
        self._migrations_run = False

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
        # Some providers use + in URL encoding for spaces; normalize to spaces.
        options_value = options_value.replace('+', ' ')
        timeout_option = f"-c statement_timeout={statement_timeout}"
        if timeout_option not in options_value:
            options_value = f"{options_value} {timeout_option}".strip()
        if options_value:
            params['options'] = options_value

        updated_query = urlencode(params, doseq=True, quote_via=quote)
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
                
                # Run migrations on first successful connection
                if not self._migrations_run:
                    self._run_migrations()
                    self._migrations_run = True
                    
            except Exception as e:
                raise ConnectionError(f"Failed to connect to PostgreSQL: {e}")
        return self.connection
    
    def close(self):
        """Close database connection."""
        if self.connection and not self.connection.closed:
            self.connection.close()
            self.connection = None
    
    def _run_migrations(self) -> None:
        """
        Run comprehensive database migrations once during startup.
        Ensures all agent tables have required columns for data persistence.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # ===== APPLICATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'applications' AND column_name IN ('first_name', 'last_name', 'high_school', 'state_code', 'is_test_data')
            """)
            existing_columns = set(row[0] for row in cursor.fetchall())
            
            if 'first_name' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN first_name VARCHAR(255)")
                logger.info("✓ Added first_name column to applications")
            
            if 'last_name' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN last_name VARCHAR(255)")
                logger.info("✓ Added last_name column to applications")
            
            if 'high_school' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN high_school VARCHAR(500)")
                logger.info("✓ Added high_school column to applications")
            
            if 'state_code' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN state_code VARCHAR(10)")
                logger.info("✓ Added state_code column to applications")
            
            if 'is_test_data' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN is_test_data BOOLEAN DEFAULT FALSE")
                logger.info("✓ Added is_test_data column to applications")
            
            # ===== RAPUNZEL GRADES TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'rapunzel_grades'
            """)
            rapunzel_columns = set(row[0] for row in cursor.fetchall())
            
            # Required columns for Rapunzel to save grade data
            rapunzel_required = {
                'contextual_rigor_index': 'NUMERIC(5,2)',
                'school_context_used': 'BOOLEAN DEFAULT FALSE'
            }
            
            for col_name, col_type in rapunzel_required.items():
                if col_name not in rapunzel_columns:
                    cursor.execute(f"ALTER TABLE rapunzel_grades ADD COLUMN {col_name} {col_type}")
                    logger.info(f"✓ Added {col_name} column to rapunzel_grades")
            
            # Create index on contextual_rigor_index for query performance
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_rapunzel_rigor ON rapunzel_grades(contextual_rigor_index)")
                logger.info("✓ Created index on rapunzel_grades.contextual_rigor_index")
            except Exception as idx_err:
                logger.warning(f"Could not create rapunzel rigor index: {idx_err}")
            
            # ===== TIANA APPLICATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'tiana_applications'
            """)
            tiana_columns = set(row[0] for row in cursor.fetchall())
            
            # Tiana uses: essay_summary, recommendation_texts, readiness_score, confidence, parsed_json
            # These should already exist in schema, but we ensure they do
            if 'parsed_json' not in tiana_columns:
                cursor.execute("ALTER TABLE tiana_applications ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                logger.info("✓ Added parsed_json column to tiana_applications")
            
            # ===== MULAN RECOMMENDATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'mulan_recommendations'
            """)
            mulan_columns = set(row[0] for row in cursor.fetchall())
            
            # Mulan uses: recommender_name, recommender_role, endorsement_strength, specificity_score, summary, raw_text, parsed_json
            if 'parsed_json' not in mulan_columns:
                cursor.execute("ALTER TABLE mulan_recommendations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                logger.info("✓ Added parsed_json column to mulan_recommendations")
            
            if 'raw_text' not in mulan_columns:
                cursor.execute("ALTER TABLE mulan_recommendations ADD COLUMN raw_text TEXT")
                logger.info("✓ Added raw_text column to mulan_recommendations")
            
            # ===== MERLIN EVALUATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'merlin_evaluations'
            """)
            merlin_columns = set(row[0] for row in cursor.fetchall())
            
            if 'parsed_json' not in merlin_columns:
                cursor.execute("ALTER TABLE merlin_evaluations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                logger.info("✓ Added parsed_json column to merlin_evaluations")
            
            # ===== AURORA EVALUATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'aurora_evaluations'
            """)
            aurora_columns = set(row[0] for row in cursor.fetchall())
            
            if 'parsed_json' not in aurora_columns:
                cursor.execute("ALTER TABLE aurora_evaluations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                logger.info("✓ Added parsed_json column to aurora_evaluations")
            
            if 'agents_completed' not in aurora_columns:
                cursor.execute("ALTER TABLE aurora_evaluations ADD COLUMN agents_completed VARCHAR(500)")
                logger.info("✓ Added agents_completed column to aurora_evaluations")
            
            # ===== STUDENT SCHOOL CONTEXT TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'student_school_context'
            """)
            context_columns = set(row[0] for row in cursor.fetchall())
            
            # Moana uses student_school_context for school enrichment
            context_required = {
                'agent_name': "VARCHAR(255) DEFAULT 'Moana'",
                'parsed_json': "JSONB DEFAULT '{}'::jsonb",
                'updated_at': "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            }
            
            for col_name, col_type in context_required.items():
                if col_name not in context_columns:
                    cursor.execute(f"ALTER TABLE student_school_context ADD COLUMN {col_name} {col_type}")
                    logger.info(f"✓ Added {col_name} column to student_school_context")
            
            # ===== CREATE MISSING INDEXES =====
            try:
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_student_match 
                    ON applications(
                        LOWER(COALESCE(first_name, '')),
                        LOWER(COALESCE(last_name, '')),
                        LOWER(COALESCE(high_school, '')),
                        UPPER(COALESCE(state_code, ''))
                    )
                """)
                logger.info("✓ Created student matching index")
            except Exception as idx_err:
                logger.warning(f"Could not create index (may already exist): {idx_err}")
            
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_state_code ON applications(state_code)")
                logger.info("✓ Created state_code index")
            except Exception as idx_err:
                logger.warning(f"Could not create state_code index: {idx_err}")
            
            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_is_test_data ON applications(is_test_data)")
                logger.info("✓ Created is_test_data index")
            except Exception as idx_err:
                logger.warning(f"Could not create is_test_data index: {idx_err}")
            
            conn.commit()
            cursor.close()
            logger.info("⭐ COMPREHENSIVE DATABASE MIGRATIONS COMPLETED")
            
        except Exception as e:
            logger.error(f"❌ Migration error: {e}")
            # Don't fail if migrations have issues - the app will continue
            if self.connection:
                self.connection.rollback()
    
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
    
    # =====================================================================
    # PHASE 1: Student Matching and Record Management
    # =====================================================================
    
    def find_student_by_match(
        self, 
        first_name: str, last_name: str, high_school: str, state_code: str
    ) -> Optional[Dict[str, Any]]:
        """
        Find existing student record by exact match:
        first_name + last_name + high_school + state_code
        
        Returns application record if found, else None.
        This ensures we don't create duplicate records for same student.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT application_id, first_name, last_name, high_school, state_code
                FROM applications
                WHERE LOWER(COALESCE(first_name, '')) = LOWER(%s)
                  AND LOWER(COALESCE(last_name, '')) = LOWER(%s)
                  AND LOWER(COALESCE(high_school, '')) = LOWER(%s)
                  AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                LIMIT 1
            """, (first_name.strip(), last_name.strip(), high_school.strip(), state_code.strip()))
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                logger.info(
                    f"Found existing student record: {row[0]} "
                    f"for {first_name} {last_name} from {high_school}, {state_code}"
                )
                return {
                    'application_id': row[0],
                    'first_name': row[1],
                    'last_name': row[2],
                    'high_school': row[3],
                    'state_code': row[4]
                }
            return None
        except Exception as e:
            logger.error(f"Error matching student: {e}")
            return None
    
    def find_similar_students(
        self,
        first_name: str,
        last_name: str,
        high_school: str,
        state_code: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find similar student records for fuzzy matching (PHASE 5 file upload).
        
        Uses multiple strategies for similarity:
        1. Exact name + school match
        2. Similar name (first char match) + same school
        3. Same school + same state
        4. Similar name + same state
        
        Args:
            first_name: First name to match
            last_name: Last name to match
            high_school: High school name
            state_code: State code
            limit: Max number of results
            
        Returns:
            List of similar student records sorted by relevance
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Use Levenshtein distance for fuzzy matching (if available)
            # Falls back to substring matching
            cursor.execute("""
                SELECT 
                    application_id, 
                    first_name, 
                    last_name, 
                    high_school, 
                    state_code,
                    CASE
                        -- Exact match (highest score)
                        WHEN LOWER(COALESCE(first_name, '')) = LOWER(%s)
                         AND LOWER(COALESCE(last_name, '')) = LOWER(%s)
                         AND LOWER(COALESCE(high_school, '')) = LOWER(%s)
                         AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                        THEN 100
                        
                        -- Same school & state, similar first char of name
                        WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                         AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                         AND LEFT(LOWER(COALESCE(first_name, '')), 1) = LEFT(LOWER(%s), 1)
                        THEN 90
                        
                        -- Same school & state
                        WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                         AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                        THEN 70
                        
                        -- Same school only, similar name
                        WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                         AND (LEFT(LOWER(COALESCE(first_name, '')), 3) = LEFT(LOWER(%s), 3)
                           OR LEFT(LOWER(COALESCE(last_name, '')), 3) = LEFT(LOWER(%s), 3))
                        THEN 60
                        
                        -- Similar name (starts with same letters)
                        WHEN LEFT(LOWER(COALESCE(first_name, '')), 2) = LEFT(LOWER(%s), 2)
                         AND LEFT(LOWER(COALESCE(last_name, '')), 2) = LEFT(LOWER(%s), 2)
                        THEN 50
                        
                        -- Same school only
                        WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                        THEN 40
                        
                        -- Same last name & state
                        WHEN LOWER(COALESCE(last_name, '')) = LOWER(%s)
                         AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                        THEN 35
                        
                        ELSE 0
                    END as match_score
                FROM applications
                WHERE CASE
                    -- Exact match (highest score)
                    WHEN LOWER(COALESCE(first_name, '')) = LOWER(%s)
                     AND LOWER(COALESCE(last_name, '')) = LOWER(%s)
                     AND LOWER(COALESCE(high_school, '')) = LOWER(%s)
                     AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                    THEN 100
                    
                    -- Same school & state, similar first char of name
                    WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                     AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                     AND LEFT(LOWER(COALESCE(first_name, '')), 1) = LEFT(LOWER(%s), 1)
                    THEN 90
                    
                    -- Same school & state
                    WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                     AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                    THEN 70
                    
                    -- Same school only, similar name
                    WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                     AND (LEFT(LOWER(COALESCE(first_name, '')), 3) = LEFT(LOWER(%s), 3)
                       OR LEFT(LOWER(COALESCE(last_name, '')), 3) = LEFT(LOWER(%s), 3))
                    THEN 60
                    
                    -- Similar name (starts with same letters)
                    WHEN LEFT(LOWER(COALESCE(first_name, '')), 2) = LEFT(LOWER(%s), 2)
                     AND LEFT(LOWER(COALESCE(last_name, '')), 2) = LEFT(LOWER(%s), 2)
                    THEN 50
                    
                    -- Same school only
                    WHEN LOWER(COALESCE(high_school, '')) = LOWER(%s)
                    THEN 40
                    
                    -- Same last name & state
                    WHEN LOWER(COALESCE(last_name, '')) = LOWER(%s)
                     AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                    THEN 35
                    
                    ELSE 0
                END > 0
                ORDER BY match_score DESC
                LIMIT %s
            """, (
                first_name.strip(), last_name.strip(), high_school.strip(), state_code.strip(),  # Exact
                high_school.strip(), state_code.strip(), first_name.strip(),  # Same school & state
                high_school.strip(), state_code.strip(),  # Same school & state (score 70)
                high_school.strip(), first_name.strip(), last_name.strip(),  # Similar name
                first_name.strip(), last_name.strip(),  # Similar name (50)
                high_school.strip(),  # Same school (40)
                last_name.strip(), state_code.strip(),  # Same last name & state
                # Repeat all for WHERE clause
                first_name.strip(), last_name.strip(), high_school.strip(), state_code.strip(),
                high_school.strip(), state_code.strip(), first_name.strip(),
                high_school.strip(), state_code.strip(),
                high_school.strip(), first_name.strip(), last_name.strip(),
                first_name.strip(), last_name.strip(),
                high_school.strip(),
                last_name.strip(), state_code.strip(),
                limit
            ))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'application_id': row[0],
                    'first_name': row[1],
                    'last_name': row[2],
                    'high_school': row[3],
                    'state_code': row[4],
                    'match_score': row[5]
                })
            
            cursor.close()
            
            if results:
                logger.info(f"Found {len(results)} similar students for '{first_name} {last_name}'")
            
            return results
            
        except Exception as e:
            logger.error(f"Error finding similar students: {e}")
            return []

    def create_student_record(
        self, first_name: str, last_name: str, high_school: str, 
        state_code: str, **kwargs
    ) -> Optional[int]:
        """
        Create new student application record with metadata.
        Ensures accurate student record creation with key matching fields.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            # Build INSERT with all available metadata
            applicant_name = f"{first_name} {last_name}".strip()
            
            cursor.execute("""
                INSERT INTO applications 
                (applicant_name, first_name, last_name, high_school, 
                 state_code, application_text, uploaded_date, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING application_id
            """, (
                applicant_name,
                first_name.strip(),
                last_name.strip(),
                high_school.strip(),
                state_code.strip().upper(),
                kwargs.get('application_text', ''),
                datetime.now(),
                'Pending'
            ))
            app_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            logger.info(
                f"Created new student record: {app_id} "
                f"for {first_name} {last_name} from {high_school}, {state_code}"
            )
            return app_id
        except Exception as e:
            logger.error(f"Error creating student record: {e}")
            return None
    
    def mark_for_re_evaluation(self, application_id: int) -> bool:
        """
        Mark a student record for re-evaluation.
        Called when new files are uploaded for an existing student.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE applications
                SET status = 'Pending', updated_date = %s
                WHERE application_id = %s
            """, (datetime.now(), application_id))
            conn.commit()
            cursor.close()
            logger.info(f"Marked application {application_id} for re-evaluation")
            return True
        except Exception as e:
            logger.error(f"Error marking for re-evaluation: {e}")
            return False
    
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

    def update_application_status(self, application_id: int, status: str) -> None:
        """Update a student's application status safely across schema variants."""
        applications_table = self.get_table_name("applications")
        status_col = self.get_applications_column("status") or "status"
        app_id_col = self.get_applications_column("application_id") or "application_id"
        query = f"UPDATE {applications_table} SET {status_col} = %s WHERE {app_id_col} = %s"
        self.execute_non_query(query, (status, application_id))
    
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

    def log_agent_interaction(
        self,
        application_id: int,
        agent_name: str,
        interaction_type: str,
        question_text: Optional[str] = None,
        user_response: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
        extracted_data: Optional[Dict[str, Any]] = None,
        sequence_number: Optional[int] = None
    ) -> int:
        """
        Log all agent interactions for full audit trail.
        
        Tracks:
        - Agent questions asked
        - User responses
        - File uploads with metadata
        - Data extracted from documents
        - Interaction sequence
        """
        query = """
            INSERT INTO agent_interactions
            (application_id, agent_name, interaction_type, question_text,
             user_response, file_name, file_size, file_type, extracted_data,
             timestamp, sequence_number)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING interaction_id
        """
        return self.execute_scalar(query, (
            application_id,
            agent_name,
            interaction_type,
            question_text,
            user_response,
            file_name,
            file_size,
            file_type,
            json.dumps(extracted_data) if extracted_data else None,
            datetime.now(),
            sequence_number
        ))

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
        contextual_rigor_index: Optional[float] = None,
        school_context_used: bool = False,
        parsed_json: Optional[str] = None
    ) -> int:
        """
        Save Rapunzel grade analysis output.
        Now includes contextual_rigor_index (weighted by school data) and school_context_used flag.
        """
        def _truncate(value: Optional[str], max_len: int) -> Optional[str]:
            if value is None:
                return None
            return value if len(value) <= max_len else value[:max_len]

        query = """
            INSERT INTO rapunzel_grades
            (application_id, agent_name, gpa, academic_strength, course_levels,
             transcript_quality, notable_patterns, confidence_level, summary, 
             contextual_rigor_index, school_context_used, parsed_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            contextual_rigor_index,
            school_context_used,
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

    def save_user_feedback(
        self,
        feedback_type: str,
        message: str,
        email: Optional[str] = None,
        page: Optional[str] = None,
        app_version: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: str = 'received'
    ) -> int:
        """Save a user feedback submission."""
        query = """
            INSERT INTO user_feedback
            (feedback_type, message, email, page, app_version, user_agent, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING feedback_id
        """
        return self.execute_scalar(query, (
            feedback_type,
            message,
            email,
            page,
            app_version,
            user_agent,
            status
        ))

    def update_user_feedback(
        self,
        feedback_id: int,
        triage_json: Optional[Dict[str, Any]] = None,
        issue_url: Optional[str] = None,
        status: Optional[str] = None
    ) -> None:
        """Update feedback record with triage and issue metadata."""
        query = """
            UPDATE user_feedback
            SET triage_json = COALESCE(%s, triage_json),
                issue_url = COALESCE(%s, issue_url),
                status = COALESCE(%s, status),
                updated_at = CURRENT_TIMESTAMP
            WHERE feedback_id = %s
        """
        self.execute_non_query(query, (
            json.dumps(triage_json) if triage_json is not None else None,
            issue_url,
            status,
            feedback_id
        ))

    def get_user_feedback(self, feedback_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a feedback record by id."""
        query = """
            SELECT * FROM user_feedback
            WHERE feedback_id = %s
        """
        results = self.execute_query(query, (feedback_id,))
        if not results:
            return None
        result = results[0]
        triage_key = next((k for k in result.keys() if 'triage' in k.lower()), None)
        if triage_key:
            val = result.get(triage_key)
            if isinstance(val, str):
                try:
                    result[triage_key] = json.loads(val)
                except Exception:
                    pass
        return result

    def get_recent_user_feedback(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent user feedback records."""
        query = """
            SELECT * FROM user_feedback
            ORDER BY created_at DESC
            LIMIT %s
        """
        results = self.execute_query(query, (limit,))
        for result in results:
            triage_key = next((k for k in result.keys() if 'triage' in k.lower()), None)
            if triage_key:
                val = result.get(triage_key)
                if isinstance(val, str):
                    try:
                        result[triage_key] = json.loads(val)
                    except Exception:
                        pass
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
            'file_type',
            'student_id'
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

    def get_application_match_candidates(self, is_training: bool, is_test_data: bool) -> List[Dict[str, Any]]:
        """Get potential application matches for a given upload type."""
        applications_table = self.get_table_name("applications")
        context_table = self.get_table_name("student_school_context")

        app_id_col = self.get_applications_column("application_id")
        applicant_col = self.get_applications_column("applicant_name")
        email_col = self.get_applications_column("email")
        status_col = self.get_applications_column("status")
        app_text_col = self.get_applications_column("application_text")
        transcript_col = self.get_applications_column("transcript_text")
        recommendation_col = self.get_applications_column("recommendation_text")
        student_id_col = self.get_applications_column("student_id")

        training_col = self.get_training_example_column()
        test_col = self.get_test_data_column()

        context_join = ""
        school_select = "NULL as school_name"
        if context_table and self.has_table(context_table):
            context_app_id_col = self.resolve_table_column(
                "student_school_context",
                ["application_id", "applicationid"],
            )
            context_school_name_col = self.resolve_table_column(
                "student_school_context",
                ["school_name", "schoolname"],
            )
            if context_app_id_col and context_school_name_col:
                context_join = f"LEFT JOIN {context_table} ssc ON a.{app_id_col} = ssc.{context_app_id_col}"
                school_select = f"ssc.{context_school_name_col} as school_name"

        where_clause = f"a.{training_col} = %s"
        params: List[Any] = [is_training]
        if self.has_applications_column(test_col):
            if is_test_data:
                where_clause += f" AND a.{test_col} = TRUE"
            else:
                where_clause += f" AND (a.{test_col} = FALSE OR a.{test_col} IS NULL)"

        query = f"""
            SELECT
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{app_text_col} as application_text,
                a.{transcript_col} as transcript_text,
                a.{recommendation_col} as recommendation_text,
                a.{student_id_col} as student_id,
                {school_select}
            FROM {applications_table} a
            {context_join}
            WHERE {where_clause}
        """

        return self.execute_query(query, tuple(params))
    
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
                {missing_fields_select},
                a.{training_col} as is_training_example,
                a.{test_col} as is_test_data
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
                'missing_fields': missing_fields,
                'is_test_data': bool(row.get('is_test_data')) if row.get('is_test_data') is not None else False,
                'is_training_example': bool(row.get('is_training_example')) if row.get('is_training_example') is not None else False
            })
        
        return formatted

    # ==================== SCHOOL ENRICHMENT METHODS ====================
    
    def create_school_enriched_data(self, school_data: Dict[str, Any]) -> Optional[int]:
        """Create a new enriched school record."""
        query = """
            INSERT INTO school_enriched_data (
                school_name, school_district, state_code, county_name, school_url,
                opportunity_score, total_students, graduation_rate, college_acceptance_rate,
                free_lunch_percentage, ap_course_count, ap_exam_pass_rate, stem_program_available,
                ib_program_available, dual_enrollment_available, analysis_status, 
                human_review_status, web_sources_analyzed, data_confidence_score, created_by,
                school_investment_level, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING school_enrichment_id
        """
        
        try:
            # Map Naveen's field names to database column names
            result = self.execute_query(
                query,
                (
                    school_data.get('school_name'),
                    school_data.get('school_district'),
                    school_data.get('state_code'),
                    school_data.get('county_name'),
                    school_data.get('school_url'),
                    school_data.get('opportunity_score', 0),
                    school_data.get('enrollment_size') or school_data.get('total_students'),  # Naveen uses enrollment_size
                    school_data.get('graduation_rate', 0),
                    school_data.get('college_placement_rate') or school_data.get('college_acceptance_rate', 0) or 0,  # Naveen uses college_placement_rate
                    school_data.get('free_lunch_percentage', 0),
                    school_data.get('ap_classes_count') or school_data.get('ap_course_count', 0),  # Naveen uses ap_classes_count
                    school_data.get('ap_exam_pass_rate', 0),
                    school_data.get('stem_programs', False) or school_data.get('stem_program_available', False),  # Naveen uses stem_programs
                    school_data.get('ib_offerings', False) or school_data.get('ib_program_available', False),  # Naveen uses ib_offerings
                    school_data.get('honors_programs', False) or school_data.get('dual_enrollment_available', False),
                    school_data.get('analysis_status', 'complete'),
                    school_data.get('human_review_status', 'pending'),
                    json.dumps(school_data.get('web_sources', [])) if school_data.get('web_sources') else None,
                    school_data.get('confidence_score', 0) or school_data.get('data_confidence_score', 0),
                    school_data.get('created_by', 'naveen'),
                    school_data.get('school_investment_level', 'medium'),
                    school_data.get('is_active', True)  # New column for active status
                )
            )
            
            return result[0].get('school_enrichment_id') if result else None
        except Exception as e:
            logger.error(
                f"Error creating school enriched data: {e}", 
                exc_info=True, 
                extra={'school_name': school_data.get('school_name'), 'school_data_keys': list(school_data.keys())}
            )
            return None

    def get_school_enriched_data(self, school_id: Optional[int] = None, school_name: Optional[str] = None, 
                                 state_code: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve enriched school data by ID or name/state."""
        try:
            if not self.has_table("school_enriched_data"):
                logger.warning("School enrichment table missing: school_enriched_data")
                return None
            if school_id:
                query = "SELECT * FROM school_enriched_data WHERE school_enrichment_id = %s"
                result = self.execute_query(query, (school_id,))
            elif school_name and state_code:
                query = "SELECT * FROM school_enriched_data WHERE LOWER(school_name) = LOWER(%s) AND state_code = %s"
                result = self.execute_query(query, (school_name, state_code))
            else:
                return None
            
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting school enriched data: {e}")
            return None

    def get_all_schools_enriched(self, filters: Optional[Dict[str, Any]] = None, 
                                limit: int = 100) -> List[Dict[str, Any]]:
        """Get all enriched schools with optional filters."""
        try:
            if not self.has_table("school_enriched_data"):
                logger.warning("School enrichment table missing: school_enriched_data")
                return []
            query = "SELECT * FROM school_enriched_data WHERE is_active = TRUE"
            params = []
            
            if filters:
                if filters.get('state_code'):
                    query += " AND state_code = %s"
                    params.append(filters['state_code'])
                if filters.get('human_review_status'):
                    query += " AND human_review_status = %s"
                    params.append(filters['human_review_status'])
                if filters.get('opportunity_score_min'):
                    query += " AND opportunity_score >= %s"
                    params.append(filters['opportunity_score_min'])
                if filters.get('search_text'):
                    query += " AND (LOWER(school_name) LIKE LOWER(%s) OR LOWER(school_district) LIKE LOWER(%s))"
                    search_pattern = f"%{filters['search_text']}%"
                    params.append(search_pattern)
                    params.append(search_pattern)
            
            query += " ORDER BY opportunity_score DESC LIMIT %s"
            params.append(limit)
            
            return self.execute_query(query, tuple(params))
        except Exception as e:
            logger.error(f"Error getting all schools enriched: {e}")
            return []

    def update_school_review(self, school_id: int, review_data: Dict[str, Any]) -> bool:
        """Update school record with human review."""
        try:
            query = """
                UPDATE school_enriched_data
                SET human_review_status = %s,
                    opportunity_score = %s,
                    reviewed_by = %s,
                    reviewed_date = CURRENT_TIMESTAMP,
                    human_notes = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE school_enrichment_id = %s
            """
            
            self.execute_non_query(
                query,
                (
                    review_data.get('review_status', 'pending'),
                    review_data.get('opportunity_score'),
                    review_data.get('reviewed_by', 'system'),
                    review_data.get('human_notes'),
                    school_id
                )
            )
            
            # Save version for audit trail
            self._save_school_version(school_id, review_data, 'human_adjustment')
            
            # Save to analysis history
            self._save_analysis_history(school_id, 'human_review', review_data)
            
            return True
        except Exception as e:
            logger.error(f"Error updating school review: {e}")
            return False

    def _save_school_version(self, school_id: int, data: Dict[str, Any], change_reason: str) -> None:
        """Save version snapshot for audit trail."""
        try:
            school = self.get_school_enriched_data(school_id)
            if not school:
                return
            
            query = """
                INSERT INTO school_data_versions (school_enrichment_id, data_snapshot, 
                                                 change_summary, changed_by, change_reason)
                VALUES (%s, %s, %s, %s, %s)
            """
            
            self.execute_non_query(
                query,
                (
                    school_id,
                    json.dumps(dict(school)),
                    data.get('human_notes', ''),
                    data.get('reviewed_by', 'system'),
                    change_reason
                )
            )
        except Exception as e:
            logger.error(f"Error saving school version: {e}")

    def _save_analysis_history(self, school_id: int, analysis_type: str, data: Dict[str, Any]) -> None:
        """Save to analysis history."""
        try:
            query = """
                INSERT INTO school_analysis_history (school_enrichment_id, analysis_type, 
                                                    agent_name, status, findings_summary, 
                                                    reviewed_by, review_notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            
            self.execute_non_query(
                query,
                (
                    school_id,
                    analysis_type,
                    'human_review_system',
                    'complete',
                    data.get('human_notes', ''),
                    data.get('reviewed_by', 'system'),
                    json.dumps(data)
                )
            )
        except Exception as e:
            logger.error(f"Error saving analysis history: {e}")
    
    # =====================================================================
    # PHASE 3: School Validation Tracking
    # =====================================================================
    
    def mark_school_validation_complete(
        self,
        school_name: str,
        state_code: str,
        validation_passed: bool
    ) -> bool:
        """
        Mark school validation as complete in school_enriched_data table.
        
        Updates:
        - moana_requirements_met: True if validation_passed, False otherwise
        - last_moana_validation: Current timestamp
        
        Args:
            school_name: School name to update
            state_code: State code to identify school
            validation_passed: Boolean indicating validation result
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            query = """
                UPDATE school_enriched_data
                SET moana_requirements_met = %s,
                    last_moana_validation = %s
                WHERE school_name = %s AND state_code = %s
            """
            
            current_time = datetime.now()
            
            self.execute_non_query(
                query,
                (validation_passed, current_time, school_name, state_code)
            )
            
            logger.info(
                f"✓ Marked school validation complete",
                extra={
                    'school': school_name,
                    'state': state_code,
                    'validation_passed': validation_passed
                }
            )
            return True
            
        except Exception as e:
            logger.error(
                f"Error marking school validation: {e}",
                extra={'school': school_name, 'state': state_code}
            )
            return False
    
    def get_school_validation_status(
        self,
        school_name: str,
        state_code: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get school validation status from database.
        
        Args:
            school_name: School name
            state_code: State code
            
        Returns:
            Dict with {moana_requirements_met, last_moana_validation} or None
        """
        try:
            query = """
                SELECT moana_requirements_met, last_moana_validation
                FROM school_enriched_data
                WHERE school_name = %s AND state_code = %s
                LIMIT 1
            """
            
            result = self.fetch_one(query, (school_name, state_code))
            
            if result:
                return {
                    'moana_requirements_met': result.get('moana_requirements_met'),
                    'last_moana_validation': result.get('last_moana_validation')
                }
            
            return None
            
        except Exception as e:
            logger.warning(
                f"Error getting school validation status: {e}",
                extra={'school': school_name, 'state': state_code}
            )
            return None

    # =====================================================================
    # PHASE 5: File Upload Audit & Matching Tracking
    # =====================================================================

    def log_file_upload_audit(
        self,
        file_name: str,
        file_type: str,
        file_size: int,
        extracted_first_name: str,
        extracted_last_name: str,
        extracted_high_school: str,
        extracted_state_code: str,
        extraction_confidence: float,
        matched_application_id: int,
        ai_match_confidence: float,
        match_status: str,
        match_reasoning: str = None,
        extraction_method: str = 'AI'
    ) -> Optional[int]:
        """
        Log file upload and AI matching details for human audit.
        
        Args:
            file_name: Original uploaded file name
            file_type: MIME type
            file_size: File size in bytes
            extracted_first_name: AI-extracted first name from file
            extracted_last_name: AI-extracted last name from file
            extracted_high_school: AI-extracted high school from file
            extracted_state_code: AI-extracted state code from file
            extraction_confidence: Confidence 0-1 of extraction accuracy
            matched_application_id: Student record this file is matched to
            ai_match_confidence: Confidence 0-1 of the student match
            match_status: 'new_student', 'matched_existing', 'low_confidence'
            match_reasoning: Text explanation of matching decision
            extraction_method: 'AI', 'manual', etc
            
        Returns:
            audit_id if successful, None on error
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO file_upload_audit (
                    file_name,
                    file_type,
                    file_size,
                    extracted_first_name,
                    extracted_last_name,
                    extracted_high_school,
                    extracted_state_code,
                    extraction_confidence,
                    matched_application_id,
                    ai_match_confidence,
                    match_status,
                    match_reasoning,
                    extraction_method,
                    upload_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                RETURNING audit_id
            """, (
                file_name,
                file_type,
                file_size,
                extracted_first_name,
                extracted_last_name,
                extracted_high_school,
                extracted_state_code,
                extraction_confidence,
                matched_application_id,
                ai_match_confidence,
                match_status,
                match_reasoning,
                extraction_method
            ))
            
            audit_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()
            
            logger.info(
                f"Logged file upload audit: {file_name}",
                extra={
                    'audit_id': audit_id,
                    'application_id': matched_application_id,
                    'match_confidence': ai_match_confidence
                }
            )
            
            return audit_id
            
        except Exception as e:
            logger.error(f"Error logging file upload audit: {e}")
            return None

    def get_file_matching_audit_for_student(
        self,
        application_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all file uploads and matching decisions for a student (human review).
        
        Args:
            application_id: Student application ID
            
        Returns:
            List of file upload audit records with matching details
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    audit_id,
                    upload_date,
                    file_name,
                    file_type,
                    file_size,
                    extracted_first_name,
                    extracted_last_name,
                    extracted_high_school,
                    extracted_state_code,
                    extraction_confidence,
                    ai_match_confidence,
                    match_status,
                    match_reasoning,
                    human_reviewed,
                    human_review_date,
                    human_review_notes,
                    human_review_approved,
                    reviewed_by
                FROM file_upload_audit
                WHERE matched_application_id = %s
                ORDER BY upload_date DESC
            """, (application_id,))
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'audit_id': row[0],
                    'upload_date': row[1],
                    'file_name': row[2],
                    'file_type': row[3],
                    'file_size': row[4],
                    'extracted_first_name': row[5],
                    'extracted_last_name': row[6],
                    'extracted_high_school': row[7],
                    'extracted_state_code': row[8],
                    'extraction_confidence': float(row[9]) if row[9] else 0.0,
                    'ai_match_confidence': float(row[10]) if row[10] else 0.0,
                    'match_status': row[11],
                    'match_reasoning': row[12],
                    'human_reviewed': row[13],
                    'human_review_date': row[14],
                    'human_review_notes': row[15],
                    'human_review_approved': row[16],
                    'reviewed_by': row[17]
                })
            
            cursor.close()
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving file matching audit for student {application_id}: {e}")
            return []

    def get_all_pending_file_reviews(self) -> List[Dict[str, Any]]:
        """
        Get all files pending human review across all students.
        
        Returns:
            List of file upload audit records with low confidence or pending review
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    a.audit_id,
                    a.upload_date,
                    a.file_name,
                    a.extracted_first_name,
                    a.extracted_last_name,
                    a.extracted_high_school,
                    a.extracted_state_code,
                    a.extraction_confidence,
                    a.ai_match_confidence,
                    a.match_status,
                    a.matched_application_id,
                    app.applicant_name,
                    app.first_name,
                    app.last_name,
                    app.high_school,
                    app.state_code
                FROM file_upload_audit a
                INNER JOIN applications app ON a.matched_application_id = app.application_id
                WHERE a.human_reviewed = FALSE
                   OR a.ai_match_confidence < 0.85
                ORDER BY a.ai_match_confidence ASC, a.upload_date DESC
                LIMIT 100
            """)
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    'audit_id': row[0],
                    'upload_date': row[1],
                    'file_name': row[2],
                    'extracted_student': f"{row[3]} {row[4]}",
                    'extracted_school': row[5],
                    'extracted_state': row[6],
                    'extraction_confidence': float(row[7]) if row[7] else 0.0,
                    'ai_match_confidence': float(row[8]) if row[8] else 0.0,
                    'match_status': row[9],
                    'matched_application_id': row[10],
                    'student_name': row[11],
                    'student_first_name': row[12],
                    'student_last_name': row[13],
                    'student_school': row[14],
                    'student_state': row[15],
                    'accuracy_summary': f"Extraction: {float(row[7]):.0%}, Match: {float(row[8]):.0%}"
                })
            
            cursor.close()
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving pending file reviews: {e}")
            return []

    def update_file_upload_review(
        self,
        audit_id: int,
        human_review_approved: bool,
        human_review_notes: str = None,
        reviewed_by: str = 'system'
    ) -> bool:
        """
        Update human review of a file upload match.
        
        Args:
            audit_id: File upload audit ID
            human_review_approved: True if match is approved, False if rejected
            human_review_notes: Human reviewer notes
            reviewed_by: Username of reviewer
            
        Returns:
            True if successful
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE file_upload_audit
                SET human_reviewed = TRUE,
                    human_review_date = CURRENT_TIMESTAMP,
                    human_review_notes = %s,
                    human_review_approved = %s,
                    reviewed_by = %s
                WHERE audit_id = %s
            """, (human_review_notes, human_review_approved, reviewed_by, audit_id))
            
            conn.commit()
            cursor.close()
            
            logger.info(
                f"Updated file upload review: audit_id={audit_id}, approved={human_review_approved}",
                extra={'reviewed_by': reviewed_by}
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating file upload review: {e}")
            return False


# Create a singleton instance for module-level import
db = Database()
