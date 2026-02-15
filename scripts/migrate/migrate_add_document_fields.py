#!/usr/bin/env python3
"""Add document storage fields to applications table."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Database

def migrate():
    """Add evaluation_document_path, evaluation_document_url, and document_generated_at columns."""
    db = Database()
    
    print("Adding document storage fields to applications table...")
    
    try:
        # Add columns if they don't exist
        db.execute_non_query("""
            ALTER TABLE applications 
            ADD COLUMN IF NOT EXISTS evaluation_document_path TEXT,
            ADD COLUMN IF NOT EXISTS evaluation_document_url TEXT,
            ADD COLUMN IF NOT EXISTS document_generated_at TIMESTAMP
        """)
        
        print("✅ Successfully added document storage fields")
        print("   - evaluation_document_path: Local file path to evaluation document")
        print("   - evaluation_document_url: Azure Storage URL for evaluation document")
        print("   - document_generated_at: Timestamp when document was created")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        raise

if __name__ == "__main__":
    migrate()
