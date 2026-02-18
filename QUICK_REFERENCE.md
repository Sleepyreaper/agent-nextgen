# 🎯 Quick Reference - Disney Agents & Models

## All 13 Agents at a Glance

### Pipeline Agents (Auto-executes in order)
```
👸 Tiana         → Reads app data        | GPT-4
💇 Rapunzel      → Analyzes transcript   | GPT-4
🌊 Moana         → School context ⭐    | GPT-4 (uses Naveen's enriched data)
🗡️  Mulan         → Recommendations      | GPT-4
🧙 Merlin        → Final evaluation      | GPT-4
✨ Aurora        → Formats output        | Local
💨 Smee          → Orchestrates all      | GPT-4
```

### Support Agents (On-demand)
```
🎭 Gaston        → Backup evaluation     | GPT-4
📖 Belle         → Document analysis     | GPT-4
🔍 Milo ⭐       → Pattern finder       | GPT-4.1 (mini - FAST)
🏰 Naveen ⭐    → School enrichment    | GPT-4.1 (mini - FAST)
🪶 Scuttle       → Feedback triage       | GPT-4
🧚 Fairy GodMa   → Doc generator         | Programmatic
```

**⭐ = New or Updated**

---

## Model Assignment - Simple

### Use Standard (GPT-4):
Tiana, Rapunzel, Moana, Mulan, Merlin, Belle, Gaston, Scuttle, Smee, Aurora

### Use Mini (GPT-4.1):
- **Milo** - `config.deployment_name_mini` 
- **Naveen** - `config.deployment_name_mini`

**Benefits of Mini:**
- ✅ Faster (pattern recognition, data aggregation)
- ✅ Lower cost
- ✅ Same quality for focused tasks

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

## School Enrichment Flow

```
1. User visits /schools dashboard
                ↓
2. Naveen (mini model) analyzes school
                ↓
3. Data stored with opportunity_score (0-100)
                ↓
4. Human reviews & approves
                ↓
5. Marked as "approved" in database
                ↓
6. Next student from that school:
   Moana checks enriched data FIRST
                ↓
7. Uses approved enriched data
   (better context → better evaluation)
```

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
# .env or Key Vault
AZURE_DEPLOYMENT_NAME=<your-gpt4>
AZURE_DEPLOYMENT_NAME_MINI=o4miniagent  # Optional, defaults to this

# In config.py (auto-loads both)
config.deployment_name       # Standard GPT-4
config.deployment_name_mini  # Mini (default: o4miniagent)
```

---

## Quick Commands

### Seed initial schools
```bash
python scripts/seed_schools.py
```

### Check agent assignments
```python
from src.agents import NaveenSchoolDataScientist, MiloDataScientist
naveen = NaveenSchoolDataScientist(model="o4miniagent")
milo = MiloDataScientist(model="o4miniagent")
print(f"Naveen: {naveen.model_display}")
print(f"Milo: {milo.model_display}")
```

### Verify models in foundry
```bash
# Standard model available?
curl https://<foundry>.openai.azure.com/deployments/<standard>/versions

# Mini model available?
curl https://<foundry>.openai.azure.com/deployments/o4miniagent/versions
```

---

## Files to Know

| File | Purpose |
|------|---------|
| `src/config.py` | Model configuration (both deployment names) |
| `src/database.py` | School enrichment DB methods |
| `app.py` | API routes for schools |
| `src/agents/milo_data_scientist.py` | Pattern finder (mini model) |
| `src/agents/school_detail_data_scientist.py` | Now: NaveenSchoolDataScientist (mini model) |
| `src/agents/feedback_triage_agent.py` | Now: ScuttleFeedbackTriageAgent |
| `src/agents/moana_school_context.py` | Enhanced to use enriched data |
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

## Status Overview

✅ **School Enrichment System**: Complete (database + API + dashboard)
✅ **Disney Character Names**: All agents named
✅ **Model Assignments**: Standard (gpt-4) + Mini (gpt-4.1)
✅ **Model Metadata**: In all outputs
✅ **Moana Integration**: Queries enriched data
✅ **Backwards Compatibility**: Maintained
✅ **Documentation**: Comprehensive

---

**🚀 Ready to push when you give the signal!**
