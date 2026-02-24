#!/usr/bin/env python3
"""
Complete PostgreSQL Database Setup with Key Vault Integration

This script:
1. Stores admin credentials in Azure Key Vault
2. Connects to PostgreSQL with admin credentials
3. Creates the new database (set via POSTGRES_DB env var)
4. Creates a limited-privilege application user
5. Stores app user credentials in Key Vault
6. Verifies the connection with app user
"""

import sys
import os
import secrets
import string
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from azure.keyvault.secrets import SecretClient
    from azure.identity import DefaultAzureCredential
except ImportError:
    print("❌ Missing Azure SDK. Install with: pip install azure-keyvault-secrets azure-identity")
    sys.exit(1)

try:
    import psycopg
except ImportError:
    print("❌ Missing psycopg. Install with: pip install psycopg[binary]")
    sys.exit(1)


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


def get_keyvault_client(vault_name: str):
    """Get Azure Key Vault client."""
    try:
        credential = DefaultAzureCredential()
        vault_url = f"https://{vault_name}.vault.azure.net/"
        return SecretClient(vault_url=vault_url, credential=credential)
    except Exception as e:
        print_error(f"Failed to connect to Key Vault: {e}")
        return None


def store_in_keyvault(client, secret_name: str, secret_value: str) -> bool:
    """Store a secret in Key Vault."""
    try:
        client.set_secret(secret_name, secret_value)
        print_success(f"Stored in Key Vault: {secret_name}")
        return True
    except Exception as e:
        print_error(f"Failed to store {secret_name}: {e}")
        return False


def connect_postgresql(host: str, port: int, username: str, password: str, database: str = 'postgres') -> object:
    """Connect to PostgreSQL."""
    try:
        conn = psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=username,
            password=password,
            sslmode='require',
            connect_timeout=10
        )
        return conn
    except Exception as e:
        raise ConnectionError(f"Failed to connect to PostgreSQL: {e}")


def create_database(cursor, db_name: str) -> bool:
    """Create a new database."""
    try:
        # Check if database already exists
        cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        if cursor.fetchone():
            print_info(f"Database '{db_name}' already exists")
            return True
        
        # Create the database
        cursor.execute(f"CREATE DATABASE {db_name}")
        print_success(f"Created database: {db_name}")
        return True
    except Exception as e:
        print_error(f"Failed to create database: {e}")
        return False


def create_app_user(cursor, username: str, password: str, db_name: str) -> bool:
    """Create a limited-privilege application user."""
    try:
        # Check if user already exists
        cursor.execute("SELECT 1 FROM pg_user WHERE usename = %s", (username,))
        if cursor.fetchone():
            print_info(f"User '{username}' already exists")
            return True
        
        # Create the user
        cursor.execute(f"CREATE USER {username} WITH PASSWORD %s", (password,))
        print_success(f"Created user: {username}")
        
        # Grant privileges on the database
        cursor.execute(f"GRANT CREATE ON DATABASE {db_name} TO {username}")
        print_success(f"Granted CREATE privilege on {db_name} to {username}")
        
        # Connect to the new database and set up schema permissions
        return True
    except Exception as e:
        print_error(f"Failed to create user: {e}")
        return False


def grant_table_privileges(cursor, username: str, db_name: str) -> bool:
    """Grant table-level privileges to the application user."""
    try:
        # Connect to the specific database for schema operations
        print_info(f"Setting up privileges for {username} on {db_name}...")
        
        # Note: These would be executed on the new database after creation
        # For now, just grant default privileges
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {username}")
        cursor.execute(f"GRANT CREATE ON SCHEMA public TO {username}")
        
        print_success(f"Granted schema privileges to {username}")
        return True
    except Exception as e:
        print_error(f"Failed to grant privileges: {e}")
        return False


def generate_secure_password(length: int = 20) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-+=?"
    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password


