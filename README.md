# NextGen Multi-Agent Student Evaluation System

> **Production-Ready AI Evaluation Pipeline** with comprehensive audit trails, intelligent student matching, and fairness-aware assessment.

An intelligent multi-agent system that evaluates student applications using specialized Disney-themed agents working in a coordinated 9-step workflow.

## 🎯 Features

- **9-Step Intelligent Workflow**: Orchestrated multi-agent evaluation with decision gates and remediation loops
- **Smart Student Matching**: Composite key matching (name + school + state) prevents duplicates
- **AI-Powered Extraction**: BELLE extracts structured data from any document format
- **School Context Analysis**: NAVEEN + MOANA bidirectional validation for fair assessment
- **Contextual Rigor Weighting**: RAPUNZEL calculates academic rigor adjusted by school opportunity (0-5 scale)
- **Comprehensive Audit Trail**: 14 interaction types logged to database for compliance verification
- **File Upload Matching**: AI-based student identification with confidence scoring (0-1 scale)
- **Unlimited Re-Evaluations**: More data sources = more accurate assessments
- **Concise Student Summaries**: Each application row now includes a
  `student_summary` payload (score, recommendation, rationale, strengths/risks)
  that can be displayed in the UI and backfilled for historical records
  using `scripts/backfill_summaries.py`.
- **Validation Gates**: Per-agent readiness verification with reactive BELLE extraction
- **Web Interface**: Modern Flask app for uploads and result visualization
- **Secure by Default**: All credentials stored in Azure Key Vault
- **Azure Integration**: Uses Azure OpenAI, PostgreSQL, and Managed Identity

## 🦸 Disney Agent Team - 9-Step Workflow

```
1️⃣ BELLE (Document Analyzer)
   │  Extracts structured data from documents
   │
2️⃣ Student Matching
   │  Prevents duplicates via composite key (name + school + state)
   │
2️⃣➕ High School Pre-Enrichment
   │  Proactively validates/enriches school data before validation loop
   │
3️⃣ NAVEEN (School Data Scientist)
   │  Enriches school context (AP/Honors availability, opportunity score)
   │
3️⃣➕ School Validation Loop (MOANA ↔ NAVEEN)
   │  Bidirectional validation with up to 2 remediation attempts
   │
4️⃣ Core Agents (with per-agent validation gates):
   ├─ TIANA (Application Reader)
   ├─ RAPUNZEL (Grade Reader with contextual rigor weighting)
   ├─ MOANA (School Context & Fairness Weighting)
   └─ MULAN (Recommendation Reader)
   │
5️⃣ MILO (Data Scientist)
   │  Pattern analysis across student profile
   │
6️⃣ MERLIN (Student Evaluator)
   │  Synthesizes all results into comprehensive assessment
   │
7️⃣ AURORA (Results Formatter)
   └─ Generates polished evaluation report with executive summary
```

### **Agent Specializations**

- **📖 Belle**: Document understanding & information extraction
- **👸 TIANA**: Application essay analysis & communication assessment
- **👑 RAPUNZEL**: Academic performance with **contextual rigor scoring (0-5 scale based on school resources)**
- **🌊 MOANA**: School opportunity analysis & **fairness-aware weighting**
- **🥋 MULAN**: Recommendation letter synthesis
- **📊 MILO**: Training data insights & pattern detection
- **🧑‍🔬 NAVEEN**: School enrichment & demographic research
- **🧙 MERLIN**: Overall recommendation & rationale synthesis
- **✨ AURORA**: Executive summary & report formatting

## 🏗️ Azure Architecture

**Primary Components:**

- **Azure OpenAI**: GPT models for intelligent evaluation (gpt-4, gpt-35-turbo, etc.)
- **PostgreSQL Database**: Application data, student records, audit trails (14 interaction types)
- **Azure Key Vault**: Secure credential management (never exposed in code)
- **Azure Blob Storage**: Document uploads and storage integration
- **Azure App Service**: Production web application hosting
- **Application Insights**: Agent telemetry, usage tracking, performance monitoring

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
python scripts/init/init_database.py
```

### 3. Configure Environment

#### Option A: Azure Key Vault (Production - Recommended)

```bash
# One-time setup - Interactive configuration
./scripts/setup/keyvault_setup.sh

