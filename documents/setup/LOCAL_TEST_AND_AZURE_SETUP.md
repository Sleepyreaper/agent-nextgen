# NextGen AI System - Local Testing & Azure Setup Guide

## Current Status: ✅ OPERATIONAL

### Server Running
- **URL**: http://localhost:5001
- **Dashboard**: http://localhost:5001/
- **Test Interface**: http://localhost:5001/test
- **Students**: http://localhost:5001/students
- **Training Data**: http://localhost:5001/training

### Configuration
- **Local Dev Environment**: `.env.local` (gitignored)
- **Production Environment**: Azure Key Vault
- **Database**: PostgreSQL (your-postgres-host)
- **LLM**: Azure OpenAI (NextGenGPT deployment)
- **Code Quality**: Security-hardened, no hardcoded secrets

---

## Security Implementation Summary

### ✅ No Hardcoded Secrets
Verified: Zero hardcoded credentials in source code
- All credentials sourced from environment variables
- Environment variables from Key Vault (prod) or .env.local (dev)
- Secrets never logged (logger masks sensitive data)

### ✅ Local Development Mode
When `.env.local` exists:
1. Skips Azure Key Vault authentication
2. Loads credentials from `.env.local`
3. Uses PostgreSQL directly
4. Allows offline testing

### ✅ Production Mode
When deployed to Azure:
1. No `.env.local` file present
2. Uses Managed Identity authentication
3. Retrieves secrets from Key Vault
4. No local configuration needed

---

## Local Testing Workflow

### 1. Start Server
```bash
cd "/path/to/Agent NextGen"
source .venv/bin/activate
python app.py
```

### 2. View Web Interface
- **Dashboard**: http://localhost:5001
- **Test Agents**: http://localhost:5001/test

### 3. Generate Test Data
- Click "Random Fake Applications" (different students each run)
- Or "Fixed Fake Applications" (Alice, Brian, Carol - same each time)
- Watch agents process applications in real-time

### 4. View Results
- Go to http://localhost:5001/students
- Click on a student name to view detailed evaluation
- See Aurora-formatted summary of agent analysis

### 5. Check Logs
- **Application logs**: `logs/application.log`
- **Audit logs**: `logs/audit.log`
- **Test results**: `test_results_local.json`

---

## Azure Key Vault Setup (Production)

### Required Secrets

Store these in Key Vault: `your-keyvault-name`

#### Database
```
postgres-host          → PostgreSQL server hostname
postgres-port          → 5432
postgres-database      → ApplicationsDB
postgres-username      → Database user
postgres-password      → Database password
postgres-url (opt)     → Full connection string
```

#### Azure OpenAI
```
azure-openai-endpoint       → https://{resource}.openai.azure.com/
azure-deployment-name       → NextGenGPT
azure-api-version           → 2024-12-01-preview
```

#### Azure Configuration
```
azure-subscription-id       → Azure subscription ID
azure-resource-group        → Azure resource group name
flask-secret-key            → Random 64-char hex string
```

### Add Secrets Using Azure CLI
```bash
VAULT="your-keyvault-name"

# Database
az keyvault secret set --vault-name $VAULT --name "postgres-host" --value "your-postgres-host"
az keyvault secret set --vault-name $VAULT --name "postgres-password" --value "YOUR_PASSWORD_HERE"

# Azure OpenAI
az keyvault secret set --vault-name $VAULT --name "azure-openai-endpoint" --value "https://your-openai-resource.openai.azure.com/"
az keyvault secret set --vault-name $VAULT --name "azure-deployment-name" --value "NextGenGPT"

# Flask
az keyvault secret set --vault-name $VAULT --name "flask-secret-key" --value "$(openssl rand -hex 32)"
```

---

## File Structure

```
NextGen/
├── .env.local                          # Local dev secrets (gitignored)
├── .env.example                        # Template for local dev
├── documents/setup/KEYVAULT_SETUP_GUIDE.md  # Detailed Key Vault setup
│
├── src/
│   ├── config.py                      # Credential management (KV + env vars)
│   ├── logger.py                      # Professional logging (masks secrets)
│   ├── database.py                    # PostgreSQL with parameterized queries
│   ├── storage.py                     # Azure Storage (graceful fallback)
│   └── agents/                        # All AI agents (Smee, Belle, Tiana, etc.)
│
├── app.py                             # Flask routes (no hardcoded secrets)
├── test_local.py                      # Local dev test suite
├── test_comprehensive.py              # Full integration tests
│
├── logs/                              # Generated at runtime
│   ├── application.log
│   └── audit.log
│
└── web/
    ├── templates/                     # HTML templates
    └── static/                        # CSS, JS, etc.
```

