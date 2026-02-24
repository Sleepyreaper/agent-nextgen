# 🎭 Multi-Agent Student Evaluation System

> **Production-Ready AI Evaluation Pipeline** with comprehensive audit trails, intelligent student matching, and fairness-aware assessment.

An intelligent multi-agent system that evaluates student applications using specialized Disney-themed agents working in a coordinated 9-step workflow.

---

## 🎯 Key Features

### **Core Capabilities**
- ✅ **9-Step Intelligent Workflow**: Orchestrated multi-agent evaluation with decision gates and remediation loops
- ✅ **Multi-Agent Team**: 9 specialized agents with distinct roles and expertise
- ✅ **AI-Powered Extraction**: BELLE extracts structured data from any document format
- ✅ **Student Matching**: Composite key matching (name + school + state) prevents duplicates
- ✅ **School Context Analysis**: NAVEEN + MOANA bidirectional validation for fair assessment
- ✅ **Contextual Rigor Weighting**: RAPUNZEL calculates academic rigor adjusted by school opportunity
- ✅ **Validation Gates**: Per-agent readiness verification with reactive BELLE extraction
- ✅ **File Upload Matching**: AI-based student identification with confidence scoring
- ✅ **Unlimited Re-Evaluations**: More data sources = more accurate assessments
- ✅ **Comprehensive Audit Trail**: 14 interaction types logged to database for compliance
- ✅ **File Matching Audit**: Human-reviewable logs of AI student matching decisions
- ✅ **Pause/Resume Capability**: Workflows pause when documents needed, resume with new data
- ✅ **Web Interface**: Modern Flask app for uploads and result visualization
- ✅ **Secure by Default**: All credentials in Azure Key Vault

---

## 🦸 Disney Agent Team

### **The 9-Step Workflow**

```
1️⃣ BELLE (Document Analyzer)
   └─ Extracts structured data from documents

2️⃣ Student Matching
   └─ Prevents duplicates via composite key lookup

2️⃣➕ High School Pre-Enrichment
   └─ Proactively enriches or looks up schools

3️⃣ NAVEEN (School Data Scientist)
   └─ Enriches school context (AP/Honors availability, opportunity score)

3️⃣➕ School Validation Loop (MOANA ↔ NAVEEN)
   └─ Bidirectional validation with up to 2 remediation attempts

4️⃣ Core Agents (with per-agent validation gates):
   ├─ TIANA (Application Reader)
   ├─ RAPUNZEL (Grade Reader with contextual rigor weighting)
   ├─ MOANA (School Context & Fairness Weighting)
   └─ MULAN (Recommendation Reader)

5️⃣ MILO (Data Scientist)
   └─ Analyzes training patterns and selection indicators

6️⃣ MERLIN (Student Evaluator)
   └─ Synthesizes all results into comprehensive assessment

7️⃣ AURORA (Results Formatter)
   └─ Generates polished evaluation report
```

Each agent is a specialized expert:
- **Belle**: Document understanding & information extraction
- **TIANA**: Application essay analysis & communication assessment
- **RAPUNZEL**: Academic performance with **contextual rigor scoring (0-5 scale based on school resources)**
- **MOANA**: School opportunity analysis & **fairness-aware weighting**
- **MULAN**: Recommendation letter synthesis
- **MERLIN**: Overall recommendation & rationale
- **AURORA**: Executive summary & report formatting
- **MILO**: Training data insights & pattern detection
- **NAVEEN**: School enrichment & research

---

## 🏗️ Workflow Architecture

### **9-Step Process with Decision Gates**

See [WORKFLOW_MAP.md](WORKFLOW_MAP.md) for complete visual workflow and data flows.

**Key Features:**

#### **Step 2: Smart Student Matching**
- Composite key: `first_name + last_name + high_school + state_code`
- Prevents duplicate records
- Enables re-evaluation with new files

