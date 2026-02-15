#!/usr/bin/env python3
"""Setup PostgreSQL database and app user"""
import os
import psycopg
import secrets
import string

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

# Generate secure password
pwd = ''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*_-') for _ in range(24))

try:
    print("Connecting to PostgreSQL...")
    conn = psycopg.connect(host=HOST, port=5432, dbname='postgres', user=ADMIN_USER, password=ADMIN_PASS, sslmode='require')
    conn.autocommit = True
    cur = conn.cursor()
    
    print("Creating database...")
    try:
        cur.execute(f'CREATE DATABASE {DB_NAME}')
        print(f'  ✅ Database created: {DB_NAME}')
    except psycopg.errors.DuplicateDatabase:
        print(f'  ℹ️  Database exists: {DB_NAME}')
    
    print("Creating application user...")
    try:
        cur.execute(f"CREATE USER {APP_USER} WITH PASSWORD '{pwd}'")
        print(f'  ✅ User created: {APP_USER}')
    except psycopg.errors.DuplicateObject:
        cur.execute(f"ALTER USER {APP_USER} WITH PASSWORD '{pwd}'")
        print(f'  ✅ User updated: {APP_USER}')
    
    print("Granting privileges...")
    cur.execute(f'GRANT CONNECT ON DATABASE {DB_NAME} TO {APP_USER}')
    cur.execute(f'GRANT USAGE ON SCHEMA public TO {APP_USER}')
    cur.execute(f'GRANT CREATE ON SCHEMA public TO {APP_USER}')
    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {APP_USER}')
    cur.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {APP_USER}')
    print('  ✅ Privileges granted')
    
    conn.close()
    
    print("\n✅ Setup Complete!\n")
    print(f"Database:  {DB_NAME}")
    print(f"App User:  {APP_USER}")
    print(f"Password:  {pwd}")
    print()
    print("Store in Key Vault:")
    print(f"  postgres-host:     {HOST}")
    print(f"  postgres-port:     5432")
    print(f"  postgres-database: {DB_NAME}")
    print(f"  postgres-username: {APP_USER}")
    print(f"  postgres-password: {pwd}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