# This creates all required secrets in your Key Vault:
# - Azure OpenAI credentials
# - PostgreSQL connection info
# - Flask secret key
# - Content processing endpoint details
```

#### Option B: Local Development (.env.local)

For offline development when Key Vault isn't accessible:

```bash
# Copy template
cp .env.example .env.local

# Edit with your values (development-only)
nano .env.local

# Key variables needed:
# AZURE_OPENAI_ENDPOINT=<your-endpoint>
# AZURE_OPENAI_API_KEY=<your-key>
# POSTGRES_HOST=localhost
# POSTGRES_PASSWORD=<dev-password>
# FLASK_SECRET_KEY=<random-string>
```

> ⚠️ **Important**: Never commit `.env.local` to Git. It's only for local development.

### 4. Initialize Database

```bash
# Create all required tables (runs schema migrations)
python scripts/init/init_database.py

# Verify database is ready
python -c "from src.database import Database; db = Database(); print('Database ready!')"
```

### 5. Run the Web Application

```bash
python app.py
```

**Access the application:**
- 🌐 Dashboard: http://localhost:5001
- 📝 Upload Documents: http://localhost:5001/upload
- 🧪 Test System: http://localhost:5001/test
- 📊 Student List: http://localhost:5001/students

> **Note**: The application automatically retrieves credentials from Key Vault (or .env.local). No additional configuration needed!

## 🌍 Environment Variables Reference

### Azure OpenAI Configuration
- `AZURE_OPENAI_ENDPOINT` - Azure OpenAI API endpoint URL
- `AZURE_OPENAI_API_KEY` - API key for authentication
- `AZURE_OPENAI_DEPLOYMENT_NAME` - GPT model deployment name (gpt-4, gpt-35-turbo)
- `AZURE_OPENAI_API_VERSION` - API version (e.g., 2024-12-01-preview)

### PostgreSQL Database
- `POSTGRES_HOST` - Database server hostname
- `POSTGRES_PORT` - Port (default: 5432)
- `POSTGRES_DATABASE` - Database name (ApplicationsDB)
- `POSTGRES_USERNAME` - Connection username
- `POSTGRES_PASSWORD` - Connection password

### Application Configuration
- `FLASK_SECRET_KEY` - Secret key for session management
- `FLASK_ENV` - Environment (development/production)
- `APPLICATIONINSIGHTS_CONNECTION_STRING` - Azure Application Insights (optional)
- `NEXTGEN_CAPTURE_PROMPTS` - Enable/disable prompt logging (true/false)

### Content Processing (Optional)
- `CONTENT_PROCESSING_ENDPOINT` - Content processing service URL
- `CONTENT_PROCESSING_API_KEY` - API key for content service
- `CONTENT_PROCESSING_API_KEY_HEADER` - Header name for API key
- `CONTENT_PROCESSING_ENABLED` - Enable/disable feature (true/false)

### Azure Container Resources
- `AZURE_SUBSCRIPTION_ID` - Your Azure subscription ID
- `AZURE_RESOURCE_GROUP` - Azure resource group name
- `AZURE_STORAGE_ACCOUNT_NAME` - Blob storage account name

## 📊 Database Schema

### **Core Tables**

- **applications** - Student applications with demographics, documents, status
- **student_school_context** - School enrichment data (AP courses, demographics, opportunity scores)
- **rapunzel_grades** - Academic data with contextual rigor weighting (0-5 scale)
- **ai_evaluations** - Agent outputs from all 9 steps

### **Audit & Compliance Tables (Phase 5)**

- **agent_interactions** - Comprehensive logging of all agent executions
  - 14 interaction types covering entire 9-step workflow
  - Full JSONB output from each agent
  - Timestamps for chronological tracking
  - Used for compliance verification and debugging

- **file_upload_audit** - AI-based student matching audit trail
  - Extracted student info from uploaded files
  - AI confidence scores (0-1 scale)
  - Matching decisions (new_student / matched_existing / low_confidence)
  - Human review fields for administrator verification
  - 16 columns for complete traceability

## 🤖 How It Works - The 9-Step Workflow

### **Step 1️⃣ - BELLE Extraction**
- Uploads trigger BELLE to extract student data from documents
- Extracts: name, school, grades, test scores, achievements

### **Step 2️⃣ - Smart Student Matching**
- Composite key lookup: `first_name + last_name + high_school + state_code`
- Matches to existing student OR creates new record
- Prevents duplicates while enabling re-evaluation with new files

### **Step 2️⃣➕ - High School Pre-Enrichment**
- Validates school record exists in database
- If not found: NAVEEN is called to proactively enrich before validation loop
- Reduces downstream validation failures

### **Step 3️⃣ - School Enrichment (NAVEEN)**
- Enriches school record with:
  - AP courses available (count + list)
  - Honors programs available  
  - Community opportunity score (0-100)
  - Free/reduced lunch percentage
  - Total enrollment & demographics

### **Step 3️⃣➕ - School Validation Loop**
- **MOANA validates** school against 7 required fields
- If validation fails:
  - **NAVEEN remediates** (up to 2 attempts) with targeted research
  - MOANA re-validates
- Outcome: Either school meets requirements ✅ OR workflow pauses for user docs

### **Step 4️⃣ - Core Agent Evaluation**
Four agents run in parallel, each with per-agent validation gates:

1. **TIANA** - Analyzes application essays and communication
2. **RAPUNZEL** - Grades & rigor analysis with **contextual weighting (0-5 scale)**
   - Base rigor from GPA and course difficulty
   - Adjusted by school's AP/Honors availability  
   - Weighted by student's opportunity score
   - Fair assessment accounts for school resources
3. **MOANA** - School context & fairness factor application
4. **MULAN** - Synthesizes recommendation letters

### **Step 5️⃣ - Pattern Analysis (MILO)**
- Analyzes performance against training data
- Identifies selection indicators and patterns
- Provides contextual insights

### **Step 6️⃣ - Comprehensive Evaluation (MERLIN)**
- Synthesizes all agent outputs
- Applies fairness adjustments from MOANA
- Produces overall score and recommendation
- Detailed strengths/considerations analysis

### **Step 7️⃣ - Results Formatting (AURORA)**
- Generates executive summary
- Formats evaluation report for human review
- Provides clear rationale for recommendation

## 📁 Project Structure

```
.
├── app.py                             # Flask web application
├── main.py                            # CLI interface (optional)
├── requirements.txt                   # Python dependencies
├── database/
│   ├── schema_postgresql.sql          # Core database schema
│   ├── schema_school_enrichment.sql   # School context tables
│   ├── schema_azure_sql.sql           # Azure SQL variant
│   └── add_transcript_recommendation_columns.sql  # Migrations
├── src/
│   ├── config.py                      # Configuration management
│   ├── database.py                    # PostgreSQL operations + audit logging
│   ├── logger.py                      # Logging utilities
│   ├── storage.py                     # Blob storage operations
│   ├── test_data_generator.py         # Synthetic test data with realistic birthdates
│   ├── file_upload_handler.py         # AI-based student matching & file upload orchestration
│   └── agents/
│       ├── base_agent.py              # Base agent class
│       ├── smee_orchestrator.py       # 9-step workflow orchestrator
│       ├── belle_document_analyzer.py # Document extraction
│       ├── tiana_application_reader.py
│       ├── rapunzel_grade_reader.py   # Grade analysis with contextual rigor weighting
│       ├── naveen_school_data_scientist.py  # School enrichment
│       ├── moana_school_context.py    # School validation & fairness weighting
│       ├── mulan_recommendation_reader.py
│       ├── milo_data_scientist.py     # Pattern analysis
│       ├── merlin_student_evaluator.py
│       ├── aurora_agent.py            # Results formatting
│       └── system_prompts.py          # Shared agent prompts
├── web/
│   └── templates/
│       ├── base.html                  # Base template
│       ├── index.html                 # Dashboard
│       ├── upload.html                # File upload
│       ├── test.html                  # Test system (9-step workflow reporter)
│       ├── students.html              # Student list
│       ├── application.html           # Application details & AURORA report
│       └── training.html              # Training data management
├── scripts/
│   ├── setup/                         # Setup scripts
│   ├── init/                          # Database initialization
│   ├── migrate/                       # Migration scripts
│   ├── verify/                        # Verification scripts
│   └── audit/                         # Audit scripts
├── documents/                         # Documentation
│   ├── setup/                         # Setup guides
│   ├── deployment/                    # Deployment documentation
│   ├── security/                      # Security guidelines
│   └── verification/                  # Verification checklists
├── testing/                           # Test scripts
├── uploads/                           # Temporary upload storage
└── logs/                              # Application logs
```

## 🔧 Configuration

### Primary: Azure Key Vault (Recommended)

All configuration is stored in **Azure Key Vault** (`your-keyvault-name`) by default.

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
- Content Processing: `content-processing-endpoint`, `content-processing-api-key`, `content-processing-api-key-header`, `content-processing-enabled`

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
python -c "from src.config import config; print('Configuration loaded successfully')"
```

