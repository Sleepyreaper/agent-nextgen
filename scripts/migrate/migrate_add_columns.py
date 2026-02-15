#!/usr/bin/env python3
"""Run database migration to add transcript and recommendation columns."""

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Database

load_dotenv('.env.local')

print("Starting migration...")

db = Database()

try:
    print("Adding TranscriptText column...")
    db.execute_non_query('ALTER TABLE Applications ADD COLUMN IF NOT EXISTS TranscriptText TEXT')
    
    print("Adding RecommendationText column...")
    db.execute_non_query('ALTER TABLE Applications ADD COLUMN IF NOT EXISTS RecommendationText TEXT')
    
    print('✅ Migration successful - added TranscriptText and RecommendationText columns')
    sys.exit(0)
    
except Exception as e:
    print(f'❌ Migration failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
