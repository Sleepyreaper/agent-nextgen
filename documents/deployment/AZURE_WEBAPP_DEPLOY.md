# Deploying to Azure Web App

This guide explains how to deploy the NextGen Agent System to Azure Web App for production hosting.

## Prerequisites

- Azure CLI installed and authenticated
- Git repository initialized (recommended)
- Sufficient quota for App Service plan (see troubleshooting)

## Architecture

```
Azure Web App (Linux, Python 3.9+)
    ↓
Gunicorn WSGI Server (4 workers)
    ↓
Flask Application (app.py)
    ↓
Azure Services:
    - Azure OpenAI (GPT-5.2)
    - Azure SQL Database
    - Azure Key Vault
```

## Step 1: Create App Service Plan

Before creating the web app, you need an App Service Plan. The quota must be available in your subscription.

### Option A: Standard Plan (Recommended for Production)

```bash
az appservice plan create \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B2 \
  --is-linux
```

**SKU Options:**
- `F1` - Free tier (1 GB memory, limited)
- `B1` - Basic tier (1.75 GB memory)
- `B2` - Standard tier (3.5 GB memory) ← Recommended
- `B3` - Standard tier (7 GB memory) ← For high traffic

### Option B: Free Tier (Development)

```bash
az appservice plan create \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku F1
```

**⚠️ Note:** If you get a quota error, you need to request a quota increase at:
https://portal.azure.com/#view/Microsoft_Azure_Support/NewSupportRequestV3Blade

## Step 2: Create the Web App

```bash
az webapp create \
  --resource-group your-resource-group \
  --plan your-appservice-plan \
  --name your-webapp-name \
  --runtime "PYTHON|3.9"
```

**Note:** Replace `your-webapp-name` with a globally unique name (3-24 characters, letters/numbers/hyphens only).

## Step 3: Configure Managed Identity

This enables the web app to access Key Vault without credentials:

```bash
# Enable managed identity
az webapp identity assign \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --identities [system]

# Get the principal ID
principal_id=$(az webapp identity show \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --query principalId -o tsv)

# Grant Key Vault access
az keyvault set-policy \
  --name your-keyvault-name \
  --object-id $principal_id \
  --secret-permissions get list

echo "✓ Managed Identity configured"
echo "  Principal ID: $principal_id"
```

## Step 4: Configure Web App Settings

### Set the Startup Command

The Web App needs to know how to start your Flask app with Gunicorn:

```bash
az webapp config set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --startup-file "gunicorn --workers=4 --worker-class=sync --threads=2 --timeout=60 --bind=0.0.0.0:8000 --access-logfile=- --error-logfile=- wsgi:app"
```

### Configure Application Settings

These are stored securely and passed as environment variables:

```bash
# Key Vault name (tells config.py to use Key Vault)
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --settings AZURE_KEY_VAULT_NAME=your-keyvault-name

# Environment
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --settings FLASK_ENV=production

# Gunicorn workers (adjust based on plan memory)
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --settings GUNICORN_WORKERS=4

# Max upload size (16MB)
az webapp config set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --http20-enabled true \
  --ftps-state Disabled
```

## Step 5: Deploy the Code

### Option A: Deploy from Git (Recommended)

```bash
# Create a deployment user (one-time setup)
az webapp deployment user set \
  --user-name <username> \
  --password <password>

# Configure local Git deployment
az webapp deployment source config-local-git \
  --resource-group your-resource-group \
  --name your-webapp-name

# Add Azure as a git remote
git remote add azure $(az webapp deployment source config-local-git \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --query url -o tsv)

# Deploy your code
git push azure main  # or 'master' depending on your branch name
```

### Option B: Deploy from ZIP

```bash
# Create a ZIP file of your application
zip -r app.zip . -x "*.git*" ".venv/*" "__pycache__/*" "uploads/*"

# Deploy the ZIP
az webapp deployment source config-zip \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --src-path app.zip
```

### Option C: Deploy Using Azure DevOps or GitHub Actions

See `.github/workflows/deploy.yml` for CI/CD setup.

