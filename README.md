# NextGen Multi-Agent Student Evaluation System

> **Version 1.0.43** · Production-ready AI evaluation pipeline with 15+ Disney-themed agents, 4-tier model architecture, and enterprise security via Azure Front Door + WAF.

An intelligent multi-agent system that evaluates high school internship applications using specialized Disney-themed agents coordinated in a 9-step workflow. Built on Azure AI Foundry with comprehensive audit trails, fairness-aware assessment, and school context enrichment.

---

## 🎯 Features

- **9-Step Intelligent Workflow** — Orchestrated evaluation: Extract → Match → Enrich → Validate → Evaluate → Synthesize → Report
- **15+ Specialized Agents** — Disney-themed AI agents each handling a focused evaluation aspect
- **4-Tier Model Architecture** — Premium, Merlin, Workhorse, and Lightweight tiers for cost/quality optimization
- **Smart Student Matching** — Composite key matching (name + school + state) prevents duplicates
- **School Context Enrichment** — Database-first NCES data with NAVEEN AI evaluation + MOANA contextual narratives
- **Contextual Rigor Weighting** — RAPUNZEL calculates academic rigor adjusted by school opportunity (0–5 scale)
- **Video Application Support** — MIRABEL analyzes video submissions with chunked upload (100KB for WAF compatibility)
- **Interactive Q&A** — ARIEL answers natural language questions about any evaluated student
- **Model Validation** — Milo validates prediction accuracy against training data with confusion matrix and per-student metrics
- **Document Reprocessing** — Re-extract all training documents through the improved pipeline with progress tracking
- **Training Diagnostics** — Real-time field-size dashboard showing extraction health for all training records
- **AI-Powered Section Detection** — Belle uses GPT fallback when keyword scoring is inconclusive for page classification
- **Vision OCR** — Scanned/image-based PDF pages automatically OCR'd via GPT-4o vision model
- **Historical Score Import** — Upload XLSX scoring spreadsheets and link to training applications
- **XLSX Resolution UI** — Search and link unmatched historical scores to training records
- **Session Authentication** — Username/password login with configurable session expiry
- **Comprehensive Audit Trail** — 14 interaction types logged to database for compliance
- **Feedback System** — User-submitted issues auto-create GitHub issues
- **Telemetry & Observability** — OpenTelemetry + Application Insights for agent performance monitoring
- **Azure Front Door + WAF** — Enterprise DDoS protection, SSL termination, and bot management
- **Secure by Default** — Azure Key Vault credentials, no plaintext secrets, managed identity

---

## 🦸 Disney Agent Team

### 9-Step Workflow

```
1️⃣  BELLE (Document Analyzer)
    │  Extracts structured data from PDF, DOCX, TXT, MP4
    │
2️⃣  Student Matching
    │  Composite key lookup prevents duplicates
    │
2️⃣➕ High School Pre-Enrichment
    │  Proactively validates/enriches school data
    │
3️⃣  NAVEEN (School Data Scientist)
    │  Evaluates NCES database records → component scores + school summary
    │
3️⃣➕ MOANA (School Context Analyzer)
    │  Builds AI-powered contextual narrative using Naveen + student data
    │
4️⃣  Core Agents (parallel, with per-agent validation gates):
    ├─ TIANA (Application Reader)
    ├─ RAPUNZEL (Grade Reader with contextual rigor weighting)
    ├─ MOANA (School Context & Fairness Weighting)
    └─ MULAN (Recommendation Reader)
    │
5️⃣  MILO (Data Scientist)
    │  Pattern analysis against training data
    │
6️⃣  MERLIN (Student Evaluator)
    │  Synthesizes all results into comprehensive assessment
    │
7️⃣  AURORA (Results Formatter)
    └─ Generates executive summary and evaluation report
```

### All Agents

