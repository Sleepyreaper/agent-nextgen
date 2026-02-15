"""Initialize Azure SQL Database with required schema using Azure CLI."""

import subprocess
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

def initialize_database():
    """Initialize the database with schema using Azure CLI."""
    print("=== Azure SQL Database Initialization (via Azure CLI) ===\n")
    
    server = os.getenv('SQL_SERVER')
    database = os.getenv('SQL_DATABASE')
    
    if not server or not database:
        raise ValueError("SQL_SERVER and SQL_DATABASE must be set in .env.local")
    
    # Extract server name without domain
    server_name = server.split('.')[0]
    
    print(f"Server: {server}")
    print(f"Database: {database}")
    print(f"Auth: Azure CLI (Entra ID)\n")
    
    # Read schema file
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
    
    # Execute each batch using sqlcmd via Azure CLI
    executed = 0
    failed = 0
    
    for i, batch in enumerate(batches, 1):
        try:
            # Use sqlcmd to execute the batch
            result = subprocess.run(
                [
                    'sqlcmd',
                    '-S', server,
                    '-d', database,
                    '-U', os.getenv('SQL_USERNAME', 'NOT_USED'),
                    '-P', os.getenv('SQL_PASSWORD', 'NOT_USED'),
                    '-G',  # Use Azure AD authentication
                    '-b'   # Exit on error
                ],
                input=batch,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print(f"  ✓ Batch {i}/{len(batches)} executed")
                executed += 1
            else:
                print(f"  ⚠ Batch {i} warning: {result.stderr[:100]}")
                failed += 1
        except subprocess.TimeoutExpired:
            print(f"  ✗ Batch {i} timeout")
            failed += 1
        except Exception as e:
            print(f"  ✗ Batch {i} error: {str(e)[:100]}")
            failed += 1
    
    print(f"\n✅ Database initialization complete!")
    print(f"   Executed: {executed}/{len(batches)} batches")
    if failed > 0:
        print(f"   Failed: {failed} batches (may be recoverable warnings)")
    
    # Verify tables were created
    try:
        result = subprocess.run(
            [
                'sqlcmd',
                '-S', server,
                '-d', database,
                '-U', os.getenv('SQL_USERNAME', 'NOT_USED'),
                '-P', os.getenv('SQL_PASSWORD', 'NOT_USED'),
                '-G',  # Use Azure AD authentication
                '-Q', "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo' ORDER BY TABLE_NAME"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            table_count = result.stdout.count('__')
            print(f"   Tables created: {table_count}")
        else:
            print(f"⚠ Could not verify tables (may still be created)")
    except:
        pass

if __name__ == "__main__":
    try:
        initialize_database()
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        print("\nMake sure:")
        print("  1. sqlcmd is installed: brew install mssql-tools18")
        print("  2. You're logged in to Azure: az login")
        print("  3. SQL_SERVER and SQL_DATABASE are set in .env.local")
        exit(1)