#### **Step 2.5: Proactive High School Enrichment**
- Checks if school exists in cached database
- If not cached: calls NAVEEN to pre-enrich before validation loop
- Reduces validation loop failures

#### **Steps 3-3.5: Bidirectional School Validation**
- **NAVEEN**: Enriches with AP courses, honors programs, opportunity score
- **MOANA**: Validates against 7 required fields
- **Remediation Loop**: Up to 2 NAVEEN re-calls with targeted context
- **Outcome**: Either school is validated &✅ OR workflow pauses for user docs

#### **Steps 4-4.5: Core Agents with Validation Gates**
- **Per-Agent Gate #1**: Check if required data exists
  - If missing: Reactively call BELLE to extract
- **Per-Agent Gate #2**: Still missing?
  - If yes: Pause workflow, ask user for documents
  - If no: Execute agent
- **RAPUNZEL Special**: Calculates **contextual_rigor_index (0-5 scale)**
  - Base rigor from GPA
  - Adjusted by school's AP/Honors availability
  - Weighted by student's opportunity score
  - Used by MERLIN for fair assessment

#### **Step 5-7: Synthesis & Reporting**
- **MILO**: Analyzes patterns vs. outcomes
- **MERLIN**: Aggregates with fairness adjustments
- **AURORA**: Formats into readable report

### **File Upload Handler (Phase 5b)**
- **AI-Based Student Matching**: Extracts student info from file
- **Confidence Scoring**: 0-1 scale matching confidence
- **Smart Matching Decision**: 
  - ✅ If confidence ≥ 0.8: Add to existing student folder
  - ❌ If confidence < 0.8: Create new student record
- **Unlimited Re-Evaluations**: Every new file triggers fresh 9-step workflow
- **Audit Trail**: Human-reviewable file matching decisions

---

## 📊 Database Schema (PHASE 5 Updates)

### **Core Tables**

**applications**
- `application_id` (PK)
- Student demographics: `first_name`, `last_name`, `high_school`, `state_code`
- Document text: `application_text`, `transcript_text`, `recommendation_text`
- Status tracking: `status`, `uploaded_date`, `for_re_evaluation`

**student_school_context** / **school_enriched_data**
- `school_enrichment_id` (PK)
- School data: `school_name`, `state_code`, `school_district`
- Opportunity metrics: `opportunity_score` (0-100)
- MOANA validation: `moana_requirements_met`, `last_moana_validation`
- AP/Honors: `ap_course_list`, `honors_program_list`
- 7 required fields for MOANA validation

**rapunzel_grades** (Phase 4 Update)
- `grade_id` (PK), `application_id` (FK)
- Academic data: `gpa`, `trend`, `rigor`
- **NEW**: `contextual_rigor_index` (0-5 scale)
- **NEW**: `school_context_used` (boolean)
- **NEW**: `school_name` (for context reference)

### **Audit & Compliance Tables**

**agent_interactions** (Phase 5a - Comprehensive Logging)
- Logs every agent execution with:
  - `interaction_type`: 14 types covering all 9 steps
  - `extracted_data`: Full JSONB output
  - `timestamp`: When interaction occurred
- Used for audit trails, debugging, compliance

**file_upload_audit** (Phase 5b - AI Matching Audit)
- `audit_id` (PK)
- **Extracted Info**: `extracted_first_name`, `extracted_last_name`, etc.
- **Extraction Confidence**: confidence score
- **Matching Decision**: `ai_match_confidence`, `match_status`
- **Human Review**: `human_reviewed`, `human_review_approved`, `reviewed_by`
- **Audit Ready**: All fields ready for human verification

---

## 🚀 Quick Start

### **1. Install & Configure**

```bash
# Clone repository
cd "Agent NextGen"

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure Azure & Key Vault (first time)
az login
./scripts/setup/keyvault_setup.sh

# Initialize database with schema
python scripts/init/init_database.py
```

### **2. Set Environment Variables**

