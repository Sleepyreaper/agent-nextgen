#!/usr/bin/env python3
"""Add is_test_data column to distinguish test data from production data."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Database

def migrate():
    """Add is_test_data column to applications table."""
    db = Database()
    
    print("Adding is_test_data column to applications table...")
    
    try:
        # Add column if it doesn't exist
        db.execute_non_query("""
            ALTER TABLE applications 
            ADD COLUMN IF NOT EXISTS is_test_data BOOLEAN DEFAULT FALSE
        """)
        
        print("✅ Successfully added is_test_data column")
        print("\nData categories:")
        print("  📊 Production (2026): is_training_example=FALSE AND is_test_data=FALSE")
        print("  🧪 Test Data: is_test_data=TRUE (for quick test students)")
        print("  📚 Training: is_training_example=TRUE (for training examples)")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate()
