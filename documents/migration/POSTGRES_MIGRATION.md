# PostgreSQL Migration Guide

## Overview

This project now uses **PostgreSQL** instead of Azure SQL Server for better portability, easier local development, and simpler authentication.

## Migration Changes

### 1. Dependencies Changed
- **Removed**: `pyodbc` (SQL Server driver)
- **Added**: `psycopg[binary]` (PostgreSQL driver)

### 2. Configuration Changes

Old (Azure SQL):
```python
SQL_SERVER=your-sql-server.database.windows.net
SQL_DATABASE=ApplicationsDB
SQL_USERNAME=username
SQL_PASSWORD=password
```

New (PostgreSQL):
```python
# Option 1: Full URL
DATABASE_URL=postgresql://user:password@host:5432/dbname?sslmode=require

# Option 2: Individual components
POSTGRES_HOST=your-server.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=ApplicationsDB
POSTGRES_USER=username
POSTGRES_PASSWORD=password
```

### 3. Schema Changes
- `INT IDENTITY(1,1)` → `SERIAL`
- `NVARCHAR` → `VARCHAR`
- `NVARCHAR(MAX)` → `TEXT`
- `DATETIME2` → `TIMESTAMP`
- `BIT` → `BOOLEAN`
- `DECIMAL` → `NUMERIC`
- `FLOAT` → `DOUBLE PRECISION`
- `OUTPUT INSERTED.ID` → `RETURNING ID`
- `?` placeholders → `%s` placeholders

### 4. SQL Syntax Changes
- `TOP 10` → `LIMIT 10`
- `GETDATE()` → `CURRENT_TIMESTAMP`
- `+` string concat → `||` or `CONCAT()`
- `[Table]` brackets → `"table"` quotes (optional)

## Deploy PostgreSQL on Azure

### Option 1: Azure Database for PostgreSQL Flexible Server (Recommended)

```bash
# Create PostgreSQL server
az postgres flexible-server create \
  --resource-group your-resource-group \
  --name your-postgres-server \
  --location westus2 \
  --admin-user adminuser \
  --admin-password 'your-strong-password' \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --version 15 \
  --storage-size 32 \
  --public-access 0.0.0.0-255.255.255.255

# Create database
az postgres flexible-server db create \
  --resource-group your-resource-group \
  --server-name your-postgres-server \
  --database-name ApplicationsDB
```

**Pricing**: ~$15-30/month for B1ms tier (1 vCore, 2GB RAM)

### Option 2: Azure Container Instance with PostgreSQL

```bash
# Run Postgres in Azure Container Instances
az container create \
  --resource-group your-resource-group \
  --name postgres-container \
  --image postgres:15 \
  --cpu 1 \
  --memory 2 \
  --port 5432 \
  --environment-variables \
    POSTGRES_DB=ApplicationsDB \
    POSTGRES_USER=adminuser \
    POSTGRES_PASSWORD='your-strong-password' \
  --dns-name-label your-postgres-server
```

**Pricing**: ~$30/month for 1 vCore, 2GB RAM

### Option 3: Local Development with Docker

```bash
docker run -d \
  --name your-postgres-server \
  -e POSTGRES_DB=ApplicationsDB \
  -e POSTGRES_USER=adminuser \
  -e POSTGRES_PASSWORD=your-password \
  -p 5432:5432 \
  postgres:15
```

**Cost**: Free (local only)

## Configuration Setup

### Using Environment Variables (.env file)

```bash
# Create .env file
cat > .env << 'EOF'
# PostgreSQL
POSTGRES_HOST=your-postgres-server.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=ApplicationsDB
POSTGRES_USER=adminuser
POSTGRES_PASSWORD=your-strong-password

# Or use DATABASE_URL
# DATABASE_URL=postgresql://adminuser:your-strong-password@your-postgres-host:5432/ApplicationsDB?sslmode=require

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai-resource.openai.azure.com/
AZURE_DEPLOYMENT_NAME=NextGenGPT
AZURE_API_VERSION=2024-12-01-preview

# Flask
FLASK_SECRET_KEY=$(openssl rand -hex 32)
EOF
```

### Using Azure Key Vault

```bash
# Store Postgres credentials
az keyvault secret set --vault-name your-keyvault-name \
  --name postgres-host --value your-postgres-server.postgres.database.azure.com

az keyvault secret set --vault-name your-keyvault-name \
  --name postgres-port --value 5432

az keyvault secret set --vault-name your-keyvault-name \
  --name postgres-database --value ApplicationsDB

az keyvault secret set --vault-name your-keyvault-name \
  --name postgres-username --value adminuser

az keyvault secret set --vault-name your-keyvault-name \
  --name postgres-password --value 'your-strong-password'
```

## Initialize Database

```bash
# Install new dependencies
pip install -r requirements.txt

# Run schema initialization
python scripts/init/init_database.py
```

## Firewall Configuration

### Azure Flexible Server

```bash
# Allow your IP
az postgres flexible-server firewall-rule create \
  --resource-group your-resource-group \
  --name your-postgres-server \
  --rule-name AllowMyIP \
  --start-ip-address YOUR_IP \
  --end-ip-address YOUR_IP

# Allow Azure services
az postgres flexible-server firewall-rule create \
  --resource-group your-resource-group \
  --name your-postgres-server \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

## Testing Connection

```bash
# Test with psql CLI
psql "postgresql://adminuser:password@your-postgres-host:5432/ApplicationsDB?sslmode=require"

# Or with Python
python3 << 'EOF'
import psycopg
conn = psycopg.connect(
    "host=your-postgres-server.postgres.database.azure.com "
    "port=5432 dbname=ApplicationsDB user=adminuser "
    "password='your-strong-password' sslmode=require"
)
print("✓ Connected successfully")
conn.close()
EOF
```

## Running the Application

```bash
# Activate venv
source .venv/bin/activate

# Run Flask app
python app.py
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check firewall rules allow your IP |
| SSL required | Add `sslmode=require` to connection string |
| Authentication failed | Verify username/password in Key Vault or .env |
| Database does not exist | Create with `az postgres flexible-server db create` |
| psycopg not found | Run `pip install -r requirements.txt` |

## Benefits of PostgreSQL

✅ **Simpler Auth**: Username/password (no AAD complexity)  
✅ **Lower Cost**: ~$15/month vs $50+ for Azure SQL  
✅ **Local Dev**: Easy Docker setup  
✅ **Standard SQL**: More portable across clouds  
✅ **Better tooling**: pgAdmin, DBeaver, psql CLI  
✅ **JSON support**: Native JSONB for agent outputs  

## Migration Rollback (if needed)

To revert to Azure SQL:

```bash
git checkout HEAD~10 -- requirements.txt src/database.py src/config.py database/schema.sql
pip install -r requirements.txt
```
