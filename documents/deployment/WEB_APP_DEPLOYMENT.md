# Web App Deployment Quick Reference

## What We've Prepared

Your application is now ready for production deployment to Azure Web App:

✅ **WSGI Entry Point** - `wsgi.py` for proper WSGI server integration
✅ **Gunicorn Configuration** - Production-grade Python WSGI HTTP server
✅ **Key Vault Integration** - Secure credential management via Managed Identity
✅ **Deployment Scripts** - Startup configuration and GitHub Actions CI/CD
✅ **Security Hardened** - HTTPS, secure cookies, no hardcoded secrets

## Files Created/Modified

### New Files
| File | Purpose |
|------|---------|
| `wsgi.py` | WSGI entry point for production servers |
| `startup.py` | Optional startup script for Gunicorn |
| `.webappconfig.json` | Web App configuration metadata |
| `.github/workflows/deploy.yml` | GitHub Actions CI/CD workflow |
| `AZURE_WEBAPP_DEPLOY.md` | Detailed deployment instructions |
| `DEPLOYMENT_CHECKLIST.md` | Step-by-step deployment checklist |

### Modified Files
| File | Changes |
|------|---------|
| `requirements.txt` | Added `gunicorn` and `whitenoise` |
| `app.py` | Production-ready Flask configuration |
| `README.md` | Added Web App deployment section |

## Quick Deploy (3 Steps)

### Step 1: Create Resources

```bash
# Create App Service Plan (B2 recommended)
az appservice plan create \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B2 \
  --is-linux

# Create Web App
az webapp create \
  --resource-group your-resource-group \
  --plan your-appservice-plan \
  --name your-webapp-name \
  --runtime "PYTHON|3.9"
```

### Step 2: Configure Security

```bash
# Enable Managed Identity for Key Vault access
az webapp identity assign \
  --resource-group your-resource-group \
  --name your-webapp-name

# Get principal ID and grant Key Vault access
principal_id=$(az webapp identity show \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --query principalId -o tsv)

az keyvault set-policy \
  --name your-keyvault-name \
  --object-id $principal_id \
  --secret-permissions get list
```

### Step 3: Deploy Code

```bash
# Configure startup command
az webapp config set \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --startup-file "gunicorn --workers=4 --worker-class=sync --threads=2 --timeout=60 --bind=0.0.0.0:8000 --access-logfile=- --error-logfile=- wsgi:app"

# Deploy code
zip -r app.zip . -x ".git/*" ".venv/*" "__pycache__/*" "*.pyc"
az webapp deployment source config-zip \
  --resource-group your-resource-group \
  --name your-webapp-name \
  --src-path app.zip

# Verify deployment
az webapp show --resource-group your-resource-group --name your-webapp-name --query defaultHostName
```

## Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| "Quota exceeded" | Request limit increase at Azure Portal → Quotas |
| "502 Bad Gateway" | Check logs with `az webapp log tail` |
| "Permission denied" Key Vault | Verify Managed Identity granted access |
| "Startup command failed" | Verify `wsgi.py` exists and `gunicorn` installed |
| Database connection error | Ensure Azure SQL firewall allows Azure services |

## Monitoring & Debugging

```bash
# View live logs
az webapp log tail --resource-group your-resource-group --name your-webapp-name

# Download log files
az webapp log download --resource-group your-resource-group --name your-webapp-name

# Get web app status
az webapp show --resource-group your-resource-group --name your-webapp-name \
  --query "{ name: name, state: state, url: defaultHostName }"
```

## Local Testing Before Deploying

```bash
# Install dependencies (if not already installed)
pip install -r requirements.txt

# Test WSGI entry point
python -c "from wsgi import app; print(f'✓ WSGI app loads: {app}')"

# Test agent functionality
python test_agent.py

# Run Flask in development
python app.py
```

## CI/CD with GitHub Actions

GitHub Actions automatically deploys on every push to `main`:

1. Create publish profile: Get from Azure Portal → Web App → Deployment Center
2. Add to GitHub Secrets: `AZURE_WEBAPP_PUBLISH_PROFILE`
3. Workflow runs on every push to `main` branch

See `.github/workflows/deploy.yml` for configuration.

## Production Checklist

- [ ] App Service Plan created with appropriate SKU
- [ ] Web App created and running
- [ ] Managed Identity enabled
- [ ] Key Vault access granted
- [ ] Startup command configured
- [ ] Code deployed successfully
- [ ] No errors in `az webapp log tail`
- [ ] Database connection working
- [ ] SSL/HTTPS working (automatic)
- [ ] Custom domain configured (optional)
- [ ] Monitoring alerts configured (optional)

## Scaling

### Scale Up (Larger Instance)
```bash
az appservice plan update --name your-appservice-plan \
  --resource-group your-resource-group --sku B3
```

### Scale Out (Multiple Instances)
```bash
az appservice plan update --name your-appservice-plan \
  --resource-group your-resource-group --number-of-workers 2
```

## Cost Estimation

| SKU | Price/Month | CPU | Memory |
|-----|-------------|-----|--------|
| F1 (Free) | $0 | Shared | 1 GB |
| B1 | ~$12 | 1 core | 1.75 GB |
| B2 | ~$60 | 2 cores | 3.5 GB |
| B3 | ~$120 | 4 cores | 7 GB |

Plus: Database, Storage, AI Foundry, and Key Vault costs

## Next Steps

1. **Immediate:**
   - [ ] Request quota increase (if needed)
   - [ ] Follow "Quick Deploy" above
   - [ ] Test the deployment

2. **Short-term:**
   - [ ] Configure custom domain
   - [ ] Set up monitoring/alerts
   - [ ] Configure automated backups

3. **Long-term:**
   - [ ] Implement CI/CD via GitHub Actions
   - [ ] Plan capacity and scaling
   - [ ] Review and optimize costs

## Full Documentation

- **[AZURE_WEBAPP_DEPLOY.md](AZURE_WEBAPP_DEPLOY.md)** - Comprehensive deployment guide
- **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)** - Step-by-step checklist
- **[SECURITY.md](../security/SECURITY.md)** - Security configuration
- **[README.md](../../README.md)** - Application documentation

## Getting Help

```bash
# Azure CLI help
az webapp --help
az appservice plan --help

# View deployment logs
az webapp deployment log show --resource-group your-resource-group --name your-webapp-name

# Check service health
az webapp show --resource-group your-resource-group --name your-webapp-name
```

---

**Status:** ✅ Application is production-ready for Azure Web App deployment
**Next Action:** Follow "Quick Deploy" (3 steps) above or see [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
