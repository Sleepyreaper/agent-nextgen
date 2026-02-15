# PostgreSQL + Azure Key Vault Setup Guide

## Overview
This guide walks you through setting up the NextGen application with PostgreSQL on Azure and securing secrets in Azure Key Vault.

## Prerequisites
- Azure Subscription
- Azure PostgreSQL Flexible Server (ready with database created)
- Azure Key Vault (your-keyvault-name or similar)
- Azure CLI installed and authenticated
- psql command-line tool

## Step 1: Verify PostgreSQL Database

### Check Connection to Azure PostgreSQL

```bash
# Test connection to your PostgreSQL database
psql -h your-postgres-host \
     -U nextgenadmin \
     -d ApplicationsDB \
     -c "SELECT version();"
```

**Expected Output:**
```
PostgreSQL X.X.X on x86_64-pc-linux-gnu...
```

If connection fails:
- Check PostgreSQL server firewall rules (allow your IP)
- Verify credentials in .env.local
- Ensure "Require secure connections" is enabled on the server

### Initialize Database Schema

```bash
# Create the schema in your PostgreSQL database
psql -h your-postgres-host \
     -U nextgenadmin \
     -d ApplicationsDB \
     -f database/schema_postgresql.sql
```

**Verify Schema Creation:**

```bash
psql -h your-postgres-host \
     -U nextgenadmin \
     -d ApplicationsDB \
     -c "\dt"
```

You should see tables like:
- Applications
- merlin_evaluations
- student_school_context
- tiana_applications
- mulan_recommendations
- aurora_evaluations
- etc.

## Step 2: Set Up Azure Key Vault Secrets

