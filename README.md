# Azure AI Foundry Multi-Agent System

An AI-powered application evaluation system that uses Azure OpenAI to assess internship/job applications against excellence criteria.

## 🎯 Features

- **AI-Powered Evaluation**: GPT-4o evaluates applications on technical skills, communication, experience, and cultural fit
- **Training with Excellence**: Upload examples of excellent applications to train the AI
- **Web Interface**: Modern Flask web app for uploading applications and viewing evaluations
- **Azure Integration**: Uses Azure OpenAI, Azure SQL Database, and Azure AD authentication
- **Multi-Format Support**: Processes PDF, Word (.docx), and text files

## 🏗️ Azure Resources Deployed

**Resource Group:** `NextGen_Agents`

- **Azure OpenAI**: `reapaihub6853304142` (GPT-5.2 NextGenGPT deployment)
- **Azure SQL Server**: `nextgen-sql-server.database.windows.net`
- **SQL Database**: `ApplicationsDB`
- **Azure Key Vault**: `nextgen-agents-kv` (secure credential management)
- **Authentication**: Azure AD (secure, no passwords required)

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.8+
- Azure CLI
- ODBC Driver 18 for SQL Server

### 2. Install ODBC Driver (if not installed)

**macOS:**
```bash
brew install unixodbc
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18 mssql-tools18
```