## 📋 Key Features Explained

### **Audit Logging (Phase 5a)**
Every workflow step is logged to the `agent_interactions` table with:
- **14 interaction types** covering all 9 steps
- Step 1: BELLE extraction
- Step 2: Student matching  
- Step 2.5: High school enrichment
- Steps 3-3.5: School validation & remediation
- Steps 4-4.5: Core agent execution & validation gates
- Steps 5-7: Synthesis & reporting
- Plus pause/resume interactions

Query audit trail:
```sql
SELECT * FROM agent_interactions 
WHERE application_id = 'student-id'
ORDER BY created_at;
```

### **File Upload Handler (Phase 5b)**
Intelligent student matching for new file uploads:
- **AI Extraction**: Extracts student info from uploaded documents
- **Fuzzy Matching**: 8-tier relevance scoring
- **Confidence Threshold**: 0.8 for positive matches
- **Smart Decision**:
  - ✅ If confidence ≥ 0.8: Adds file to existing student, triggers re-evaluation
  - ❌ If confidence < 0.8: Creates new student record
- **Audit Trail**: Every matching decision logged with human review fields

Query file upload decisions:
```sql
SELECT * FROM file_upload_audit 
WHERE human_reviewed = FALSE
ORDER BY uploaded_at DESC;
```