### Connect to Azure Portal
1. Go to [Azure Portal](https://portal.azure.com)
2. Search for your Key Vault: **your-keyvault-name**
3. Click on "Secrets" in the left sidebar

### Add PostgreSQL Secrets

Create the following secrets in Key Vault:

| Secret Name | Value | Example |
|---|---|---|
| `postgres-host` | Your PostgreSQL server hostname | `your-postgres-host` |
| `postgres-port` | PostgreSQL port | `5432` |
| `postgres-database` | Database name | `ApplicationsDB` |
| `postgres-username` | Database admin username | `nextgenadmin` |
| `postgres-password` | Database admin password | `<your-db-password>` |

**Alternative: Connection String Secret**

Instead of individual parameters, you can use:

```bash
# Create a single connection string secret
az keyvault secret set \
     --vault-name your-keyvault-name \
  --name postgres-connection-string \
     --value "postgresql://your-username:YOUR_PASSWORD@your-postgres-host:5432/ApplicationsDB?sslmode=require"
```

### Add Azure OpenAI Secrets

| Secret Name | Value |
|---|---|
| `azure-openai-endpoint` | Your Azure OpenAI endpoint URL |
| `azure-deployment-name` | Your deployment name (e.g., NextGenGPT) |
| `azure-api-version` | API version (e.g., 2024-12-01-preview) |
| `azure-subscription-id` | Your Azure subscription ID |
| `azure-resource-group` | Your resource group name |

### Add Storage Secrets (if using Azure Storage)

| Secret Name | Value |
|---|---|
| `storage-account-name` | Storage account name |
| `storage-account-key` | Storage account access key |
| `storage-container-name` | Container name (e.g., student-uploads) |

### Add Flask Secret

```bash
# Generate a secure Flask secret key
FLASK_SECRET=$(openssl rand -hex 32)

# Add to Key Vault
az keyvault secret set \
     --vault-name your-keyvault-name \
  --name flask-secret-key \
  --value "$FLASK_SECRET"
```

## Step 3: Verify Key Vault Access

### Check Your Identity Has Access

```bash
# List all secrets you can access
az keyvault secret list --vault-name your-keyvault-name
```

### Add Access Policy (if needed)

```bash
# Get your object ID
USER_ID=$(az ad signed-in-user show --query id -o tsv)

# Grant secret get/list permissions
az keyvault set-policy \
     --vault-name your-keyvault-name \
  --object-id $USER_ID \
  --secret-permissions get list set
```

## Step 4: Update .env.local

Edit `.env.local` to point to your PostgreSQL database:

```bash
# PostgreSQL Configuration
POSTGRES_HOST=your-postgres-host
POSTGRES_PORT=5432
POSTGRES_DB=ApplicationsDB
POSTGRES_USER=nextgenadmin
POSTGRES_PASSWORD=<YOUR_PASSWORD>

# Key Vault
AZURE_KEY_VAULT_NAME=your-keyvault-name
```

## Step 5: Install Dependencies

```bash
cd /path/to/Agent\ NextGen

# Activate virtual environment
source .venv/bin/activate

# Install/update requirements
pip install -r requirements.txt

# Verify psycopg installation
python -c "import psycopg; print(f'psycopg version: {psycopg.__version__}')"
```

## Step 6: Test Connection

```bash
# Test database connection
python -c "
from src.database import Database
from src.config import config

try:
    db = Database()
    result = db.execute_query('SELECT 1 as test')
    print('✅ PostgreSQL connection successful!')
    print(f'Result: {result}')
except Exception as e:
    print(f'❌ Connection failed: {e}')
"
```

## Step 7: Verify Key Vault Integration

```python
from src.config import config

# Check if Key Vault is connected
print(f"Key Vault Connected: {config._secret_client is not None}")
print(f"Postgres Host (from KV): {config.postgres_host}")
print(f"Deployment Name (from KV): {config.deployment_name}")

# View configuration summary
print(config.get_config_summary())
```

## Step 8: Start Application

```bash
# Clear any previous Python processes
killall -9 python3

# Start the Flask application
python app.py
```

## Troubleshooting

### Issue: Connection Timeout to PostgreSQL

```bash
# Check firewall rules
# In Azure Portal → Postgresql server → Networking → Add current IP

# Verify SSL is enabled
psql -h your-postgres-host \
     -U nextgenadmin \
     -d ApplicationsDB \
     -c "SHOW ssl;"
```

### Issue: Key Vault Access Denied

```bash
# Check you're authenticated to Azure
az account show

# Verify Key Vault access
az keyvault secret list --vault-name your-keyvault-name
```

### Issue: psycopg import error

```bash
# Reinstall psycopg with all dependencies
pip uninstall -y psycopg
pip install psycopg[binary]
```

### Issue: Database schema not found

```bash
# Verify schema was created
psql -h your-postgres-host \
     -U nextgenadmin \
     -d ApplicationsDB \
     -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';"
```

## Security Notes

### 1. SSL/TLS Connection
- PostgreSQL Azure requires SSL/TLS encryption
- Connection string includes `sslmode=require` automatically
- Certificate verification is enabled by default

### 2. Secret Rotation
- Change PostgreSQL password periodically
- Update Key Vault secret immediately
- Monitor Key Vault access logs

### 3. Least Privilege Access
- Use `nextgenadmin` user for application (setup) and consider a read-only user for queries only
- Restrict Key Vault access to service principals only
- Enable Key Vault audit logging

### 4. Environment Variables
- `.env.local` should NOT be committed to git
- Ensure `.env.local` is in `.gitignore`
- Use Key Vault in production, not environment files

## Next Steps

1. ✅ PostgreSQL database created and schema initialized
2. ✅ Key Vault secrets configured
3. ✅ Application updated to use PostgreSQL  
4. ✅ Dependencies installed
5. Run: `python app.py`
6. Access at: `http://localhost:5002`

## Additional Resources

- [Azure PostgreSQL Flexible Server Docs](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/)
- [Azure Key Vault Docs](https://learn.microsoft.com/en-us/azure/key-vault/)
- [psycopg Documentation](https://www.psycopg.org/psycopg3/docs/)
- [Azure Identity Python SDK](https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme)