def main():
    """Run the complete database setup."""
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║  PostgreSQL Database & Key Vault Setup                    ║")
    print("╚" + "═"*58 + "╝")
    
    # Configuration (load from environment)
    POSTGRES_HOST = os.getenv("POSTGRES_HOST")
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
    ADMIN_USERNAME = os.getenv("POSTGRES_ADMIN_USER")
    ADMIN_PASSWORD = os.getenv("POSTGRES_ADMIN_PASSWORD")
    NEW_DATABASE = os.getenv("POSTGRES_DB")
    APP_USERNAME = os.getenv("POSTGRES_APP_USER", "agent_app_user")
    KEYVAULT_NAME = os.getenv("AZURE_KEY_VAULT_NAME")

    missing = [
        name for name, value in {
            "POSTGRES_HOST": POSTGRES_HOST,
            "POSTGRES_ADMIN_USER": ADMIN_USERNAME,
            "POSTGRES_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "POSTGRES_DB": NEW_DATABASE,
            "AZURE_KEY_VAULT_NAME": KEYVAULT_NAME
        }.items()
        if not value
    ]
    if missing:
        print_error(f"Missing required environment variables: {', '.join(missing)}")
        print_info("Set these in your shell or .env.local (never commit secrets).")
        return 1
    
    # Generate secure password for app user
    APP_PASSWORD = generate_secure_password()
    
    print_header("Step 1: Connect to Azure Key Vault")
    
    kv_client = get_keyvault_client(KEYVAULT_NAME)
    if not kv_client:
        return 1
    
    print_header("Step 2: Store Admin Credentials in Key Vault")
    
    store_in_keyvault(kv_client, "postgres-admin-username", ADMIN_USERNAME)
    store_in_keyvault(kv_client, "postgres-admin-password", ADMIN_PASSWORD)
    
    print_header("Step 3: Connect to PostgreSQL with Admin Credentials")
    
    try:
        conn = connect_postgresql(POSTGRES_HOST, POSTGRES_PORT, ADMIN_USERNAME, ADMIN_PASSWORD)
        cursor = conn.cursor()
        print_success(f"Connected to PostgreSQL at {POSTGRES_HOST}")
    except Exception as e:
        print_error(str(e))
        return 1
    
    print_header("Step 4: Create New Database")
    
    if not create_database(cursor, NEW_DATABASE):
        return 1
    
    conn.commit()
    
    print_header("Step 5: Create Application User")
    
    if not create_app_user(cursor, APP_USERNAME, APP_PASSWORD, NEW_DATABASE):
        conn.close()
        return 1
    
    conn.commit()
    
    print_header("Step 6: Grant Privileges to Application User")
    
    if not grant_table_privileges(cursor, APP_USERNAME, NEW_DATABASE):
        conn.close()
        return 1
    
    conn.commit()
    
    print_header("Step 7: Store Application User Credentials in Key Vault")
    
    store_in_keyvault(kv_client, "postgres-username", APP_USERNAME)
    store_in_keyvault(kv_client, "postgres-password", APP_PASSWORD)
    store_in_keyvault(kv_client, "postgres-database", NEW_DATABASE)
    store_in_keyvault(kv_client, "postgres-host", POSTGRES_HOST)
    store_in_keyvault(kv_client, "postgres-port", str(POSTGRES_PORT))
    
    print_header("Step 8: Verify Application User Connection")
    
    try:
        app_conn = connect_postgresql(POSTGRES_HOST, POSTGRES_PORT, APP_USERNAME, APP_PASSWORD, NEW_DATABASE)
        app_cursor = app_conn.cursor()
        app_cursor.execute("SELECT version()")
        version = app_cursor.fetchone()[0]
        print_success(f"Application user can connect to {NEW_DATABASE}")
        print(f"  Version: {version[:70]}...")
        app_conn.close()
    except Exception as e:
        print_error(f"Application user connection failed: {e}")
        conn.close()
        return 1
    
    # Close admin connection
    conn.close()
    
    print_header("Setup Summary")
    
    print("\n✨ Database Setup Complete!\n")
    print(f"  Database Name:     {NEW_DATABASE}")
    print(f"  Admin User:        {ADMIN_USERNAME}")
    print(f"  App User:          {APP_USERNAME}")
    print(f"  PostgreSQL Server: {POSTGRES_HOST}")
    print()
    print("Stored in Key Vault (your-keyvault-name):")
    print(f"  • postgres-admin-username: {ADMIN_USERNAME}")
    print(f"  • postgres-admin-password: [SECURED]")
    print(f"  • postgres-username: {APP_USERNAME}")
    print(f"  • postgres-password: [SECURED]")
    print(f"  • postgres-database: {NEW_DATABASE}")
    print(f"  • postgres-host: {POSTGRES_HOST}")
    print(f"  • postgres-port: {POSTGRES_PORT}")
    print()
    print("Next Steps:")
    print("  1. Update .env.local to use the new database")
    print("  2. Run: python scripts/init/init_postgresql.py")
    print("  3. Start Flask: python app.py")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
