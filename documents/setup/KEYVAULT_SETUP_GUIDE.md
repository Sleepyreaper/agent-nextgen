# Azure Key Vault Setup Guide for NextGen AI System

## Overview

This guide ensures all sensitive credentials are properly managed through Azure Key Vault in production, while supporting local development with `.env.local`.

## Secret Management Strategy

### Production (Azure Deployment)
- All secrets stored in Azure Key Vault
- Application authenticates via Managed Identity
- No `.env` files in production
- Secrets retrieved on-demand from Key Vault

### Local Development  
- Secrets stored in `.env.local` (gitignored)
- Used when Key Vault is not accessible
- Mimics production credential structure
- Never commit to version control

---

## Secrets to Store in Azure Key Vault

### 1. **Database Credentials**
```
Secret Name: postgres-host
Value: (PostgreSQL server hostname)

Secret Name: postgres-port  
Value: 5432

Secret Name: postgres-database
Value: ApplicationsDB

Secret Name: postgres-username
Value: (database user)

Secret Name: postgres-password
Value: (database password - long random string)

Secret Name: postgres-url (optional - full connection string)
Value: postgresql://user:password@host:5432/database
```

### 2. **Azure OpenAI Credentials**
```
Secret Name: azure-openai-endpoint
Value: https://{resource-name}.openai.azure.com/

Secret Name: azure-deployment-name
Value: (e.g., NextGenGPT, gpt-4, etc.)

Secret Name: azure-api-version
Value: 2024-12-01-preview
```

### 3. **Azure Configuration**
```
Secret Name: azure-subscription-id
Value: (Azure subscription ID)

Secret Name: azure-resource-group
Value: (Azure resource group name)

Secret Name: flask-secret-key
Value: (long random string from: openssl rand -hex 32)
```

### 4. **Azure Storage (Optional - if using blob storage)**
```
Secret Name: storage-account-name
Value: (Azure Storage account name)

Secret Name: storage-account-key
Value: (Storage account access key)

Secret Name: storage-container-name
Value: (Container name for uploads)
```

---

## How Credentials Flow

### Local Development
```
.env.local (git-ignored)
    ↓
load_dotenv('.env.local')
    ↓
config.py reads environment variables
    ↓
Application uses credentials
```

### Production (Azure)
```
Key Vault (your-keyvault-name)
    ↓
DefaultAzureCredential (Managed Identity)
    ↓
config.py retrieves secrets
    ↓
Application uses credentials
```

---

## Setting Up Secrets in Azure Key Vault

### Using Azure CLI

```bash
# Login to Azure
az login

# Set key vault name
VAULT_NAME="your-keyvault-name"

# Database Secrets
az keyvault secret set --vault-name $VAULT_NAME --name "postgres-host" --value "your-postgres-host"
az keyvault secret set --vault-name $VAULT_NAME --name "postgres-port" --value "5432"
az keyvault secret set --vault-name $VAULT_NAME --name "postgres-database" --value "ApplicationsDB"
az keyvault secret set --vault-name $VAULT_NAME --name "postgres-username" --value "your-db-username"
az keyvault secret set --vault-name $VAULT_NAME --name "postgres-password" --value "your-db-password"

# Azure OpenAI Secrets
az keyvault secret set --vault-name $VAULT_NAME --name "azure-openai-endpoint" --value "https://your-openai-resource.openai.azure.com/"
az keyvault secret set --vault-name $VAULT_NAME --name "azure-deployment-name" --value "your-deployment-name"
az keyvault secret set --vault-name $VAULT_NAME --name "azure-api-version" --value "2024-12-01-preview"

# Azure Configuration
az keyvault secret set --vault-name $VAULT_NAME --name "azure-subscription-id" --value "your-subscription-id"
az keyvault secret set --vault-name $VAULT_NAME --name "azure-resource-group" --value "your-resource-group"

# Flask Secret
az keyvault secret set --vault-name $VAULT_NAME --name "flask-secret-key" --value "$(openssl rand -hex 32)"
```

### Using Azure Portal

1. Go to Key Vault: **your-keyvault-name**
2. Click **Secrets** in left sidebar
3. Click **+ Generate/Import**
4. For each secret:
   - **Name**: (secret name from list above)
   - **Value**: (secret value)
   - Click **Create**

