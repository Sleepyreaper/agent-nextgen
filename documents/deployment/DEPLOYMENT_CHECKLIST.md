# Azure Web App Deployment Checklist

Follow this checklist to deploy the NextGen Agent System to Azure Web App.

## Prerequisites

- [ ] Azure CLI installed: `az --version`
- [ ] Authenticated with Azure: `az login`
- [ ] Git repository initialized (for CI/CD)
- [ ] Key Vault (`your-keyvault-name`) already created

## Quota Check

- [ ] Verify you have quota for App Service Plans
  ```bash
  # Check quotas
  az vm usage list --location westus2
  ```
  - If no quota available, request increase at Azure Portal → Quotas

## Step 1: Create App Service Plan

- [ ] Decide on SKU:
  - [ ] F1 (Free) for testing
  - [ ] B1 (Basic) for small apps
  - [ ] B2 (Standard) recommended for production

```bash
az appservice plan create \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B2 \
  --is-linux
```

## Step 2: Create Web App

- [ ] Choose a globally unique name (3-24 chars, alphanumeric + hyphens)
  - Suggestion: `your-webapp-name` (or with your initials)

```bash
app_name="your-webapp-name"

az webapp create \
  --resource-group your-resource-group \
  --plan your-appservice-plan \
  --name $app_name \
  --runtime "PYTHON|3.9"
```

## Step 3: Enable Managed Identity

- [ ] Assign system-managed identity
- [ ] Grant Key Vault access

```bash
app_name="your-webapp-name"

# Enable managed identity
az webapp identity assign \
  --resource-group your-resource-group \
  --name $app_name \
  --identities [system]

# Get principal ID
principal_id=$(az webapp identity show \
  --resource-group your-resource-group \
  --name $app_name \
  --query principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name your-keyvault-name \
  --object-id $principal_id \
  --secret-permissions get list

echo "✓ Granted Key Vault access to: $principal_id"
```

## Step 4: Configure Application Settings

- [ ] Set Key Vault name
- [ ] Set environment
- [ ] Configure Gunicorn workers

```bash
app_name="your-webapp-name"

# Set startup command
az webapp config set \
  --resource-group your-resource-group \
  --name $app_name \
  --startup-file "gunicorn --workers=4 --worker-class=sync --threads=2 --timeout=60 --bind=0.0.0.0:8000 --access-logfile=- --error-logfile=- wsgi:app"

# Set application settings
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name $app_name \
  --settings \
    AZURE_KEY_VAULT_NAME=your-keyvault-name \
    FLASK_ENV=production \
    GUNICORN_WORKERS=4
```

## Step 5: Deploy Code

Choose one deployment method:

### Option A: Deploy from ZIP

- [ ] Create deployment package
- [ ] Deploy ZIP file

```bash
app_name="your-webapp-name"

# Create ZIP excluding unnecessary files
zip -r deployment.zip . \
  -x ".git/*" \
  ".venv/*" \
  "__pycache__/*" \
  "*.pyc" \
  ".pytest_cache/*" \
  "node_modules/*"

# Deploy
az webapp deployment source config-zip \
  --resource-group your-resource-group \
  --name $app_name \
  --src-path deployment.zip
```

### Option B: Deploy from Git (Recommended for CI/CD)

- [ ] Create deployment user
- [ ] Configure local Git
- [ ] Push code

```bash
app_name="your-webapp-name"

# Configure local Git
git_url=$(az webapp deployment source config-local-git \
  --resource-group your-resource-group \
  --name $app_name \
  --query url -o tsv)

# Add remote
git remote add azure $git_url

# Push code
git push azure main  # or your main branch name
```

### Option C: GitHub Actions (Continuous Deployment)

- [ ] Create service principal for GitHub
- [ ] Add publish profile to GitHub Secrets
- [ ] Push code to trigger deployment

See `.github/workflows/deploy.yml` for configuration.

## Step 6: Verify Deployment

- [ ] Check application URL
- [ ] View application logs
- [ ] Test the web app

```bash
app_name="your-webapp-name"

# Get web app URL
web_url=$(az webapp show \
  --resource-group your-resource-group \
  --name $app_name \
  --query defaultHostName -o tsv)

echo "✓ Web App URL: https://$web_url"

# View logs in real-time
az webapp log tail \
  --resource-group your-resource-group \
  --name $app_name

# Test the app
curl https://$web_url
```

## Step 7: Post-Deployment

- [ ] Access the web application at the URL
- [ ] Test uploading an application
- [ ] Verify database connection works
- [ ] Check logs for errors: `az webapp log tail`
- [ ] Monitor CPU and memory usage

## Troubleshooting

**Issue:** "Startup command failed"
- [ ] Check logs: `az webapp log tail`
- [ ] Verify wsgi.py exists
- [ ] Verify all dependencies in requirements.txt

**Issue:** "Permission denied" accessing Key Vault
- [ ] Verify Managed Identity assigned: `az webapp identity show`
- [ ] Check Key Vault policy: `az keyvault show-deleted --name your-keyvault-name`
- [ ] Grant access again if needed

**Issue:** Database connection error
- [ ] Verify SQL Server firewall allows Azure services
- [ ] Test locally with `python app.py` first
- [ ] Check Azure AD authentication in Key Vault

**Issue:** "502 Bad Gateway"
- [ ] Check startup command is correct
- [ ] Verify Gunicorn can start with: `gunicorn wsgi:app`
- [ ] Check for missing dependencies: `pip install -r requirements.txt`

## Cost Monitoring

- [ ] Set up cost alerts in Azure Cost Management
- [ ] Monitor Web App metrics
- [ ] Review daily costs

## Production Hardening

- [ ] Enable HTTPS only: `UPDATE_ME`
- [ ] Set up custom domain (if desired)
- [ ] Enable Application Insights for monitoring
- [ ] Configure backup policies
- [ ] Set up deployment slots for blue-green deployment
- [ ] Enable auto-scaling (B2+ plans)

## Scaling Up Later

When you need to handle more traffic:

```bash
app_name="your-webapp-name"

# Scale up (larger instance)
az appservice plan update \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B3

# Scale out (multiple instances)
az appservice plan update \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --number-of-workers 2
```

## Cleanup (If Needed)

```bash
app_name="your-webapp-name"

# Delete Web App
az webapp delete \
  --resource-group your-resource-group \
  --name $app_name

# Delete App Service Plan
az appservice plan delete \
  --resource-group your-resource-group \
  --name your-appservice-plan
```

## Support

For detailed instructions, see:
- [AZURE_WEBAPP_DEPLOY.md](AZURE_WEBAPP_DEPLOY.md) - Complete deployment guide
- [SECURITY.md](../security/SECURITY.md) - Security best practices
- [README.md](../../README.md) - Application documentation