```bash
# Create .env from template
cp .env.example .env.local

# Add your credentials (or use Key Vault for production)
export AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
export OPENAI_API_KEY=your-key
export OPENAI_MODEL_DEPLOYMENT=your-deployment-name
```

### **3. Run Application**

```bash
# Start web server
python app.py

# Or start with multi-agent system directly
python main.py
```

Visit: http://localhost:5001

---

## 📈 Workflow Examples

### **Example 1: First-Time Student Upload**
```
File: student_essay.pdf

STEP 1: BELLE extracts name, school, GPA
STEP 2: No matching student → CREATE new record (ID: 1001)
STEP 2.5: Look up school → Not in cache → NAVEEN enriches
STEP 3: NAVEEN enriches school data
STEP 3.5: MOANA validates → ✅ Passes
STEP 4: Core agents analyze (4 agents, ~40 sec)
STEP 4.5: All data ready ✅
STEP 5: MILO analyzes patterns
STEP 6: MERLIN synthesizes (contextual rigor applied)
STEP 7: AURORA generates report

RESULT: Complete evaluation in ~90 seconds
AUDIT: 14 interactions logged to database
```

### **Example 2: Re-Evaluation with New File**
```
File: student_transcript.pdf (for existing student ID: 1001)

FILE UPLOAD HANDLER:
  ├─ Extract name from file: "John Smith"
  ├─ Query existing students
  ├─ AI match: "John Smith" + "Lincoln High" from existing record
  ├─ Confidence: 0.94 ✅ (> 0.8 threshold)
  └─ ACTION: Add to existing student, mark for re-evaluation

FILE MATCHING AUDIT:
  ├─ audit_id: 5432
  ├─ extracted_first_name: "John"
  ├─ ai_match_confidence: 0.94
  ├─ match_status: "matched_existing"
  └─ Ready for human review: YES

NEW EVALUATION:
  ├─ Step 1: BELLE re-extracts from all 2 files
  ├─ Steps 2-7: Full workflow with more data
  └─ Result: Fresh perspective with 2 document sources

AUDIT: "file_upload" interaction logged + full 9-step logs
```

### **Example 3: Validation Gate Failure**
```
STEP 4.5 Validation Gate (RAPUNZEL):
  ├─ RAPUNZEL needs: transcript_text
  ├─ Check: NOT found
  ├─ Action: Reactively call BELLE
  │         "Extract: academic transcript data"
  ├─ Retry validation gate
  │
  ├─ Still missing?
  │ ├─ YES → Log "pause_for_documents"
  │ ├─ Pause workflow
  │ └─ Wait for user to upload transcript
  │
  └─ NO → Continue to Step 5

AUDIT: Both attempts logged
  ├─ step_4_5_validation (gate 1 failure)
  ├─ step_4_5_validation (gate 2 failure)
  └─ pause_for_documents (user action needed)

USER UPLOADS TRANSCRIPT:
  ├─ File upload handler matches to student
  ├─ Marks for re-evaluation
  └─ Workflow restarts from Step 1
```

---

## 🔐 Security & Compliance

### **Audit Trail Coverage**
Every workflow step generates standardized logs:

| Step | Interactions Logged | Audit Info |
|------|-------------------|-----------|
| 1 | BELLE extraction | File metadata + extracted data |
| 2 | Student matching | Action (created/matched) |
| 2.5 | School check | Status + enrichment ID |
| 3 | NAVEEN enrichment | Full enrichment + opportunity score |
| 3.5 | Validation loop | Each attempt + remediation |
| 4-4.5 | Agent validation + execution | Readiness checks + results |
| 5 | MILO analysis | Analysis results |
| 6 | MERLIN synthesis | Synthesis results |
| 7 | AURORA report | Report sections |
| Pauses | User pauses | Reason + missing data |

### **File Matching Audit**
For every file upload:
- Extracted student info captured
- AI matching confidence logged
- Match decision tracked
- Human review fields provided
- All data ready for compliance audit