| Agent | File | Role | Model Tier |
|-------|------|------|------------|
| 📖 **BELLE** | `belle_document_analyzer.py` | Document extraction (PDF, DOCX, TXT, MP4) | Lightweight |
| 👸 **TIANA** | `tiana_application_reader.py` | Application essay & communication analysis | Workhorse |
| 👑 **RAPUNZEL** | `rapunzel_grade_reader.py` | Academic rigor with contextual weighting (0–5) | Premium |
| 🌊 **MOANA** | `moana_school_context.py` | AI-powered student school context narratives | Workhorse |
| 🥋 **MULAN** | `mulan_recommendation_reader.py` | Recommendation letter synthesis | Workhorse |
| 📊 **MILO** | `milo_data_scientist.py` | Training data insights & pattern detection | Premium |
| 🧑‍🔬 **NAVEEN** | `naveen_school_data_scientist.py` | NCES database school evaluation & scoring | Workhorse |
| 🧙 **MERLIN** | `merlin_student_evaluator.py` | Overall recommendation & rationale synthesis | Merlin |
| ✨ **AURORA** | `aurora_agent.py` | Executive summary & report formatting | Workhorse |
| 🎬 **MIRABEL** | `mirabel_video_analyzer.py` | Video application analysis (frame extraction) | Vision (gpt-4o) |
| 🧜 **ARIEL** | `ariel_qa_agent.py` | Interactive Q&A about evaluated students | Workhorse |
| ⚔️ **GASTON** | `gaston_evaluator.py` | Evaluation validation & quality checks | Workhorse |
| 🐚 **BASHFUL** | `bashful_agent.py` | Supporting classification tasks | Lightweight |
| 🧚 **FAIRY GODMOTHER** | `fairy_godmother_document_generator.py` | Document generation | Workhorse |
| 📋 **FEEDBACK TRIAGE** | `feedback_triage_agent.py` | User feedback classification & GitHub issue creation | Workhorse |

**Orchestrator:** **SMEE** (`smee_orchestrator.py`) — Coordinates the full 9-step pipeline.

---

## 🏗️ 4-Tier Model Architecture

Models are configured in `src/config.py` and overridable via Key Vault or environment variables:

| Tier | Deployment Name | Base Model | Used By | Env Var |
|------|----------------|------------|---------|---------|
| **Premium** | `gpt-4.1` | GPT-4.1 | Rapunzel, Milo (complex reasoning) | `MODEL_TIER_PREMIUM` |
| **Merlin** | `MerlinGPT5Mini` | GPT-5-mini | Merlin (final evaluation) | `MODEL_TIER_MERLIN` |
| **Workhorse** | `WorkForce4.1mini` | GPT-4.1-mini | Tiana, Mulan, Moana, Gaston, Smee, Naveen, Ariel, Aurora | `MODEL_TIER_WORKHORSE` |
| **Lightweight** | `LightWork5Nano` | GPT-5-nano | Belle, Bashful (classification/triage) | `MODEL_TIER_LIGHTWEIGHT` |
| **Vision** | `gpt-4o` | GPT-4o | Mirabel (video analysis) | — |

Additional deployment: `text-embedding-ada-002` for embeddings.

---

## 🌐 Web Interface — All Pages

The application provides a full-featured web UI built with Flask and Jinja2 templates.

### Navigation Menu (8 pages)

| Nav Item | Route | Description |
|----------|-------|-------------|
| 📊 Dashboard | `/` | Home page showing pending/evaluated/total counts and recent applications |
| 👥 2026 Applicants | `/students` | Searchable list of all 2026 applicants sorted by last name with status badges |
| 🧪 Test Data | `/test-data` | Students created via Quick Test for development and testing |
| 📚 Training | `/training` | Historical training applications with upload, import scores, XLSX resolution, and Milo insights |
| 🗄️ Data Management | `/data-management` | Central hub for schools, training data, and database operations |
| 📤 Upload Application | `/upload` | Upload student documents (PDF, DOCX, TXT, MP4) to trigger the evaluation pipeline |
| 📝 Feedback | `/feedback` | Report issues or request features — auto-creates GitHub issues |
| ⚡ Quick Test | `/test` | Real-time 9-step pipeline test with live agent progress tracking |
| 🔐 Login | `/login` | Session-based authentication (auto-redirect when auth is configured) |

### Additional Pages (not in nav)