## 🌐 Deployment to Azure Web App

Deploy your Flask application to Azure for production hosting with automatic scaling and monitoring.

### Quick Deploy

```bash
# 1. Create App Service Plan (adjust SKU as needed)
az appservice plan create \
  --name your-appservice-plan \
  --resource-group your-resource-group \
  --sku B2 \
  --is-linux

# 2. Create Web App
az webapp create \
  --resource-group your-resource-group \
  --plan your-appservice-plan \
  --name your-webapp-name \
  --runtime "PYTHON|3.9"

# 3. See documents/deployment/AZURE_WEBAPP_DEPLOY.md for complete setup instructions
```

**Complete Deployment Guide:** See [documents/deployment/AZURE_WEBAPP_DEPLOY.md](documents/deployment/AZURE_WEBAPP_DEPLOY.md)

**CI/CD Notes:** The active workflow is [/.github/workflows/deploy-to-azure.yml](.github/workflows/deploy-to-azure.yml) and uses Azure OIDC. Set GitHub Secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`. The legacy publish profile workflow is no longer required.

### Features When Deployed
- ✅ Automatic HTTPS/SSL
- ✅ Key Vault integration via Managed Identity
- ✅ Gunicorn WSGI server with multiple workers
- ✅ Continuous deployment via GitHub Actions
- ✅ Production-ready configuration
- ✅ Automatic scaling (higher plans)

## 🧪 Testing

### **Real-Time Test System**
The web application includes a dedicated test page (`/test`) that allows you to:

1. **Run 9-Step Workflows** - Watch real-time agent execution
2. **Test Modes**:
   - 🚀 **Random Students**: Generate new synthetic data each run
   - ⚡ **Preset Students**: Use fixed test data (Alice, Brian, Carol)
   - ⚡ **Single Student**: Quick test with one student
   - 🗑️ **Clear Test Data**: Delete all test students for fresh runs

3. **Real-Time Monitoring** - Watch agents execute as:
   - BELLE extracts student data
   - Student records are matched/created
   - School context is validated
   - Core agents evaluate applications
   - Results are synthesized and reported

### **Realistic Test Data**
Test data generator creates students with:
- ✅ Realistic birthdates based on grade level
  - Sophomores: Born 2009-2010 (ages 15-16 in June 2026)
  - Juniors: Born 2008-2009 (ages 16-17 in June 2026)
  - Seniors: Born 2007-2008 (ages 17-18 in June 2026)
- ✅ Full 4-year academic history with 5-8 courses per semester
- ✅ Realistic GPA, AP courses, and test scores
- ✅ Diverse school contexts (public, magnet, private)
- ✅ Quality tiers: High, Medium, Low (for variety)

Generate test batch:
```python
from src.test_data_generator import test_data_generator

