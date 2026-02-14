# Security Documentation

## Overview

This application implements comprehensive security practices to protect sensitive information and ensure secure cloud operations on Azure.

## 🔒 Credential Management with Azure Key Vault

### What is Azure Key Vault?

Azure Key Vault is a cloud service for securely managing secrets, cryptographic keys, and certificates. It provides:
- **Centralized management** of all credentials
- **Audit logging** of all access
- **Access control** using Azure RBAC
- **Encryption** of secrets at rest and in transit
- **Automatic credential rotation** capabilities

### Secrets We Store

All sensitive configuration is managed in Key Vault (`nextgen-agents-kv`):

| Secret Name | Purpose | Source |
|---|---|---|
| `azure-openai-endpoint` | Azure OpenAI service URL | Created in Azure Portal |
| `azure-deployment-name` | GPT-5.2 model deployment name | Created in Azure Portal |
| `azure-api-version` | OpenAI API version | Hardcoded in code |
| `azure-subscription-id` | Azure subscription identifier | Your Azure account |
| `azure-resource-group` | Azure resource group name | NextGen_Agents |
| `sql-server` | SQL Server hostname | Created in Azure Portal |
| `sql-database` | SQL Database name | Created in Azure Portal |
| `flask-secret-key` | Flask session encryption key | Auto-generated, cryptographically secure |

### How the Application Uses Secrets

```
User Request
    ↓
Flask App (app.py)
    ↓
Config Module (src/config.py)
    ↓
DefaultAzureCredential (Azure Identity)
    ↓
Azure Key Vault
    ↓
Returns Decrypted Secret
```

1. When the application starts, `src/config.py` initializes
2. It creates a `SecretClient` using `DefaultAzureCredential`
3. On first use of a secret, it fetches from Key Vault
4. Secrets are cached in memory for performance
5. Azure AD handles authentication transparently

### No Secrets in Code

✅ **What we DON'T store in code:**
- API keys or connection strings
- Database passwords
- Session secrets
- Encryption keys
- Access tokens

✅ **Configuration methods (in order of preference):**
1. Azure Key Vault (production)
2. `.env` file environment variables (local development)
3. Hardcoded defaults (development config only)

## 🔑 Authentication Methods

### DefaultAzureCredential Chain

The application uses `DefaultAzureCredential` which automatically handles authentication:

```python
from azure.identity import DefaultAzureCredential
credential = DefaultAzureCredential()
```

This tries authentication methods in order:
1. **Environment variables** - `AZURE_SUBSCRIPTION_ID`, etc. (CI/CD pipelines)
2. **Managed Identity** - For Azure App Service, Azure Container Instances
3. **Azure CLI** - Current logged-in user (local development)
4. **Azure PowerShell** - Current logged-in user fallback
5. **Visual Studio** - Current logged-in user fallback

### Local Development (Recommended)

For local development, authenticate with Azure CLI:

```bash
az login
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

This creates credentials in `~/.azure` that DefaultAzureCredential automatically uses.

### Production Deployment

For production, use **Managed Identity**:

```python
# In Azure App Service, Container Instances, Virtual Machines, etc.
credential = DefaultAzureCredential()  # Automatically uses Managed Identity
```

No credentials needed! The Azure resource's identity authenticates automatically.

## 🛡️ Database Security

### Azure AD Authentication (No Passwords)

The application uses Azure AD authentication instead of passwords:

```python
Authentication=ActiveDirectoryInteractive;
```

**Benefits:**
- No passwords to store or rotate
- Multi-factor authentication supported
- Built-in audit logging
- Expires automatically after login
- Works across all Azure services

### SQL Database Firewall

Firewall rules in Azure SQL Server:

| Rule | Purpose |
|---|---|
| Allow Azure Services | Allows Azure App Service to connect |
| Allow Client IP | Allows your development machine IP |

### Connection String Security

Connection string built dynamically using Key Vault secrets:

```python
server = config.sql_server  # From Key Vault
database = config.sql_database  # From Key Vault
connection_string = f"""
Driver={{ODBC Driver 18 for SQL Server}};
Server=tcp:{server},1433;
Database={database};
Authentication=ActiveDirectoryInteractive;
Encrypt=yes;
TrustServerCertificate=no;
"""
```

- Uses TLS encryption (`Encrypt=yes`)
- Verifies server certificate (`TrustServerCertificate=no`)
- Credentials never in connection string

## 🔐 Application-Level Security

### Flask Session Security

The Flask secret key is:
- Stored securely in Key Vault
- Retrieved at startup
- Used to encrypt all session cookies
- Cryptographically random (64-byte hex)

### File Upload Security

File uploads are:
- Validated by extension
- Stored in `uploads/` directory
- Scanned for sensitive content
- Deleted after processing (optional)
- Not accessible via web server

### SQL Injection Prevention

All database queries use parameterized statements:

```python
# ✅ SAFE - Uses parameters
cursor.execute("SELECT * FROM Users WHERE id = ?", (user_id,))

