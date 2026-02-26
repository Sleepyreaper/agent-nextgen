"""Database connection and models for the application evaluation system - PostgreSQL."""

from typing import Optional, List, Dict, Any
from datetime import datetime
import sqlite3
try:
    import psycopg
    PSYCOPG_AVAILABLE = True
except Exception:
    psycopg = None
    PSYCOPG_AVAILABLE = False

try:
    from config import config
except Exception:
    from .config import config

try:
    from logger import app_logger as logger
except Exception:
    from .logger import app_logger as logger
import json
import time
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse, quote
from decimal import Decimal
from src.utils import safe_load_json


class Database:
    def get_formatted_student_list(self, is_training: bool = False, search_query: str = None) -> list:
        """Return a list of students/applications for 2026 or training, with defensive filtering."""
        applications_table = self.get_table_name("applications")
        if not applications_table:
            return []
        app_id_col = self.get_applications_column("application_id") or "application_id"
        applicant_col = self.get_applications_column("applicant_name") or "applicant_name"
        email_col = self.get_applications_column("email") or "email"
        status_col = self.get_applications_column("status") or "status"
        uploaded_col = self.get_applications_column("uploaded_date") or "uploaded_date"
        was_selected_col = self.get_applications_column("was_selected") or "was_selected"
        training_col = self.get_training_example_column() or "is_training_example"
        test_col = self.get_test_data_column() or "is_test_data"

        where_clauses = []
        params = []
        if is_training:
            where_clauses.append(f"a.{training_col} = TRUE")
            where_clauses.append(f"(a.{test_col} = FALSE OR a.{test_col} IS NULL)")
        else:
            where_clauses.append(f"(a.{training_col} = FALSE OR a.{training_col} IS NULL)")
            where_clauses.append(f"(a.{test_col} = FALSE OR a.{test_col} IS NULL)")
        if search_query:
            where_clauses.append(f"(a.{applicant_col} ILIKE %s OR a.{email_col} ILIKE %s)")
            params.extend([f"%{search_query}%", f"%{search_query}%"])
        where_clause = " AND ".join(where_clauses)
        # If the new student_summary column exists we can return it here and
        # later convert it to a Python object.  We don't attempt any JSON
        # extraction in SQL so that both Postgres (JSONB) and SQLite (TEXT)
        # continue to work.  The caller code will inspect the value and derive a
        # merlin_score if needed.
        select_cols = [
            f"a.{app_id_col} as application_id",
            f"a.{applicant_col} as applicant_name",
            f"a.{email_col} as email",
            f"a.{status_col} as status",
            f"a.{uploaded_col} as uploaded_date",
            f"a.{was_selected_col} as was_selected",
            f"a.{training_col} as is_training_example",
            f"a.{test_col} as is_test_data"
        ]
        # Include first_name, last_name, high_school for the list template
        for extra_col in ('first_name', 'last_name', 'high_school'):
            if self.has_applications_column(extra_col):
                select_cols.append(f"a.{extra_col}")
        # Fallback school name from student_school_context (Moana) when
        # applications.high_school is NULL.  Use subquery to avoid duplicates.
        select_cols.append(
            "(SELECT ssc.school_name FROM student_school_context ssc"
            " WHERE ssc.application_id = a." + app_id_col +
            " ORDER BY ssc.context_id DESC LIMIT 1) AS moana_school_name"
        )
        # pull in agent_results as well so callers (including list view) can
        # compute a temporary merlin_score if necessary.  The field might be
        # JSONB or TEXT depending on migration state.
        if self.has_applications_column('agent_results'):
            select_cols.append("a.agent_results")
        if self.has_applications_column('student_summary'):
            select_cols.append("a.student_summary")

        # For training data, detect if a matching historical score record exists
        join_clause = ""
        if is_training:
            select_cols.append(
                "CASE WHEN hs.score_id IS NOT NULL THEN TRUE ELSE FALSE END AS has_historical_match"
            )
            join_clause = "LEFT JOIN historical_scores hs ON hs.application_id = a." + app_id_col

        column_fragment = ",\n                ".join(select_cols)

        query = f"""
            SELECT
                {column_fragment}
            FROM {applications_table} a
            {join_clause}
            WHERE {where_clause}
            ORDER BY LOWER(a.{applicant_col}) ASC
        """
        rows = self.execute_query(query, tuple(params))

        # post-process rows to parse JSON columns and provide a uniform
        # ``merlin_score`` property that the UI expects.
        for row in rows:
            # parse JSON text columns if necessary
            if 'student_summary' in row:
                try:
                    row['student_summary'] = safe_load_json(row['student_summary'])
                except Exception:
                    pass
            if 'agent_results' in row:
                try:
                    row['agent_results'] = safe_load_json(row['agent_results'])
                except Exception:
                    pass

            # Resolve high_school: prefer applications column, fall back to
            # student_school_context (Moana), then agent_results JSON.
            if not row.get('high_school'):
                moana_name = row.pop('moana_school_name', None)
                if moana_name:
                    row['high_school'] = moana_name
                elif row.get('agent_results') and isinstance(row['agent_results'], dict):
                    moana = row['agent_results'].get('moana') or row['agent_results'].get('school_context') or {}
                    if isinstance(moana, dict):
                        row['high_school'] = moana.get('school_name') or moana.get('school')
            else:
                row.pop('moana_school_name', None)

            # give the UI something to render in the main table
            score = None
            if row.get('student_summary'):
                ss = row.get('student_summary')
                if isinstance(ss, dict):
                    score = ss.get('overall_score') or ss.get('score')
            # if we still don't have a score, try agent_results innards
            if score is None and row.get('agent_results'):
                ar = row.get('agent_results')
                if isinstance(ar, dict):
                    mer = ar.get('merlin') or {}
                    score = mer.get('overall_score') or mer.get('overallscore')
            if score is not None:
                row['merlin_score'] = score

        return rows
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
        self._using_sqlite_fallback = False

    # ------------------------------------------------------------------
    # OPTIONAL DATABASE HELPERS
    # ------------------------------------------------------------------

    def backfill_student_summaries(self) -> int:
        """Backfill the ``student_summary`` column for existing applications.

        This helper is safe to call repeatedly.  For any row that has a
        non-null ``agent_results`` field but no ``student_summary`` we compute a
        lightweight summary (mimicking ``SmeeOrchestrator._create_student_summary``)
        and update the row.  Returns the number of rows modified.
        """
        if not self.has_applications_column('student_summary'):
            logger.info("backfill_student_summaries: column not present, skipping")
            return 0

        updated = 0
        rows = self.execute_query(
            "SELECT application_id, student_summary, agent_results FROM applications"
        )
        for row in rows:
            if row.get('student_summary'):
                continue
            agents = row.get('agent_results') or {}
            if not isinstance(agents, dict) or not agents:
                continue

            merlin = agents.get('merlin') or {}
            aurora = agents.get('aurora') or {}
            summary = {
                'status': 'completed',
                'overall_score': merlin.get('overall_score') or merlin.get('overallscore'),
                'recommendation': merlin.get('recommendation'),
                'rationale': merlin.get('rationale', ''),
                'key_strengths': merlin.get('key_strengths', []),
                'key_risks': merlin.get('key_risks', []),
                'confidence': merlin.get('confidence'),
                'agents_completed': list(agents.keys()),
                'formatted_by_aurora': bool(aurora),
                'aurora_sections': list(aurora.keys()) if isinstance(aurora, dict) else []
            }
            summary['agent_details'] = agents
            try:
                self.execute_non_query(
                    "UPDATE applications SET student_summary = %s WHERE application_id = %s",
                    (json.dumps(summary), row.get('application_id'))
                )
                updated += 1
            except Exception:
                # swallow errors to continue backfilling others
                logger.debug(f"failed to backfill summary for {row.get('application_id')}")
        logger.info(f"backfill_student_summaries: updated {updated} rows")
        return updated


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
                # If psycopg is not available or no connection params provided, fall back to a lightweight
                # in-memory SQLite database for local prototype runs. This avoids hard failures when
                # Postgres is not configured in local development.
                if not PSYCOPG_AVAILABLE:
                    self._using_sqlite_fallback = True
                    self.connection = sqlite3.connect(":memory:")
                    # Return rows as tuples but provide cursor.description for mapping
                    self.connection.row_factory = None
                    return self.connection

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
                    try:
                        self._run_migrations()
                        self._migrations_run = True
                    except Exception as mig_err:
                        # if migrations fail, close the connection so future
                        # calls will make a fresh one instead of reusing the
                        # aborted/errored session.
                        try:
                            if self.connection and not self.connection.closed:
                                self.connection.close()
                        except Exception:
                            pass
                        self.connection = None
                        raise mig_err
            except Exception as e:
                # ensure we don't keep a bad connection alive
                if self.connection:
                    try:
                        self.connection.close()
                    except Exception:
                        pass
                    self.connection = None
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
            # Disable statement_timeout for the duration of migrations; some ALTER
            # statements can take longer than the default 5000ms so we want to
            # let them run without cancellation.  ``SET LOCAL`` affects only the
            # current transaction and is reverted automatically.
            try:
                cursor.execute("SET LOCAL statement_timeout = 0")
            except Exception:
                pass
            
            # ===== APPLICATIONS TABLE MIGRATIONS =====
            # include the new JSON columns in our probe so we don't try to
            # add them every time the migration runs (which triggers harmless
            # but noisy "column already exists" errors).
            cursor.execute("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'applications' AND column_name IN (
                    'first_name', 'last_name', 'high_school', 'state_code',
                    'is_test_data', 'student_summary', 'agent_results'
                )
            """)
            existing_columns = {row[0] for row in cursor.fetchall()}
            
            if 'first_name' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN first_name VARCHAR(255)")
                conn.commit()
                logger.info("✓ Added first_name column to applications")
            
            if 'last_name' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN last_name VARCHAR(255)")
                conn.commit()
                logger.info("✓ Added last_name column to applications")
            
            if 'high_school' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN high_school VARCHAR(500)")
                conn.commit()
                logger.info("✓ Added high_school column to applications")
            
            if 'state_code' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN state_code VARCHAR(10)")
                conn.commit()
                logger.info("✓ Added state_code column to applications")
            
            if 'is_test_data' not in existing_columns:
                cursor.execute("ALTER TABLE applications ADD COLUMN is_test_data BOOLEAN DEFAULT FALSE")
                conn.commit()
                logger.info("✓ Added is_test_data column to applications")
            
            # add student_summary JSON column so we can store a concise
            # precomputed summary of what the agents have reasoned about this
            # application.  This is used by the UI as well as APIs to quickly
            # surface results without having to join all of the individual
            # evaluation tables.
            if 'student_summary' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE applications ADD COLUMN student_summary JSONB")
                    conn.commit()
                    existing_columns.add('student_summary')
                    logger.info("✓ Added student_summary column to applications")
                except Exception as first_err:
                    conn.rollback()
                    # if the column already exists (race or prior migration) skip
                    if 'already exists' in str(first_err).lower():
                        logger.debug("student_summary already exists, skipping")
                    else:
                        try:
                            cursor.execute("ALTER TABLE applications ADD COLUMN student_summary TEXT")
                            conn.commit()
                            existing_columns.add('student_summary')
                            logger.info("✓ Added student_summary (TEXT) column to applications")
                        except Exception as second_err:
                            conn.rollback()
                            if 'already exists' in str(second_err).lower():
                                logger.debug("student_summary (TEXT) already exists, skipping")
                            else:
                                logger.warning(f"Could not add student_summary column: {first_err} / {second_err}")

            # likewise keep an overall dump of each agent's raw output so the
            # reasoning can be inspected later; this lives in agent_results.
            if 'agent_results' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE applications ADD COLUMN agent_results JSONB")
                    conn.commit()
                    existing_columns.add('agent_results')
                    logger.info("✓ Added agent_results column to applications")
                except Exception as first_err:
                    conn.rollback()
                    if 'already exists' in str(first_err).lower():
                        logger.debug("agent_results already exists, skipping")
                    else:
                        try:
                            cursor.execute("ALTER TABLE applications ADD COLUMN agent_results TEXT")
                            conn.commit()
                            existing_columns.add('agent_results')
                            logger.info("✓ Added agent_results (TEXT) column to applications")
                        except Exception as second_err:
                            conn.rollback()
                            if 'already exists' in str(second_err).lower():
                                logger.debug("agent_results (TEXT) already exists, skipping")
                            else:
                                logger.warning(f"Could not add agent_results column: {first_err} / {second_err}")
            
            # ===== RAPUNZEL GRADES TABLE MIGRATIONS =====
            # First check if table exists (check all schemas)
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'rapunzel_grades'
                    AND table_schema NOT IN ('pg_catalog', 'information_schema')
                )
            """)
            rapunzel_exists = cursor.fetchone()[0]
            
            if rapunzel_exists:
                # Get the actual schema name where the table exists
                cursor.execute("""
                    SELECT table_schema FROM information_schema.tables 
                    WHERE table_name = 'rapunzel_grades'
                    AND table_schema NOT IN ('pg_catalog', 'information_schema')
                    LIMIT 1
                """)
                schema_row = cursor.fetchone()
                schema_name = schema_row[0] if schema_row else 'public'
                logger.info(f"Found rapunzel_grades in schema: {schema_name}")
                
                cursor.execute(f"""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'rapunzel_grades'
                    AND table_schema = '{schema_name}'
                """)
                rapunzel_columns = set(row[0] for row in cursor.fetchall())
                logger.info(f"Rapunzel columns found: {rapunzel_columns}")
                
                # Required columns for Rapunzel to save grade data
                rapunzel_required = {
                    'contextual_rigor_index': 'NUMERIC(5,2)',
                    'school_context_used': 'BOOLEAN DEFAULT FALSE'
                }
                
                for col_name, col_type in rapunzel_required.items():
                    if col_name not in rapunzel_columns:
                        try:
                            # Use schema-qualified name to be explicit
                            cursor.execute(f"ALTER TABLE \"{schema_name}\".\"rapunzel_grades\" ADD COLUMN \"{col_name}\" {col_type}")
                            conn.commit()
                            logger.info(f"✓ Added {col_name} column to rapunzel_grades")
                            # Re-check immediately after adding
                            cursor.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name = 'rapunzel_grades' AND table_schema = '{schema_name}' AND column_name = '{col_name}'")
                            if cursor.fetchone():
                                logger.info(f"✓ VERIFIED: {col_name} now exists in rapunzel_grades")
                            else:
                                logger.error(f"❌ VERIFICATION FAILED: {col_name} was not added to rapunzel_grades")
                        except Exception as col_err:
                            logger.error(f"❌ Failed to add {col_name} to rapunzel_grades: {col_err}")
                            conn.rollback()
                    else:
                        logger.info(f"✓ Column {col_name} already exists in rapunzel_grades")
                
                # Create index on contextual_rigor_index for query performance
                try:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_rapunzel_rigor ON \"{schema_name}\".\"rapunzel_grades\"(\"contextual_rigor_index\")")
                    logger.info("✓ Created index on rapunzel_grades.contextual_rigor_index")
                except Exception as idx_err:
                    logger.warning(f"Could not create rapunzel rigor index: {idx_err}")
            else:
                logger.warning("⚠️  rapunzel_grades table does not exist yet")
            
            # ===== TIANA APPLICATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'tiana_applications'
                )
            """)
            tiana_exists = cursor.fetchone()[0]
            
            if tiana_exists:
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'tiana_applications'
                """)
                tiana_columns = set(row[0] for row in cursor.fetchall())
                
                # Tiana uses: essay_summary, recommendation_texts, readiness_score, confidence, parsed_json
                # These should already exist in schema, but we ensure they do
                if 'parsed_json' not in tiana_columns:
                    try:
                        cursor.execute("ALTER TABLE tiana_applications ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                        conn.commit()
                        logger.info("✓ Added parsed_json column to tiana_applications")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add parsed_json to tiana_applications: {col_err}")
                        conn.rollback()
            
            # ===== MULAN RECOMMENDATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'mulan_recommendations'
                )
            """)
            mulan_exists = cursor.fetchone()[0]
            
            if mulan_exists:
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'mulan_recommendations'
                """)
                mulan_columns = set(row[0] for row in cursor.fetchall())
                
                # Mulan uses: recommender_name, recommender_role, endorsement_strength, specificity_score, summary, raw_text, parsed_json
                if 'parsed_json' not in mulan_columns:
                    try:
                        cursor.execute("ALTER TABLE mulan_recommendations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                        conn.commit()
                        logger.info("✓ Added parsed_json column to mulan_recommendations")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add parsed_json to mulan_recommendations: {col_err}")
                        conn.rollback()
                
                if 'raw_text' not in mulan_columns:
                    try:
                        cursor.execute("ALTER TABLE mulan_recommendations ADD COLUMN raw_text TEXT")
                        conn.commit()
                        logger.info("✓ Added raw_text column to mulan_recommendations")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add raw_text to mulan_recommendations: {col_err}")
                        conn.rollback()
            
            # ===== MERLIN EVALUATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'merlin_evaluations'
                )
            """)
            merlin_exists = cursor.fetchone()[0]
            
            if merlin_exists:
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'merlin_evaluations'
                """)
                merlin_columns = set(row[0] for row in cursor.fetchall())
                
                if 'parsed_json' not in merlin_columns:
                    try:
                        cursor.execute("ALTER TABLE merlin_evaluations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                        conn.commit()
                        logger.info("✓ Added parsed_json column to merlin_evaluations")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add parsed_json to merlin_evaluations: {col_err}")
                        conn.rollback()
            
            # ===== AURORA EVALUATIONS TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'aurora_evaluations'
                )
            """)
            aurora_exists = cursor.fetchone()[0]
            
            if aurora_exists:
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'aurora_evaluations'
                """)
                aurora_columns = set(row[0] for row in cursor.fetchall())
                
                if 'parsed_json' not in aurora_columns:
                    try:
                        cursor.execute("ALTER TABLE aurora_evaluations ADD COLUMN parsed_json JSONB DEFAULT '{}'::jsonb")
                        conn.commit()
                        logger.info("✓ Added parsed_json column to aurora_evaluations")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add parsed_json to aurora_evaluations: {col_err}")
                        conn.rollback()
                
                if 'agents_completed' not in aurora_columns:
                    try:
                        cursor.execute("ALTER TABLE aurora_evaluations ADD COLUMN agents_completed VARCHAR(500)")
                        conn.commit()
                        logger.info("✓ Added agents_completed column to aurora_evaluations")
                    except Exception as col_err:
                        logger.error(f"❌ Failed to add agents_completed to aurora_evaluations: {col_err}")
                        conn.rollback()
            
            # ===== SCHOOL ENRICHED DATA TABLE =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'school_enriched_data'
                )
            """)
            school_enriched_exists = cursor.fetchone()[0]
            
            if not school_enriched_exists:
                try:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS school_enriched_data (
                            school_enrichment_id SERIAL PRIMARY KEY,
                            school_name VARCHAR(500) NOT NULL,
                            school_district VARCHAR(255),
                            state_code VARCHAR(2),
                            county_name VARCHAR(100),
                            school_url VARCHAR(1000),
                            school_url_verified BOOLEAN DEFAULT FALSE,
                            school_url_verified_date TIMESTAMP,
                            opportunity_score NUMERIC(5,2),
                            opportunity_score_last_updated TIMESTAMP,
                            total_students INTEGER,
                            graduation_rate NUMERIC(5,2),
                            college_acceptance_rate NUMERIC(5,2),
                            free_lunch_percentage NUMERIC(5,2),
                            ap_course_count INTEGER,
                            ap_exam_pass_rate NUMERIC(5,2),
                            honors_course_count INTEGER,
                            standard_course_count INTEGER,
                            stem_program_available BOOLEAN,
                            ib_program_available BOOLEAN,
                            dual_enrollment_available BOOLEAN,
                            avg_class_size NUMERIC(5,2),
                            student_teacher_ratio NUMERIC(5,2),
                            college_prep_focus BOOLEAN,
                            career_technical_focus BOOLEAN,
                            median_graduate_salary NUMERIC(10,2),
                            salary_data_source VARCHAR(255),
                            salary_data_year INTEGER,
                            community_sentiment_score NUMERIC(5,2),
                            parent_satisfaction_score NUMERIC(5,2),
                            school_investment_level VARCHAR(50),
                            analysis_status VARCHAR(50) DEFAULT 'pending',
                            human_review_status VARCHAR(50) DEFAULT 'pending',
                            reviewed_by VARCHAR(255),
                            reviewed_date TIMESTAMP,
                            human_notes TEXT,
                            data_confidence_score NUMERIC(5,2),
                            data_source_notes TEXT,
                            web_sources_analyzed TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            created_by VARCHAR(255),
                            is_active BOOLEAN DEFAULT TRUE,
                            archived_at TIMESTAMP,
                            moana_requirements_met BOOLEAN DEFAULT FALSE,
                            last_moana_validation TIMESTAMP
                        )
                    """)
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_school_enriched_name ON school_enriched_data(school_name)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_school_enriched_state ON school_enriched_data(state_code)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_school_enriched_opportunity ON school_enriched_data(opportunity_score)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_school_enriched_review_status ON school_enriched_data(human_review_status)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_school_enriched_active ON school_enriched_data(is_active)")
                    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_school_enriched_name_state ON school_enriched_data(LOWER(school_name), state_code)")
                    conn.commit()
                    logger.info("✓ Created school_enriched_data table with indexes")
                except Exception as school_err:
                    logger.error(f"❌ Failed to create school_enriched_data table: {school_err}")
                    conn.rollback()
            else:
                # Ensure moana columns exist on existing tables
                cursor.execute("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'school_enriched_data'
                """)
                school_columns = set(row[0] for row in cursor.fetchall())
                
                for col_name, col_type in {
                    'moana_requirements_met': 'BOOLEAN DEFAULT FALSE',
                    'last_moana_validation': 'TIMESTAMP'
                }.items():
                    if col_name not in school_columns:
                        try:
                            cursor.execute(f"ALTER TABLE school_enriched_data ADD COLUMN {col_name} {col_type}")
                            conn.commit()
                            logger.info(f"✓ Added {col_name} column to school_enriched_data")
                        except Exception as col_err:
                            logger.error(f"❌ Failed to add {col_name} to school_enriched_data: {col_err}")
                            conn.rollback()

                # Ensure unique index on (school_name, state_code) exists
                try:
                    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_school_enriched_name_state ON school_enriched_data(LOWER(school_name), state_code)")
                    conn.commit()
                    logger.info("✓ Ensured unique index on school_enriched_data(school_name, state_code)")
                except Exception as idx_err:
                    logger.warning(f"Could not create unique index (duplicates may exist): {idx_err}")
                    conn.rollback()

            # ===== STUDENT SCHOOL CONTEXT TABLE MIGRATIONS =====
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'student_school_context'
                )
            """)
            context_exists = cursor.fetchone()[0]
            
            if context_exists:
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
                        try:
                            cursor.execute(f"ALTER TABLE student_school_context ADD COLUMN {col_name} {col_type}")
                            conn.commit()
                            logger.info(f"✓ Added {col_name} column to student_school_context")
                        except Exception as col_err:
                            logger.error(f"❌ Failed to add {col_name} to student_school_context: {col_err}")
                            conn.rollback()
            
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

            # ===== HISTORICAL SCORES TABLE =====
            try:
                cursor.execute("""
                    SELECT EXISTS(
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'historical_scores'
                    )
                """)
                hs_exists = cursor.fetchone()[0]
                if not hs_exists:
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS historical_scores (
                            score_id SERIAL PRIMARY KEY,
                            cohort_year INTEGER NOT NULL DEFAULT 2024,
                            applicant_name VARCHAR(255) NOT NULL,
                            applicant_name_normalized VARCHAR(255),
                            status TEXT,
                            was_selected BOOLEAN DEFAULT NULL,
                            preliminary_score TEXT,
                            quick_notes TEXT,
                            reviewer_name VARCHAR(255),
                            was_scored BOOLEAN DEFAULT FALSE,
                            academic_record NUMERIC(3,1),
                            stem_interest NUMERIC(3,1),
                            essay_video NUMERIC(3,1),
                            recommendation NUMERIC(3,1),
                            bonus NUMERIC(3,1),
                            total_rating NUMERIC(4,1),
                            eligibility_notes TEXT,
                            previous_research_experience TEXT,
                            advanced_coursework TEXT,
                            overall_rating VARCHAR(255),
                            column_q TEXT,
                            application_id INTEGER REFERENCES Applications(application_id) ON DELETE SET NULL,
                            imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            import_source VARCHAR(500),
                            row_number INTEGER
                        )
                    """)
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_year ON historical_scores(cohort_year)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_name ON historical_scores(applicant_name_normalized)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_status ON historical_scores(status)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_app_id ON historical_scores(application_id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_total ON historical_scores(total_rating)")
                    conn.commit()
                    logger.info("✓ Created historical_scores table with indexes")
                else:
                    # Add was_selected column if missing (eligible ≠ selected)
                    try:
                        cursor.execute("""
                            SELECT column_name FROM information_schema.columns
                            WHERE table_name = 'historical_scores' AND column_name = 'was_selected'
                        """)
                        if not cursor.fetchone():
                            cursor.execute("ALTER TABLE historical_scores ADD COLUMN was_selected BOOLEAN DEFAULT NULL")
                            cursor.execute("CREATE INDEX IF NOT EXISTS idx_historical_scores_selected ON historical_scores(was_selected)")
                            conn.commit()
                            logger.info("✓ Added was_selected column to historical_scores")
                    except Exception as col_err:
                        logger.warning(f"Could not add was_selected column: {col_err}")
                        conn.rollback()

                    # Widen narrow VARCHAR columns that overflow with real-world data
                    for col_name, new_type in [('status', 'TEXT'), ('preliminary_score', 'TEXT')]:
                        try:
                            cursor.execute(f"""
                                SELECT data_type FROM information_schema.columns
                                WHERE table_name = 'historical_scores' AND column_name = '{col_name}'
                            """)
                            row_info = cursor.fetchone()
                            if row_info and row_info[0] == 'character varying':
                                cursor.execute(f"ALTER TABLE historical_scores ALTER COLUMN {col_name} TYPE {new_type}")
                                conn.commit()
                                logger.info(f"✓ Widened historical_scores.{col_name} to {new_type}")
                        except Exception as widen_err:
                            logger.warning(f"Could not widen {col_name}: {widen_err}")
                            conn.rollback()

                    logger.debug("historical_scores table already exists, skipping creation")
            except Exception as hs_err:
                logger.error(f"❌ Failed to create historical_scores table: {hs_err}")
                conn.rollback()

            # attempt automatic backfill of student_summary for any existing
            # rows that already have agent_results.  This is idempotent and
            # safe to run repeatedly.
            try:
                rows_updated = self.backfill_student_summaries()
                logger.info(f"★ Backfilled {rows_updated} student_summary row(s)")
            except Exception as back_err:
                logger.warning(f"Backfill helper failed during migrations: {back_err}")

            cursor.close()
            logger.info("⭐ COMPREHENSIVE DATABASE MIGRATIONS COMPLETED")
            
        except Exception as e:
            logger.error(f"❌ Migration error: {e}")
            # ensure transaction is aborted and connection is reset so later
            # operations don't hit "current transaction is aborted"
            if self.connection:
                try:
                    self.connection.rollback()
                except Exception:
                    pass
                # drop conn so next call creates a fresh connection
                self.connection = None
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results."""
        try:
            conn = self.connect()
            cursor = conn.cursor()

            # If using SQLite fallback, adapt parameter placeholders from %s to ?
            if self._using_sqlite_fallback:
                exec_query = query.replace('%s', '?')
            else:
                exec_query = query

            if params:
                cursor.execute(exec_query, params)
            else:
                cursor.execute(exec_query)
            
            # Get column names from cursor description
            columns = [column[0].lower() for column in cursor.description] if cursor.description else []
            results = []
            for row in cursor.fetchall():
                # sqlite3 returns rows as tuples as does psycopg; mapping by column names works for both
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
            # rollback and drop connection to avoid reuse of bad session
            if self.connection:
                try:
                    self.connection.rollback()
                except:
                    pass
                self.connection = None
            # if the failure was due to a previous aborted transaction, we
            # can safely attempt the query one more time after reconnecting.
            try:
                from psycopg import errors as _ps_errors
            except ImportError:
                _ps_errors = None
            if _ps_errors and isinstance(e, _ps_errors.InFailedSqlTransaction):
                try:
                    return self.execute_query(query, params)
                except Exception:
                    pass
            raise e
    
    def execute_non_query(self, query: str, params: tuple = None) -> int:
        """Execute INSERT, UPDATE, or DELETE and return affected rows."""
        try:
            conn = self.connect()
            cursor = conn.cursor()
            # Adapt placeholders for sqlite fallback
            if self._using_sqlite_fallback:
                exec_query = query.replace('%s', '?')
            else:
                exec_query = query

            if params:
                cursor.execute(exec_query, params)
            else:
                cursor.execute(exec_query)
            
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
            # Adapt placeholders for sqlite fallback
            if self._using_sqlite_fallback:
                exec_query = query.replace('%s', '?')
            else:
                exec_query = query

            if params:
                cursor.execute(exec_query, params)
            else:
                cursor.execute(exec_query)
            
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
        first_name: str, last_name: str, high_school: str, state_code: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Find existing student record by matching name + high school.
        
        Primary match keys: first_name + last_name + high_school
        Optional refinement: state_code (used when available to narrow results)
        
        Returns application record if found, else None.
        This ensures we don't create duplicate records for same student.
        """
        try:
            conn = self.connect()
            cursor = conn.cursor()
            
            state_code_clean = state_code.strip().upper() if state_code else ""
            
            if state_code_clean:
                # Match on all four fields when state is available
                cursor.execute("""
                    SELECT application_id, first_name, last_name, high_school, state_code
                    FROM applications
                    WHERE LOWER(COALESCE(first_name, '')) = LOWER(%s)
                      AND LOWER(COALESCE(last_name, '')) = LOWER(%s)
                      AND LOWER(COALESCE(high_school, '')) = LOWER(%s)
                      AND UPPER(COALESCE(state_code, '')) = UPPER(%s)
                    LIMIT 1
                """, (first_name.strip(), last_name.strip(), high_school.strip(), state_code_clean))
            else:
                # Match on name + high school only (state unknown)
                cursor.execute("""
                    SELECT application_id, first_name, last_name, high_school, state_code
                    FROM applications
                    WHERE LOWER(COALESCE(first_name, '')) = LOWER(%s)
                      AND LOWER(COALESCE(last_name, '')) = LOWER(%s)
                      AND LOWER(COALESCE(high_school, '')) = LOWER(%s)
                    LIMIT 1
                """, (first_name.strip(), last_name.strip(), high_school.strip()))
            
            row = cursor.fetchone()
            cursor.close()
            
            if row:
                logger.info(
                    f"Found existing student record: {row[0]} "
                    f"for {first_name} {last_name} from {high_school}"
                    + (f", {state_code_clean}" if state_code_clean else "")
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

        # Include student_id if provided and the column exists
        if student_id and self.has_applications_column("student_id"):
            columns.append("student_id")
            values.append(student_id)

        if test_col and self.has_applications_column(test_col):
            test_filter = ""
            if test_col and self.has_applications_column(test_col):
                test_filter = f" AND (a.{test_col} = FALSE OR a.{test_col} IS NULL)"
            # Defensive: if test_col is None, skip test_filter
            columns.insert(6, test_col)
            values.insert(6, is_test_data)
        # Defensive: if test_col is None, skip test_col in columns/values

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
        """Get application by ID.

        Returns the row as a dictionary and will attempt to parse any JSON
        columns (student_summary, agent_results) so callers see Python objects
        instead of raw strings.  This keeps UI code simple.
        """
        applications_table = self.get_table_name("applications")
        app_id_col = self.get_applications_column("application_id")
        query = f"SELECT * FROM {applications_table} WHERE {app_id_col} = %s"
        results = self.execute_query(query, (application_id,))
        if not results:
            return None
        result = results[0]

        # parse any JSON columns that may be stored as TEXT
        try:
            if 'student_summary' in result:
                result['student_summary'] = safe_load_json(result.get('student_summary'))
        except Exception:
            pass

        try:
            if 'agent_results' in result:
                result['agent_results'] = safe_load_json(result.get('agent_results'))
                # If agents store rich JSON inside nested `parsed_json` structures
                # (for example: merlin.parsed_json.content == "{...}"), try to
                # deserialize and merge useful top-level fields so templates can
                # access `overall_score`, `recommendation`, and `rationale`.
                try:
                    agents_tmp = result.get('agent_results') or {}
                    merlin = agents_tmp.get('merlin') or agents_tmp.get('student_evaluator') or {}
                    if isinstance(merlin, dict):
                        parsed = merlin.get('parsed_json') or merlin.get('parsedjson') or {}
                        if isinstance(parsed, dict):
                            content = parsed.get('content') or parsed.get('text') or parsed.get('body')
                            if isinstance(content, str) and content.strip():
                                try:
                                    parsed_inner = json.loads(content)
                                    # Promote a few well-known keys if present
                                    for k in ('overall_score', 'overallscore', 'recommendation', 'rationale', 'confidence', 'key_strengths', 'key_risks'):
                                        if parsed_inner.get(k) is not None and not merlin.get(k):
                                            merlin[k] = parsed_inner.get(k)
                                except Exception:
                                    # content may not be pure JSON; ignore silently
                                    pass
                        # write back any changes
                        if merlin:
                            if 'merlin' in agents_tmp:
                                agents_tmp['merlin'] = merlin
                            else:
                                agents_tmp['student_evaluator'] = merlin
                            result['agent_results'] = agents_tmp
                except Exception:
                    pass
        except Exception:
            pass

        # If student_summary is missing but agent_results exist, synthesize
        # a lightweight summary (mirrors backfill_student_summaries) so the
        # UI can render agent reasoning immediately. Also attempt to persist
        # the synthesized summary back to the DB as a best-effort operation.
        if not result.get('student_summary') and result.get('agent_results') and isinstance(result.get('agent_results'), dict):
            agents = result.get('agent_results') or {}
            merlin = agents.get('merlin') or {}
            aurora = agents.get('aurora') or {}

            summary = {
                'status': 'completed',
                'overall_score': merlin.get('overall_score') or merlin.get('overallscore'),
                'recommendation': merlin.get('recommendation'),
                'rationale': merlin.get('rationale', ''),
                'key_strengths': merlin.get('key_strengths', []),
                'key_risks': merlin.get('key_risks', []),
                'confidence': merlin.get('confidence'),
                'agents_completed': list(agents.keys()),
                'formatted_by_aurora': bool(aurora),
                'aurora_sections': list(aurora.keys()) if isinstance(aurora, dict) else []
            }
            summary['agent_details'] = agents

            # Attach synthesized summary for immediate rendering
            result['student_summary'] = summary

            # Persist synthesized summary back to DB (best-effort)
            try:
                update_query = f"UPDATE {applications_table} SET student_summary = %s WHERE {app_id_col} = %s"
                self.execute_non_query(update_query, (json.dumps(summary), application_id))
            except Exception:
                logger.debug(f"Could not persist synthesized student_summary for {application_id}")

        return result

    def delete_student(self, application_id: int) -> Dict[str, Any]:
        """Delete a student and all related records across all agent tables.

        Cascades deletes through every child table that references ApplicationID.

        Args:
            application_id: The application ID to delete

        Returns:
            Dict with 'deleted' counts per table and 'total' count
        """
        applications_table = self.get_table_name("applications")
        app_id_col = self.get_applications_column("application_id") or "application_id"

        # All child tables that reference application_id
        child_tables = [
            "agent_audit_logs",
            "tiana_applications",
            "rapunzel_grades",
            "mulan_recommendations",
            "merlin_evaluations",
            "aurora_evaluations",
            "student_school_context",
            "ai_evaluations",
            "selection_decisions",
            "training_feedback",
            "grades",
        ]

        deleted: Dict[str, int] = {}
        total = 0

        for table in child_tables:
            table_name = self.get_table_name(table)
            if not table_name:
                continue
            try:
                count = self.execute_non_query(
                    f"DELETE FROM {table_name} WHERE application_id = %s",
                    (application_id,),
                )
                if count and count > 0:
                    deleted[table] = count
                    total += count
            except Exception as e:
                logger.debug(f"Skipping child table {table}: {e}")

        # Delete the application itself
        try:
            count = self.execute_non_query(
                f"DELETE FROM {applications_table} WHERE {app_id_col} = %s",
                (application_id,),
            )
            deleted["applications"] = count or 0
            total += count or 0
        except Exception as e:
            logger.error(f"Error deleting application {application_id}: {e}")
            raise

        logger.info(
            f"Deleted student {application_id}: {total} total rows across {len(deleted)} tables"
        )
        return {"deleted": deleted, "total": total}

    def find_training_duplicates(self) -> List[Dict[str, Any]]:
        """Find duplicate training records grouped by name.

        Returns groups where LOWER(first_name) + LOWER(last_name) appear
        more than once among training examples (is_training_example = TRUE).
        Each group contains the list of matching application records so the
        caller can decide which to keep and which to delete.
        """
        training_col = self.get_training_example_column() or "is_training_example"
        test_col = self.get_test_data_column() or "is_test_data"

        # Step 1: find duplicate name combos
        dup_query = f"""
            SELECT LOWER(COALESCE(first_name, '')) AS fn,
                   LOWER(COALESCE(last_name, ''))  AS ln,
                   COUNT(*) AS cnt
            FROM applications
            WHERE {training_col} = TRUE
              AND ({test_col} = FALSE OR {test_col} IS NULL)
            GROUP BY fn, ln
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC, ln, fn
        """
        dup_groups = self.execute_query(dup_query)

        if not dup_groups:
            return []

        # Step 2: for each group, fetch the individual records
        results = []
        for group in dup_groups:
            fn = group["fn"]
            ln = group["ln"]
            detail_query = f"""
                SELECT application_id, applicant_name, email, first_name, last_name,
                       high_school, status, uploaded_date, was_selected,
                       {training_col} AS is_training_example
                FROM applications
                WHERE {training_col} = TRUE
                  AND ({test_col} = FALSE OR {test_col} IS NULL)
                  AND LOWER(COALESCE(first_name, '')) = %s
                  AND LOWER(COALESCE(last_name, ''))  = %s
                ORDER BY uploaded_date ASC
            """
            records = self.execute_query(detail_query, (fn, ln))
            results.append({
                "first_name": records[0].get("first_name", fn) if records else fn,
                "last_name": records[0].get("last_name", ln) if records else ln,
                "count": group["cnt"],
                "records": records,
            })

        return results

    def update_application_status(self, application_id: int, status: str) -> None:
        """Update a student's application status safely across schema variants."""
        applications_table = self.get_table_name("applications")
        status_col = self.get_applications_column("status") or "status"
        app_id_col = self.get_applications_column("application_id") or "application_id"
        query = f"UPDATE {applications_table} SET {status_col} = %s WHERE {app_id_col} = %s"
        self.execute_non_query(query, (status, application_id))
    
    def get_training_examples(self) -> List[Dict[str, Any]]:
        """Get all training examples."""
        applications_table = self.get_table_name("applications") or 'applications'
        training_col = self.get_training_example_column() or 'is_training_example'
        # Use COALESCE to handle NULLs and missing columns defensively
        query = f"SELECT * FROM {applications_table} WHERE COALESCE({training_col}, FALSE) = TRUE ORDER BY uploaded_date DESC"
        return self.execute_query(query)
    
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
        # Ensure extracted_data is JSON serializable (convert Decimal, datetime, etc.)
        safe_extracted = None
        if extracted_data is not None:
            try:
                safe_extracted = json.dumps(self._sanitize_for_json(extracted_data))
            except Exception:
                # Fallback: stringify the object
                try:
                    safe_extracted = json.dumps(str(extracted_data))
                except Exception:
                    safe_extracted = None

        return self.execute_scalar(query, (
            application_id,
            agent_name,
            interaction_type,
            question_text,
            user_response,
            file_name,
            file_size,
            file_type,
            safe_extracted,
            datetime.now(),
            sequence_number
        ))

    @staticmethod
    def _sanitize_for_json(obj: Any) -> Any:
        """Recursively convert non-JSON-serializable types (Decimal, datetime) into serializable types."""
        if obj is None:
            return None
        if isinstance(obj, Decimal):
            # Preserve numeric fidelity where possible
            try:
                return float(obj)
            except Exception:
                return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: Database._sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [Database._sanitize_for_json(v) for v in obj]
        if isinstance(obj, tuple):
            return tuple(Database._sanitize_for_json(v) for v in obj)
        if isinstance(obj, (int, float, str, bool)):
            return obj
        # Fallback to string for any other types
        return str(obj)

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
        # Sanitize params: convert dict/list/tuple to JSON strings and coerce decimals/datetimes
        # Ensure confidence fits DB column (VARCHAR(50)). Prefer canonical High/Medium/Low when possible.
        if isinstance(confidence, str):
            conf_lower = confidence.lower()
            if 'high' in conf_lower:
                confidence = 'High'
            elif 'medium' in conf_lower:
                confidence = 'Medium'
            elif 'low' in conf_lower:
                confidence = 'Low'
            else:
                if len(confidence) > 50:
                    confidence = confidence[:47] + '...'

        # Coerce readiness_score to numeric or None
        try:
            if readiness_score is not None and readiness_score != "":
                readiness_score = float(readiness_score)
        except Exception:
            readiness_score = None

        params = [
            application_id,
            agent_name,
            essay_summary,
            recommendation_texts,
            readiness_score,
            confidence,
            parsed_json,
        ]

        def _prepare_param(v):
            if v is None:
                return None
            if isinstance(v, (dict, list, tuple)):
                return json.dumps(Database._sanitize_for_json(v), ensure_ascii=True)
            if isinstance(v, Decimal):
                try:
                    return float(v)
                except Exception:
                    return str(v)
            if isinstance(v, datetime):
                return v.isoformat()
            # For strings, leave as-is; truncation for DB-limited columns is handled below
            if isinstance(v, str):
                return v
            return v

        # Prepare params and then defensively truncate `confidence` to fit VARCHAR(50)
        prepared = [_prepare_param(p) for p in params]
        try:
            # confidence is the 6th parameter in this query
            conf_idx = 5
            conf_val = prepared[conf_idx]
            if conf_val is not None:
                # Ensure it's a string
                conf_str = str(conf_val)
                if len(conf_str) > 50:
                    prepared[conf_idx] = conf_str[:47] + '...'
                else:
                    prepared[conf_idx] = conf_str
        except Exception:
            # Be defensive: if anything goes wrong, coerce to None so insert won't fail
            try:
                prepared[5] = None
            except Exception:
                pass

        safe_params = tuple(prepared)
        return self.execute_scalar(query, safe_params)

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
        applications_table = self.get_table_name("applications") or 'applications'
        training_col = training_col or 'is_training_example'
        query = f"SELECT * FROM {applications_table} WHERE COALESCE({training_col}, FALSE) = FALSE ORDER BY uploaded_date DESC"
        rows = self.execute_query(query)
        # parse JSON columns if present
        for row in rows:
            for key in ("student_summary", "agent_results"):
                if key in row:
                    try:
                        row[key] = safe_load_json(row[key])
                    except Exception:
                        pass
        return rows

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
            # Parse the formatted_evaluation JSON if it's a string and create
            # a second key without underscores so templates written against the
            # old backup-style might still work.
            formatted_eval_key = next((k for k in result.keys() if 'formatted' in k.lower()), None)
            if formatted_eval_key:
                val = result.get(formatted_eval_key)
                if isinstance(val, str):
                    try:
                        parsed = safe_load_json(val)
                        result[formatted_eval_key] = parsed
                    except Exception:
                        # leave original string if parsing fails
                        pass
                # normalize result to always contain both variants so templates
                # can reference either key without worrying about missing data.
                canon = result.get(formatted_eval_key)
                result['formatted_evaluation'] = canon
                result['formattedevaluation'] = canon
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
                        result[app_ids_key] = safe_load_json(val)
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
                        result[app_ids_key] = safe_load_json(val)
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
                    result[triage_key] = safe_load_json(val)
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
                        result[triage_key] = safe_load_json(val)
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

    def update_application(self, application_id: int, **fields) -> None:
        """Update application record with arbitrary fields.

        If a provided field does not exist as a column in the `applications` table,
        this method will attempt to add a TEXT column to store the value.
        Values that are dict/list will be JSON-serialized.
        """
        if not fields:
            return

        applications_table = self.get_table_name('applications') or 'applications'
        # Resolve or create columns as needed
        updates = []
        values = []
        existing_cols = self._get_table_columns(applications_table)

        for key, val in fields.items():
            # normalize logical keys to column names when possible
            col_name = self.get_applications_column(key) or key
            # ensure column exists, otherwise attempt to add it as TEXT
            if col_name not in existing_cols:
                try:
                    conn = self.connect()
                    cur = conn.cursor()
                    alter_sql = f'ALTER TABLE {applications_table} ADD COLUMN "{col_name}" TEXT'
                    cur.execute(alter_sql)
                    conn.commit()
                    cur.close()
                    # refresh cache
                    self._table_columns_cache.pop(applications_table, None)
                    existing_cols = self._get_table_columns(applications_table)
                    logger.info(f"Added missing applications column: {col_name}")
                except Exception as e:
                    logger.warning(f"Could not add column {col_name} to {applications_table}: {e}")

            # prepare value
            if isinstance(val, (dict, list)):
                val = json.dumps(val)
            updates.append(f"\"{col_name}\" = %s")
            values.append(val)

        if not updates:
            return

        query = f"UPDATE {applications_table} SET {', '.join(updates)} WHERE application_id = %s"
        values.append(application_id)
        self.execute_non_query(query, tuple(values))

    def get_application_match_candidates(self, is_training: bool, is_test_data: bool, search_query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get potential application matches for a given upload type.

        This is a simplified, defensive implementation that avoids complex joins
        and missing-name variables. It returns recent applications filtered by
        training/test flags and an optional search query.
        """
        try:
            applications_table = self.get_table_name("applications") or 'applications'

            app_id_col = self.get_applications_column("application_id") or 'application_id'
            applicant_col = self.get_applications_column("applicant_name") or 'applicant_name'
            email_col = self.get_applications_column("email") or 'email'
            status_col = self.get_applications_column("status") or 'status'
            uploaded_col = self.get_applications_column("uploaded_date") or 'uploaded_date'
            was_selected_col = self.get_applications_column("was_selected") or 'was_selected'
            missing_fields_col = self.get_applications_column("missing_fields") or 'missing_fields'

            training_col = self.get_training_example_column() or 'is_training_example'
            test_col = self.get_test_data_column() or 'is_test_data'

            filters = [f"COALESCE(a.{training_col}, FALSE) = {'TRUE' if is_training else 'FALSE'}"]
            # Apply test data filter according to the flag requested
            filters.append(f"COALESCE(a.{test_col}, FALSE) = {'TRUE' if is_test_data else 'FALSE'}")

            params = []
            if search_query:
                filters.append(f"(a.{applicant_col} ILIKE %s OR a.{email_col} ILIKE %s)")
                params.extend([f"%{search_query}%", f"%{search_query}%"])

            where_clause = " AND ".join(filters)
            query = f"""
                SELECT
                    a.{app_id_col} as application_id,
                    a.{applicant_col} as applicant_name,
                    a.{email_col} as email,
                    a.{status_col} as status,
                    a.{uploaded_col} as uploaded_date,
                    a.{was_selected_col} as was_selected,
                    a.{missing_fields_col} as missing_fields,
                    COALESCE(a.{training_col}, FALSE) as is_training_example,
                    COALESCE(a.{test_col}, FALSE) as is_test_data
                FROM {applications_table} a
                WHERE {where_clause}
                ORDER BY LOWER(COALESCE(a.{applicant_col}, '')) ASC
                LIMIT 200
            """

            results = self.execute_query(query.format(
                app_id_col=app_id_col,
                applicant_col=applicant_col,
                email_col=email_col,
                status_col=status_col,
                uploaded_col=uploaded_col,
                was_selected_col=was_selected_col,
                missing_fields_col=missing_fields_col,
                training_col=training_col,
                test_col=test_col,
                applications_table=applications_table,
                where_clause=where_clause
            ), tuple(params) if params else None)

            formatted = []
            for row in results:
                parts = row.get('applicant_name', '').strip().split()
                first_name = parts[0] if parts else ''
                last_name = parts[-1] if len(parts) > 1 else ''

                missing_fields = []
                mf = row.get('missing_fields')
                if mf:
                    try:
                        missing_fields = safe_load_json(mf) if isinstance(mf, str) else mf
                    except Exception:
                        missing_fields = []

                formatted.append({
                    'application_id': row.get('application_id'),
                    'first_name': first_name,
                    'last_name': last_name,
                    'full_name': row.get('applicant_name'),
                    'email': row.get('email'),
                    'status': row.get('status'),
                    'uploaded_date': row.get('uploaded_date'),
                    'was_selected': bool(row.get('was_selected')) if row.get('was_selected') is not None else None,
                    'missing_fields': missing_fields,
                    'is_test_data': bool(row.get('is_test_data')),
                    'is_training_example': bool(row.get('is_training_example'))
                })

            return formatted
        except Exception as e:
            logger.error(f"Error getting application match candidates: {e}")
            return []

    # ==================== SCHOOL ENRICHMENT METHODS ====================
    
    def create_school_enriched_data(self, school_data: Dict[str, Any]) -> Optional[int]:
        """Create or upsert an enriched school record.
        
        If a school with the same name and state already exists, returns
        the existing record's ID instead of creating a duplicate.
        """
        # --- Dedup check: look for existing school by name + state ---
        school_name = school_data.get('school_name')
        state_code = school_data.get('state_code')
        if school_name and state_code:
            existing = self.get_school_enriched_data(
                school_name=school_name, state_code=state_code
            )
            if existing:
                logger.info(
                    f"School already exists, skipping duplicate: {school_name} ({state_code}) → ID {existing['school_enrichment_id']}"
                )
                return existing['school_enrichment_id']

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

    def delete_all_school_enriched_data(self) -> int:
        """Delete ALL school enriched data records and cascade to child tables.
        
        Returns:
            Number of records deleted
        """
        try:
            if not self.has_table("school_enriched_data"):
                logger.warning("School enrichment table missing: school_enriched_data")
                return 0
            
            # Count first
            count_result = self.execute_query("SELECT COUNT(*) as cnt FROM school_enriched_data")
            count = count_result[0]['cnt'] if count_result else 0
            
            # Child tables cascade via FK, but delete explicitly for safety
            child_tables = [
                'school_web_sources', 'school_academic_profile', 
                'school_salary_outcomes', 'school_analysis_history',
                'school_opportunity_index', 'school_data_versions'
            ]
            for table in child_tables:
                if self.has_table(table):
                    self.execute_non_query(f"DELETE FROM {table}")
            
            self.execute_non_query("DELETE FROM school_enriched_data")
            
            logger.info(f"Deleted {count} school enrichment records (and cascade children)")
            return count
        except Exception as e:
            logger.error(f"Error deleting all school enriched data: {e}")
            return 0

    def delete_school_enriched_data(self, school_id: int) -> bool:
        """Delete a single school enriched data record by ID.
        
        Args:
            school_id: The school_enrichment_id to delete
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            self.execute_non_query(
                "DELETE FROM school_enriched_data WHERE school_enrichment_id = %s",
                (school_id,)
            )
            logger.info(f"Deleted school enrichment record {school_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting school enrichment {school_id}: {e}")
            return False

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
            # Ensure the MOANA validation columns exist (defensive for older schemas)
            applications_table = 'school_enriched_data'
            try:
                cols = self._get_table_columns(applications_table)
                if 'moana_requirements_met' not in cols:
                    conn = self.connect()
                    cur = conn.cursor()
                    cur.execute("ALTER TABLE school_enriched_data ADD COLUMN IF NOT EXISTS moana_requirements_met BOOLEAN DEFAULT FALSE")
                    conn.commit()
                    cur.close()
                    # refresh cache
                    self._table_columns_cache.pop(applications_table, None)
                    cols = self._get_table_columns(applications_table)
                if 'last_moana_validation' not in cols:
                    conn = self.connect()
                    cur = conn.cursor()
                    cur.execute("ALTER TABLE school_enriched_data ADD COLUMN IF NOT EXISTS last_moana_validation TIMESTAMP")
                    conn.commit()
                    cur.close()
                    self._table_columns_cache.pop(applications_table, None)
            except Exception:
                # If we can't modify schema here, continue and let the normal update handle errors
                pass

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

    # =====================================================================
    # Historical Scores - 2024 cohort human-assigned rubric data
    # =====================================================================

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a student name for fuzzy matching.
        Handles 'Last, First' and 'First Last' formats.
        Strips whitespace, lowercases, removes extra punctuation.
        """
        if not name:
            return ""
        import re
        name = name.strip().lower()
        # Remove extra whitespace
        name = re.sub(r'\s+', ' ', name)
        # If "Last, First" → "first last"
        if ',' in name:
            parts = [p.strip() for p in name.split(',', 1)]
            if len(parts) == 2:
                name = f"{parts[1]} {parts[0]}"
        return name

    def insert_historical_score(self, score_data: Dict[str, Any]) -> Optional[int]:
        """Insert a single historical score row. Returns score_id or None."""
        try:
            # Truncate string values to prevent VARCHAR overflow
            def _safe_str(val, max_len=500):
                if val is None:
                    return None
                s = str(val).strip()
                return s[:max_len] if s else None

            query = """
                INSERT INTO historical_scores
                (cohort_year, applicant_name, applicant_name_normalized,
                 status, preliminary_score, quick_notes, reviewer_name, was_scored,
                 academic_record, stem_interest, essay_video, recommendation,
                 bonus, total_rating, eligibility_notes, previous_research_experience,
                 advanced_coursework, overall_rating, column_q,
                 import_source, row_number)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING score_id
            """
            normalized = self._normalize_name(score_data.get('applicant_name', ''))
            params = (
                score_data.get('cohort_year', 2024),
                _safe_str(score_data.get('applicant_name', ''), 255),
                normalized,
                _safe_str(score_data.get('status')),
                _safe_str(score_data.get('preliminary_score')),
                _safe_str(score_data.get('quick_notes'), 5000),
                _safe_str(score_data.get('reviewer_name'), 255),
                score_data.get('was_scored', False),
                score_data.get('academic_record'),
                score_data.get('stem_interest'),
                score_data.get('essay_video'),
                score_data.get('recommendation'),
                score_data.get('bonus'),
                score_data.get('total_rating'),
                _safe_str(score_data.get('eligibility_notes'), 5000),
                _safe_str(score_data.get('previous_research_experience'), 5000),
                _safe_str(score_data.get('advanced_coursework'), 5000),
                _safe_str(score_data.get('overall_rating'), 255),
                _safe_str(score_data.get('column_q'), 5000),
                _safe_str(score_data.get('import_source'), 500),
                score_data.get('row_number'),
            )
            return self.execute_scalar(query, params)
        except Exception as e:
            logger.error(f"Error inserting historical score: {e}")
            return None

    def bulk_insert_historical_scores(self, scores: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Bulk insert historical scores. Returns summary of results."""
        inserted = 0
        errors = 0
        for score in scores:
            result = self.insert_historical_score(score)
            if result:
                inserted += 1
            else:
                errors += 1
        return {"inserted": inserted, "errors": errors, "total": len(scores)}

    def get_historical_scores(self, cohort_year: Optional[int] = None,
                               status: Optional[str] = None,
                               scored_only: bool = False) -> List[Dict[str, Any]]:
        """Get historical scores with optional filters."""
        conditions = []
        params = []
        if cohort_year:
            conditions.append("cohort_year = %s")
            params.append(cohort_year)
        if status:
            conditions.append("LOWER(status) = LOWER(%s)")
            params.append(status)
        if scored_only:
            conditions.append("was_scored = TRUE")

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM historical_scores {where} ORDER BY applicant_name"
        return self.execute_query(query, tuple(params) if params else None)

    def get_historical_score_by_name(self, name: str, cohort_year: int = 2024) -> Optional[Dict[str, Any]]:
        """Find a historical score by fuzzy name matching.
        Tries exact normalized match first, then LIKE-based partial match.
        """
        normalized = self._normalize_name(name)
        if not normalized:
            return None

        # Exact normalized match
        query = """
            SELECT * FROM historical_scores
            WHERE applicant_name_normalized = %s AND cohort_year = %s
            LIMIT 1
        """
        results = self.execute_query(query, (normalized, cohort_year))
        if results:
            return results[0]

        # Partial match: try last name + first initial
        parts = normalized.split()
        if len(parts) >= 2:
            # Try "first% last%" pattern
            like_pattern = f"%{parts[0]}%{parts[-1]}%"
            query = """
                SELECT * FROM historical_scores
                WHERE applicant_name_normalized LIKE %s AND cohort_year = %s
                ORDER BY applicant_name_normalized
                LIMIT 1
            """
            results = self.execute_query(query, (like_pattern, cohort_year))
            if results:
                return results[0]

            # Try reversed: "last% first%"
            like_pattern_rev = f"%{parts[-1]}%{parts[0]}%"
            results = self.execute_query(query, (like_pattern_rev, cohort_year))
            if results:
                return results[0]

        return None

    def link_historical_score_to_application(self, score_id: int, application_id: int,
                                                was_selected: Optional[bool] = None) -> bool:
        """Link a historical score record to an application.
        Optionally propagates was_selected from the application."""
        try:
            if was_selected is not None:
                query = "UPDATE historical_scores SET application_id = %s, was_selected = %s WHERE score_id = %s"
                self.execute_non_query(query, (application_id, was_selected, score_id))
            else:
                query = "UPDATE historical_scores SET application_id = %s WHERE score_id = %s"
                self.execute_non_query(query, (application_id, score_id))
            return True
        except Exception as e:
            logger.error(f"Error linking historical score {score_id} to application {application_id}: {e}")
            return False

    def get_unmatched_training_students(self) -> List[Dict[str, Any]]:
        """Get training students that have no linked historical score record."""
        try:
            applications_table = self.get_table_name("applications") or "applications"
            app_id_col = self.get_applications_column("application_id") or "application_id"
            applicant_col = self.get_applications_column("applicant_name") or "applicant_name"
            email_col = self.get_applications_column("email") or "email"
            training_col = self.get_training_example_column() or "is_training_example"
            test_col = self.get_test_data_column() or "is_test_data"

            extra_cols = []
            for col in ('first_name', 'last_name'):
                if self.has_applications_column(col):
                    extra_cols.append(f"a.{col}")
            extra_fragment = (", " + ", ".join(extra_cols)) if extra_cols else ""

            query = f"""
                SELECT a.{app_id_col} AS application_id,
                       a.{applicant_col} AS applicant_name,
                       a.{email_col} AS email
                       {extra_fragment}
                FROM {applications_table} a
                LEFT JOIN historical_scores hs ON hs.application_id = a.{app_id_col}
                WHERE a.{training_col} = TRUE
                  AND (a.{test_col} = FALSE OR a.{test_col} IS NULL)
                  AND hs.score_id IS NULL
                ORDER BY LOWER(a.{applicant_col}) ASC
            """
            rows = self.execute_query(query)
            results = []
            for r in rows:
                name = r.get('applicant_name', '')
                parts = name.strip().split() if name else []
                results.append({
                    'application_id': r.get('application_id'),
                    'applicant_name': name,
                    'first_name': r.get('first_name') or (parts[0] if parts else ''),
                    'last_name': r.get('last_name') or (parts[-1] if len(parts) > 1 else ''),
                    'email': r.get('email'),
                })
            return results
        except Exception as e:
            logger.error(f"Error getting unmatched training students: {e}")
            return []

    def search_unlinked_historical_scores(self, search: str, cohort_year: int = 2024) -> List[Dict[str, Any]]:
        """Search historical scores that are NOT yet linked to any application."""
        try:
            if not search or not search.strip():
                # Return all unlinked scores
                query = """
                    SELECT score_id, applicant_name, status, was_selected, was_scored,
                           total_rating, academic_record, stem_interest, essay_video,
                           recommendation, bonus
                    FROM historical_scores
                    WHERE cohort_year = %s AND application_id IS NULL
                    ORDER BY applicant_name
                    LIMIT 50
                """
                return self.execute_query(query, (cohort_year,))

            normalized = self._normalize_name(search)
            query = """
                SELECT score_id, applicant_name, status, was_selected, was_scored,
                       total_rating, academic_record, stem_interest, essay_video,
                       recommendation, bonus
                FROM historical_scores
                WHERE cohort_year = %s
                  AND application_id IS NULL
                  AND (applicant_name_normalized ILIKE %s OR applicant_name ILIKE %s)
                ORDER BY applicant_name
                LIMIT 20
            """
            pattern = f"%{normalized}%"
            return self.execute_query(query, (cohort_year, pattern, f"%{search.strip()}%"))
        except Exception as e:
            logger.error(f"Error searching unlinked historical scores: {e}")
            return []

    def get_historical_stats(self, cohort_year: int = 2024) -> Dict[str, Any]:
        """Get aggregate stats for a cohort year's historical scores.
        
        Note on terminology:
        - 'eligible' (status='accepted') = met basic requirements (files, age, deadline)
        - 'selected' (was_selected=TRUE) = actually chosen for the program
        """
        try:
            query = """
                SELECT
                    COUNT(*) as total_applicants,
                    COUNT(CASE WHEN LOWER(status) = 'accepted' THEN 1 END) as eligible,
                    COUNT(CASE WHEN LOWER(status) != 'accepted' OR status IS NULL THEN 1 END) as not_eligible,
                    COUNT(CASE WHEN was_selected = TRUE THEN 1 END) as selected,
                    COUNT(CASE WHEN was_selected = FALSE THEN 1 END) as not_selected,
                    COUNT(CASE WHEN was_selected IS NULL THEN 1 END) as selection_unknown,
                    COUNT(CASE WHEN was_scored = TRUE THEN 1 END) as scored_count,
                    AVG(CASE WHEN was_scored THEN total_rating END) as avg_total_rating,
                    AVG(CASE WHEN was_scored THEN academic_record END) as avg_academic_record,
                    AVG(CASE WHEN was_scored THEN stem_interest END) as avg_stem_interest,
                    AVG(CASE WHEN was_scored THEN essay_video END) as avg_essay_video,
                    AVG(CASE WHEN was_scored THEN recommendation END) as avg_recommendation,
                    AVG(CASE WHEN was_scored THEN bonus END) as avg_bonus,
                    AVG(CASE WHEN was_scored AND was_selected = TRUE THEN total_rating END) as avg_selected_total,
                    AVG(CASE WHEN was_scored AND was_selected = FALSE THEN total_rating END) as avg_not_selected_total,
                    AVG(CASE WHEN was_scored AND LOWER(status) = 'accepted' THEN total_rating END) as avg_eligible_total,
                    COUNT(CASE WHEN application_id IS NOT NULL THEN 1 END) as linked_to_applications
                FROM historical_scores
                WHERE cohort_year = %s
            """
            results = self.execute_query(query, (cohort_year,))
            if results:
                row = results[0]
                # Convert Decimal values to float for JSON serialization
                return {k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()}
            return {}
        except Exception as e:
            logger.error(f"Error getting historical stats: {e}")
            return {}

    def get_historical_scores_for_milo(self, cohort_year: int = 2024) -> Dict[str, Any]:
        """Get historical scores formatted for Milo's calibration.
        
        Groups by was_selected (actual program selection), NOT by status
        (which only indicates eligibility — correct files, age, on-time).
        
        Returns selected vs not-selected samples with rubric dimensions.
        When was_selected is unknown, falls back to eligible grouping with a warning.
        """
        try:
            all_scores = self.get_historical_scores(cohort_year=cohort_year, scored_only=True)
            stats = self.get_historical_stats(cohort_year)

            selected = []
            not_selected = []
            selection_unknown = []
            for row in all_scores:
                entry = {
                    "applicant_name": row.get("applicant_name"),
                    "eligible": (row.get("status") or "").lower() == "accepted",
                    "was_selected": row.get("was_selected"),
                    "preliminary_score": row.get("preliminary_score"),
                    "academic_record": float(row["academic_record"]) if row.get("academic_record") is not None else None,
                    "stem_interest": float(row["stem_interest"]) if row.get("stem_interest") is not None else None,
                    "essay_video": float(row["essay_video"]) if row.get("essay_video") is not None else None,
                    "recommendation": float(row["recommendation"]) if row.get("recommendation") is not None else None,
                    "bonus": float(row["bonus"]) if row.get("bonus") is not None else None,
                    "total_rating": float(row["total_rating"]) if row.get("total_rating") is not None else None,
                    "overall_rating": row.get("overall_rating"),
                    "previous_research_experience": row.get("previous_research_experience"),
                    "reviewer_name": row.get("reviewer_name"),
                }
                if row.get("was_selected") is True:
                    selected.append(entry)
                elif row.get("was_selected") is False:
                    not_selected.append(entry)
                else:
                    selection_unknown.append(entry)

            has_selection_data = len(selected) > 0 or len(not_selected) > 0

            return {
                "cohort_year": cohort_year,
                "stats": stats,
                "selected_scores": selected,
                "not_selected_scores": not_selected,
                "selection_unknown_scores": selection_unknown,
                "has_selection_data": has_selection_data,
                "total_scored": len(all_scores),
                "note": (
                    "Grouped by actual program selection (was_selected)."
                    if has_selection_data else
                    "Selection data not yet available. Upload 2024 applications and flag "
                    "who was selected to enable model building. Current 'eligible' status "
                    "only means the student had correct files, age, and submitted on time."
                ),
            }
        except Exception as e:
            logger.error(f"Error getting historical scores for Milo: {e}")
            return {"error": str(e)}

    def clear_historical_scores(self, cohort_year: int = 2024) -> int:
        """Delete all historical scores for a given cohort year. Returns count deleted."""
        try:
            query = "DELETE FROM historical_scores WHERE cohort_year = %s"
            conn = self.connect()
            cursor = conn.cursor()
            cursor.execute(query, (cohort_year,))
            deleted = cursor.rowcount
            conn.commit()
            cursor.close()
            return deleted
        except Exception as e:
            logger.error(f"Error clearing historical scores: {e}")
            return 0


# Create a singleton instance for module-level import
db = Database()
