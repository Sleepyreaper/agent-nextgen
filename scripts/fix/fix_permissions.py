#!/usr/bin/env python3
"""Fix PostgreSQL app user permissions"""
import psycopg

import os

HOST = os.getenv('POSTGRES_HOST')
DB_NAME = os.getenv('POSTGRES_DB')
APP_USER = os.getenv('POSTGRES_APP_USER', 'agent_app_user')
ADMIN_USER = os.getenv('POSTGRES_ADMIN_USER')
ADMIN_PASS = os.getenv('POSTGRES_ADMIN_PASSWORD')

missing = [
    name for name, value in {
        'POSTGRES_HOST': HOST,
        'POSTGRES_DB': DB_NAME,
        'POSTGRES_ADMIN_USER': ADMIN_USER,
        'POSTGRES_ADMIN_PASSWORD': ADMIN_PASS
    }.items()
    if not value
]
if missing:
    raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

try:
    print("Connecting to PostgreSQL as admin...")
    conn = psycopg.connect(host=HOST, port=5432, dbname=DB_NAME, user=ADMIN_USER, password=ADMIN_PASS, sslmode='require')
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Granting additional permissions to app user...")
    
    # Grant privileges on schema
    cur.execute(f'GRANT ALL PRIVILEGES ON SCHEMA public TO {APP_USER}')
    print(f'  ✅ Granted SCHEMA privileges to {APP_USER}')
    
    # Set default privileges for new tables
    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {APP_USER}')
    print(f'  ✅ Set default table privileges')
    
    # Set default privileges for new sequences
    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {APP_USER}')
    print(f'  ✅ Set default sequence privileges')
    
    # Explicitly grant on existing tables (if any)
    cur.execute(f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {APP_USER}')
    print(f'  ✅ Granted privileges on existing tables')
    
    cur.execute(f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {APP_USER}')
    print(f'  ✅ Granted privileges on existing sequences')
    
    print("\n✅ Permission fixes applied!")
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