## Step 6: Verify Deployment

### Check Web App Status

```bash
# Get web app details
az webapp show \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --query "{ name: name, state: state, url: defaultHostName }"

# Get the application URL
web_app_url="https://$(az webapp show \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --query defaultHostName -o tsv)"

echo "Web App URL: $web_app_url"
```

### Check Logs

```bash
# Stream application logs in real-time
az webapp log tail \
  --resource-group your-resource-group \
  --name your-webapp-name

# View recent logs
az webapp log download \
  --resource-group your-resource-group \
  --name your-webapp-name
```

## Step 7: Test the Application

```bash
# Visit the web app
open "https://your-webapp.azurewebsites.net"

# Or test with curl
curl https://your-webapp.azurewebsites.net
```

## Production Checklist

- [ ] App Service Plan created with appropriate SKU
- [ ] Web App created and configured
- [ ] Managed Identity enabled and granted Key Vault access
- [ ] Startup command configured for Gunicorn
- [ ] Application settings configured
- [ ] Code deployed to Web App
- [ ] Web app is running and accessible
- [ ] Logs show no errors
- [ ] Database migrations complete
- [ ] SSL certificate configured (automatic with Azure)
- [ ] Custom domain configured (optional)
- [ ] Monitoring and alerts set up (optional)

## Performance Tuning

### Adjust Worker Count

For B2+ plans with more CPU:

```bash
az webapp config appsettings set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --settings GUNICORN_WORKERS=8
```

**Formula:** NumWorkers = (2 × NumCPUs) + 1

### Enable Application Insights

```bash
# Create Application Insights resource
az monitor metrics-alert create \
  --name "your-appinsights-alert" \
  --resource-group your-resource-group \
  --scopes "$(az webapp show \
    --resource-group your-resource-group \
    --name your-webapp-name \
    --query id -o tsv)"
```

## Scaling

### Scale Up (Larger Instance)

```bash
az appservice plan update \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B3
```

### Scale Out (Multiple Instances)

```bash
az appservice plan update \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --number-of-workers 2
```

## Troubleshooting

### Common Issues

**Issue:** "Quota exceeded" error when creating App Service Plan

**Solution:** Request quota increase at Azure Portal → Quotas → App Service

**Issue:** Web app starts but shows "502 Bad Gateway"

**Solution:** Check logs with `az webapp log tail` and ensure Gunicorn is configured

**Issue:** "Permission denied" accessing Key Vault

**Solution:** Verify Managed Identity has been assigned and granted permissions

**Issue:** Static files (CSS/JS) not loading

**Solution:** Check `web/static/` directory exists and is included in deployment

### View Detailed Logs

```bash
# SSH into the web app container
az webapp remote-connection create \
  --resource-group your-resource-group \
  --name your-webapp-name

# View application logs
cat /home/LogFiles/Application/default_docker.log
```

## Cost Estimation

**Monthly Cost (Approximate):**
- F1 (Free): $0
- B1 (Basic): $12
- B2 (Standard): $60
- B3 (Standard): $120

Plus storage, database, and AI Foundry usage costs.

## Cleanup

If you need to delete the Web App:

```bash
# Delete the web app
az webapp delete \
  --resource-group your-resource-group \
  --name your-webapp-name

# Delete the App Service Plan
az appservice plan delete \
  --resource-group your-resource-group \
  --name your-appservice-plan
```

## Next Steps

1. Request quota increase if needed
2. Follow Steps 1-7 above
3. Monitor application logs
4. Configure custom domain (if desired)
5. Set up monitoring and alerts
6. Plan for automatic deployments with GitHub Actions

## Additional Resources

- [Azure App Service Documentation](https://learn.microsoft.com/azure/app-service/)
- [Python on Azure App Service](https://learn.microsoft.com/azure/app-service/quickstart-python)
- [Gunicorn Configuration](https://docs.gunicorn.org/en/stable/configure.html)
- [Flask on Azure](https://learn.microsoft.com/azure/developer/python/tutorial-deploy-app-service-on-linux-01)
