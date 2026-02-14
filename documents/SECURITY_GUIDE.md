# Security Guide - Secure by Default

## 🔒 Overview

This application follows a **secure-by-default** approach:
- ✅ **No credentials in code** - Ever
- ✅ **No credentials in .env files** - Checked into Git
- ✅ **All secrets in Azure Key Vault** - Enterprise-grade security
- ✅ **Azure AD authentication** - For Azure OpenAI
- ✅ **HTTPS/TLS everywhere** - Encrypted connections

## 🎯 Security Architecture

```
Application Code
     ↓
Config Module (src/config.py)
     ↓
DefaultAzureCredential (Azure Identity SDK)
     ↓
Azure Key Vault
     ↓
Encrypted Secrets (at rest & in transit)
```

### Authentication Flow

1. **Application starts** → Initializes `Config` class
2. **Config checks** → Looks for `AZURE_KEY_VAULT_NAME` environment variable
3. **Azure AD auth** → Uses `DefaultAzureCredential` (automatic)
4. **Fetch secrets** → Retrieves all configuration from Key Vault
5. **Cache in memory** → Secrets cached (never written to disk)
6. **Fallback** → If Key Vault unavailable, uses `.env.local` (local dev only)

## 🔐 Key Vault Secrets

All sensitive configuration is stored in Azure Key Vault: `nextgen-agents-kv`

### Secrets Stored

| Secret Name | Purpose | Example |
|-------------|---------|---------|
| `azure-openai-endpoint` | Azure OpenAI service URL | `https://your-resource.openai.azure.com/` |
| `azure-deployment-name` | GPT model deployment | `NextGenGPT` |
| `azure-api-version` | API version | `2024-12-01-preview` |
| `azure-subscription-id` | Azure subscription | `xxxxxxxx-xxxx-...` |
| `azure-resource-group` | Resource group | `NextGen_Agents` |
| `postgres-host` | PostgreSQL hostname | `your-db.postgres.database.azure.com` |
| `postgres-port` | PostgreSQL port | `5432` |
| `postgres-database` | Database name | `ApplicationsDB` |
| `postgres-username` | DB username | `dbuser` |
| `postgres-password` | DB password | `***` (secure) |
| `flask-secret-key` | Flask session encryption | Auto-generated 64-char hex |

### Setting Up Secrets

**Option 1: Use the setup script (recommended)**

```bash
./setup_keyvault.sh
```

**Option 2: Manual setup**

```bash
# Set each secret individually
az keyvault secret set \
  --vault-name nextgen-agents-kv \
  --name postgres-password \
  --value 'your-secure-password'
```

**Option 3: Bulk import from existing .env.local**

```bash
# Only use this locally - never commit the script with real values
while IFS='=' read -r key value; do
  [[ $key =~ ^#.*$ ]] && continue
  [[ -z $key ]] && continue
  secret_name=$(echo "$key" | tr '[:upper:]' '[:lower:]' | sed 's/_/-/g')
  az keyvault secret set --vault-name nextgen-agents-kv --name "$secret_name" --value "$value"
done < .env.local
```

## 🛡️ Access Control

### Required Azure Permissions

To run this application, you need:

1. **Azure AD Login**
   ```bash
   az login
   ```

2. **Key Vault Permissions**
   - Role: `Key Vault Secrets User` or `Key Vault Reader`
   - Grants: `Get` and `List` permissions on secrets

3. **Azure OpenAI Permissions**
   - Role: `Cognitive Services OpenAI User`
   - Scope: Your Azure OpenAI resource

### Granting Access

**Grant yourself access (one-time setup):**

```bash
# Get your user object ID
USER_ID=$(az ad signed-in-user show --query id -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $USER_ID \
  --secret-permissions get list

# Grant Azure OpenAI access
az role assignment create \
  --assignee $USER_ID \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/YOUR_SUB_ID/resourceGroups/NextGen_Agents/providers/Microsoft.CognitiveServices/accounts/YOUR_OPENAI_RESOURCE
```

**Grant managed identity access (for Azure Web App):**

```bash
# Get the web app's managed identity
PRINCIPAL_ID=$(az webapp identity show \
  --resource-group NextGen_Agents \
  --name your-webapp-name \
  --query principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $PRINCIPAL_ID \
  --secret-permissions get list
```

## 🚫 What NOT to Do

### Never Do This