# Generate 5 random students
students = test_data_generator.generate_batch(count=5)

# Generate specific grade levels
senior = test_data_generator.generate_student(grade_level=12)
junior = test_data_generator.generate_student(grade_level=11)
sophomore = test_data_generator.generate_student(grade_level=10)
```

### **Command-Line Testing**
```bash
# Test file upload handler
python testing/test_agent.py

# Test orchestrator
python testing/test_smee.py
```

## 📤 Upload & Evaluation Flow

### **File Upload Triggers 9-Step Workflow**

**For 2026 Applicants (Real Admissions):**
1. Upload document (PDF, DOCX, TXT, etc.)
2. BELLE extracts student info + documents
3. Student matching (composite key lookup)
4. High school enrichment check
5. NAVEEN enriches schools data
6. MOANA validates school (with remediation if needed)
7. Core agents evaluate (TIANA, RAPUNZEL, MOANA, MULAN)
8. MILO pattern analysis
9. MERLIN synthesis + AURORA report generation

**For Test Uploads:**
- Same 9-step pipeline but isolated in test data
- Monitor agent execution on Test page (`/test`)
- Clear test data without affecting real applicants

**For Training Data:**
- Historical excellent examples
- Used to calibrate MILO pattern detection
- Supports re-evaluation analysis

### **Re-Evaluation with Additional Files**
If a student already exists in the system:
- New files are added to the same student record
- Student is marked for re-evaluation
- Full 9-step workflow runs with all available documents
- More data sources = more accurate assessment

Progress is tracked via status badges:
- 📋 Pending: Waiting for evaluation
- 🔄 Processing: Workflow in progress  
- ✅ Complete: All steps finished
- ⚠️ Waiting: Additional documents needed for next steps

## 🔐 Azure Storage Access

Storage uploads use Azure AD authentication via the App Service managed identity. Ensure the web app identity has the **Storage Blob Data Contributor** role on the storage account, and that storage network access allows the app to reach Blob endpoints.

## 📈 Application Insights (Agents View)

Telemetry is enabled when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set. Prompt capture is controlled by `NEXTGEN_CAPTURE_PROMPTS`.
Agent runs, model usage, and token counts appear in the Agents view once telemetry is flowing.

## 💡 Usage Tips

### Training the AI
- Upload 5-10 examples of excellent applications
- Mark them as "Training Examples"
- Indicate if they were selected
- The AI learns what excellence looks like
- Use the Training page to clear legacy training data when you need a fresh baseline.

### Best Practices
- Provide detailed applications for better evaluation  
- Include relevant experience and skills
- Review AI recommendations before final decisions
- Give feedback to improve accuracy

## 🔐 Security - Secure by Default

### Zero Plaintext Credentials

This application is designed to **never expose credentials**:

✅ **All secrets in Azure Key Vault** - Enterprise-grade encryption  
✅ **No .env files in Git** - `.gitignore` configured properly  
✅ **No hardcoded credentials** - Code only references config variables  
✅ **Managed Identity** - Application authenticates via Azure AD  
✅ **TLS/SSL everywhere** - All connections encrypted  
✅ **Audit trail** - All operations logged for compliance

**First-Time Setup:**
```bash
./scripts/setup/keyvault_setup.sh
```

**Stored in Key Vault:**
- PostgreSQL: `postgres-host`, `postgres-password`, etc.
- Azure OpenAI: `azure-openai-endpoint`, `azure-deployment-name`
- Application: `flask-secret-key` (auto-generated)

For complete security guidelines, see [documents/security/SECURITY_GUIDE.md](documents/security/SECURITY_GUIDE.md).

## 📚 Additional Resources

### Core Documentation
- **[WORKFLOW_MAP.md](WORKFLOW_MAP.md)** - Complete 9-step workflow visualization with data flows
- **[README_WORKFLOW.md](README_WORKFLOW.md)** - User-focused workflow guide with examples
- **[PHASE_5_SUMMARY.md](PHASE_5_SUMMARY.md)** - Audit logging & file upload implementation details
- **[AGENT_ARCHITECTURE_DETAILED.md](AGENT_ARCHITECTURE_DETAILED.md)** - Agent implementation details and specializations

### Setup & Configuration
- **[documents/setup/SETUP_GUIDE_MANUAL.md](documents/setup/SETUP_GUIDE_MANUAL.md)** - Step-by-step manual setup
- **[documents/setup/KEY_VAULT_SETUP.md](documents/setup/KEY_VAULT_SETUP.md)** - Key Vault configuration guide
- **[documents/setup/POSTGRESQL_KEYVAULT_SETUP.md](documents/setup/POSTGRESQL_KEYVAULT_SETUP.md)** - PostgreSQL + Key Vault integration
- **[documents/setup/LOCAL_TEST_AND_AZURE_SETUP.md](documents/setup/LOCAL_TEST_AND_AZURE_SETUP.md)** - Local vs Azure setup comparison

### Deployment Documentation
- **[documents/deployment/AZURE_WEBAPP_DEPLOY.md](documents/deployment/AZURE_WEBAPP_DEPLOY.md)** - Production deployment guide
- **[documents/deployment/DEPLOYMENT_CHECKLIST.md](documents/deployment/DEPLOYMENT_CHECKLIST.md)** - Pre-deployment verification
- **[documents/deployment/DEPLOYMENT_SUCCESS.md](documents/deployment/DEPLOYMENT_SUCCESS.md)** - Current deployment status

### Data & Security
- **[documents/migration/POSTGRES_MIGRATION.md](documents/migration/POSTGRES_MIGRATION.md)** - Database migration guide
- **[documents/security/SECURITY_GUIDE.md](documents/security/SECURITY_GUIDE.md)** - Security best practices
- **[documents/security/SECURITY_AND_EFFICIENCY_AUDIT.md](documents/security/SECURITY_AND_EFFICIENCY_AUDIT.md)** - Compliance audit results

### Verification & Testing
- **[documents/verification/AGENT_STATUS_TRACKING.md](documents/verification/AGENT_STATUS_TRACKING.md)** - Agent status monitoring
- **[documents/verification/AGENT_GPT_VERIFICATION.md](documents/verification/AGENT_GPT_VERIFICATION.md)** - Agent output verification

## 🎯 Quick Reference

### Common Commands

```bash
# Start development
source .venv/bin/activate && python app.py