---

## Verifying Secrets in Key Vault

```bash
# List all secrets
az keyvault secret list --vault-name your-keyvault-name --query "[].name" -o tsv

# Get a specific secret value (careful - logs to terminal!)
az keyvault secret show --vault-name your-keyvault-name --name "postgres-password" --query value -o tsv

# Check secret metadata (not the value)
az keyvault secret show --vault-name your-keyvault-name --name "postgres-password"
```

---

## Code Review: No Hardcoded Secrets

### ✅ Verified - No Hardcoded Credentials

Scan results show:
- ✅ No passwords in source code
- ✅ No API keys in source code  
- ✅ No connection strings in source code
- ✅ All credentials sourced from config.py
- ✅ config.py uses environment variables
- ✅ Environment variables come from Key Vault (production) or .env.local (dev)

### Secret Retrieval Flow

```python
# src/config.py
class Config:
    def _get_secret(self, kv_name, env_name):
        """
        Try Key Vault first (production), fall back to environment variable.
        """
        if self._secret_client:
            # Production: get from Key Vault
            return self._secret_client.get_secret(kv_name).value
        else:
            # Local dev: get from environment (set by .env.local)
            return os.getenv(env_name)
```

No credentials are hardcoded anywhere in the application.

---

## .env.local Format (Local Development Only)

```dotenv
# PostgreSQL Database
POSTGRES_HOST=your-postgres-host
POSTGRES_PORT=5432
POSTGRES_DATABASE=ApplicationsDB
POSTGRES_USERNAME=your-db-username
POSTGRES_PASSWORD=your-db-password

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai-resource.openai.azure.com/
AZURE_DEPLOYMENT_NAME=your-deployment-name
AZURE_API_VERSION=2024-12-01-preview

# Azure Configuration
AZURE_SUBSCRIPTION_ID=your-subscription-id
AZURE_RESOURCE_GROUP=your-resource-group

# Flask
FLASK_SECRET_KEY=your-random-secret-key-here

# Key Vault (set to empty for local dev)
AZURE_KEY_VAULT_NAME=
```

---

## Security Checklist

- [ ] All secrets created in Azure Key Vault
- [ ] `.env.local` exists but is gitignored (never committed)
- [ ] Source code contains no hardcoded credentials
- [ ] Local dev uses `.env.local` for testing
- [ ] Production uses Key Vault via Managed Identity
- [ ] No secrets in logs (logger masks sensitive data)
- [ ] Database uses parameterized queries (SQL injection protection)
- [ ] HTTPS enforced in production
- [ ] Managed Identity configured with minimum required permissions

---

## Troubleshooting

### Key Vault Access Denied
- Check Managed Identity has "Secret Officer" or "Secret Getter" role on Key Vault
- Verify network access rules (if private endpoint configured)
- Check if using correct credentials (az login)

### .env.local Not Loading
- Ensure file is in project root
- Check file name is exactly `.env.local` (case-sensitive on Linux/Mac)
- Verify gitignore includes `.env.local`

### Secrets Not Found Error
```python
# This happens when:
1. .env.local doesn't exist and Key Vault is unavailable
2. AZURE_KEY_VAULT_NAME is set but inaccessible
3. Secret doesn't exist in Key Vault

# Solution: Create .env.local for local dev
```

---

## Migration from .env.local to Key Vault

When moving from local dev to production:

1. **Create secrets in Key Vault** (see commands above)
2. **Remove .env.local from deployment**
3. **Set AZURE_KEY_VAULT_NAME** environment variable
4. **Assign Managed Identity** to Key Vault (Secret Getter role)
5. **Test credential retrieval** via Azure SDK

---

## Recommended Secret Rotation

- Database passwords: every 90 days
- API keys: every 180 days
- Flask secret: every 365 days or when compromised
- Minor version updates to auth libraries: immediately

---

## Additional Resources

- [Azure Key Vault Documentation](https://docs.microsoft.com/en-us/azure/key-vault/)
- [Azure Identity Library (Python)](https://docs.microsoft.com/en-us/python/api/azure-identity/)
- [Managed Identities for Azure Resources](https://docs.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/)

