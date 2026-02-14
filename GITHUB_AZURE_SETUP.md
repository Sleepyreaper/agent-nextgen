# GitHub & Azure CI/CD Setup Guide

This guide explains how to set up continuous integration and deployment for the Agent NextGen project.

## Prerequisites

- GitHub account with this repository
- Azure Web App already deployed (`nextgen-agents-web.azurewebsites.net`)
- Access to Azure Portal

## Step 1: Get Azure Web App Publish Profile

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **App Services** → **nextgen-agents-web**
3. Click **Get publish profile** (top right)
   - This downloads an XML file with deployment credentials
4. Keep this file safe - it contains sensitive deployment information

## Step 2: Add GitHub Secrets

1. Go to your GitHub repository
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add:

### Required Secrets:

**`AZURE_WEBAPP_NAME`**
- Value: `nextgen-agents-web`
- Description: Your Azure Web App name

**`AZURE_WEBAPP_PUBLISH_PROFILE`**
- Value: Upload the entire XML file contents from Step 1
- Description: Azure Web App publish profile

## Step 3: Configure GitHub Repository

### Enable branch protection (optional but recommended):

1. Go to **Settings** → **Branches**
2. Click **Add rule** under "Branch protection rules"
3. Pattern: `main`
4. Enable:
   - ✅ Require status checks to pass before merging
   - ✅ Require code reviews before merging (at least 1)
   - ✅ Dismiss stale pull request approvals

## How the CI/CD Pipeline Works

### Manual Deployment Steps

The workflows will automatically:

1. **On Push to Main** (deploy-to-azure.yml):
   - ✅ Run tests
   - ✅ Lint code
   - ✅ Deploy to Azure Web App

2. **On Pull Requests** (quality-checks.yml):
   - ✅ Run security scans (Gitleaks, Trivy)
   - ✅ Check for hardcoded credentials
   - ✅ Validate dependencies for vulnerabilities
   - ✅ Verify all modules load correctly

### Manual Trigger (Optional)

If you want to manually trigger a deployment without pushing code:

1. Go to **Actions** tab in GitHub
2. Select **Deploy to Azure Web App** workflow
3. Click **Run workflow** → **Run workflow**

## Environment Variables for Azure Web App

Make sure these are configured in your Azure Web App **Settings**:

```
AZURE_OPENAI_ENDPOINT=<your-endpoint>
AZURE_DEPLOYMENT_NAME=<your-deployment>
AZURE_API_VERSION=2024-12-01-preview
AZURE_SUBSCRIPTION_ID=<your-subscription-id>
AZURE_RESOURCE_GROUP=<your-resource-group>
AZURE_KEY_VAULT_NAME=nextgen-agents-kv
POSTGRES_DB=ApplicationsDB
POSTGRES_USER=<username>
AZURE_STORAGE_ACCOUNT_NAME=nextgenagentsstorage
AZURE_STORAGE_CONTAINER_NAME=student-uploads
FLASK_SECRET_KEY=<generate-a-strong-random-key>
```

To add these:
1. Azure Portal → App Services → **nextgen-agents-web** → **Configuration**
2. Click **New application setting** for each variable
3. Click **Save**

## First Deployment

1. Make a small change to the code (e.g., update a comment)
2. Push to main branch:
   ```bash
   git add .
   git commit -m "Initial commit with CI/CD setup"
   git push origin main
   ```
3. Go to GitHub **Actions** tab
4. Watch the **Deploy to Azure Web App** workflow run
5. Once complete, visit `https://nextgen-agents-web.azurewebsites.net/` to verify deployment

## Security Best Practices

✅ **What We've Done:**
- Removed exposed credentials from documentation
- .gitignore excludes `.env` files
- GitHub Actions runs security scans
- Credentials managed via Azure Key Vault (not in code)
- Environment variables stored in Azure App Settings (not in repoimestamp

⚠️ **Important:**
- Never commit `.env` files
- Never hardcode API keys, passwords, or tokens
- Use Azure Key Vault for production secrets
- Rotate credentials if accidentally exposed

## Troubleshooting

### Deployment fails with authentication error

**Check:**
1. Did you upload the correct publish profile?
2. Is the Azure Web App still online?
3. Try re-generating the publish profile and updating the secret

### Code quality checks fail

**Common issues:**
- Missing Python dependencies → Update `requirements.txt`
- Hardcoded credentials detected → Remove and use environment variables
- Module import errors → Run locally with `python app.py` to debug

### App runs locally but fails on Azure

**Likely causes:**
1. Missing environment variables → Add to Azure App Settings
2. Different Python version → Check Azure runtime stack versions
3. File permission issues → Check Azure deployment logs

## Monitoring Deployments

1. Go to **Actions** in your GitHub repo
2. Each workflow run shows:
   - ✅ Tests & validation results
   - ✅ Deployment status
   - ❌ Any failures with error details
3. For Azure logs, visit Azure Portal:
   - **App Services** → **nextgen-agents-web** → **Deployment center** or **Log stream**

## Next Steps

1. ✅ Push code to GitHub
2. ✅ Verify GitHub Actions workflows run
3. ✅ Check that deployment succeeds
4. ✅ Test the deployed app
5. ✅ Set up monitoring alerts (optional)

---

For additional help with GitHub Actions, see: https://docs.github.com/en/actions
For Azure deployment issues, see: https://docs.microsoft.com/en-us/azure/app-service/
