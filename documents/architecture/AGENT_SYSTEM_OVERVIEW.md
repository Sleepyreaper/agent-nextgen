# Agent System - Complete Overview

**Last Updated**: March 2026  
**Status**: ✅ All 15 agents operational with 4-tier model architecture

---

## 🎭 Complete Agent List

### Main Application Evaluation Pipeline

| # | Disney Character | Class Name | Model Tier | Purpose |
|---|---|---|---|---|
| 1 | 👸 **Tiana** | `TianaApplicationReader` | Workhorse | Reads and extracts core application data |
| 2 | 💇 **Rapunzel** | `RapunzelGradeReader` | Premium | Analyzes transcripts and grade trends |
| 3 | 🌊 **Moana** | `MoanaSchoolContext` | Workhorse | AI-powered student school context narratives |
| 4 | 🗡️ **Mulan** | `MulanRecommendationReader` | Workhorse | Extracts recommendation letters |
| 5 | 🧙 **Merlin** | `MerlinStudentEvaluator` | Merlin | Final comprehensive evaluation and scoring |
| 6 | ✨ **Aurora** | `AuroraAgent` | N/A (local) | Formats final output |
| 7 | 🎭 **Gaston** | `GastonEvaluator` | Workhorse | Counter-evaluation and bias check |

### Support & Analysis Agents

| # | Disney Character | Class Name | Model Tier | Purpose |
|---|---|---|---|---|
| 8 | 📖 **Belle** | `BelleDocumentAnalyzer` | Lightweight | PDF/DOCX parsing, AI section detection, OCR |
| 9 | 🔍 **Milo** | `MiloDataScientist` | Premium | ML training, validation, ranking |
| 10 | 🏰 **Naveen** | `NaveenSchoolDataScientist` | Workhorse | NCES database school evaluation & component scoring |
| 11 | 🧜 **Ariel** | `ArielQAAgent` | Workhorse | Conversational Q&A over student data |
| 12 | 🌺 **Mirabel** | `MirabelVideoAnalyzer` | Vision | Video submission analysis (frame + audio) |
| 13 | 😊 **Bashful** | `BashfulAgent` | Workhorse | Agent output summarization |
| 14 | 📬 **FeedbackTriage** | `FeedbackTriageAgent` | Lightweight | User feedback routing |
| 15 | 🧚 **Fairy Godmother** | `FairyGodmotherDocumentGenerator` | N/A (programmatic) | Document generation |

---

## 🚀 4-Tier Model Architecture

| Tier | Default Deployment | Config Key | Agents |
|------|-------------------|------------|--------|
| **Premium** | `gpt-4.1` | `model_tier_premium` | Rapunzel, Milo |
| **Merlin** | `MerlinGPT5Mini` | `model_tier_merlin` | Merlin |
| **Workhorse** | `WorkForce4.1mini` | `model_tier_workhorse` | Tiana, Mulan, Moana, Gaston, Ariel, Naveen, Bashful |
| **Lightweight** | `LightWork5Nano` | `model_tier_lightweight` | Belle, FeedbackTriage |
| **Vision** | `gpt-4o` | `foundry_vision_model_name` | Mirabel, Belle OCR fallback |

### Tier Selection Rationale

- **Premium**: Tasks requiring deep reasoning — transcript analysis, ML code generation
- **Merlin**: Dedicated tier for final evaluation (independent scaling and tuning)
- **Workhorse**: Balanced cost/performance for most agent tasks
- **Lightweight**: High-volume, simpler tasks — document classification, feedback routing
- **Vision**: Multimodal tasks — video frame analysis, scanned page OCR

---

## 📋 Model Information in Outputs

All agents include model metadata in their responses:

```json
{
  "status": "success",
  "agent_name": "Milo Data Scientist",
  "model_used": "gpt-4.1",
  "model_display": "gpt-4.1",
  "analysis": {}
}
```

---

## 🔧 Configuration

### In Key Vault (`nextgen-agents-kv`) or Environment:

```
MODEL_TIER_PREMIUM=gpt-4.1
MODEL_TIER_MERLIN=MerlinGPT5Mini
MODEL_TIER_WORKHORSE=WorkForce4.1mini
MODEL_TIER_LIGHTWEIGHT=LightWork5Nano
FOUNDRY_VISION_MODEL_NAME=gpt-4o
AZURE_OPENAI_ENDPOINT=https://<foundry>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
```

### In `src/config.py`:

