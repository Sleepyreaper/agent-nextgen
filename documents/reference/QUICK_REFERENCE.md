# 🎯 Quick Reference - Disney Agents & Models

**Last Updated**: March 2, 2026 (v1.0.43)

## All 15 Agents at a Glance

### Pipeline Agents (Auto-executes in order)
```
📖 Belle          → Document extraction    | Lightweight (LightWork5Nano)
👸 Tiana         → Reads application       | Workhorse (WorkForce4.1mini)
👑 Rapunzel      → Transcript analysis     | Premium (gpt-4.1)
🌊 Moana         → School context narrative| Workhorse (uses Naveen + NCES data)
🥋 Mulan         → Recommendations         | Workhorse
📊 Milo          → Training data patterns  | Premium (gpt-4.1)
🧙 Merlin        → Final evaluation        | Merlin (MerlinGPT5Mini)
✨ Aurora        → Formats output          | Local (no model)
🎩 Smee          → Orchestrates all        | Workhorse
```

### Support Agents
```
🧑‍🔬 Naveen        → School evaluation       | Workhorse (NCES database records)
🎭 Gaston        → Counter-evaluation      | Workhorse
🧜 Ariel         → Student Q&A             | Workhorse
🌺 Mirabel       → Video analysis          | Vision (gpt-4o)
😊 Bashful       → Summarization           | Workhorse
📎 FeedbackTriage→ Feedback routing        | Lightweight
🧚 Fairy GodMa   → Doc generator           | Programmatic
```

---

## Model Tiers (4-Tier Architecture)

| Tier | Deployment | Used By |
|------|------------|---------|
| **Premium** | `gpt-4.1` | Rapunzel, Milo |
| **Merlin** | `MerlinGPT5Mini` | Merlin |
| **Workhorse** | `WorkForce4.1mini` | Tiana, Mulan, Moana, Gaston, Naveen, Ariel, Bashful |
| **Lightweight** | `LightWork5Nano` | Belle, FeedbackTriage |
| **Vision** | `gpt-4o` | Mirabel, Belle OCR fallback |

---

## Agent Output Includes

Every agent response now includes:
```json
{
  "agent_name": "Naveen School Data Scientist",
  "model_used": "o4miniagent",
  "model_display": "gpt-4.1",
  "results": {...}
}
```

---

## School Data Flow (Database-First)

```
1. Upload NCES CCD CSV via Training → Schools tab
                ↓
2. Schools matched/created in database (fuzzy match 0.55)
                ↓
3. Naveen evaluates NCES records → component scores + summary
                ↓
4. Human reviews & approves (optional)
                ↓
5. Student from that school is uploaded:
   Moana builds contextual narrative using Naveen + NCES + student data
                ↓
6. Narrative flows to Merlin for fair evaluation
```

**Key insight**: A 4.0 GPA at a school with 2 APs and 70% FRPL is categorically different from the same GPA at a school with 20 APs and 15% FRPL.

---

## Key URLs

| Route | Purpose |
|-------|---------|
| `/schools` | Dashboard view |
| `/api/schools/list` | Get schools (filterable) |
| `/api/school/<id>/review` | Submit human review |
| `/api/school/<id>/analyze` | Trigger re-analysis |

---

## Configuration

```python
# src/config.py (auto-loads from Key Vault or env vars)
config.model_tier_premium      # gpt-4.1
config.model_tier_merlin       # MerlinGPT5Mini
config.model_tier_workhorse    # WorkForce4.1mini
config.model_tier_lightweight  # LightWork5Nano
config.foundry_vision_model_name  # gpt-4o
```

---

## Quick Commands

### Import NCES school data
Upload a CCD CSV file via Training → Schools tab in the web UI.

### Run Milo validation
Training → Milo Insights → Validate Model (or `POST /api/milo/validate`)

### Generate rankings
Training → Milo Insights → Generate Rankings (or `POST /api/milo/rank`)

---

## Files to Know

| File | Purpose |
|------|---------|
| `src/config.py` | Model configuration (both deployment names) |
| `src/database.py` | School enrichment DB methods |
| `app.py` | API routes for schools |
| `src/agents/milo_data_scientist.py` | Pattern finder (mini model) |
| `src/agents/naveen_school_data_scientist.py` | School evaluation from NCES data |
| `src/agents/feedback_triage_agent.py` | Feedback triage and routing |
| `src/agents/moana_school_context.py` | AI-powered contextual narratives |
| `database/schema_school_enrichment.sql` | 7 tables for school data |
| `scripts/seed_schools.py` | Bootstrap schools |

---

## For New Team Members

**To understand the system:**
1. Read: `AGENT_SYSTEM_OVERVIEW.md` - See all agents
2. Read: `COMPLETE_IMPLEMENTATION_SUMMARY.md` - Big picture
3. Read: `API_QUICK_REFERENCE.md` - How to use APIs
4. Check: Code comments for Disney character names

**To use specific features:**
- School dashboard: See `/schools`
- API operations: See `API_QUICK_REFERENCE.md`
- Agent details: See `AGENT_SYSTEM_OVERVIEW.md`
- Model config: See `MODEL_AGENT_CONFIGURATION.md`

---

## Status Overview (v1.0.43)

✅ **School Data**: NCES CCD CSV import → database-first approach
✅ **Naveen**: AI evaluation of NCES records with component scores
✅ **Moana**: Contextual narratives from database + student data
✅ **4-Tier Models**: Premium, Merlin, Workhorse, Lightweight, Vision
✅ **Milo**: Training, validation, ranking with async processing
✅ **All 15 Agents**: Operational with Disney character names
✅ **Documentation**: Comprehensive and current
