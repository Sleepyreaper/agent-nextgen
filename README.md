# Azure AI Foundry Multi-Agent System

> 🔒 **Secure by Default**: All credentials stored in Azure Key Vault. No plaintext secrets in code or configuration files.

An AI-powered application evaluation system that uses Azure OpenAI to assess internship/job applications against excellence criteria.

## 🎯 Features

- **AI-Powered Evaluation**: GPT-5.2 evaluates applications on technical skills, communication, experience, and cultural fit
- **Multi-Agent System**: Specialized Disney-themed agents for different evaluation aspects
- **Training with Excellence**: Upload examples of excellent applications to train the AI
- **Web Interface**: Modern Flask web app for uploading applications and viewing evaluations
- **Secure by Default**: All secrets in Azure Key Vault, no plaintext credentials
- **Azure Integration**: Uses Azure OpenAI, PostgreSQL, and Azure AD authentication
- **Multi-Format Support**: Processes PDF, Word (.docx), and text files
- **School Context Analysis**: Moana agent analyzes school resources and opportunity access
  - **Georgia School Data**: Automatic integration with Georgia public school data for verified context

## 🦸 Disney Agent Team

This system uses a multi-agent approach with specialized agents:

- **🎩 Smee (Orchestrator)**: Coordinates all agents and manages the evaluation workflow
- **👸 Tiana (Application Reader)**: Parses student applications into structured profiles
- **💇 Rapunzel (Grade Reader)**: Analyzes transcripts and academic performance
- **🌊 Moana (School Context)**: Discovers school environment and program access
  - Detects Georgia schools and references [public data](https://gaawards.gosa.ga.gov/analytics/saw.dll?dashboard)
  - Evaluates student opportunity relative to school resources
  - Provides socioeconomic context for fair evaluation
- **🗡️ Mulan (Recommendation Reader)**: Parses and analyzes recommendation letters
- **🧙 Merlin (Student Evaluator)**: Synthesizes all agent outputs into final recommendation

See [MOANA_GEORGIA_DATA.md](documents/MOANA_GEORGIA_DATA.md) for details on Georgia school data integration.

## 🏗️ Azure Resources Deployed

**Resource Group:** `NextGen_Agents`

- **Azure OpenAI**: `reapaihub6853304142` (GPT-5.2 NextGenGPT deployment)
- **PostgreSQL Database**: `nextgen-postgres.eastus.azurecontainer.io` (Azure Container Instance)
- **Database**: `ApplicationsDB`
- **Azure Key Vault**: `nextgen-agents-kv` (secure credential management)
- **Authentication**: Azure AD for OpenAI, username/password for PostgreSQL

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.9+
- Azure CLI
- Azure account with Key Vault access

### 2. Setup

```bash
# Clone and navigate to repository
cd "Agent NextGen"

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with Azure (required for Key Vault and OpenAI)
az login

# Configure Azure Key Vault secrets (one-time setup)
./setup_keyvault.sh

# Initialize database
python init_database.py
```

### 3. Run the Web Application

```bash
python app.py
```

Visit: http://localhost:5001

> **Note**: The application automatically retrieves all credentials from Azure Key Vault. No `.env` file needed!

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
├── requirements.txt            # Python dependencies
├── .env                        # Configuration (PostgreSQL credentials)
├── database/
│   └── schema.sql              # PostgreSQL database schema
├── documents/                  # Documentation files
│   ├── AZURE_WEBAPP_DEPLOY.md
│   ├── DEPLOYMENT_CHECKLIST.md
│   ├── DEPLOYMENT_SUCCESS.md
│   ├── KEY_VAULT_SETUP.md
│   ├── POSTGRES_MIGRATION.md
│   ├── SECURITY.md
│   └── WEB_APP_DEPLOYMENT.md
├── src/
│   ├── config.py               # Configuration management
│   ├── database.py             # PostgreSQL operations  
│   ├── document_processor.py   # Extract text from documents
│   └── agents/
│       ├── base_agent.py       # Base agent class
│       ├── simple_agent.py     # Simple chat agent
│       ├── evaluator_agent.py  # Application evaluator
│       ├── smee_orchestrator.py # Agent orchestrator
│       ├── tiana_application_reader.py
│       ├── rapunzel_grade_reader.py
│       ├── moana_school_context.py
│       ├── mulan_recommendation_reader.py
│       └── merlin_student_evaluator.py
├── testing/                    # Test scripts and examples
│   ├── test_agent.py
│   ├── test_smee.py
│   └── hello_app.py
├── web/
│   └── templates/              # HTML templates
│       ├── base.html          
│       ├── index.html          # Dashboard
│       ├── upload.html         # Upload page
│       └── application.html    # Application details
└── uploads/                    # Uploaded files

```

## 🔧 Configuration

### Primary: Azure Key Vault (Recommended)

All configuration is stored in **Azure Key Vault** (`nextgen-agents-kv`) by default.

**Setup once:**
```bash
./setup_keyvault.sh
```

The application automatically retrieves all secrets using `DefaultAzureCredential` (your Azure AD login).

**Stored secrets:**
- PostgreSQL: `postgres-host`, `postgres-port`, `postgres-database`, `postgres-username`, `postgres-password`
- Azure OpenAI: `azure-openai-endpoint`, `azure-deployment-name`, `azure-api-version`
- Azure config: `azure-subscription-id`, `azure-resource-group`
- Flask: `flask-secret-key` (auto-generated)

### Fallback: Local Development Only

If you cannot access Key Vault (e.g., offline development), create a `.env.local` file:

```bash
# Copy template
cp .env.example .env.local

# Edit with your values (never commit this file!)
nano .env.local
```

**Note**: `.env.local` is gitignored and should **never** be committed. It's only for local development when Key Vault is unavailable.

### Verifying Configuration

```bash
python -c "from src.config import config; print(config.get_config_summary())"
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

# 3. See documents/AZURE_WEBAPP_DEPLOY.md for complete setup instructions
```

**Complete Deployment Guide:** See [documents/AZURE_WEBAPP_DEPLOY.md](documents/AZURE_WEBAPP_DEPLOY.md)

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
python testing/test_agent.py
```

**Test Smee Orchestrator:**
```bash
python testing/test_smee.py
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

## 🔐 Security - Secure by Default

### 🎯 Zero Plaintext Credentials

This application is designed to **never expose credentials**:

✅ **All secrets in Azure Key Vault** - Enterprise-grade encryption  
✅ **No .env files in Git** - `.gitignore` configured properly  
✅ **No hardcoded credentials** - Code only references config variables  
✅ **Auto-fetch from Key Vault** - Application retrieves secrets on startup  
✅ **Azure AD authentication** - For Azure OpenAI (passwordless)  
✅ **TLS/SSL everywhere** - All connections encrypted  

### 🔒 How It Works

```
Application Startup
       ↓
Config.py initializes
       ↓
DefaultAzureCredential (Azure AD login)
       ↓
Connects to Azure Key Vault
       ↓
Retrieves all secrets
       ↓
Cached in memory (never written to disk)
       ↓
Application runs securely
```

### 📋 First-Time Setup

**Configure secrets in Azure Key Vault:**

```bash
# Run the interactive setup script
./setup_keyvault.sh

# Or set secrets manually
az keyvault secret set --vault-name nextgen-agents-kv \
  --name postgres-password --value 'your-secure-password'
```

**All secrets are stored in Key Vault:**
- `postgres-host`, `postgres-port`, `postgres-database`
- `postgres-username`, `postgres-password`
- `azure-openai-endpoint`, `azure-deployment-name`
- `azure-subscription-id`, `azure-resource-group`
- `flask-secret-key` (auto-generated)

### 🔑 Access Requirements

To run this application, you need:

1. **Azure CLI authentication**
   ```bash
   az login
   ```

2. **Key Vault Permissions**
   - Role: "Key Vault Secrets User" on `nextgen-agents-kv`
   - Automatically granted to your Azure AD account

3. **Azure OpenAI Permissions**
   - Role: "Cognitive Services OpenAI User"
   - Required to call GPT models

### 📚 Security Documentation

For comprehensive security guidelines, see:
- **[Security Guide](documents/SECURITY_GUIDE.md)** - Complete security documentation
- **[Setup Script](setup_keyvault.sh)** - Interactive Key Vault configuration

# Get a secret value
az keyvault secret show \
  --vault-name nextgen-agents-kv \
  --name secret-name \
  --query value -o tsv
```

## 📚 Additional Resources

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)