**Windows:**
Download from [Microsoft](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

### 3. Setup

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with Azure
az login

# Initialize database
python init_database.py
```

### 4. Run the Web Application

```bash
python app.py
```

Visit: http://localhost:5000

## 📊 Database Schema

- **Applications** - Stores uploaded applications
- **Grades** - Academic/performance grades
- **AIEvaluations** - AI agent evaluations
- **SelectionDecisions** - Final human decisions  
- **TrainingFeedback** - Tracks AI improvement

## 🤖 How It Works

### Upload Applications
1. Go to "Upload Application"
2. Fill in applicant details
3. Upload document (PDF/Word/Text)
4. Optionally mark as "Excellent Example" for training

### AI Evaluation
The evaluator agent:
- Analyzes application content
- Compares against training examples
- Scores on 4 dimensions (0-100)
- Provides detailed analysis
- Makes recommendation

### Review Results
- View all applications on dashboard
- See AI scores and recommendations
- Read detailed strengths/weaknesses
- Compare to excellence criteria

## 📁 Project Structure

```
.
├── app.py                      # Flask web application
├── init_database.py            # Database initialization
├── main.py                     # CLI agent interface  
├── test_agent.py               # Automated tests
├── requirements.txt            # Python dependencies
├── .env                        # Configuration (Azure credentials)
├── database/
│   └── schema.sql              # Database schema
├── src/
│   ├── config.py               # Configuration management
│   ├── database.py             # Database operations  
│   ├── document_processor.py   # Extract text from documents
│   └── agents/
│       ├── base_agent.py       # Base agent class
│       ├── simple_agent.py     # Simple chat agent
│       └── evaluator_agent.py  # Application evaluator
├── web/
│   └── templates/              # HTML templates
│       ├── base.html          
│       ├── index.html          # Dashboard
│       ├── upload.html         # Upload page
│       └── application.html    # Application details
└── uploads/                    # Uploaded files

```

## 🔧 Configuration

### Secure Credential Management with Azure Key Vault

All sensitive configuration is stored securely in **Azure Key Vault** (`nextgen-agents-kv`). No credentials are stored in code or `.env` files!

**Secrets stored in Key Vault:**
- `azure-openai-endpoint` - Azure OpenAI service endpoint
- `azure-deployment-name` - GPT model deployment name
- `azure-api-version` - Azure OpenAI API version
- `azure-subscription-id` - Azure subscription ID
- `azure-resource-group` - Resource group name
- `sql-server` - SQL Server hostname
- `sql-database` - SQL Database name
- `flask-secret-key` - Flask session secret (auto-generated)

**How it works:**
1. The application uses `DefaultAzureCredential` to authenticate
2. Retrieves secrets from Key Vault automatically
3. Falls back to `.env` file for local development (optional)

### Local Development Setup

For local development without Key Vault access, create a `.env` file:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://reapaihub6853304142.openai.azure.com/
AZURE_DEPLOYMENT_NAME=NextGenGPT
AZURE_API_VERSION=2024-12-01-preview

# Azure SQL Database  
SQL_SERVER=nextgen-sql-server.database.windows.net
SQL_DATABASE=ApplicationsDB

# Flask (use a secure random value in production)
FLASK_SECRET_KEY=your-secret-key-here
```

**Note:** The `.env` file is only used if Key Vault is unavailable. In production, all credentials come from Key Vault.

## 🌐 Deployment to Azure Web App

Deploy your Flask application to Azure for production hosting with automatic scaling and monitoring.

### Quick Deploy

```bash
# 1. Create App Service Plan (adjust SKU as needed)
az appservice plan create \
  --name NextGen-AppServicePlan \
  --resource-group NextGen_Agents \
  --sku B2 \
  --is-linux

# 2. Create Web App
az webapp create \
  --resource-group NextGen_Agents \
  --plan NextGen-AppServicePlan \
  --name nextgen-agents-app \
  --runtime "PYTHON|3.9"

# 3. See AZURE_WEBAPP_DEPLOY.md for complete setup instructions
```

**Complete Deployment Guide:** See [AZURE_WEBAPP_DEPLOY.md](AZURE_WEBAPP_DEPLOY.md)

### Features When Deployed
- ✅ Automatic HTTPS/SSL
- ✅ Key Vault integration via Managed Identity
- ✅ Gunicorn WSGI server with multiple workers
- ✅ Continuous deployment via GitHub Actions
- ✅ Production-ready configuration
- ✅ Automatic scaling (higher plans)

## 🧪 Testing

**Test AI Agent:**
```bash
python test_agent.py
```

**Test Web App:**
1. Run `python app.py`
2. Upload a test application
3. Click "Evaluate" to see AI assessment

## 💡 Usage Tips

### Training the AI
- Upload 5-10 examples of excellent applications
- Mark them as "Training Examples"
- Indicate if they were selected
- The AI learns what excellence looks like

### Best Practices
- Provide detailed applications for better evaluation  
- Include relevant experience and skills
- Review AI recommendations before final decisions
- Give feedback to improve accuracy

## 🔐 Security

### Multi-Layer Security Architecture

- **Azure Key Vault**: All credentials stored in enterprise-grade vault
- **Azure AD Authentication**: No passwords or API keys in code
- **Managed Identities**: Uses DefaultAzureCredential for automatic auth
- **Role-Based Access**: Managed through Azure RBAC
- **Encrypted Connections**: All data in transit is encrypted (TLS)
- **No Secrets in Code**: Zero hardcoded credentials or connection strings
- **Audit Trail**: Key Vault provides access logging

### Access Requirements

To run this application, you need:
1. Azure CLI authentication: `az login`
2. **Key Vault Permissions**:
   - "Key Vault Secrets User" role on `nextgen-agents-kv`
3. **Azure OpenAI Permissions**:
   - "Cognitive Services OpenAI User" role
4. **SQL Database Permissions**:
   - Azure AD account added to database

### Adding Key Vault Secrets

To add or update secrets:

```bash
# Add a new secret
az keyvault secret set \
  --vault-name nextgen-agents-kv \
  --name secret-name \
  --value "secret-value"

# List all secrets
az keyvault secret list --vault-name nextgen-agents-kv

# Get a secret value
az keyvault secret show \
  --vault-name nextgen-agents-kv \
  --name secret-name \
  --query value -o tsv
```

## 📚 Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)
- [Azure SQL Database](https://learn.microsoft.com/azure/azure-sql/)

## 🛠️ Troubleshooting

**Database Connection Issues:**
- Run `az login` to authenticate
- Check ODBC Driver is installed: `odbcinst -j`
- Verify Azure AD permissions

**ODBC Driver Not Found:**
```bash
# macOS
brew install msodbcsql18

# Check installation
odbcinst -q -d
```

**AI Evaluation Errors:**
- Ensure Azure OpenAI resource is accessible
- Check deployment name matches .env
- Verify you have "Cognitive Services OpenAI User" role

## 🎓 Next Steps

1. **Add More Agents**: Create specialized evaluators for different positions
2. **Integrate Blob Storage**: Store original documents in Azure Blob Storage  
3. **Add Analytics**: Dashboard for evaluation trends and insights
4. **Email Notifications**: Notify applicants of decisions
5. **API Endpoints**: Build REST API for integrations

---

**Built with Azure AI** 🚀
