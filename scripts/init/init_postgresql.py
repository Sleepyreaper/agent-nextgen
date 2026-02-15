#!/usr/bin/env python3
"""
Initialize PostgreSQL database schema and verify Key Vault configuration.

This script:
1. Validates PostgreSQL connection parameters
2. Tests connection to PostgreSQL
3. Creates database schema if not exists
4. Verifies Key Vault access (if configured)
5. Tests all agent tables exist

Usage:
    python scripts/init/init_postgresql.py
"""

import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import config
import psycopg


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_success(text: str):
    """Print success message."""
    print(f"✅ {text}")


def print_error(text: str):
    """Print error message."""
    print(f"❌ {text}")


def print_info(text: str):
    """Print info message."""
    print(f"ℹ️  {text}")


def check_environment():
    """Verify environment configuration."""
    print_header("Checking Environment Configuration")
    
    # Check Key Vault
    if config._secret_client:
        print_success("Connected to Azure Key Vault: " + config.key_vault_name)
    else:
        print_info("Not using Key Vault (using .env.local)")
    
    # Check PostgreSQL parameters
    if config.postgres_url:
        print_success("Using PostgreSQL connection string from environment")
        return True
    elif config.postgres_host and config.postgres_database:
        print_success(f"PostgreSQL Host: {config.postgres_host}")
        print_success(f"PostgreSQL Database: {config.postgres_database}")
        print_success(f"PostgreSQL Port: {config.postgres_port}")
        return True
    else:
        print_error("PostgreSQL configuration incomplete")
        return False


def test_database_connection():
    """Test connection to PostgreSQL."""
    print_header("Testing PostgreSQL Connection")
    
    try:
        from src.database import Database
        db = Database()
        conn = db.connect()
        
        # Simple test query
        cursor = conn.cursor()
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        cursor.close()
        
        print_success("Connected to PostgreSQL")
        print(f"  Version: {version[:80]}...")
        return True
        
    except Exception as e:
        print_error(f"Failed to connect to PostgreSQL: {e}")
        return False


def create_schema():
    """Create database schema from SQL file."""
    print_header("Creating Database Schema")
    
    schema_file = PROJECT_ROOT / "database" / "schema_postgresql.sql"
    
    if not schema_file.exists():
        print_error(f"Schema file not found: {schema_file}")
        return False
    
    try:
        from src.database import Database
        db = Database()
        conn = db.connect()
        cursor = conn.cursor()
        
        # Read and execute schema
        with open(schema_file, 'r') as f:
            schema_sql = f.read()
        
        # Execute schema creation
        cursor.execute(schema_sql)
        conn.commit()
        cursor.close()
        
        print_success("Database schema created successfully")
        return True
        
    except Exception as e:
        print_error(f"Failed to create schema: {e}")
        return False


def verify_tables():
    """Verify that all required tables exist."""
    print_header("Verifying Database Tables")
    
    required_tables = [
        'applications',
        'ai_evaluations',
        'student_school_context',
        'tiana_applications',
        'mulan_recommendations',
        'merlin_evaluations',
        'aurora_evaluations',
        'agent_audit_logs',
        'test_submissions',
        'schools'
    ]
    
    try:
        from src.database import Database
        db = Database()
        conn = db.connect()
        cursor = conn.cursor()
        
        # Query information_schema
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        
        existing_tables = {row[0] for row in cursor.fetchall()}
        cursor.close()
        
        print(f"Found {len(existing_tables)} tables:")
        
        all_present = True
        for table in sorted(existing_tables):
            print(f"  • {table}")
            
        print()
        
        for table in required_tables:
            if table in existing_tables:
                print_success(f"Table '{table}' exists")
            else:
                print_error(f"Table '{table}' missing")
                all_present = False
        
        return all_present
        
    except Exception as e:
        print_error(f"Failed to verify tables: {e}")
        return False


def test_sample_query():
    """Test a sample query to verify schema integrity."""
    print_header("Testing Sample Query")
    
    try:
        from src.database import Database
        db = Database()
        
        # Test creating and retrieving an application
        app_id = db.create_application(
            applicant_name="Test User",
            email="test@example.com",
            application_text="Test application",
            file_name="test.pdf",
            file_type="pdf",
            is_training=True
        )
        
        if app_id:
            print_success(f"Created test application with ID: {app_id}")
            
            # Retrieve it
            app = db.get_application(app_id)
            if app:
                print_success(f"Retrieved application: {app.get('applicant_name')}")
                
                # Clean up test data
                db.clear_test_data()
                print_success("Cleaned up test data")
                return True
        
        return False
        
    except Exception as e:
        print_error(f"Sample query failed: {e}")
        return False


def test_key_vault():
    """Test Key Vault access if configured."""
    print_header("Testing Key Vault Access")
    
    if not config._secret_client:
        print_info("Key Vault not configured (using .env.local)")
        return True
    
    try:
        # Try to access a secret
        secrets_to_check = [
            'postgres-host',
            'postgres-database',
            'azure-openai-endpoint'
        ]
        
        success = True
        for secret_name in secrets_to_check:
            try:
                secret = config._secret_client.get_secret(secret_name)
                if secret.value:
                    print_success(f"Secret '{secret_name}' is accessible")
                else:
                    print_error(f"Secret '{secret_name}' exists but has no value")
                    success = False
            except Exception as e:
                print_error(f"Cannot access secret '{secret_name}': {e}")
                success = False
        
        return success
        
    except Exception as e:
        print_error(f"Key Vault test failed: {e}")
        return False


def main():
    """Run all initialization checks."""
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║ PostgreSQL + Key Vault Initialization & Verification     ║")
    print("╚" + "═"*58 + "╝")
    
    results = {
        "Environment": check_environment(),
        "Key Vault": test_key_vault(),
        "Database Connection": test_database_connection(),
        "Schema Creation": create_schema(),
        "Table Verification": verify_tables(),
        "Sample Query": test_sample_query(),
    }
    
    # Summary
    print_header("Initialization Summary")
    
    for check, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {check:.<40} {status}")
    
    all_passed = all(results.values())
    
    print()
    if all_passed:
        print_success("All checks passed! Application is ready to run.")
        print("\n  To start the application:")
        print("  $ python app.py")
        return 0
    else:
        print_error("Some checks failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