### **Data Protection**
- ✅ All credentials in Azure Key Vault
- ✅ Database encryption at rest
- ✅ Audit logs never deleted
- ✅ Human review trails retained
- ✅ No plaintext secrets in code

---

## 🧪 Testing the Workflow

### **Test File 1: Application Essay Only**
```bash
python -c "
from src.agents.smee_orchestrator import SmeeOrchestrator
# Should: Extract from essay, pause for transcript at Step 4.5
"
```

### **Test File 2: Complete Application (Pause Expected)**
```bash
python -c "
from src.agents.smee_orchestrator import SmeeOrchestrator
# Should: Validate school, extract all data, complete workflow
# If school not in DB: Will pause at Step 3.5 for school docs
"
```

### **Test File 3: File Upload Matching**
```bash
curl -X POST http://localhost:5001/upload \
  -F "file=@student_essay.pdf" \
  -F "student_context=Jane Doe from Lincoln High"
# Should: Return audit_id and match_confidence
```

---

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| [WORKFLOW_MAP.md](WORKFLOW_MAP.md) | **Complete 9-step workflow with data flows** |
| [AGENT_ARCHITECTURE_DETAILED.md](AGENT_ARCHITECTURE_DETAILED.md) | Agent implementation details |
| [CODE_REFACTORING_PLAN.md](CODE_REFACTORING_PLAN.md) | Phase 1-5 implementation history |
| [API_QUICK_REFERENCE.md](API_QUICK_REFERENCE.md) | API endpoint documentation |

---

## 🛠️ Development

### **Running Tests**
```bash
# Full workflow test
python testing/test_workf low.py

# File upload matching test
python testing/test_file_upload_handler.py

# Database schema test
python testing/test_database_schema.py
```

### **Database Migrations**
```bash
# Apply all schema updates
psql postgresql://user@host/dbname < database/schema_postgresql.sql

# Apply Phase 5 audit tables
psql postgresql://user@host/dbname < database/schema_postgresql.sql
```

---

## 📊 Performance

| Component | Typical Time |
|-----------|-------------|
| BELLE extraction (Step 1) | 5-10 sec |
| Student matching (Step 2) | <1 sec |
| School enrichment (Step 3) | 10-15 sec |
| School validation (Step 3.5) | 5-30 sec |
| Core agents (Step 4) | 20-40 sec |
| MILO analysis (Step 5) | 5-10 sec |
| MERLIN synthesis (Step 6) | 10-15 sec |
| AURORA report (Step 7) | 2-5 sec |
| **Total** | **60-150 sec** |

---

## 🐛 Troubleshooting

### **Workflow Paused Unexpectedly**
Check `agent_interactions` table:
```sql
SELECT * FROM agent_interactions 
WHERE application_id = 1001 
AND interaction_type = 'pause_for_documents'
ORDER BY timestamp DESC LIMIT 1;
```

### **File Upload Not Matching**
Check `file_upload_audit` table:
```sql
SELECT * FROM file_upload_audit
WHERE uploaded_date > NOW() - interval '1 hour'
AND ai_match_confidence < 0.8
ORDER BY upload_date DESC;
```

### **School Validation Failing**
Check school enrichment data:
```sql
SELECT school_enrichment_id, school_name, moana_requirements_met 
FROM school_enriched_data 
WHERE moana_requirements_met = FALSE;
```

---

## 📞 Support

- 🐛 **Bugs**: Check logs at `logs/app.log`
- 📋 **Audit Trail**: Query `agent_interactions` table
- 📁 **File Matching**: Query `file_upload_audit` table
- 🔧 **Configuration**: Use Azure Key Vault (never commit `.env` files)

---

## 📄 License

Proprietary - All rights reserved

---

## 🙏 Acknowledgments

Built with:
- Azure OpenAI for AI capabilities
- PostgreSQL for reliable data storage
- Python ecosystem for agent implementation
- Disney theme for memorable agent personalities

