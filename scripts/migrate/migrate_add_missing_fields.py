#!/usr/bin/env python3
"""Add missing_fields column for tracking what info is needed per student."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import db

def migrate():
    """Add missing_fields column to Applications table."""
    try:
        # Check if column exists
        check_query = """
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='applications' AND column_name='missing_fields'
        """
        result = db.execute_query(check_query)
        
        if result:
            print("✓ missing_fields column already exists")
            return True
        
        # Add the column
        print("Adding missing_fields column to Applications table...")
        add_column_query = """
        ALTER TABLE applications
        ADD COLUMN missing_fields JSONB DEFAULT '[]'::jsonb
        """
        
        db.execute_non_query(add_column_query)
        print("✓ missing_fields column added")
        
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
