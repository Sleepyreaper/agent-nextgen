# Migration Guide: PostgreSQL to Azure SQL Database

## Overview

Your application has been migrated from PostgreSQL to Azure SQL Database. All database code has been updated to use SQL Server with pyodbc driver.

## Files Changed

### New Files Created
- `database/schema_azure_sql.sql` - Azure SQL schema (T-SQL compatible)
- `scripts/init/init_azure_sql_database.py` - Database initialization script
- `.env.local.template` - Configuration template for Azure SQL
- `src/database_postgres_backup.py` - Backup of old PostgreSQL database.py

### Modified Files
- `src/database.py` - **Replaced** with Azure SQL version using pyodbc
- `src/config.py` - Added SQL Server configuration fields
- `requirements.txt` - Changed from `psycopg[binary]` to `pyodbc`

## Setup Steps

### 1. Install ODBC Driver (if not already installed)

**macOS:**
```bash
brew install unixodbc
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18 mssql-tools18
```

**Linux (Ubuntu/Debian):**
```bash
curl https://packages.microsoft.com/keys/microsoft.asc | sudo apt-key add -
curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list
sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
```

**Windows:**
Download from: https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server

### 2. Update Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure .env.local

Update your `.env.local` file with Azure SQL Database credentials:

```env
SQL_SERVER=your-sql-server.database.windows.net
SQL_DATABASE=your-sql-database
SQL_USERNAME=your_admin_username
SQL_PASSWORD=your_admin_password
```

### 4. Initialize Azure SQL Database

Run the initialization script to create all tables:

```bash
python scripts/init/init_azure_sql_database.py
```

This will:
- Connect to your Azure SQL Database
- Create all 15 required tables
- Create indexes for performance
- Verify the schema

### 5. Test the Connection

Test the updated database connection:

```bash
python -c "from src.database import db; print('✓ Connection successful'); print(f'Tables: {len(db.execute_query(\"SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'dbo'\"))}')"
```

## Key Changes from PostgreSQL to SQL Server

### Data Type Conversions
- `SERIAL` → `INT IDENTITY(1,1)`
- `BOOLEAN` → `BIT`
- `TEXT` → `NVARCHAR(MAX)
`
- `VARCHAR(n)` → `NVARCHAR(n)`
- `JSONB` → `NVARCHAR(MAX)` (stored as JSON string)
- `DOUBLE PRECISION` → `FLOAT`
- `TIMESTAMP` → `DATETIME2`
- `NUMERIC(x,y)` → `DECIMAL(x,y)`

### SQL Syntax Changes
- `%s` placeholders → `?` placeholders
- `RETURNING column` → `OUTPUT INSERTED.column`
- `CURRENT_TIMESTAMP` → `GETDATE()`
- `ILIKE` → `LIKE` (case-insensitive search)
- `LIMIT n` → `TOP n`
- Boolean values: `TRUE/FALSE` → `1/0`

### Connection String
- PostgreSQL: `host={host} dbname={db} user={user} password={pass} sslmode=require`
- SQL Server: `DRIVER={ODBC Driver 18};SERVER={server};DATABASE={db};UID={user};PWD={pass};Encrypt=yes`

## Azure SQL Database Information

Your database: **your-sql-database**
- Server: `your-sql-server.database.windows.net`
- Service Tier: Set based on your Azure configuration
- Region: Based on deployment

## Migration Checklist

- [ ] Install ODBC Driver 18 for SQL Server
- [ ] Update `.env.local` with SQL Server credentials
- [ ] Run `pip install -r requirements.txt`
- [ ] Test connection with the test command
- [ ] Run `python scripts/init/init_azure_sql_database.py`
- [ ] Verify all 15 tables created
- [ ] Test Flask application startup
- [ ] Migrate data (if needed) from PostgreSQL

## Data Migration (if needed)

If you have existing data in PostgreSQL you want to migrate:

1. Export data from PostgreSQL:
   ```bash
   pg_dump -h your-postgres-host -U your-user -d ApplicationsDB --data-only --inserts > data_export.sql
   ```

2. Modify the export for SQL Server compatibility
3. Import into Azure SQL Database using SQL Server Management Studio or Azure Data Studio

## Troubleshooting

### Error: "Data source name not found"
- Install ODBC Driver 18 for SQL Server (see step 1)

### Error: "Login failed for user"
- Verify SQL_USERNAME and SQL_PASSWORD in .env.local
- Check Azure SQL firewall rules allow your IP

### Error: "Cannot open database"
- Verify SQL_DATABASE name is correct
- Ensure database exists in Azure SQL Server

### Error: "SSL Provider: Certificate verify failed"
- Connection string already includes `TrustServerCertificate=no;Encrypt=yes` for secure connection

## Rollback (if needed)

If you need to rollback to PostgreSQL:

1. Restore original database.py:
   ```bash
   cp src/database_postgres_backup.py src/database.py
   ```

2. Restore requirements.txt:
   ```txt
   psycopg[binary]>=3.1.0
   ```

3. Run: `pip install -r requirements.txt`

4. Update `.env.local` with PostgreSQL credentials

## Support

- Azure SQL Database Documentation: https://docs.microsoft.com/en-us/azure/azure-sql/database/
- pyodbc Documentation: https://github.com/mkleehammer/pyodbc/wiki
- ODBC Driver Download: https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
