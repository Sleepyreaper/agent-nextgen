#!/usr/bin/env python3
"""Quick test of PostgreSQL connection."""
from src.database import Database

print('Testing Azure PostgreSQL Flexible Server connection...')
try:
    db = Database()
    result = db.execute_query('SELECT version(), current_database(), current_user')
    if result:
        print('✅ Connected successfully!')
        print(f"  Database: {result[0]['current_database']}")
        print(f"  User: {result[0]['current_user']}")
        print(f"  Version: {result[0]['version'][:70]}")
    else:
        print('❌ No results returned')
except Exception as e:
    print(f'❌ Connection failed: {type(e).__name__}: {e}')
