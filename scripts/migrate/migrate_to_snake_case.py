#!/usr/bin/env python3
"""
Migrate database schema from PascalCase to snake_case table/column names.
This ensures compatibility with the Python conventions and psycopg expectations.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Database


def rename_table_and_columns(db: Database, old_table: str, new_table: str, column_mappings: dict):
    """
    Rename a table and its columns.
    column_mappings: dict of {'old_column_name': 'new_column_name', ...}
    """
    try:
        conn = db.connect()
        cursor = conn.cursor()
        
        print(f"\nMigrating {old_table} → {new_table}")
        
        # Create new table with correct column names
        cursor.execute(f"DROP TABLE IF EXISTS {new_table} CASCADE")
        
        # Build CREATE TABLE statement by examining old table
        cursor.execute(f"""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (old_table.lower(),))
        
        columns = cursor.fetchall()
        if not columns:
            print(f"  ⚠️  Table {old_table} not found, skipping")
            return False
        
        # Build CREATE TABLE statement
        create_columns = []
        for col_name, data_type, is_nullable, default in columns:
            # Map old column name to new one
            new_col_name = column_mappings.get(col_name, col_name.lower())
            
            col_def = f"{new_col_name} {data_type}"
            if default and 'nextval' not in default:
                col_def += f" DEFAULT {default}"
            if is_nullable == 'NO':
                col_def += " NOT NULL"
            
            create_columns.append(col_def)
        
        # Create the new table (without constraints initially)
        create_stmt = f"CREATE TABLE {new_table} ({', '.join(create_columns)})"
        cursor.execute(create_stmt)
        
        # Copy data from old table
        select_cols = []
        insert_cols = []
        for col_name, _, _, _ in columns:
            select_cols.append(col_name)
            new_col_name = column_mappings.get(col_name, col_name.lower())
            insert_cols.append(new_col_name)
        
        copy_stmt = f"""
            INSERT INTO {new_table} ({', '.join(insert_cols)})
            SELECT {', '.join(select_cols)} FROM {old_table}
        """
        cursor.execute(copy_stmt)
        
        conn.commit()
        print(f"  ✅ Migrated {cursor.rowcount if hasattr(cursor, 'rowcount') else '?'} rows")
        
        # Drop old table
        cursor.execute(f"DROP TABLE IF EXISTS {old_table} CASCADE")
        conn.commit()
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        conn.rollback()
        return False