---

## Routes & Functionality

| Route | Purpose | Test |
|-------|---------|------|
| `/` | Dashboard home | ✅ Working |
| `/test` | Generate test applications | ✅ Working |
| `/students` | View all students | ✅ Working |
| `/student/<id>` | View detailed results | ✅ Fixed |
| `/training` | View training examples | ✅ Working |
| `/api/test/submit` | Generate random applications | ✅ Working |
| `/api/test/submit-preset` | Generate fixed 3 candidates | ✅ Working |
| `/api/test/students` | Get student status (polling) | ✅ Working |

---

## Credential Flow Diagram

### Local Development
```
.env.local (contains secrets)
    ↓
config.py: load_dotenv('.env.local')
    ↓
os.getenv() retrieves credentials
    ↓
Database, OpenAI, Storage initialized
    ↓
App runs with local resources
```

### Production (Azure)
```
Azure Key Vault (secrets secured)
    ↓
Managed Identity (automatic authentication)
    ↓
config.py: azure.keyvault.secrets.SecretClient
    ↓
_secret_client.get_secret(name)
    ↓
Database, OpenAI, Storage initialized
    ↓
App runs with Azure resources
```

---

## Testing Locally

### Prerequisites
✅ `.env.local` file exists with credentials
✅ PostgreSQL accessible at configured host
✅ Python 3.9+ with dependencies installed

### Run Tests
```bash
# Quick syntax check
python -m py_compile app.py src/*.py

# Local development tests
python test_local.py

# Full integration tests (if Azure creds available)
python test_comprehensive.py
```

### Verify No Secrets in Code
```bash
# Search for hardcoded credentials
grep -r "password\|secret\|api_key\|token" --include="*.py" src/ app.py | \
  grep -v "config.py\|logger.py\|_get_secret\|getenv\|get_secret"

# Result: Should return nothing (no hardcoded secrets)
```

---

## Common Issues & Solutions

### Issue: "Student not found" when clicking results
**Status**: ✅ FIXED (added student/<id> route)
**Solution**: Server now properly routes to student detail pages

### Issue: Azure Storage not configured
**Status**: ✅ EXPECTED (graceful fallback)
**Behavior**: Uses local storage instead of blob storage
**Solution**: Add storage credentials to `.env.local` or Key Vault if needed

### Issue: PostgreSQL connection failed
**Status**: ⚠️ Configuration needed
**Solution**: Verify POSTGRES_HOST, POSTGRES_PASSWORD in `.env.local`

### Issue: Azure Key Vault access denied
**Status**: ⚠️ Expected in local dev (falls back to .env.local)
**Solution**: Either configure Managed Identity or use `.env.local`

---

## Security Checklist

Before Production Deployment:

- [ ] All secrets in Azure Key Vault
- [ ] `.env.local` file NOT committed to git
- [ ] `.gitignore` includes `.env.local`
- [ ] Managed Identity configured on Azure resources
- [ ] Key Vault network access restricted (if needed)
- [ ] Secret rotation schedule defined
- [ ] Database encryption enabled (TLS)
- [ ] HTTPS enforced in production
- [ ] Audit logging enabled (logs all secret access)
- [ ] Security scanning in CI/CD pipeline

---

## Next Steps

### For Local Development
1. ✅ Server running at http://localhost:5001
2. ✅ Test agents generating synthetic data
3. ✅ All routes operational
4. ✅ Logs properly formatted and masked

### For Production Deployment
1. Set up Azure Key Vault secrets (see guide above)
2. Deploy to Azure App Service or Container Instance
3. Configure Managed Identity
4. Assign Secret Getter role on Key Vault
5. Verify health checks passing
6. Enable monitoring and alerts
7. Document runbook for secret rotation

---

## Documentation References

- 📖 [KEYVAULT_SETUP_GUIDE.md](KEYVAULT_SETUP_GUIDE.md) - Detailed Key Vault setup
- 📖 [SECURITY_AND_EFFICIENCY_AUDIT.md](./SECURITY_AND_EFFICIENCY_AUDIT.md) - Security review
- 📖 [TEST_RESULTS_SUMMARY.md](./TEST_RESULTS_SUMMARY.md) - Test results

---

**Status**: System ready for local testing and production deployment ✅
**Last Updated**: February 15, 2026