| Page | Route | Description |
|------|-------|-------------|
| Student Detail | `/student/<id>` | Full student dashboard with score cards and all agent results (Merlin, Aurora, Tiana, Rapunzel, Mulan, Moana) |
| Application Detail | `/application/<id>` | Comprehensive evaluation view with executive summary, agent evaluations, audit trail, and ARIEL Q&A |
| Import Historical Scores | `/import-scores` | Upload XLSX scoring spreadsheets for Milo calibration data |
| School Management | `/schools` | School database with filters, batch enrichment (Naveen + Moana), add/edit schools |
| School Enrichment Detail | `/schools/<id>` | Individual school's demographics, resources, and opportunity scores |
| Process Student | `/process/<id>` | Real-time processing view showing agent progress during evaluation |
| Telemetry Dashboard | `/telemetry` | Agent performance metrics, Application Insights status, school pipeline status |
| Agent Monitor | `/agent-monitor` | Standalone dark-terminal UI for real-time agent debugging |
| Feedback Admin | `/feedback/admin` | Admin view of all user feedback with GitHub issue tracking |
| Test Detail | `/test/<id>` | Individual test run details |

---

## 🏗️ Azure Architecture

### Production Infrastructure

| Component | Resource | Details |
|-----------|----------|---------|
| **Azure Front Door** | `nextgen-frontdoor` (Premium) | DDoS protection, SSL termination, global load balancing |
| **WAF Policy** | `nextgenWAFPolicy` | Prevention mode, DRS 2.1, BotManager 1.1, 128KB body inspection |
| **Web App** | `nextgen-agents-web` | Python 3.12 on Linux App Service (gunicorn 4 workers, 600s timeout) |
| **AI Foundry** | `nextgenagentfoundry` (West US 3) | 7 model deployments across 4 tiers |
| **PostgreSQL** | Flexible Server | Application data, audit trails, training records |
| **Key Vault** | Secure credential store | All secrets managed via Azure AD / Managed Identity |
| **Blob Storage** | Document storage | Student uploads with managed identity access |
| **Application Insights** | Telemetry | Agent performance, token usage, request tracing |

### Endpoints

| Environment | URL |
|-------------|-----|
| **Production** | `https://nextgen-app-h7hvaybqd4grd0b2.b02.azurefd.net` |
| **Staging** | `https://nextgen-staging-acfvbrd4g2cud9cs.b02.azurefd.net` |

### Security Architecture (7 Phases — All Complete)

1. **Key Vault Integration** — All credentials stored in Azure Key Vault
2. **Managed Identity** — App authenticates via Azure AD, no API keys in code
3. **Network Security** — SCM basic auth disabled, access restricted to Front Door
4. **Front Door + WAF** — Enterprise edge security with bot protection
5. **Audit Logging** — 14 interaction types for compliance verification
6. **Storage Security** — Blob access via managed identity with RBAC
7. **Deployment Security** — ARM-based zip deploy, SCM lock/unlock pattern

---

## 🚀 Quick Start

### Prerequisites

- Python 3.12+ (3.9+ compatible)
- Azure CLI (`az login`)
- Azure subscription with Key Vault + OpenAI access

### Setup

```bash
# Clone and navigate
cd "Agent NextGen"

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Authenticate with Azure
az login

# Initialize database
python scripts/init/init_database.py

# Start the application
python app.py
```

### Local URLs

| Page | URL |
|------|-----|
| Dashboard | http://localhost:5001 |
| Upload | http://localhost:5001/upload |
| Students | http://localhost:5001/students |
| Test System | http://localhost:5001/test |
| Training | http://localhost:5001/training |
| Schools | http://localhost:5001/schools |

### Configuration

**Primary (Production):** Azure Key Vault — secrets retrieved via `DefaultAzureCredential`.

```bash
# One-time setup
./scripts/setup/keyvault_setup.sh
```

**Fallback (Development only):** `.env.local` file for offline development.

```bash
cp .env.example .env.local
nano .env.local  # Add your credentials (never commit this file)
```

---

## 🌍 Environment Variables

