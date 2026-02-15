#!/usr/bin/env python3
"""Add student_id column to Applications table"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

def migrate():
    """Add student_id column if it doesn't exist"""
    
    try:
        # Check if column exists
        check_query = """
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='applications' AND column_name='student_id'
        """
        
        result = db.execute_query(check_query)
        if result:
            print("✓ student_id column already exists")
            return True
        
        # Add the column
        print("Adding student_id column to Applications table...")
        add_column_query = """
        ALTER TABLE applications
        ADD COLUMN student_id VARCHAR(64) UNIQUE
        """
        
        db.execute_non_query(add_column_query)
        print("✓ student_id column added successfully")
        
        # Add index for better query performance
        print("Adding index on student_id...")
        index_query = """
        CREATE INDEX IF NOT EXISTS idx_applications_student_id 
        ON applications(student_id)
        """
        
        db.execute_non_query(index_query)
        print("✓ Index created on student_id")
        
        return True
        
    except Exception as e:
        print(f"✗ Error adding student_id column: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    success = migrate()
    sys.exit(0 if success else 1)