# Run tests
python testing/test_smee.py
python testing/test_agent.py

# Check database
python testing/show_database_structure.py

# Clear test data
python testing/clear_database.py

# Deploy to Azure
az webapp deployment source config-zip --resource-group your-rg --name your-app --src app.zip
```

### Key URLs (Local Development)
- Dashboard: http://localhost:5001
- Upload: http://localhost:5001/upload
- Test System: http://localhost:5001/test
- Students: http://localhost:5001/students
- Application Details: http://localhost:5001/application/{id}

### Key Directories
- **src/agents/** - Agent implementations (BELLE, TIANA, RAPUNZEL, etc.)
- **src/services/** - Business logic and processing
- **web/templates/** - HTML templates for web interface
- **database/** - SQL schema definitions
- **scripts/** - Automation scripts (setup, init, migrate, verify)
- **testing/** - Test utilities and debugging tools
- **documents/** - Comprehensive documentation

### Performance Tips
- **Batch Processing**: Use test data generator for 5+ students at once
- **Caching**: Agent outputs are cached in ai_evaluations table
- **Parallel Execution**: Core agents (TIANA, RAPUNZEL, MOANA, MULAN) run simultaneously
- **Database Indices**: Ensure school_lookup_index exists for fast matching
- **Content Processing**: Enable only when needed (CONTENT_PROCESSING_ENABLED)

## 🎓 Architecture Decision Records

### Why 9-Step Workflow?
- **Stages agents by dependency**: Extract → Match → Enrich → Validate → Evaluate → Synthesize → Report
- **Enables validation gates**: Each agent validates input before processing
- **Supports remediation loops**: Validation failures trigger targeted re-processing (e.g., NAVEEN ↔ MOANA)
- **Audit-friendly**: Each step logs separately for compliance

### Why Composite Key Matching?
- **Prevents duplicates**: Same student → Same records (no data fragmentation)
- **Enables re-evaluation**: New files added to existing student record
- **Fair assessment**: All available data considered in final evaluation
- **Multi-school scenarios**: Students who moved between schools are correctly identified

### Why RAPUNZEL Contextual Rigor Weighting?
- **Fair assessment across school types**: Private school vs public school grade distributions differ significantly
- **Opportunity-adjusted scoring**: Considers AP/Honors availability, not just GPA
- **Demographic awareness**: Accounts for school free/reduced lunch rates
- **0-5 scale clarity**: Easy to interpret in reports and decisions

### Why Fairness Factor (MOANA)?
- **Systemic bias reduction**: Adjusts for documented school resource disparities
- **Evidence-based**: Weights derived from public school data
- **Transparent**: All weighting factors documented in outputs
- **Reviewable**: Human evaluators can see and question adjustments

## 🚀 Project Roadmap

**Current Phase (5):** ✅ Complete
- 9-step orchestration
- Audit logging (14 types)
- File upload handler with AI matching

**Future Enhancements:**
- [ ] API endpoints for integration
- [ ] Email notifications for applicants
- [ ] Advanced analytics dashboard
- [ ] Custom evaluation criteria per program
- [ ] Multi-language support
- [ ] Batch import from SFTP/S3
- [ ] Scheduled re-evaluations
- [ ] Stakeholder feedback loop

## 📝 License & Support

This project is built with Azure AI services and requires:
- ✅ Azure subscription (OpenAI, Key Vault, PostgreSQL)
- ✅ GitHub account (for CI/CD)
- ✅ Python 3.9+

For support, refer to deployment documentation and security guides in the `/documents` directory.

## �‍💻 Development Workflow

### Local Development Setup

**Every development session:**
```bash
# Activate virtual environment
source .venv/bin/activate

