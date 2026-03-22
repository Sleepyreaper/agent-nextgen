<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

## Next Gen Agents — AI Scholarship Evaluation Platform

### Mission
The purpose of this system is not to replicate human evaluation. It is to find the student the committee would miss. A "Diamond in the Rough" — the applicant whose contextual potential exceeds their raw metrics. The kid at the under-resourced school who maxed out every opportunity available to them, whose recommendation letter says what the transcript can't show. Traditional rubrics reward access and polish. This system exists to also reward resilience and potential. Every architectural decision, every agent prompt, every scoring algorithm should be evaluated against this mission: **does it help surface students who deserve a second look?**

Production Flask application (~8100 lines in `app.py`) that evaluates high-school scholarship applicants using 15+ Disney-themed AI agents backed by Azure AI Foundry. Deployed on Azure App Service with VNet + private endpoints and session-based authentication.

### Architecture

- **Entry point**: `app.py` (Flask, served by gunicorn via `startup.sh`)
- **Config**: `src/config.py` — loads secrets from Azure Key Vault, falls back to env vars
- **Database**: Azure PostgreSQL (schema in `database/schema_postgresql.sql`)
- **Storage**: Azure Blob Storage for student documents (PDFs, DOCX, videos)
- **Frontend**: Jinja2 templates in `web/templates/`, static assets in `web/static/`

### 4-Tier Model Architecture

| Tier | Default Deployment | Config Key | Used By |
|------|-------------------|------------|---------|
| Premium | `gpt-4.1` | `model_tier_premium` | Milo (data science) |
| Merlin | `MerlinGPT5Mini` | `model_tier_merlin` | Merlin (final evaluation) |
| Workhorse | `WorkForce4.1mini` | `model_tier_workhorse` | Rapunzel (grades), Belle (document analysis), Tiana, Mulan, Moana, Gaston, Ariel, Naveen, Bashful |
| Lightweight | `LightWork5Nano` | `model_tier_lightweight` | FeedbackTriage, inline classifiers |
| Vision | `gpt-4o` | `foundry_vision_model_name` | Mirabel (video), Belle OCR fallback |

### Agent Roster

| Agent | Class | Purpose |
|-------|-------|---------|
| Belle | `BelleDocumentAnalyzer` | PDF/DOCX parsing, section detection (AI fallback), OCR |
| Tiana | `TianaApplicationReader` | Application text extraction and scoring |
| Rapunzel | `RapunzelGradeReader` | Transcript/grade analysis |
| Mulan | `MulanRecommendationReader` | Recommendation letter analysis |
| Moana | `MoanaSchoolContext` | AI-powered student school context narratives using NCES data |
| Merlin | `MerlinStudentEvaluator` | Final comprehensive evaluation |
| Gaston | `GastonEvaluator` | Counter-evaluation and bias check |
| Aurora | `AuroraAgent` | Result formatting and presentation |
| Milo | `MiloDataScientist` | ML training, validation, ranking |
| Ariel | `ArielQAAgent` | Conversational Q&A over student data |
| Mirabel | `MirabelVideoAnalyzer` | Video submission analysis (frame + audio) |
| Naveen | `NaveenSchoolDataScientist` | NCES database school evaluation & component scoring |
| Pocahontas | `PocahontasCohortAnalyst` | Cross-school cohort analysis, equity tiers, context multipliers |
| Bashful | `BashfulAgent` | Agent output summarization |
| FeedbackTriage | `FeedbackTriageAgent` | User feedback routing |
| FairyGodmother | `FairyGodmotherDocumentGenerator` | Document generation |

### Key Files

- `app.py` — Flask application with all routes (~8100 lines)
- `src/config.py` — Configuration from Key Vault / env vars
- `src/agents/base_agent.py` — Abstract base class for all agents
- `src/agents/belle_document_analyzer.py` — Document analysis with AI section detection
- `src/agents/milo_data_scientist.py` — ML training, validation, and ranking
- `src/database.py` — PostgreSQL database operations
- `src/storage.py` — Azure Blob Storage operations
- `src/document_processor.py` — PDF/DOCX text extraction with OCR fallback
- `startup.sh` — Gunicorn launch script (4 workers, 2 threads, 600s timeout)
- `VERSION` — Current version number (1.0.45)

### School Data — Public Sources

School data is built entirely from **publicly available U.S. government datasets** — specifically the NCES Common Core of Data (CCD) published by the U.S. Department of Education. Multiple CCD datasets (school directory, enrollment, free/reduced lunch, district finance, staffing) are combined by NCES school ID, aggregated across school years, and uploaded as a merged CSV via the Training → Schools tab. Naveen and Moana then evaluate and enrich this public data locally — no proprietary data or runtime web calls are used.

### Key API Endpoints

- `POST /api/training/reprocess` — Re-extract all training documents (background task)
- `GET /api/training/reprocess` — Poll reprocessing progress
- `GET /api/training/diagnostic` — Field-size dashboard for training records
- `POST /api/milo/validate` — Start model validation (async, file-based state)
- `GET /api/milo/validate` — Poll validation progress/results
- `POST /api/milo/rank` — Generate ML-based applicant rankings
- `POST /login` — Session-based authentication

### Deployment

- **Production**: App Service (West US 2), gunicorn timeout 600s, platform LB timeout ~230s
- **Staging**: App Service staging slot
- **SCM**: Locked by default; unlock with `az webapp config access-restriction set ... --use-same-restrictions-for-scm-site false`, deploy via `az webapp deploy --type zip`, then re-lock
- **Git**: Branch `main`, pushed to GitHub

### Development Guidelines

- Extend `BaseAgent` to create new agents; add them in `src/agents/`
- Use `config.model_tier_*` properties for model selection (never hardcode deployment names)
- Use `src/logger.py` for structured logging with `get_logger()`
- All agent processing follows the `process(student_data)` async pattern
- Long-running operations use background threads + file-based polling (for multi-worker gunicorn compatibility)
- Test files live in `testing/`; scripts in `scripts/`