### Azure OpenAI
| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI API endpoint |
| `AZURE_OPENAI_API_KEY` | API key (or use managed identity) |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | Default model deployment name |
| `AZURE_OPENAI_API_VERSION` | API version (e.g., `2024-12-01-preview`) |

### Model Tiers
| Variable | Description | Default |
|----------|-------------|---------|
| `MODEL_TIER_PREMIUM` | Complex reasoning (Rapunzel, Milo) | `gpt-4.1` |
| `MODEL_TIER_MERLIN` | Final evaluation (Merlin) | `MerlinGPT5Mini` |
| `MODEL_TIER_WORKHORSE` | Structured extraction (most agents) | `WorkForce4.1mini` |
| `MODEL_TIER_LIGHTWEIGHT` | Classification/triage (Belle, Bashful) | `LightWork5Nano` |

### PostgreSQL
| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | Database server hostname |
| `POSTGRES_PORT` | Port (default: 5432) |
| `POSTGRES_DATABASE` | Database name (`ApplicationsDB`) |
| `POSTGRES_USERNAME` | Connection username |
| `POSTGRES_PASSWORD` | Connection password |

### Application
| Variable | Description |
|----------|-------------|
| `FLASK_SECRET_KEY` | Session management secret |
| `FLASK_ENV` | `development` or `production` |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insights telemetry |
| `NEXTGEN_CAPTURE_PROMPTS` | Enable/disable prompt logging (`true`/`false`) |

---

## 📊 Database Schema

### Core Tables

| Table | Purpose |
|-------|---------|
| `applications` | Student applications with demographics, documents, status |
| `student_school_context` | School enrichment data (AP courses, demographics, opportunity scores) |
| `rapunzel_grades` | Academic data with contextual rigor weighting (0–5 scale) |
| `ai_evaluations` | Agent outputs from all 9 workflow steps |
| `agent_results` | Structured agent evaluation results |
| `historical_scores` | Imported XLSX scoring data for Milo calibration |

### Audit & Compliance Tables

| Table | Purpose |
|-------|---------|
| `agent_interactions` | 14 interaction types covering the full 9-step workflow (JSONB output, timestamps) |
| `file_upload_audit` | AI-based student matching decisions with confidence scores and human review fields |

### School Data (NCES)

School data is sourced from the **NCES Common Core of Data (CCD)** — the U.S. Department of Education's annual census of public schools. Data is imported via CSV upload on the Training page (Schools tab) rather than fetched from external APIs at runtime.

