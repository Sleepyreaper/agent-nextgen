"""Check Key Vault for storage credentials."""

import os

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

try:
    vault_name = os.getenv('AZURE_KEY_VAULT_NAME', 'your-keyvault-name')
    credential = DefaultAzureCredential()
    vault_url = f'https://{vault_name}.vault.azure.net/'
    client = SecretClient(vault_url=vault_url, credential=credential)
    
    print(f'🔐 Checking Key Vault: {vault_name}\n')
    
    # Check for storage-specific secrets
    storage_related = [
        'storage-account-name',
        'storage-account-key', 
        'storage-container-name',
        'azure-storage-connection-string'
    ]
    
    print('Storage-related secrets:')
    found = []
    for secret_name in storage_related:
        try:
            secret = client.get_secret(secret_name)
            print(f'  ✅ {secret_name}: {secret.value[:20]}...' if len(secret.value) > 20 else f'  ✅ {secret_name}: {secret.value}')
            found.append(secret_name)
        except Exception:
            print(f'  ❌ {secret_name}: Not found')
    
    if not found:
        print('\n⚠️  No storage credentials found in Key Vault')
        print('\n📝 All available secrets:')
        secrets = list(client.list_properties_of_secrets())
        for secret in secrets:
            print(f'     - {secret.name}')
    
except Exception as e:
    print(f'❌ Error accessing Key Vault: {e}')
    print('\nℹ️  Please provide the Azure Storage credentials')
