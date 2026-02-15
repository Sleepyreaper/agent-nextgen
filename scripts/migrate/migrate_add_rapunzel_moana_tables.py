#!/usr/bin/env python3
"""Add rapunzel_grades and update school context tables"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

def migrate():
    """Add rapunzel_grades table and ensure moana can be queried properly."""
    
    try:
        # Check if rapunzel_grades table exists
        check_rapunzel = """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_name='rapunzel_grades'
        )
        """
        result = db.execute_query(check_rapunzel)
        
        if not result or not result[0].get('exists', False):
            print("Creating rapunzel_grades table...")
            create_rapunzel = """
            CREATE TABLE IF NOT EXISTS rapunzel_grades (
                rapunzel_grade_id SERIAL PRIMARY KEY,
                application_id INTEGER REFERENCES Applications(application_id) ON DELETE CASCADE,
                agent_name VARCHAR(255) DEFAULT 'Rapunzel',
                gpa NUMERIC(5,2),
                academic_strength VARCHAR(255),
                course_levels JSONB,
                transcript_quality VARCHAR(255),
                notable_patterns JSONB,
                confidence_level VARCHAR(50),
                summary TEXT,
                parsed_json JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
            db.execute_non_query(create_rapunzel)
            
            # Create index
            create_index = """
            CREATE INDEX IF NOT EXISTS idx_rapunzel_grades_app_id 
            ON rapunzel_grades(application_id)
            """
            db.execute_non_query(create_index)
            print("✓ rapunzel_grades table created")
        else:
            print("✓ rapunzel_grades table already exists")
        
        # Verify student_school_context exists and has necessary columns
        print("Verifying student_school_context table...")
        verify_moana = """
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='student_school_context'
        ORDER BY column_name
        """
        columns = db.execute_query(verify_moana)
        column_names = [col['column_name'] for col in columns]
        print(f"✓ student_school_context has {len(column_names)} columns")
        
        # Check for parsed_json column
        if 'parsed_json' not in column_names:
            print("Adding parsed_json column to student_school_context...")
            add_parsed_json = """
            ALTER TABLE student_school_context
            ADD COLUMN parsed_json JSONB DEFAULT NULL
            """
            db.execute_non_query(add_parsed_json)
            print("✓ parsed_json column added to student_school_context")
        else:
            print("✓ parsed_json column already exists")
        
        print("\n✅ Migration complete!")
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