**Import workflow:**
1. Download CCD data from [NCES](https://nces.ed.gov/ccd/)
2. Upload the CSV via Training → Schools tab (supports NCES column names)
3. Schools are fuzzy-matched to existing records (threshold 0.55) or created
4. Naveen evaluates each school's NCES data to produce component scores
5. Moana uses the evaluation + student transcript to build contextual narratives

**Key NCES fields stored in `school_enriched_data`:**
- Enrollment, student-teacher ratio, free/reduced lunch %
- Title I status, charter/magnet flags, locale classification
- Per-pupil expenditure, AP course count, graduation rate
- District name, county, state

---

## 🤖 The 9-Step Workflow in Detail

### Step 1 — BELLE Extraction
Upload triggers BELLE to extract structured data (name, school, grades, test scores, achievements) from any supported document format.

### Step 2 — Smart Student Matching
Composite key lookup: `first_name + last_name + high_school + state_code`. Matches existing student or creates new record. Prevents duplicates while enabling re-evaluation with additional files.

### Step 2+ — High School Pre-Enrichment
Validates school record exists. If missing, NAVEEN proactively enriches before the validation loop begins.

### Step 3 — School Evaluation (NAVEEN)
Evaluates school from NCES database records imported via CSV. Produces a School Evaluation Report with component scores (Academic Rigor, Resource Investment, Student Outcomes, Equity & Access), a school summary narrative, key insights, and a context statement for downstream agents.

### Step 3+ — School Context Narrative (MOANA)
MOANA uses Naveen's school evaluation, NCES database fields (enrollment, student-teacher ratio, FRPL%, Title I status, locale, per-pupil expenditure), and the student's own coursework to produce an AI-powered contextual narrative — a 6–10 sentence data-grounded assessment of what the student's record means in context.

### Step 4 — Core Agent Evaluation (Parallel)
Four agents run simultaneously with per-agent validation gates:
1. **TIANA** — Application essays and communication
2. **RAPUNZEL** — Grades with contextual rigor (base rigor × AP availability × opportunity score)
3. **MOANA** — Student school context narrative
4. **MULAN** — Recommendation letter synthesis

### Step 5 — Pattern Analysis (MILO)
Analyzes performance against training data. Identifies selection indicators and historical patterns.

### Step 6 — Comprehensive Evaluation (MERLIN)
Synthesizes all agent outputs, applies fairness adjustments, produces overall score and recommendation with strengths/considerations.

### Step 7 — Results Formatting (AURORA)
Generates executive summary and formatted evaluation report for human review.

---

## 📤 File Upload & Re-Evaluation

### Supported Formats
PDF, DOCX, DOC, TXT, MP4 (video with chunked upload at 100KB for WAF compatibility)

### Upload Types
- **2026 Applicant** — Real admissions: full 9-step pipeline
- **Training Data** — Historical examples for Milo calibration
- **Test Upload** — Isolated test environment, clearable without affecting real data

### Re-Evaluation
When a student already exists, new files are added to the same record and the full 9-step workflow re-runs with all available documents. More data = more accurate assessment.

### Status Badges
- 📋 **Pending** — Waiting for evaluation
- 🔄 **Processing** — Workflow in progress
- ✅ **Complete** — All steps finished
- ⚠️ **Waiting** — Additional documents needed

---

## 📁 Project Structure

```
.
├── app.py                              # Flask web application (~7900 lines)
├── main.py                             # CLI interface
├── requirements.txt                    # Python dependencies
├── VERSION                             # Current version (1.0.43)
├── Dockerfile                          # Container configuration
├── Procfile                            # Process configuration
├── startup.sh / startup.py             # App Service startup
├── wsgi.py                             # WSGI entry point
├── database/
│   ├── schema_postgresql.sql           # Core PostgreSQL schema
│   ├── schema_school_enrichment.sql    # School context tables
│   ├── schema_azure_sql.sql            # Azure SQL variant
│   └── *.sql                           # Migration scripts
├── src/
│   ├── config.py                       # Configuration (Key Vault + env vars + 4-tier models)
│   ├── database.py                     # PostgreSQL operations + audit logging
│   ├── logger.py                       # Logging utilities
│   ├── storage.py                      # Blob storage operations
│   ├── test_data_generator.py          # Synthetic test data generation
│   ├── file_upload_handler.py          # AI-based student matching & upload orchestration
│   └── agents/
│       ├── smee_orchestrator.py        # 9-step workflow orchestrator
│       ├── belle_document_analyzer.py  # Step 1: Document extraction
│       ├── naveen_school_data_scientist.py  # Step 3: School enrichment
│       ├── moana_school_context.py     # Step 3+: School validation & fairness
│       ├── tiana_application_reader.py # Step 4: Application analysis
│       ├── rapunzel_grade_reader.py    # Step 4: Grade analysis + rigor weighting
│       ├── mulan_recommendation_reader.py   # Step 4: Recommendation synthesis
│       ├── milo_data_scientist.py      # Step 5: Pattern analysis
│       ├── merlin_student_evaluator.py # Step 6: Overall evaluation
│       ├── aurora_agent.py             # Step 7: Report formatting
│       ├── mirabel_video_analyzer.py   # Video application analysis
│       ├── ariel_qa_agent.py           # Interactive Q&A
│       ├── ariel_adapter.py            # Ariel adapter layer
│       ├── gaston_evaluator.py         # Evaluation validation
│       ├── bashful_agent.py            # Classification support
│       ├── fairy_godmother_document_generator.py  # Document generation
│       ├── feedback_triage_agent.py    # Feedback → GitHub issues
│       ├── agent_monitor.py            # Real-time agent monitoring
│       ├── agent_requirements.py       # Agent validation gates
│       ├── foundry_client.py           # Azure AI Foundry client
│       ├── telemetry_helpers.py        # OpenTelemetry integration
│       ├── system_prompts.py           # Shared agent prompts
│       └── base_agent.py              # Base agent class
├── web/
│   └── templates/                      # 22 Jinja2 HTML templates
│       ├── base.html                   # Shared layout with nav menu
│       ├── index.html                  # Dashboard
│       ├── students.html               # 2026 Applicants list
│       ├── student_detail.html         # Individual student dashboard
│       ├── application.html            # Full evaluation detail + ARIEL Q&A
│       ├── upload.html                 # File upload (PDF/DOCX/TXT/MP4)
│       ├── training.html               # Training data management
│       ├── test.html                   # Real-time pipeline test
│       ├── test_data.html              # Test data students
│       ├── test_detail.html            # Individual test detail
│       ├── import_scores.html          # XLSX historical score import
│       ├── school_management.html      # School database management
│       ├── school_enrichment_detail.html  # Individual school detail
│       ├── data_management.html        # Central data management hub
│       ├── process_student.html        # Live processing progress
│       ├── feedback.html               # User feedback form
│       ├── feedback_admin.html         # Feedback admin panel
│       ├── telemetry_dashboard.html    # Telemetry & observability
│       ├── agent_monitor.html          # Agent debugging terminal
│       ├── student_summary_json.html   # Student summary JSON view
│       ├── _student_list.html          # Reusable student list component
│       └── debug_dataset.html          # Debug dataset viewer
├── scripts/
│   ├── setup/                          # Setup and provisioning scripts
│   ├── init/                           # Database initialization
│   ├── migrate/                        # Database migrations
│   ├── verify/                         # Verification scripts
│   ├── audit/                          # Audit scripts
│   ├── check/                          # Health checks
│   ├── fix/                            # Fix scripts
│   ├── git-hooks/                      # Git hooks
│   ├── backfill_summaries.py           # Backfill student summaries
│   ├── seed_schools.py                 # Seed school database
│   └── bump_version.py                 # Version management
├── documents/                          # Documentation
│   ├── setup/                          # Setup guides
│   ├── deployment/                     # Deployment docs
│   ├── security/                       # Security guidelines
│   ├── verification/                   # Verification checklists
│   ├── debugging/                      # Debug guides
│   └── migration/                      # Migration docs
├── testing/                            # Test utilities
├── uploads/                            # Temporary upload storage
├── student_documents/                  # Student document storage
└── logs/                               # Application logs
```

---

## 🚢 Deployment

### Method: ARM-Based Zip Deploy

SCM basic auth is disabled and Azure Front Door is in front of the SCM endpoint. Deployment uses `az webapp deploy --type zip` which goes through the ARM management plane.

### Deployment Pattern

```bash
# 1. Create deployment zip (excludes dev files)
zip -r /tmp/nextgen-deploy.zip . \
  -x '.git/*' '.venv/*' '__pycache__/*' '*/__pycache__/*' \
     '*.pyc' '.env' '.env.*' 'node_modules/*' 'logs/*' \
     '.DS_Store' 'student_documents/*' 'uploads/*' 'testing/*'

# 2. Deploy to Production
# Unlock SCM
az webapp config access-restriction set -g NextGen_Agents \
  -n nextgen-agents-web --use-same-restrictions-for-scm-site false

# Deploy
az webapp deploy -g NextGen_Agents -n nextgen-agents-web \
  --src-path /tmp/nextgen-deploy.zip --type zip

# Re-lock SCM
az webapp config access-restriction set -g NextGen_Agents \
  -n nextgen-agents-web --use-same-restrictions-for-scm-site true

# 3. Deploy to Staging (same pattern with --slot staging)
az webapp config access-restriction set -g NextGen_Agents \
  -n nextgen-agents-web --slot staging --use-same-restrictions-for-scm-site false
az webapp deploy -g NextGen_Agents -n nextgen-agents-web --slot staging \
  --src-path /tmp/nextgen-deploy.zip --type zip
az webapp config access-restriction set -g NextGen_Agents \
  -n nextgen-agents-web --slot staging --use-same-restrictions-for-scm-site true
```

### CI/CD

GitHub Actions workflow at `.github/workflows/deploy-to-azure.yml` uses Azure OIDC authentication. Required GitHub Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.

---

## 🧪 Testing

### Real-Time Test System (`/test`)
Run the full 9-step pipeline with live agent progress tracking:
- 🚀 **Random Students** — Generate synthetic data each run
- ⚡ **Preset Students** — Fixed test data (Alice, Brian, Carol)
- ⚡ **Single Student** — Quick single-student test
- 🗑️ **Clear Test Data** — Remove all test students

### Test Data Generator
```python
from src.test_data_generator import test_data_generator

# Generate batch
students = test_data_generator.generate_batch(count=5)

# Specific grade levels (realistic birthdates for June 2026)
senior = test_data_generator.generate_student(grade_level=12)   # Born 2007-2008
junior = test_data_generator.generate_student(grade_level=11)   # Born 2008-2009
sophomore = test_data_generator.generate_student(grade_level=10) # Born 2009-2010
```

### Command-Line Testing
```bash
python testing/test_smee.py       # Test orchestrator
python testing/test_agent.py      # Test file upload handler
```

---

## 🔐 Security

### Zero Plaintext Credentials
- ✅ All secrets in Azure Key Vault with enterprise-grade encryption
- ✅ No `.env` files in Git (`.gitignore` enforced)
- ✅ No hardcoded credentials anywhere in code
- ✅ Managed Identity for Azure service authentication
- ✅ TLS/SSL everywhere via Front Door
- ✅ SCM basic auth disabled — deployments use ARM management plane
- ✅ WAF policy in Prevention mode with DRS 2.1 + Bot Manager 1.1
- ✅ Front Door ID validation on App Service (rejects direct access)
- ✅ Audit trail for all operations

### Key Vault Secrets
| Category | Secrets |
|----------|---------|
| PostgreSQL | `postgres-host`, `postgres-port`, `postgres-database`, `postgres-username`, `postgres-password` |
| Azure OpenAI | `azure-openai-endpoint`, `azure-deployment-name`, `azure-api-version` |
| Application | `flask-secret-key` (auto-generated) |
| Azure | `azure-subscription-id`, `azure-resource-group` |

---

## � Evaluating the Milo Model

Milo (Data Scientist) builds ML models from historical training data and uses them to predict applicant outcomes. To evaluate model accuracy:

### 1. Import Training Data
Upload historical applications (PDF/DOCX) via the **Training** page, then import actual outcomes using **Import Historical Scores** (XLSX). Each training record needs both the application documents and the known result (Selected/Not Selected).

### 2. Run Model Validation
Navigate to **Training → Milo Insights → Validate Model**. This runs every training student through Milo's current model and compares the AI prediction against the known outcome. The validation runs asynchronously (file-based state for multi-worker compatibility) and produces:

- **Confusion Matrix** — True positives, false positives, true negatives, false negatives
- **Accuracy, Precision, Recall, F1 Score** — Standard classification metrics
- **Per-Student Results** — Each student's predicted vs. actual outcome with confidence score
- **Misclassification Analysis** — Which students were predicted incorrectly and why

### 3. Generate Rankings
Use **Training → Milo Insights → Generate Rankings** to rank all 2026 applicants using the trained model. Rankings include a predicted outcome, confidence score, and key factors.

### API Endpoints
```bash
# Start validation (async)
POST /api/milo/validate

# Poll validation progress/results
GET /api/milo/validate

# Generate applicant rankings
POST /api/milo/rank
```

### Improving Model Accuracy
- **More training data** — Upload additional historical applications
- **Better outcomes data** — Import accurate XLSX scores with clear Selected/Not Selected labels
- **Reprocess documents** — Use **Training → Reprocess All** to re-extract training documents through the latest Belle pipeline
- **Check diagnostics** — Use **Training → Diagnostic** to verify field extraction quality across all training records

---

## �📈 Observability

### OpenTelemetry Integration
The application uses `azure-monitor-opentelemetry` for automatic instrumentation of Flask, requests, and psycopg2. Agent-level telemetry tracks:
- Token usage per agent per request
- Agent execution duration
- Model deployment utilization
- Error rates and retry counts

### Telemetry Dashboard (`/telemetry`)
Real-time metrics with 30-second auto-refresh: Application Insights connection status, agent performance, and school pipeline status.

### Agent Monitor (`/agent-monitor`)
Standalone terminal-style debugging interface for real-time agent execution monitoring.

---

## 📚 Additional Documentation

### Core
- [WORKFLOW_MAP.md](WORKFLOW_MAP.md) — 9-step workflow visualization with data flows
- [README_WORKFLOW.md](README_WORKFLOW.md) — User-focused workflow guide
- [AGENT_ARCHITECTURE_DETAILED.md](AGENT_ARCHITECTURE_DETAILED.md) — Agent implementation details

### Setup & Configuration
- [documents/setup/SETUP_GUIDE_MANUAL.md](documents/setup/SETUP_GUIDE_MANUAL.md) — Manual setup guide
- [documents/setup/KEY_VAULT_SETUP.md](documents/setup/KEY_VAULT_SETUP.md) — Key Vault configuration
- [documents/setup/POSTGRESQL_KEYVAULT_SETUP.md](documents/setup/POSTGRESQL_KEYVAULT_SETUP.md) — PostgreSQL + Key Vault

### Deployment
- [documents/deployment/AZURE_WEBAPP_DEPLOY.md](documents/deployment/AZURE_WEBAPP_DEPLOY.md) — Production deployment guide
- [documents/deployment/DEPLOYMENT_CHECKLIST.md](documents/deployment/DEPLOYMENT_CHECKLIST.md) — Pre-deployment verification

### Security
- [documents/security/SECURITY_GUIDE.md](documents/security/SECURITY_GUIDE.md) — Security best practices
- [documents/security/SECURITY_AND_EFFICIENCY_AUDIT.md](documents/security/SECURITY_AND_EFFICIENCY_AUDIT.md) — Compliance audit

---

## 🛠️ Troubleshooting

**Database connection issues:**
- Verify PostgreSQL credentials in Key Vault or `.env.local`
- Test: `python -c "from src.database import Database; db = Database(); print('OK')"`

**AI evaluation errors:**
- Ensure Azure OpenAI resource is accessible
- Check deployment names match tier config in `src/config.py`
- Verify `Cognitive Services OpenAI User` role is assigned

**Key Vault access:**
- Run `az login` to authenticate
- Verify `Reader` + `Key Vault Secrets User` roles
- Check: `az keyvault show --name your-keyvault-name`

**Application Insights not showing data:**
- Ensure `APPLICATIONINSIGHTS_CONNECTION_STRING` is set
- Wait 5–10 minutes for telemetry propagation
- Set `NEXTGEN_CAPTURE_PROMPTS=true` for detailed logging

**Video upload fails:**
- Upload uses 100KB chunked transfer (WAF 128KB body limit)
- Check Front Door WAF logs for blocked requests
- Ensure `opencv-python-headless` is installed for Mirabel

---

## 🏗️ Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| **9-Step Workflow** | Stages agents by dependency, enables validation gates, supports remediation loops, audit-friendly |
| **Composite Key Matching** | Prevents duplicates, enables re-evaluation, handles multi-school scenarios |
| **Contextual Rigor (RAPUNZEL)** | Fair assessment across school types — adjusts for AP/Honors availability and opportunity |
| **Contextual Narratives (MOANA)** | AI-powered narratives using NCES data + Naveen evaluation to contextualize student records |
| **4-Tier Models** | Cost optimization — use expensive models only for complex tasks, lightweight for simple extraction |
| **Front Door + WAF** | Enterprise DDoS protection without EasyAuth complexity |
| **ARM Zip Deploy** | Works with SCM basic auth disabled and Front Door blocking SCM |

---

## 📝 License & Support

Requires:
- Azure subscription (OpenAI, Key Vault, PostgreSQL, Front Door)
- GitHub account (CI/CD, feedback issues)
- Python 3.12+ (3.9+ compatible)

For support, see documentation in the `/documents` directory.
