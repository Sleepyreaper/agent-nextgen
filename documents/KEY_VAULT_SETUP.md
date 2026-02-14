# Azure Key Vault Setup Guide for NextGen Agent System

## Quick Reference

**Key Vault Name:** `nextgen-agents-kv`  
**Location:** West US 2  
**Status:** ✅ Created and configured

## What Was Done

### 1. ✅ Azure Key Vault Created

```bash
az keyvault create \
  --name nextgen-agents-kv \
  --resource-group NextGen_Agents \
  --location westus2
```

**Details:**
- Standard tier (for development/production)
- Soft delete enabled (90-day recovery)
- Your account has full permissions

### 2. ✅ Secrets Stored in Key Vault

The following secrets are now securely managed in Key Vault:

| Secret | Value | Purpose |
|--------|-------|---------|
| `azure-openai-endpoint` | `https://reapaihub6853304142.openai.azure.com/` | Azure OpenAI service endpoint |
| `azure-deployment-name` | `NextGenGPT` | GPT-5.2 model deployment |
| `azure-api-version` | `2024-12-01-preview` | OpenAI API version |
| `azure-subscription-id` | `b1672fa6-8e52-45d0-bf79-ceccc352177d` | Your Azure subscription |
| `azure-resource-group` | `NextGen_Agents` | Resource group name |
| `sql-server` | `nextgen-sql-server.database.windows.net` | SQL Server hostname |
| `sql-database` | `ApplicationsDB` | SQL Database name |
| `flask-secret-key` | `[auto-generated]` | Flask session encryption key |

### 3. ✅ Code Updated for Key Vault

**Files modified:**
- ✅ `src/config.py` - Integrated Azure Key Vault client
- ✅ `src/database.py` - Retrieves config from Key Vault
- ✅ `app.py` - Uses Key Vault secrets
- ✅ `requirements.txt` - Added `azure-keyvault-secrets` SDK
- ✅ `README.md` - Updated documentation

**Key changes:**
- Configuration class now fetches secrets from Key Vault
- Falls back to `.env` for local development if Key Vault unavailable
- No hardcoded credentials in code
- Automatic credential discovery via `DefaultAzureCredential`

## How to Use Key Vault

### For Developers (Local Development)

You don't need to do anything special! The app automatically:
1. Uses your Azure CLI authentication (`az login`)
2. Retrieves secrets from Key Vault
3. Caches secrets in memory for performance

Just run the app normally:
```bash
source .venv/bin/activate
python app.py
```

### For Viewing Secrets

**List all secrets:**
```bash
az keyvault secret list --vault-name nextgen-agents-kv --query "[].name"
```

**View a specific secret:**
```bash
az keyvault secret show \
  --vault-name nextgen-agents-kv \
  --name azure-openai-endpoint \
  --query value -o tsv
```

### For Updating Secrets

**Update an existing secret:**
```bash
az keyvault secret set \
  --vault-name nextgen-agents-kv \
  --name secret-name \
  --value "new-value"
```

**Add a new secret:**
```bash
az keyvault secret set \
  --vault-name nextgen-agents-kv \
  --name my-new-secret \
  --value "secret-value"
```

## Security Benefits

✅ **No secrets in code** - Credentials are fetched at runtime  
✅ **No secrets in .env** - Optional fallback only  
✅ **Centralized management** - All secrets in one place  
✅ **Audit logging** - Who accessed what, when  
✅ **Automatic expiration** - Token-based access  
✅ **Role-based access** - Fine-grained permissions  
✅ **Soft delete** - Recover deleted secrets within 90 days  
✅ **Encryption** - Secrets encrypted at rest and in transit  

## Granting Access to Others

If another person needs access to secrets:

### Method 1: Grant Full Access

```bash
# Get their Azure object ID
user_object_id=$(az ad user show --id "user@company.com" --query objectId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $user_object_id \
  --secret-permissions get list set delete
```

### Method 2: Grant Read-Only Access

```bash
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $user_object_id \
  --secret-permissions get list
```

### Method 3: Grant Service Principal Access (For CI/CD)

```bash
# Get CI/CD service principal object ID
principal_id="<paste-from-ci-cd-system>"

az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $principal_id \
  --secret-permissions get list
```

## Monitoring & Audit

### View Recent Access

```bash
# Get the Key Vault resource ID
vault_id=$(az keyvault show \
  --name nextgen-agents-kv \
  --query id -o tsv)

# View recent activity logs
az monitor activity-log list \
  --resource $vault_id \
  --max-events 10
```

### Set Up Alerts (Optional)

```bash
# Alert on secret changes
az monitor metrics alert create \
  --name "Key Vault Secret Changes" \
  --resource-group NextGen_Agents \
  --scopes $(az keyvault show --name nextgen-agents-kv --query id -o tsv) \
  --evaluation-frequency 5m \
  --window-size 5m \
  --condition "total AuditEventCount > 0"
```

## Troubleshooting

### Error: "The user...does not have permission"

Your Azure account doesn't have Key Vault permissions. Grant yourself access:

```bash
# Your user object ID
my_object_id=$(az ad signed-in-user show --query objectId -o tsv)

# Grant permissions
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $my_object_id \
  --secret-permissions get list set delete
```

### Error: "The Key Vault is not found"

The Key Vault doesn't exist or is in a different subscription:

```bash
# List your Key Vaults
az keyvault list --query "[].name"

# Check your current subscription
az account show --query name
```

### Secrets Not Updating in App

The config module caches secrets in memory. To refresh:

1. Restart the application
2. Or temporarily clear the cache (restart required anyway)

### Lost Key Vault Access

If you accidentally deleted the Key Vault:

```bash
# List deleted Key Vaults
az keyvault list-deleted

# Purge recovery (if needed)
az keyvault purge --location westus2 --name nextgen-agents-kv
```

## Production Deployment

For production on Azure App Service:

### 1. Create Managed Identity

```bash
# Enable managed identity on App Service
az webapp identity assign \
  --name nextgen-app \
  --resource-group NextGen_Agents
```

### 2. Grant Key Vault Access

```bash
# Get the managed identity's object ID
principal_id=$(az webapp identity show \
  --name nextgen-app \
  --resource-group NextGen_Agents \
  --query principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name nextgen-agents-kv \
  --object-id $principal_id \
  --secret-permissions get list
```

### 3. Deploy Code

The application automatically authenticates using the Managed Identity - no credentials needed!

## Next Steps

1. ✅ **Done** - Key Vault is set up and configured
2. ✅ **Done** - Code updated to use Key Vault
3. ⏭️ **Next** - Test the application: `python app.py`
4. ⏭️ **Then** - Deploy to production with Managed Identity

## Getting Help

**Azure Key Vault Documentation:**
https://learn.microsoft.com/azure/key-vault/

**Azure CLI Commands:**
```bash
# Get help for Key Vault commands
az keyvault --help
az keyvault secret --help
```

**Check Configuration:**
```bash
source .venv/bin/activate
python -c "from src.config import config; print(config.get_config_summary())"
```
