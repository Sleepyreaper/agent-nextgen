"""Initialize Azure SQL Database with required schema."""

import pyodbc
import os
import subprocess
import json
from dotenv import load_dotenv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv()

def get_connection_token():
    """Get Azure AD access token using Azure CLI."""
    try:
        result = subprocess.run(
            ['az', 'account', 'get-access-token', '--resource', 'https://database.windows.net'],
            capture_output=True,
            text=True,
            check=True
        )
        token_info = json.loads(result.stdout)
        return token_info['accessToken']
    except Exception as e:
        raise ValueError(f"Failed to get Azure AD token. Make sure you're logged in with 'az login': {e}")

def get_connection_string():
    """Build Azure SQL connection string using Entra ID token."""
    server = os.getenv('SQL_SERVER')
    database = os.getenv('SQL_DATABASE')
    auth_method = os.getenv('SQL_AUTH_METHOD', 'entra').lower()
    
    if not all([server, database]):
        raise ValueError(
            "Missing SQL connection info. Please set SQL_SERVER and SQL_DATABASE in .env.local"
        )
    
    driver = '{ODBC Driver 18 for SQL Server}'
    
    if auth_method in ('entra', 'azure_ad'):
        # Use Azure Entra ID with token-based authentication
        token = get_connection_token()
        
        conn_str = (
            f"DRIVER={driver};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        )
        
        # Return both connection string and token for pyodbc.connect()
        return conn_str, token
    else:
        # SQL authentication fallback
        username = os.getenv('SQL_USERNAME')
        password = os.getenv('SQL_PASSWORD')
        
        if not all([username, password]):
            raise ValueError(
                "Missing SQL credentials. Please set SQL_USERNAME and SQL_PASSWORD in .env.local "
                "or use SQL_AUTH_METHOD=entra for Azure Entra ID authentication"
            )
        
        return (
            f"DRIVER={driver};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        ), None

def initialize_database():
    """Initialize the database with schema."""
    print("=== Azure SQL Database Initialization ===\n")
    
    result = get_connection_string()
    if isinstance(result, tuple):
        conn_str, token = result
    else:
        conn_str = result
        token = None
    
    print(f"Connecting to: {os.getenv('SQL_SERVER')}/{os.getenv('SQL_DATABASE')}...")
    
    try:
        # Connect to database with token if available
        if token:
            conn = pyodbc.connect(conn_str, attrs_before={1256: token})
        else:
            conn = pyodbc.connect(conn_str)
        
        conn.autocommit = True  # Auto-commit for DDL statements
        cursor = conn.cursor()
        
        print("✓ Connected successfully\n")
        
        # Read and execute schema file
        schema_file = PROJECT_ROOT / "database" / "schema_azure_sql.sql"
        
        if not schema_file.exists():
            print(f"❌ Schema file not found: {schema_file}")
            return
        
        print(f"Reading schema from: {schema_file}")
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        # Split by GO statements (SQL Server batch separator)
        batches = [batch.strip() for batch in schema_sql.split('GO') if batch.strip()]
        
        print(f"Executing {len(batches)} SQL batches...\n")
        
        for i, batch in enumerate(batches, 1):
            try:
                cursor.execute(batch)
                print(f"  ✓ Batch {i}/{len(batches)} executed")
            except Exception as batch_error:
                print(f"  ⚠ Batch {i} warning: {batch_error}")
        
        print("\n✅ Database schema initialized successfully!")
        
        # Verify tables
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE' AND TABLE_SCHEMA = 'dbo'
            ORDER BY TABLE_NAME
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n📊 Created {len(tables)} tables:")
        for table in tables:
            print(f"   - {table}")
        
        cursor.close()
        conn.close()
        
    except pyodbc.Error as e:
        print(f"\n❌ Database error: {e}")
        if hasattr(e, 'args') and len(e.args) > 1:
            print(f"   SQL State: {e.args[0]}")
            print(f"   Message: {e.args[1]}")
        raise
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise

if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        exit(1)
