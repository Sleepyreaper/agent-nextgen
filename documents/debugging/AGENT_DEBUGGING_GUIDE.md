# Agent Monitoring & Debugging Guide

## 🎯 Quick Start

### View Real-Time Agent Execution
1. **Open the real-time monitor**: Navigate to `http://localhost:5002/debug/agents`
2. **Auto-refresh enabled**: Dashboard updates every 2 seconds
3. **Watch Naveen execute**: When school enrichment is triggered, you'll see:
   - ⏳ "Running" status while Naveen works
   - ✅ "Completed" when done
   - ⚠️ Errors if something fails

### What You'll See
When you upload an application and the workflow processes it:

```
TIMELINE:
1. Tiana (Application Reader) → Reads application and extracts school name
2. Rapunzel (Grade Reader) → Parses GPA and transcript
3. [SCHOOL ENRICHMENT TRIGGERED]
4. Naveen (School Data Scientist) → Analyzes the school (THIS IS WHAT WAS HIDDEN!)
5. Moana (School Context) → Uses Naveen's data to understand student's context
6. Merlin (Student Evaluator) → Final evaluation
```

---

## 📊 Dashboard Features

### Metrics Section (Top)
- **Total Agent Calls**: Cumulative count of all agent executions
- **Currently Running**: Number of agents actively executing right now
- **Total Errors**: Count of agent failures
- **Avg Duration**: Average execution time across recent runs

### Currently Running Section
Shows cards for any agents actively executing:
```
┌─────────────────────────────┐
│ 🤖 Naveen (School Data Scientist)
│ ⏳ Running (2.3s elapsed)
│ Model: o4miniagent
│ ▓▓▓▓▓░░░░░░░░░ (progress animation)
└─────────────────────────────┘
```

### Recent Execution History Table
Shows the last 10 executions with:
| Agent | Status | Duration | Model | Timestamp | Details |
|-------|--------|----------|-------|-----------|---------|
| Naveen (School Data Scientist) | ✅ completed | 5,240ms | o4miniagent | 14:32:10 | ✓ |
| Tiana (Application Reader) | ✅ completed | 2,100ms | gpt-4 | 14:32:08 | ✓ |

---

## 🔍 Diagnosing Issues

### Scenario 1: Naveen Not Appearing
**Problem**: You don't see Naveen running in the monitor

**Diagnosis Steps**:
1. Check if school name was extracted by Tiana
   - Open `/debug/agents`
   - Look for Tiana in history
   - If Tiana shows errors → school extraction failed
   
2. Check if Moana is being skipped
   - In monitor, look for Moana's status
   - If "skipped" → no school name was available
   
3. Check application logs:
   ```bash
   # View recent logs
   tail -f logs/app.log | grep -i naveen
   ```

### Scenario 2: Naveen Appears But Hangs
**Problem**: Naveen shows "Running" for a very long time

**Diagnosis Steps**:
1. Check if it's genuinely slow (school analysis is complex)
   - Naveen typically takes 3-8 seconds
   - If > 30 seconds, likely stuck
   
2. Check Application Insights for timeout errors:
   - Look for Azure OpenAI timeout events
   - Check usage quotas
   
3. Check logs:
   ```bash
   grep -A 5 "Naveen\|school data scientist" logs/app.log
   ```

### Scenario 3: Naveen Shows Error
**Problem**: Naveen execution shows "❌ Failed" status

**Diagnosis Steps**:
1. Click the error message in the dashboard for details
2. Check detailed logs:
   ```bash
   grep -A 10 "Naveen" logs/app.log | grep -i error
   ```
3. Common issues:
   - Invalid school name → Naveen can't find information
   - Azure OpenAI not responding → Check quotas in Azure Portal
   - Database connection issues → Check PostgreSQL connection

---

## 🛠️ Advanced Debugging

### Test Naveen Directly
Create a test script to call Naveen and see detailed execution:

```python
# testing/test_naveen_direct.py
from src.config import config
from src.database import db
from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
from openai import AzureOpenAI

client = AzureOpenAI(
    api_key=config.api_key,
    api_version=config.api_version,
    azure_endpoint=config.endpoint
)

naveen = NaveenSchoolDataScientist(
    name="Naveen",
    client=client,
    model=config.deployment_name_mini,
    db_connection=db
)

# Test with a real school
result = naveen.analyze_school(
    school_name="Lincoln High School",
    state_code="CA"
)

print("✅ Result:", result)
```

### View Telemetry in Application Insights
1. Go to Azure Portal → Application Insights
2. Look at "Performance" → "Traces"
3. Filter by:
   - `cloudRoleName == "Naveen"` or
   - `messageName == "Naveen (School Data Scientist)"`
4. View:
   - Execution duration
   - LLM token usage
   - Errors and exceptions

### Clear History When Testing
If you want to start fresh:
1. Go to `/debug/agents`
2. Click "🗑️ Clear History"
3. Refresh your application workflow
4. Watch clean execution in the monitor

---

## 📈 Monitor URLs

| URL | Purpose |
|-----|---------|
| `/debug/agents` | **Main dashboard** - Real-time visual monitor |
| `/api/debug/agent-status` | JSON endpoint - Raw status data |
| `/api/debug/agent/<agent_name>/history?limit=50` | Agent-specific history |
| `/api/debug/agent-status/clear` | POST to reset execution history |

---

## 🎓 Understanding Agent Monitoring Logs

### Log Entry Example
```
→ Triggering Naveen (school data scientist) for new school enrichment
  school: Lincoln High School
  state: CA

[Naveen executes for 5.2 seconds...]

✓ Stored Naveen enrichment in database
  school: Lincoln High School
  id: 42
  opportunity_score: 78.5
```

### What Each Section Means
- **→** = Starting an agent
- **⏳** = In progress
- **✓** = Success
- **❌** = Error
- **⊘** = Skipped

---

##💡 Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| All agents missing | Monitor not initialized | Restart Flask app |
| Naveen not called | School name missing | Check Tiana's school extraction |
| Naveen hangs | LLM timeout or stuck | Check Azure OpenAI quota/status |
| No history showing | History cleared | Run workflow to generate new data |
| Telemetry not in App Insights | SDK not connected | Check APPLICATIONINSIGHTS_CONNECTION_STRING env var |

---

## 🚀 Next Steps After Debugging

Once you identify the issue:

1. **If Tiana (school extraction) failing**:
   - Check application_text quality
   - Review Tiana logs for parsing failures

2. **If Naveen (enrichment) failing**:
   - Test with different school names
   - Check Azure OpenAI quota
   - Review error message for specifics

3. **If Moana (context) failing**:
   - Ensure Naveen ran successfully first
   - Check if school_enrichment data is malformed

4. **If database saving failing**:
   - Verify PostgreSQL connection
   - Check schema for school_enriched_data table

---

## 🔗 Related Documentation
- [AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md](../AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md) - Complete model verification
- [TELEMETRY_IMPLEMENTATION_GUIDE.md](../TELEMETRY_IMPLEMENTATION_GUIDE.md) - How to add monitoring to other agents
- [src/agents/agent_monitor.py](../../src/agents/agent_monitor.py) - Monitor implementation
