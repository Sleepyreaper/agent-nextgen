#!/usr/bin/env python3
"""Store PostgreSQL credentials in Azure Key Vault"""
import os
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# Credentials to store (load from environment)
REQUIRED_ENV = {
    'postgres-host': 'POSTGRES_HOST',
    'postgres-port': 'POSTGRES_PORT',
    'postgres-database': 'POSTGRES_DB',
    'postgres-username': 'POSTGRES_USER',
    'postgres-password': 'POSTGRES_PASSWORD'
}

KEYVAULT_NAME = os.getenv('AZURE_KEY_VAULT_NAME', 'your-keyvault-name')
KEYVAULT_URL = f'https://{KEYVAULT_NAME}.vault.azure.net/'

try:
    print(f"Connecting to Azure Key Vault: {KEYVAULT_NAME}")
    
    # Use environment credentials (must be authenticated with Azure CLI or managed identity)
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=KEYVAULT_URL, credential=credential)
    
    print("\nStoring credentials in Key Vault...")

    secrets = {}
    missing = []
    for secret_name, env_var in REQUIRED_ENV.items():
        value = os.getenv(env_var)
        if not value:
            missing.append(env_var)
            continue
        secrets[secret_name] = value

    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        print("Set them in your shell or .env.local (never commit secrets).")
        raise SystemExit(1)

    for secret_name, secret_value in secrets.items():
        try:
            client.set_secret(secret_name, secret_value)
            print(f"  ✅ Stored: {secret_name}")
        except Exception as e:
            print(f"  ❌ Failed to store {secret_name}: {e}")
    
    print("\n✅ All credentials stored in Azure Key Vault!")
    print("\nVerifying stored secrets...")
    
    # Verify secrets were stored
    for secret_name in secrets.keys():
        try:
            secret = client.get_secret(secret_name)
            print(f"  ✅ Retrieved: {secret_name} = {'*' * 20}")
        except Exception as e:
            print(f"  ❌ Cannot retrieve {secret_name}: {e}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("\nNote: Make sure you are authenticated with Azure CLI:")
    print("  $ az login")
