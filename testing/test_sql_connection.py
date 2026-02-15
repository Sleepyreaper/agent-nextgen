"""Test Azure SQL Database connection."""

import sys
from dotenv import load_dotenv
from pathlib import Path

# Load environment
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    print("❌ .env.local not found. Please create it based on .env.local.template")
    sys.exit(1)

import os
print("=== Azure SQL Database Connection Test ===\n")

# Check configuration
server = os.getenv('SQL_SERVER')
database = os.getenv('SQL_DATABASE')
auth_method = os.getenv('SQL_AUTH_METHOD', 'entra').lower()

print(f"Server: {server}")
print(f"Database: {database}")
print(f"Auth Method: {auth_method}\n")

if not server or not database:
    print("❌ SQL_SERVER and SQL_DATABASE must be set in .env.local")
    sys.exit(1)

try:
    from src.database import Database, db
    print("✓ Database module imported successfully\n")
    
    # Try to connect
    print("Attempting connection...")
    conn = db.connect()
    
    print("✓ Connection successful!\n")
    
    # Get database version
    cursor = conn.cursor()
    cursor.execute("SELECT @@VERSION")
    version = cursor.fetchone()
    print(f"SQL Server Version: {version[0][:80]}...\n")
    
    # List tables
    cursor.execute("""
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """)
    
    tables = [row[0] for row in cursor.fetchall()]
    print(f"✓ Found {len(tables)} tables:")
    for table in tables:
        print(f"   - {table}")
    
    cursor.close()
    db.close()
    
    print("\n✅ Azure SQL Database connection successful!")
    print(f"✅ Schema is initialized with {len(tables)} tables")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("\nPlease run: pip install -r requirements.txt")
    sys.exit(1)
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    
    if "ODBC" in str(e) or "Driver" in str(e):
        print("\n⚠ ODBC Driver 18 for SQL Server may not be installed.")
        print("Install it with:")
        print("  macOS: brew install msodbcsql18")
        print("  Linux: sudo apt-get install msodbcsql18")
        print("  Windows: Download from https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server")
    
    if "Authentication" in str(e) or "login" in str(e).lower():
        print("\n⚠ Authentication failed.")
        print(f"  Auth Method: {auth_method}")
        if auth_method == 'entra':
            print("  Make sure you're logged in to Azure CLI: az login")
        else:
            print("  Check SQL_USERNAME and SQL_PASSWORD in .env.local")
    
    sys.exit(1)
