# ✅ DEVELOPER SECURITY CHECKLIST

Use this checklist to ensure your local development environment is secure and doesn't leak credentials.

---

## 🚀 Before First Run

- [ ] **Clone the repository fresh**
  ```bash
  git clone https://github.com/yourorg/Agent-NextGen.git
  cd Agent-NextGen
  ```

- [ ] **Verify .gitignore exists and includes .env**
  ```bash
  grep "^\.env$" .gitignore
  # Should output: .env
  ```

- [ ] **Create local .env file**
  ```bash
  cp .env.example .env
  # Edit .env with YOUR LOCAL test credentials
  ```

- [ ] **Verify .env is ignored by git**
  ```bash
  git status | grep .env
  # Should show NOTHING - file must be ignored
  ```

- [ ] **Never ever edit .env.example with real credentials**
  ```bash
  # .env.example is a TEMPLATE - keep it clean
  # All real values go ONLY in .env (which is gitignored)
  ```

---

## 💻 Daily Development

### Before Writing Code

- [ ] **Load environment variables**
  ```python
  from dotenv import load_dotenv
  load_dotenv()  # Loads .env file automatically
  ```

- [ ] **Never use hardcoded defaults**
  ```python
  # ❌ WRONG
  password = os.getenv('POSTGRES_PASSWORD', 'my_default_password')
  
  # ✅ CORRECT
  password = os.getenv('POSTGRES_PASSWORD')
  if not password:
      raise ValueError("POSTGRES_PASSWORD not configured")
  ```

### Creating Test Scripts

- [ ] **Use environment variables, never hardcode**
  ```python
  # Use this pattern:
  import os
  from dotenv import load_dotenv
  
  load_dotenv()
  db_password = os.getenv('POSTGRES_PASSWORD')
  ```

- [ ] **If you need a default, make it obvious**
  ```python
  # For LOCAL TESTING ONLY
  DEFAULT_TEST_PASSWORD = 'test_only_not_for_production'
  password = os.getenv('POSTGRES_PASSWORD', DEFAULT_TEST_PASSWORD)
  
  # Log a warning
  if password == DEFAULT_TEST_PASSWORD:
      print("⚠️ WARNING: Using default test password")
  ```

### Documentation

- [ ] **Never include real passwords in docs**
  ```markdown
  # ❌ NEVER
  Password: my_actual_password_123
  
  # ✅ DO THIS
  Password: [Set in Azure Key Vault - see REMEDIATION_GUIDE.md]
  ```

- [ ] **Redact examples with placeholders**
  ```
  Connection: "postgresql://user:***REDACTED***@host:5432/db"
  API Key: "sk-***REDACTED***"
  ```

---

## 🔍 Before Committing

### Check Your Changes

- [ ] **Review all staged files**
  ```bash
  git diff --cached
  ```

- [ ] **Look for accidentally hardcoded secrets**
  ```bash
  git diff --cached | grep -i "password\|secret\|key\|token"
  # Should return NOTHING (or only references to variables)
  ```

- [ ] **Check for .env file in staging**
  ```bash
  git diff --cached --name-only | grep "\.env"
  # Should return NOTHING (the .env file should be ignored)
  ```

### Before `git commit`

- [ ] **Run security check**
  ```bash
  # Quick check for common secrets
  for pattern in "password\s*=" "secret\s*=" "api.key\s*=" "token\s*="; do
    if git diff --cached | grep -i "$pattern"; then
      echo "⚠️ Found potential secret: $pattern"
    fi
  done
  ```

- [ ] **Verify no .env files are staged**
  ```bash
  git add --dry-run .
  # Review the output - should not include any .env files
  ```

---

## 📝 Code Review Checklist (For Reviewers)

- [ ] No hardcoded passwords in any new code
- [ ] No credentials in documentation
- [ ] No new hardcoded defaults like `os.getenv('VAR', 'actual_secret')`
- [ ] All tests use environment variables or test fixtures, not real credentials
- [ ] No new .env files or .gitignore overrides
- [ ] Configuration uses Key Vault or environment variables
- [ ] No logging that includes passwords or secrets
- [ ] Comments don't contain example credentials

---

## 🚨 If You Accidentally Commit a Secret

**IMMEDIATE ACTION REQUIRED:**

1. **Stop everything**
   ```bash
   # Don't push! Don't do anything else!
   ```

2. **Alert the team**
   - Tell your team lead immediately
   - It's better to tell than to hide it

3. **Remove the commit locally** (if not pushed)
   ```bash
   git reset HEAD~1
   git checkout -- <file>  # Remove the secret
   ```

4. **If already pushed to remote**
   ```bash
   # Contact repo admin - may need force push
   # Run remediation guide steps (BFG or git filter-branch)
   ```

5. **Rotate the exposed credential**
   - Change the password in Azure
   - Update Key Vault with new value
   - Notify security team

---

## 🔧 Configure Your IDE

### VS Code
Add to `.vscode/settings.json`:
```json
{
  "files.exclude": {
    ".env": true,
    ".env.local": true,
    "*.pem": true,
    "*.key": true
  },
  "search.exclude": {
    ".env": true,
    "logs/": true
  }
}
```

### PyCharm
- Mark `.env` file as "Ignored"
- Add to Settings → Version Control → Git → Ignored Files

### Sublime Text
Edit `.gitignore`:
```
.env
.env.local
```

---

## 📚 Resources

- [CRITICAL_SECURITY_AUDIT.md](CRITICAL_SECURITY_AUDIT.md) - What happened and why
- [REMEDIATION_GUIDE.md](REMEDIATION_GUIDE.md) - How to clean git history
- [SECURITY_GUIDE.md](SECURITY_GUIDE.md) - General security practices
- [KEY_VAULT_SETUP.md](../setup/KEY_VAULT_SETUP.md) - Azure Key Vault setup
- [12 Factor App Configuration](https://12factor.net/config) - Best practices

---

## 🆘 Still Have Questions?

1. Check the Security Guide in `documents/security/`
2. Review configuration examples in `src/config.py`
3. Ask your team lead - it's better to ask than to leak secrets

---

## Remember

> **"A secret shared with git is a secret shared with everyone who has access to the repository."**

- ✅ Secrets in Key Vault = Safe
- ✅ Secrets in .env (gitignored) = Acceptable for local dev
- ❌ Secrets in git = Crisis
- ❌ Secrets in code = Project disaster

**Never commit credentials. Ever.**