## 🛠️ Troubleshooting

**Database Connection Issues:**
- Verify PostgreSQL credentials in `.env`
- Check PostgreSQL container is running: `az container show --resource-group NextGen_Agents --name nextgen-postgres`
- Test connection: `psql "postgresql://user:password@host:5432/ApplicationsDB"`

**AI Evaluation Errors:**
- Ensure Azure OpenAI resource is accessible
- Check deployment name matches .env
- Verify you have "Cognitive Services OpenAI User" role

**Import Errors:**
- Make sure virtual environment is activated: `source .venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

## 📚 Documentation

- [PostgreSQL Migration Guide](documents/POSTGRES_MIGRATION.md) - Database migration details
- [Deployment Success](documents/DEPLOYMENT_SUCCESS.md) - Current deployment status
- [Azure Web App Deployment](documents/AZURE_WEBAPP_DEPLOY.md) - Production deployment guide
- [Security Guide](documents/SECURITY.md) - Security best practices

## 🎓 Next Steps

1. **Add More Agents**: Create specialized evaluators for different positions
2. **Integrate Blob Storage**: Store original documents in Azure Blob Storage  
3. **Add Analytics**: Dashboard for evaluation trends and insights
4. **Email Notifications**: Notify applicants of decisions
5. **API Endpoints**: Build REST API for integrations

---

**Built with Azure AI** 🚀
# CI/CD Test - Sat Feb 14 17:13:36 EST 2026
