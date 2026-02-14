"""Initialize the database schema."""

import pyodbc
import os
from src.config import config

def init_database():
    """Initialize database with schema."""
    
    server = os.getenv("SQL_SERVER", "nextgen-sql-server.database.windows.net")
    database = os.getenv("SQL_DATABASE", "ApplicationsDB")
    
    # Connection string with Azure AD auth
    connection_string = f"""
        Driver={{ODBC Driver 18 for SQL Server}};
        Server=tcp:{server},1433;
        Database={database};
        Authentication=ActiveDirectoryInteractive;
        Encrypt=yes;
        TrustServerCertificate=no;
    """
    
    print("Connecting to Azure SQL Database...")
    try:
        conn = pyodbc.connect(connection_string)
        cursor = conn.cursor()
        
        print("Reading schema.sql...")
        with open('database/schema.sql', 'r') as f:
            schema_sql = f.read()
        
        # Split by GO statements and execute each batch
        batches = [batch.strip() for batch in schema_sql.split('GO') if batch.strip()]
        
        if not batches:
            # If no GO statements, split by semicolon
            batches = [stmt.strip() + ';' for stmt in schema_sql.split(';') if stmt.strip()]
        
        print(f"Executing {len(batches)} SQL batches...")
        for i, batch in enumerate(batches, 1):
            if batch.strip():
                try:
                    cursor.execute(batch)
                    conn.commit()
                    print(f"  ✓ Batch {i} executed successfully")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  ⚠ Batch {i}: Object already exists (skipping)")
                    else:
                        print(f"  ✗ Batch {i} failed: {str(e)}")
                        raise
        
        print("\n✅ Database schema initialized successfully!")
        
        # Verify tables exist
        cursor.execute("""
            SELECT TABLE_NAME 
            FROM INFORMATION_SCHEMA.TABLES 
            WHERE TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n📊 Created tables: {', '.join(tables)}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Error initializing database: {str(e)}")
        print("\nMake sure you:")
        print("  1. Are logged in with 'az login'")
        print("  2. Have ODBC Driver 18 for SQL Server installed")
        print("  3. Have permissions on the Azure SQL Database")
        raise


if __name__ == "__main__":
    init_database()