# Verify environment setup
python -c "from src.config import config; print('✅ Configuration loaded')"

# Start development server (auto-reloads on file changes)
python app.py
```

**Running tests:**
```bash
# Test agent orchestration
python testing/test_smee.py

# Test file upload handler
python testing/test_agent.py

# Generate test data
python testing/test_data_generator.py
```

### Code Structure for New Agents

To create a custom agent:

1. **Create agent file** in `src/agents/`:
   ```python
   from src.agents.base_agent import BaseAgent
   
   class MyAgent(BaseAgent):
       async def process(self, data):
           # Your agent logic
           return result
   ```

2. **Register in orchestrator** (`src/agents/smee_orchestrator.py`):
   ```python
   my_agent = MyAgent()
   result = await my_agent.process(application_data)
   ```

3. **Add audit logging**:
   ```python
   await self._log_interaction(
       application_id=application_id,
       agent_name="my_agent",
       step=8,  # Your step number
       action="analyze",
       output=result
   )
   ```

### Database Debugging

**Connect directly to PostgreSQL:**
```bash
psql "postgresql://user:password@host:5432/ApplicationsDB"

# View recent agent interactions
SELECT * FROM agent_interactions 
ORDER BY created_at DESC LIMIT 10;

# View file uploads and matching decisions
SELECT * FROM file_upload_audit 
ORDER BY uploaded_at DESC LIMIT 10;

# Check application status
SELECT id, first_name, status FROM applications LIMIT 5;
```

**Database Reset for Development:**
```bash
# ⚠️ WARNING: This deletes all data
python testing/clear_database.py

# Reinitialize schema
python scripts/init/init_database.py
```

## 🛠️ Troubleshooting

**Database Connection Issues:**
- Verify PostgreSQL credentials in Key Vault or `.env.local`
- Check PostgreSQL is running: `az container show --resource-group your-resource-group --name your-postgres-container`
- Test connection: `psql "postgresql://user:password@host:5432/ApplicationsDB"`
- Common fix: Ensure firewall rules allow your IP

**AI Evaluation Errors:**
- Ensure Azure OpenAI resource is accessible
- Check deployment name matches environment variable (gpt-4, gpt-35-turbo)
- Verify you have "Cognitive Services OpenAI User" role assigned
- Check token limits: Some models have different max token counts

**Import Errors:**
- Make sure virtual environment is activated: `source .venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`
- Check Python version: `python --version` (requires 3.9+)

**Key Vault Access Issues:**
- Run `az login` to authenticate with Azure
- Verify Key Vault permissions: `Reader` + `Key Vault Secrets User` role
- Check Key Vault name matches config: `az keyvault show --name your-keyvault-name`

**Application Insights Not Showing Data:**
- Ensure `APPLICATIONINSIGHTS_CONNECTION_STRING` is set in Key Vault
- Check Application Insights resource exists in Azure Portal
- Wait 5-10 minutes for telemetry to appear
- Verify `NEXTGEN_CAPTURE_PROMPTS=true` if you want detailed logging