```python
self.model_tier_premium = self._get_secret("model-tier-premium", "MODEL_TIER_PREMIUM") or "gpt-4.1"
self.model_tier_merlin = self._get_secret("model-tier-merlin", "MODEL_TIER_MERLIN") or "MerlinGPT5Mini"
self.model_tier_workhorse = self._get_secret("model-tier-workhorse", "MODEL_TIER_WORKHORSE") or "WorkForce4.1mini"
self.model_tier_lightweight = self._get_secret("model-tier-lightweight", "MODEL_TIER_LIGHTWEIGHT") or "LightWork5Nano"
```

Each agent selects its model via: `self.model = model or config.model_tier_<tier> or config.foundry_model_name or config.deployment_name`

---

## 🎯 Agent Specialization Matrix

| Operation | Agent | Tier | Why |
|-----------|-------|------|-----|
| **Parse uploaded documents** | Belle | Lightweight | High-volume, classification + OCR |
| **Read application metadata** | Tiana | Workhorse | Structured extraction |
| **Parse complex transcripts** | Rapunzel | Premium | Complex document reasoning |
| **School context analysis** | Moana | Workhorse | AI-powered contextual narratives |
| **Extract recommendations** | Mulan | Workhorse | Letter analysis |
| **Final scoring decision** | Merlin | Merlin | Multi-factor comprehensive eval |
| **Counter-evaluation** | Gaston | Workhorse | Bias detection |
| **ML training & validation** | Milo | Premium | Code generation, statistical analysis |
| **Q&A over student data** | Ariel | Workhorse | Conversational, 30s latency target |
| **Video analysis** | Mirabel | Vision | Frame extraction + GPT-4o vision |
| **Output summarization** | Bashful | Workhorse | Concise summaries |
| **Feedback routing** | FeedbackTriage | Lightweight | Fast categorization |
| **School enrichment** | Naveen | Workhorse | NCES data evaluation & scoring |
| **Document generation** | Fairy Godmother | Programmatic | Template-based |
| **Format results** | Aurora | Local | Formatting only |

---

## 🔑 Key Capabilities (v1.0.39)

### Belle Document Analyzer
- PDF/DOCX/TXT parsing with page-level section detection
- **AI fallback classification**: When keyword scoring < 3, uses GPT to classify pages
- **Sparse page handling**: Pages with 10-50 chars classified via AI
- **Vision OCR**: Scanned pages (<20 chars) rendered and processed through GPT-4o

### Milo Data Scientist
- **Training**: Builds ML models from historical evaluation data
- **Validation**: Async validation with confusion matrix, per-student metrics, file-based state for multi-worker compatibility
- **Ranking**: ML-based applicant ranking with recommendations

### Mirabel Video Analyzer
- Frame extraction from uploaded videos
- Audio transcription
- GPT-4o vision analysis of selected frames
- Combined visual + audio content assessment

### Ariel QA Agent
- Conversational Q&A over student evaluation data
- Context-aware responses using all agent outputs
- 30-second latency target

---

## 📊 Processing Pipeline

```
1. Belle (📖)     — Extract & classify document pages
2. Student Record  — Match or create student in database
3. School Enrichment — Naveen pre-enriches school if needed
4. Tiana (👸)      — Read application data          ┐
5. Rapunzel (💇)   — Analyze grades/transcript      │ Parallel
6. Moana (🌊)      — Enrich school context          │
7. Mulan (🗡️)      — Extract recommendations        ┘
8. Merlin (🧙)     — Comprehensive evaluation
9. Gaston (🎭)     — Counter-evaluation
10. Aurora (✨)     — Format final report
```

---

## 🎪 Disney Character Legend

**Application Analysis Pipeline:**
- 👸 **Tiana** — Reads applications (efficient, practical)
- 💇 **Rapunzel** — Analyzes grades (detail-oriented, precision)
- 🌊 **Moana** — Builds contextual narratives from NCES data + student records (adventurous, contextual)
- 🗡️ **Mulan** — Reads recommendations (bold, insightful)
- 🧙 **Merlin** — Makes final decisions (wise, evaluative)
- ✨ **Aurora** — Formats beautifully (elegant, polished)
- 🎭 **Gaston** — Counter-evaluates (strong alternative perspective)

**Support Agents:**
- 📖 **Belle** — Analyzes documents (learned, analytical)
- 🔍 **Milo** — Data science & ML (adventurous explorer — Atlantis)
- 🏰 **Naveen** — School evaluation from NCES database (sophisticated analyst)
- 🧜 **Ariel** — Q&A conversations (curious, communicative)
- 🌺 **Mirabel** — Video analysis (sees what others miss — Encanto)
- 😊 **Bashful** — Summarizes quietly (concise, modest)
- 📬 **FeedbackTriage** — Routes feedback (organized, efficient)
- 🧚 **Fairy Godmother** — Generates documents (magical, transformative)