❌ **DON'T** commit `.env` with real credentials
❌ **DON'T** hardcode passwords/secrets in code
❌ **DON'T** put secrets in comments or documentation
❌ **DON'T** share Key Vault secrets via email/Slack
❌ **DON'T** store secrets in application logs
❌ **DON'T** disable SSL/TLS for database connections

### If You Accidentally Commit Secrets

1. **Immediately rotate** the compromised secret in Key Vault
2. **Remove** the commit from Git history:
   ```bash
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch .env" \
     --prune-empty --tag-name-filter cat -- --all
   ```
3. **Force push** (if on private repo):
   ```bash
   git push --force --all
   ```
4. **Consider the secret compromised** - rotate to be safe

## ✅ Best Practices

### Development Workflow

1. **Clone repository**
   ```bash
   git clone <repo>
   cd Agent\ NextGen
   ```

2. **Login to Azure**
   ```bash
   az login
   az account set --subscription <your-sub-id>
   ```

3. **Set Key Vault name** (one-time)
   ```bash
   echo "AZURE_KEY_VAULT_NAME=nextgen-agents-kv" > .env.local
   ```

4. **Run application** (secrets auto-load from Key Vault)
   ```bash
   source .venv/bin/activate
   python app.py
   ```

### Production Deployment

1. **Enable Managed Identity** on Azure Web App
2. **Grant Key Vault access** to the managed identity
3. **Set environment variable**:
   ```bash
   az webapp config appsettings set \
     --resource-group NextGen_Agents \
     --name your-webapp \
     --settings AZURE_KEY_VAULT_NAME=nextgen-agents-kv
   ```
4. **Deploy** - Application uses Managed Identity automatically

### Secret Rotation

Rotate secrets regularly (recommended: every 90 days):

```bash
# Generate new password
NEW_PASSWORD=$(openssl rand -base64 32)

# Update in Key Vault
az keyvault secret set \
  --vault-name nextgen-agents-kv \
  --name postgres-password \
  --value "$NEW_PASSWORD"

# Update in PostgreSQL
psql -h your-db-host -U admin -c \
  "ALTER USER dbuser WITH PASSWORD '$NEW_PASSWORD';"

# Restart application (to pick up new secret)
az webapp restart --resource-group NextGen_Agents --name your-webapp
```

## 🔍 Audit & Monitoring

### View Secret Access Logs

```bash
# Enable diagnostic logging (one-time setup)
az monitor diagnostic-settings create \
  --name keyvault-logs \
  --resource /subscriptions/YOUR_SUB/resourceGroups/NextGen_Agents/providers/Microsoft.KeyVault/vaults/nextgen-agents-kv \
  --logs '[{"category": "AuditEvent", "enabled": true}]'

# View recent access
az monitor activity-log list \
  --resource-group NextGen_Agents \
  --max-events 50
```

### List All Secrets (without values)

```bash
az keyvault secret list --vault-name nextgen-agents-kv -o table
```

### Check Secret Metadata

```bash
az keyvault secret show \
  --vault-name nextgen-agents-kv \
  --name postgres-password \
  --query "{name:name, enabled:attributes.enabled, created:attributes.created}"
```

## 📚 References

- [Azure Key Vault Best Practices](https://learn.microsoft.com/azure/key-vault/general/best-practices)
- [DefaultAzureCredential](https://learn.microsoft.com/python/api/azure-identity/azure.identity.defaultazurecredential)
- [Managed Identities](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/overview)

## 🆘 Troubleshooting

### "Could not retrieve secret from Key Vault"

**Cause**: Missing permissions or wrong vault name

**Solution**:
```bash
# Verify vault name
az keyvault list -o table

# Check your access
az keyvault secret list --vault-name nextgen-agents-kv

# Grant yourself access if needed
az keyvault set-policy --name nextgen-agents-kv \
  --object-id $(az ad signed-in-user show --query id -o tsv) \
  --secret-permissions get list
```

### "DefaultAzureCredential failed"

**Cause**: Not logged in to Azure

**Solution**:
```bash
az login
az account set --subscription <your-subscription-id>
```

### Application using .env.local instead of Key Vault

**Cause**: AZURE_KEY_VAULT_NAME not set or Key Vault unavailable

**Solution**:
```bash
# Ensure Key Vault name is set
export AZURE_KEY_VAULT_NAME=nextgen-agents-kv

# Or add to .env.local temporarily
echo "AZURE_KEY_VAULT_NAME=nextgen-agents-kv" >> .env.local
```

---

**Remember**: Security is a layered approach. Use Key Vault, enable audit logging, rotate secrets regularly, and never commit credentials to version control.
