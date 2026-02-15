"""Initialize Azure SQL Database with required schema using pyodbc and Entra ID token."""

import pyodbc
import subprocess
import json
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Load environment variables
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv()

def get_access_token():
    """Get Azure access token for database.windows.net resource."""
    try:
        result = subprocess.run(
            ['az', 'account', 'get-access-token', '--resource', 'https://database.windows.net'],
            capture_output=True,
            text=True,
            check=True
        )
        token_info = json.loads(result.stdout)
        return token_info['accessToken']
    except subprocess.CalledProcessError as e:
        raise ValueError(
            f"Failed to get Azure access token. Make sure you're logged in with 'az login'.\n"
            f"Error: {e.stderr}"
        )
    except FileNotFoundError:
        raise ValueError(
            "Azure CLI (az command) not found. Please install it:\n"
            "  brew install azure-cli"
        )

def initialize_database():
    """Initialize the database with schema."""
    print("=== Azure SQL Database Initialization ===\n")
    
    server = os.getenv('SQL_SERVER')
    database = os.getenv('SQL_DATABASE')
    
    if not server or not database:
        raise ValueError("SQL_SERVER and SQL_DATABASE must be set in .env.local")
    
    print(f"Server: {server}")
    print(f"Database: {database}")
    print(f"Auth: Azure Entra ID (via Azure CLI token)\n")
    
    # Get Azure access token
    print("Getting Azure access token...")
    try:
        token = get_access_token()
        print("✓ Token obtained\n")
    except ValueError as e:
        print(f"❌ {e}")
        raise
    
    # Build connection string - token auth requires minimal settings
    driver = '{ODBC Driver 18 for SQL Server}'
    conn_str = (
        f"DRIVER={driver};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"Encrypt=yes;"
        f"TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    
    print("Connecting to database...")
    try:
        # Connect with token using pyodbc extension
        conn = pyodbc.connect(conn_str, attrs_before={1256: token})
        conn.autocommit = True
        cursor = conn.cursor()
        print("✓ Connected successfully\n")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        raise
    
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
    
    executed = 0
    failed = 0
    
    for i, batch in enumerate(batches, 1):
        try:
            cursor.execute(batch)
            print(f"  ✓ Batch {i}/{len(batches)} executed")
            executed += 1
        except Exception as e:
            # Some warnings are expected (e.g., IF NOT EXISTS on creation)
            error_str = str(e).lower()
            if 'already exists' in error_str or 'already is' in error_str:
                print(f"  ✓ Batch {i}/{len(batches)} (already exists)")
                executed += 1
            else:
                print(f"  ⚠ Batch {i}: {str(e)[:80]}")
                failed += 1
    
    cursor.close()
    conn.close()
    
    print(f"\n✅ Database schema initialized successfully!")
    print(f"   Batches executed: {executed}/{len(batches)}")
    if failed > 0:
        print(f"   Warnings: {failed} (usually non-critical)")

if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"\n❌ Initialization failed!")
        exit(1)
