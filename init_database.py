"""Initialize the database schema."""

import psycopg
from src.config import config

def init_database():
    """Initialize database with schema."""
    
    if config.postgres_url:
        connection_string = config.postgres_url
    else:
        connection_string = (
            f"host={config.postgres_host} "
            f"port={config.postgres_port} "
            f"dbname={config.postgres_database} "
            f"user={config.postgres_username} "
            f"password={config.postgres_password} "
            "sslmode=prefer"
        )

    print("Connecting to PostgreSQL...")
    try:
        conn = psycopg.connect(connection_string)
        cursor = conn.cursor()
        
        print("Reading schema.sql...")
        with open('database/schema.sql', 'r') as f:
            schema_sql = f.read()
        
        # Split by semicolons and execute each statement
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]

        print(f"Executing {len(statements)} SQL statements...")
        for i, statement in enumerate(statements, 1):
            if statement:
                try:
                    cursor.execute(statement)
                    conn.commit()
                    print(f"  ✓ Statement {i} executed successfully")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"  ⚠ Statement {i}: Object already exists (skipping)")
                    else:
                        print(f"  ✗ Statement {i} failed: {str(e)}")
                        raise
        
        print("\n✅ Database schema initialized successfully!")
        
        # Verify tables exist
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
        
        tables = [row[0] for row in cursor.fetchall()]
        print(f"\n📊 Created tables: {', '.join(tables)}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"\n❌ Error initializing database: {str(e)}")
        print("\nMake sure you:")
        print("  1. Have the correct Postgres credentials configured")
        print("  2. Allowed your IP in the Postgres firewall rules")
        print("  3. Have permissions on the Postgres database")
        raise


if __name__ == "__main__":
    init_database()
