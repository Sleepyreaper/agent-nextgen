# SECURITY REMEDIATION GUIDE

## 🚨 CRITICAL: Git History Cleanup Required

Your git repository contains plaintext passwords in commits. **You must clean the git history.**

---

## QUICKSTART: Clean Your Git History (5 minutes)

### Prerequisites
```bash
# Install BFG Repo-Cleaner (recommended, faster than git filter-branch)
brew install bfg

# Or use git filter-branch (built-in, but slower)
```

### Step 1: Prepare Password List
Create a file containing the exposed passwords:

```bash
cat > /tmp/credentials-to-remove.txt << 'EOF'
***REMOVED***
***REMOVED***
EOF
```

### Step 2: Clone Mirror Repository
```bash
cd /tmp
git clone --mirror https://github.com/YOUR_USERNAME/Agent-NextGen.git Agent-NextGen.git
cd Agent-NextGen.git
```

### Step 3: Use BFG to Remove Passwords
```bash
bfg --replace-text /tmp/credentials-to-remove.txt --no-blob-protection
```

**What this does:**
- Scans all commits
- Replaces exposed passwords with `***REMOVED***`
- Rewrites git history
- Leaves working directory unchanged

### Step 4: Prune and Force Push
```bash
# Clean up old objects
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push to remote (WARNS: rewrites history for all)
git push --force --all

# Verify history is clean
git log -p | grep -i "password\|P@ssw0rd\|Nextgen2024"
# Should return nothing
```

### Step 5: Cleanup
```bash
# Delete the mirror clone
cd ..
rm -rf Agent-NextGen.git

# All developers need to clone fresh
git clone https://github.com/YOUR_USERNAME/Agent-NextGen.git Agent-NextGen-Clean
```

---

## ALTERNATIVE: Using git filter-branch

If you prefer the built-in tool:

```bash
# Create placeholder
export PLACEHOLDER="***REMOVED***"

# Filter each password
git filter-branch -f --tree-filter "
  find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.json' \) \
    -exec sed -i '' 's/***REMOVED***/$PLACEHOLDER/g' {} + 2>/dev/null || true
  find . -type f \( -name '*.py' -o -name '*.md' -o -name '*.json' \) \
    -exec sed -i '' 's/***REMOVED***/$PLACEHOLDER/g' {} + 2>/dev/null || true
" -- --all

# Force push
git push --force --all
```

---

## Going Forward: PREVENT Future Leaks

### 1. Create `.env.example` (Template Only - NO Real Secrets)

Place in root directory:
```
# Database Configuration (Use actual values in .env - never commit)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=nextgenagentpostgres
POSTGRES_USER=sleepy
POSTGRES_PASSWORD=your_local_password_here

# Azure Configuration
AZURE_KEYVAULT_URL=https://nextgen-agents-kv.vault.azure.net/
AZURE_CLIENT_ID=your_client_id
AZURE_CLIENT_SECRET=your_secret_never_hardcoded
AZURE_TENANT_ID=your_tenant_id
```

### 2. Update `.gitignore`

Add to root `.gitignore`:
```gitignore
# 🔒 NEVER COMMIT SECRETS
.env
.env.local
.env.*.local
.env.production.local
.venv/
venv/

# Credentials and Keys
*.key
*.pem
*.p12
secrets/
credentials.json
config/secrets.yml

# IDE secrets
.vscode/settings.json
.idea/

# Logs that might contain credentials
logs/
*.log
npm-debug.log*

# Test files with hardcoded values
testing/
test_*.py (but keep unit tests that don't need credentials)
```

### 3. Install Pre-commit Hook

Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
# Prevents committing files with exposed passwords

PATTERNS=(
    "password.*=.*['\"].*['\"]"
    "secret.*=.*['\"].*['\"]"
    "***REMOVED***"
    "***REMOVED***"
    "POSTGRES_PASSWORD.*="
    "AZURE_CLIENT_SECRET.*="
)

EXIT_CODE=0