def main():
    print("=" * 60)
    print(" PostgreSQL Schema Migration: PascalCase → snake_case")
    print("=" * 60)
    
    try:
        db = Database()
        db.connect()
        
        # Define table renames and column renames
        migrations = {
            'Applications': {
                'table_name': 'Applications',
                'columns': {
                    'ApplicationID': 'application_id',
                    'ApplicantName': 'applicant_name',
                    'Email': 'email',
                    'PhoneNumber': 'phone_number',
                    'Position': 'position',
                    'UploadedDate': 'uploaded_date',
                    'ApplicationText': 'application_text',
                    'OriginalFileName': 'original_file_name',
                    'FileType': 'file_type',
                    'BlobStoragePath': 'blob_storage_path',
                    'IsTrainingExample': 'is_training_example',
                    'WasSelected': 'was_selected',
                    'Status': 'status',
                    'CreatedBy': 'created_by',
                    'UpdatedDate': 'updated_date',
                    'Notes': 'notes',
                    'RecommendationText': 'recommendation_text',
                    'TranscriptText': 'transcript_text'
                }
            },
            'AIEvaluations': {
                'table_name': 'ai_evaluations',
                'columns': {
                    'EvaluationID': 'evaluation_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'EvaluationDate': 'evaluation_date',
                    'OverallScore': 'overall_score',
                    'TechnicalSkillsScore': 'technical_skills_score',
                    'CommunicationScore': 'communication_score',
                    'ExperienceScore': 'experience_score',
                    'CulturalFitScore': 'cultural_fit_score',
                    'Strengths': 'strengths',
                    'Weaknesses': 'weaknesses',
                    'Recommendation': 'recommendation',
                    'DetailedAnalysis': 'detailed_analysis',
                    'ComparisonToExcellence': 'comparison_to_excellence',
                    'ModelUsed': 'model_used',
                    'ProcessingTimeMs': 'processing_time_ms'
                }
            },
            'TianaApplications': {
                'table_name': 'tiana_applications',
                'columns': {
                    'TianaApplicationID': 'tiana_application_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'EssaySummary': 'essay_summary',
                    'RecommendationTexts': 'recommendation_texts',
                    'ReadinessScore': 'readiness_score',
                    'Confidence': 'confidence',
                    'ParsedJson': 'parsed_json',
                    'CreatedAt': 'created_at'
                }
            },
            'MulanRecommendations': {
                'table_name': 'mulan_recommendations',
                'columns': {
                    'MulanRecommendationID': 'mulan_recommendation_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'RecommenderName': 'recommender_name',
                    'RecommenderRole': 'recommender_role',
                    'EndorsementStrength': 'endorsement_strength',
                    'SpecificityScore': 'specificity_score',
                    'Summary': 'summary',
                    'RawText': 'raw_text',
                    'ParsedJson': 'parsed_json',
                    'CreatedAt': 'created_at'
                }
            },
            'MerlinEvaluations': {
                'table_name': 'merlin_evaluations',
                'columns': {
                    'MerlinEvaluationID': 'merlin_evaluation_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'OverallScore': 'overall_score',
                    'Recommendation': 'recommendation',
                    'Rationale': 'rationale',
                    'Confidence': 'confidence',
                    'ParsedJson': 'parsed_json',
                    'CreatedAt': 'created_at'
                }
            },
            'AuroraEvaluations': {
                'table_name': 'aurora_evaluations',
                'columns': {
                    'AuroraEvaluationID': 'aurora_evaluation_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'FormattedEvaluation': 'formatted_evaluation',
                    'MerlinScore': 'merlin_score',
                    'MerlinRecommendation': 'merlin_recommendation',
                    'AgentsCompleted': 'agents_completed',
                    'CreatedAt': 'created_at',
                    'UpdatedAt': 'updated_at'
                }
            },
            'AgentAuditLogs': {
                'table_name': 'agent_audit_logs',
                'columns': {
                    'AuditID': 'audit_id',
                    'ApplicationID': 'application_id',
                    'AgentName': 'agent_name',
                    'SourceFileName': 'source_file_name',
                    'CreatedAt': 'created_at'
                }
            },
            'StudentSchoolContext': {
                'table_name': 'student_school_context',
                'columns': {
                    'ContextID': 'context_id',
                    'ApplicationID': 'application_id',
                    'SchoolID': 'school_id',
                    'SchoolName': 'school_name',
                    'ProgramAccessScore': 'program_access_score',
                    'ProgramParticipationScore': 'program_participation_score',
                    'RelativeAdvantageScore': 'relative_advantage_score',
                    'APCoursesAvailable': 'ap_courses_available',
                    'APCoursesTaken': 'ap_courses_taken',
                    'IBCoursesAvailable': 'ib_courses_available',
                    'IBCoursesTaken': 'ib_courses_taken',
                    'HonorsCoursesTaken': 'honors_courses_taken',
                    'STEMProgramsAvailable': 'stem_programs_available',
                    'STEMProgramsAccessed': 'stem_programs_accessed',
                    'SchoolSESLevel': 'school_ses_level',
                    'MedianHouseholdIncome': 'median_household_income',
                    'FreeLunchPct': 'free_lunch_pct',
                    'PercentageOfPeersUsingPrograms': 'percentage_of_peers_using_programs',
                    'ComparisonNotes': 'comparison_notes',
                    'CreatedAt': 'created_at'
                }
            },
            'TestSubmissions': {
                'table_name': 'test_submissions',
                'columns': {
                    'SessionID': 'session_id',
                    'StudentCount': 'student_count',
                    'ApplicationIDs': 'application_ids',
                    'Status': 'status',
                    'CreatedAt': 'created_at',
                    'UpdatedAt': 'updated_at'
                }
            }
        }
        
        success_count = 0
        for old_table, config in migrations.items():
            if rename_table_and_columns(db, old_table, config['table_name'], config['columns']):
                success_count += 1
        
        print(f"\n{'=' * 60}")
        print(f"Migration Summary: {success_count}/{len(migrations)} tables migrated")
        print("=" * 60)
        
        db.close()
        return 0 if success_count == len(migrations) else 1
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
