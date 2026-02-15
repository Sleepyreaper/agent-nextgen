#!/usr/bin/env python3
"""Quick database status check."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.database import Database

db = Database()
apps = db.execute_query('SELECT COUNT(*) as count FROM applications')
count = apps[0]['count'] if apps else 0

if count == 0:
    print('✅ DATABASE IS EMPTY - Ready for use!')
    print('\n📝 Data separation structure:')
    print('   • Training Data: is_training_example = TRUE')
    print('   • Test Data: Separate test applications')
    print('   • 2026 Production: Real student applications')
else:
    print(f'Database has {count} applications')