for pattern in "${PATTERNS[@]}"; do
    if git diff --cached -S "$pattern" | grep -q "$pattern"; then
        echo "❌ SECURITY: Possible credentials in staged changes"
        echo "   Pattern matched: $pattern"
        echo "   Run 'git diff --cached' to review changes"
        echo "   Remove sensitive data before committing"
        EXIT_CODE=1
    fi
done

if [ $EXIT_CODE -ne 0 ]; then
    exit 1
fi
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### 4. Configure Application to Use Environment Variables

**Never do this:**
```python
# ❌ WRONG - Never hardcode defaults
password = os.getenv('POSTGRES_PASSWORD', 'DefaultPassword123')
```

**Do this instead:**
```python
# ✅ CORRECT - Require explicit configuration
password = os.getenv('POSTGRES_PASSWORD')
if not password:
    raise ValueError("POSTGRES_PASSWORD environment variable not set. "
                     "Use .env file or Azure Key Vault.")
```

---

## Local Development Setup

### For Each Developer:

1. **Copy the template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit with real credentials (local only):**
   ```bash
   # .env
   POSTGRES_HOST=localhost
   POSTGRES_USER=sleepy
   POSTGRES_PASSWORD=your_local_test_password
   ```

3. **Verify it's ignored:**
   ```bash
   git status | grep .env
   # Should show nothing (file is ignored)
   ```

4. **Load in Python:**
   ```python
   from dotenv import load_dotenv
   
   load_dotenv()  # Loads .env file
   password = os.getenv('POSTGRES_PASSWORD')
   ```

5. **Install python-dotenv:**
   ```bash
   pip install python-dotenv
   ```

---

## Production Setup (Azure)

### Using Azure App Service:

1. **Set environment variables:**
   ```bash
   az webapp config appsettings set \
     --resource-group nextgen-agents-rg \
     --name nextgen-agents-api \
     --settings \
       POSTGRES_HOST="nextgenagentpostgres.postgres.database.azure.com" \
       POSTGRES_USER="sleepy" \
       POSTGRES_PASSWORD="actual_secure_password"
   ```

2. **Or better - use Azure Key Vault:**
   ```bash
   # Store in Key Vault
   az keyvault secret set \
     --vault-name nextgen-agents-kv \
     --name "postgres-password" \
     --value "actual_secure_password"
   
   # Reference in app:
   POSTGRES_PASSWORD="@Microsoft.KeyVault(SecretUri=https://nextgen-agents-kv.vault.azure.net/secrets/postgres-password/)"
   ```

3. **Access from Python:**
   ```python
   from azure.identity import ManagedIdentityCredential
   from azure.keyvault.secrets import SecretClient
   
   credential = ManagedIdentityCredential()
   client = SecretClient(vault_url="https://nextgen-agents-kv.vault.azure.net/", credential=credential)
   
   password = client.get_secret("postgres-password").value
   ```

---

## Verification Checklist

After completing remediation:

- [ ] Git history cleaned (BFG or filter-branch done)
- [ ] Force push completed to all branches
- [ ] .env.example created (no real secrets)
- [ ] .gitignore updated to exclude .env
- [ ] Pre-commit hook installed
- [ ] All developers have clean clone
- [ ] Local .env files created with test credentials
- [ ] Testing verified with environment variables
- [ ] Production using Key Vault
- [ ] Documentation updated
- [ ] Team trained on credential handling

---

## Troubleshooting

### "git push --force rejected"
This usually means the repo is protected. You may need:
- Temporarily disable branch protection on main
- Or ask repo admin to push cleaned history

### "Some passwords still in history"
Re-run BFG with additional password patterns

### "Developers getting merge conflicts"
They need to:
```bash
git fetch origin
git reset --hard origin/main
```

### "I accidentally committed credentials"
1. Don't panic - run remediation immediately
2. Rotate the exposed credentials in services
3. Consider credentials compromised until services reset them

---

## Resources

- [Git Book - Removing Data](https://git-scm.com/book/en/v2/Git-Internals-Maintenance-and-Data-Recovery)
- [BFG Repo-Cleaner Docs](https://rtyley.github.io/bfg-repo-cleaner/)
- [Azure Key Vault Documentation](https://docs.microsoft.com/azure/key-vault/)
- [12 Factor App - Configuration](https://12factor.net/config)