# ❌ UNSAFE - String concatenation
cursor.execute(f"SELECT * FROM Users WHERE id = {user_id}")
```

## 📋 Setup Instructions

### 1. Initial Setup

```bash
# Create Key Vault
az keyvault create \
  --name nextgen-agents-kv \
  --resource-group NextGen_Agents \
  --location westus2

# Grant yourself access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $(az ad signed-in-user show --query objectId -o tsv) \
  --secret-permissions get list set delete
```

### 2. Populate Secrets

```bash
# Set secrets
az keyvault secret set --vault-name nextgen-agents-kv \
  --name azure-openai-endpoint \
  --value "https://reapaihub6853304142.openai.azure.com/"

# ... (repeat for each secret)
```

### 3. Grant Application Access

For production (Azure App Service):

```bash
# Get the app's managed identity
app_principal_id=$(az webapp identity show \
  --name nextgen-app \
  --resource-group NextGen_Agents \
  --query principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $app_principal_id \
  --secret-permissions get
```

## 🔍 Security Monitoring

### Azure Key Vault Audit Logs

Check who accessed secrets:

```bash
# List audit logs
az monitor activity-log list \
  --resource-group NextGen_Agents \
  --resource-type "Microsoft.KeyVault/vaults" \
  --resource-name nextgen-agents-kv

# View recent accesses
az keyvault secret show \
  --vault-name nextgen-agents-kv \
  --name azure-openai-endpoint \
  --query attributes
```

### Database Access Logs

Azure SQL provides:
- Login attempts
- Query audit logs
- Connection information
- Per-user tracking

## 🚨 Security Best Practices

✅ **DO:**
- Use `az login` for authentication
- Rotate secrets periodically
- Monitor Key Vault audit logs
- Use strong Flask secret keys (auto-generated)
- Enable MFA on Azure account
- Review Azure role assignments regularly
- Use Managed Identity in production
- Encrypt all connections (TLS)

❌ **DON'T:**
- Commit `.env` files to git
- Share connection strings
- Use the same password across services
- Grant overly permissive roles
- Store credentials in code
- Use HTTP (only HTTPS)
- Disable SSL certificate validation
- Expose Key Vault URLs in logs

## 🆘 Troubleshooting

### "Permission denied" error

The user account doesn't have Key Vault access:

```bash
# Grant yourself access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $(az ad signed-in-user show --query objectId -o tsv) \
  --secret-permissions get list set delete
```

### "Could not connect to Key Vault"

1. Verify Key Vault exists: `az keyvault show --name nextgen-agents-kv`
2. Verify you're authenticated: `az account show`
3. Check VNet restrictions: `az keyvault show -n nextgen-agents-kv --query properties.networkAcls`

### Accessing Expired Secrets

If a secret is deleted or you need the old value:

```bash
# View deleted secrets
az keyvault secret list-deleted --vault-name nextgen-agents-kv

# Recover a deleted secret
az keyvault secret recover \
  --vault-name nextgen-agents-kv \
  --name secret-name
```

## 📚 References

- [Azure Key Vault Documentation](https://learn.microsoft.com/azure/key-vault/)
- [Azure Identity Library](https://learn.microsoft.com/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Azure SQL Database Security](https://learn.microsoft.com/azure/azure-sql/database/security-overview)
- [OWASP Security Cheat Sheet](https://cheatsheetseries.owasp.org/)
- [Azure Security Center](https://learn.microsoft.com/azure/security-center/)
