# PostgreSQL Database & Key Vault Setup - Manual Guide

## Quick Summary

You'll need to complete these tasks to set up your new PostgreSQL database with secure credential storage:

1. ✅ Create the database `<your-db-name>` (via Azure Portal)
2. ✅ Create an app user with limited privileges
3. ✅ Store credentials in Azure Key Vault
4. ✅ Test the connection

---

## Step 1: Create the New Database

### Via Azure Portal (Recommended)

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to your PostgreSQL Flexible Server
3. In the left sidebar, click **Databases**
4. Click **+ Add** to create a new database
5. Enter database name: `<your-db-name>`
6. Click **Save**

### Via psql/pgAdmin

```bash
# Connect as admin
psql -h <server-address> -U <admin-username> -d postgres

# Create the database
CREATE DATABASE <your-db-name>;

# Verify it was created
\l
```

---

## Step 2: Create Application User with Limited Privileges

Once the database is created, connect to it and create a dedicated user for the application:

```bash
# Connect as admin to the new database
psql -h <server-address> -U <admin-username> -d <your-db-name>
```

Run these SQL commands:

```sql
-- Create the application user (choose a secure password)
CREATE USER agent_app_user WITH PASSWORD '<app-user-password>';

-- Grant basic connection privileges
GRANT CONNECT ON DATABASE <your-db-name> TO agent_app_user;

-- Grant schema privileges
GRANT USAGE ON SCHEMA public TO agent_app_user;
GRANT CREATE ON SCHEMA public TO agent_app_user;

-- Grant default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO agent_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO agent_app_user;

-- Verify the user was created
\du
```

---

## Step 3: Store Credentials in Azure Key Vault

### Via Azure Portal

1. Go to your Key Vault: **your-keyvault-name**
2. Click **Secrets** in the left sidebar
3. Click **+ Generate/Import** for each secret

Create these secrets:

| Secret Name | Value | Example |
|---|---|---|
| `postgres-host` | Server hostname | `your-postgres-host` |
| `postgres-port` | Port number | `5432` |
| `postgres-database` | Database name | `<your-db-name>` |
| `postgres-username` | App user username | `agent_app_user` |
| `postgres-password` | App user password | `<app-user-password>` |
| `postgres-admin-username` | Admin username | `<admin-username>` |
| `postgres-admin-password` | Admin password | `<admin-password>` |

---

## Step 4: Update Application Configuration

Update `.env.local` with the new credentials:

```bash
# PostgreSQL Database Configuration
POSTGRES_HOST=<your-server-address>
POSTGRES_PORT=5432
POSTGRES_DB=<your-db-name>
POSTGRES_USER=agent_app_user  # Use app user, not admin
POSTGRES_PASSWORD=<app-user-password>

# Azure Key Vault (for production)
AZURE_KEY_VAULT_NAME=your-keyvault-name
```

**File location:** `/path/to/Agent NextGen/.env.local`

---

## Step 5: Test the Connection

Run the initialization script to verify everything works:

```bash
cd /path/to/Agent\ NextGen
source .venv/bin/activate

# Test the connection
python scripts/init/init_postgresql.py
```

Expected output:
```
✅ PostgreSQL Host: <your-host>
✅ PostgreSQL Database: <your-db-name>
✅ Connected to PostgreSQL
✅ Database schema created successfully
```

---

## Step 6: Enable Key Vault Access (Production)

The local setup uses `.env.local` for now. To use Key Vault in production:

1. **Enable Network Access to Key Vault:**
   - Go to: Azure Portal → Key Vault → Networking
   - Change from "Private Endpoint" mode to allow app service access
   - Or create a managed identity for your app service

2. **Verify Permissions:**
   ```bash
   az keyvault secret list --vault-name your-keyvault-name
   ```

---

## Troubleshooting

### Connection Fails - Authentication Error

```
FATAL: password authentication failed for user "<admin-username>"
```

**Solution:**
- Verify the password is correct (case-sensitive)
- Check that the user exists on the server
- Ensure you're connecting to the correct server address

### Connection Timeout

```
connection to server failed: timeout
```

**Solution:**
- Check PostgreSQL server firewall rules
- Ensure your IP is whitelisted in Azure PostgreSQL networking settings
- Verify server is running (`az postgres flexible-server show`)

### Key Vault Access Denied

```
Forbidden: Public network access is disabled
```

**Solution:**
- Use `.env.local` for local development (current setup)
- For production, configure managed identities or private endpoints
- Or temporarily enable public network access for setup

### Database Already Exists

If `<your-db-name>` already exists, you can:

```sql
-- Connect as admin
psql -h <server> -U <admin-username> -d postgres

-- Drop existing database (⚠️ WARNING: This deletes all data!)
DROP DATABASE IF EXISTS <your-db-name>;

-- Then create fresh
CREATE DATABASE <your-db-name>;
```

---

## Security Best Practices

1. **Use Strong Passwords:**
   - App user password: At least 20 characters
   - Mix uppercase, lowercase, numbers, symbols
   - Avoid dictionary words or patterns

2. **Limit User Privileges:**
   - App user has SELECT, INSERT, UPDATE, DELETE on tables
   - App user cannot create other users
   - App user cannot modify schema permanently

3. **Secure Credential Storage:**
   - Never commit `.env.local` to git
   - Use Key Vault for production
   - Rotate passwords periodically

4. **Audit Access:**
   - Enable PostgreSQL query logging
   - Monitor Key Vault access logs
   - Set up Azure Alerts for suspicious activity

---

## Next Steps

After completing 1-6 above:

1. Start the Flask application:
   ```bash
   python app.py
   ```

2. Test the app at: http://localhost:5002

3. Monitor logs for any database connectivity issues

4. Once verified, push configuration to production Key Vault

---

## Quick Reference Commands

```bash
# Test PostgreSQL connection
psql -h <server> -U <user> -d <your-db-name> -c "SELECT 1"

# List all databases
psql -h <server> -U <admin-username> -d postgres -c "\l"

# List all users
psql -h <server> -U <admin-username> -d postgres -c "\du"

# Check Key Vault secrets
az keyvault secret list --vault-name your-keyvault-name

# Get a specific secret (masked)
az keyvault secret show --vault-name your-keyvault-name --name postgres-password --query value
```

---

## Support

If you encounter issues:

1. Check Azure PostgreSQL server logs
2. Verify firewall rules allow your IP
3. Ensure credentials are correct (copy-paste to avoid typos)
4. Test from Azure Cloud Shell for baseline connectivity

For more help, see:
- [Azure PostgreSQL Docs](https://learn.microsoft.com/en-us/azure/postgresql/)
- [Azure Key Vault Docs](https://learn.microsoft.com/en-us/azure/key-vault/)
