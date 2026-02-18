# Quick Reference: Agent Models & Telemetry

## Agent Model Summary (All Verified ✅)

```
STANDARD MODELS (10 agents using config.deployment_name = GPT-4)
┌─────────────────────────────────────────────────────────┐
│ • Smee (Orchestrator)                                   │
│ • Tiana (Application Reader)                            │
│ • Rapunzel (Grade Reader)                               │
│ • Moana (School Context)                                │
│ • Mulan (Recommendation Reader)                         │
│ • Merlin (Student Evaluator)                            │
│ • Gaston (Evaluator)                                    │
│ • Belle (Document Analyzer)                             │
│ • Scuttle (Feedback Triage)                             │
│ • Bashful (Supporting Agent)                            │
└─────────────────────────────────────────────────────────┘

MINI MODELS (2 agents using config.deployment_name_mini = o4miniagent)
┌─────────────────────────────────────────────────────────┐
│ • Milo (Data Scientist)                                 │
│ • Naveen (School Data Scientist)                        │
└─────────────────────────────────────────────────────────┘

SPECIAL AGENTS (No LLM calls)
┌─────────────────────────────────────────────────────────┐
│ • Aurora (Result Formatter) - Template-based            │
│ • Fairy Godmother (Document Generator) - Template-based │
└─────────────────────────────────────────────────────────┘
```

## Telemetry Implementation Checklist

### Phase 1: Foundation (✅ DONE)
- [x] Create telemetry helpers module
- [x] Document existing telemetry
- [x] Create implementation guide
- [x] Update Belle agent (example)
- [x] Update Tiana agent (example)

### Phase 2: Core Agents
- [ ] Rapunzel (Grade Reader)
- [ ] Merlin (Student Evaluator)
- [ ] Moana (School Context)
- [ ] Mulan (Recommendation Reader)
- [ ] Gaston (Evaluator)
- [ ] Smee (Orchestrator)

### Phase 3: Data & Supporting
- [ ] Milo (Data Scientist)
- [ ] Naveen (School Data Scientist)
- [ ] Bashful (Supporting)
- [ ] Scuttle (Feedback Triage)
- [ ] Database module (`src/database.py`)
- [ ] Storage module (`src/storage.py`)

### Phase 4: Verification
- [ ] Test in development
- [ ] Verify Application Insights Agents view
- [ ] Check call graphs appear
- [ ] Confirm tool call metrics
- [ ] Document results

## Telemetry Helpers API

```python
from src.agents.telemetry_helpers import agent_run, tool_call, lm_call

# Wrap an agent's execution
with agent_run(agent_name, action, {"key": "value"}):
    # Run agent logic
    # LLM calls automatically become child spans
    pass

# Track tool/function calls
with tool_call(tool_name, tool_type, {"input": "data"}):
    # Call database, storage, API, etc.
    result = some_operation()
    pass

# Alternative LLM tracking (if needed)
with lm_call(model, operation, system_prompt):
    response = client.chat.completions.create(...)
    pass
```

## Quick Implementation Pattern

```python
# 1. Import
from src.agents.telemetry_helpers import agent_run, tool_call

# 2. Wrap main method
async def my_agent_action(self, student_id):
    with agent_run(self.name, "my_agent_action", {"student_id": student_id}):
        # 3. Existing LLM call (auto-tracked as child span)
        response = self._create_chat_completion(...)
        
        # 4. Wrap database calls
        if self.db:
            with tool_call("save_analysis", "database", {"student_id": student_id}):
                self.db.save_my_analysis(...)
        
        return result
```

## Files to Update (Priority Order)

**P1 - High Traffic**:
1. Tiana (Application Reader) ✅ DONE
2. Rapunzel (Grade Reader) - 2-3 occurrences
3. Merlin (Student Evaluator) - 1-2 occurrences
4. Naveen (School Data Scientist) - 2-3 occurrences

**P2 - Data Persistence**:
5. `src/database.py` - All save_* methods (~15-20 methods)
6. `src/storage.py` - upload_file, download_file (~2 methods)

**P3 - Remaining Agents**:
7. Moana (School Context)
8. Mulan (Recommendation Reader)
9. Gaston (Evaluator)
10. Others as needed

## Testing the Implementation

```bash
# 1. Run agent normally
python main.py

# 2. Check Application Insights
# Navigate to: App Insights → Performance → Traces
# Filter for: dependency_type = "InProc" and name contains "agent.run"

# 3. Verify in Agents view
# Navigate to: App Insights → Usage → Users
# Or: Performance → Dependencies (if available)

# 4. Expected results
# - agent.run spans appear (parent spans)
# - tool.call spans appear (child spans)
# - Duration and success metrics visible
```

## Telemetry Attributes Created

**For agent_run():**
```
agent.id: "Tiana Application Reader"
agent.action: "parse_application"
agent.context.*: Context data passed in
agent.run.duration_ms: 2500
agent.run.success: true
```

**For tool_call():**
```
tool.name: "save_tiana_application"
tool.type: "database"
tool.input: {...}  # Sanitized
tool.call.duration_ms: 150
tool.success: true
```

## Application Insights Views After Implementation

### 1. Agents View (Once populated)
```
Tiana Application Reader
├─ parse_application (2500ms, ✓)
│  ├─ LLM call: 2000ms, 850 tokens
│  └─ DB tool: 150ms
│
More agent runs...
```

### 2. Metrics
```
Agent Runs: 47
Tool Calls: 156
DB Calls: 89
Storage Calls: 12
Success Rate: 97.5%
Avg Duration: 4.8s
```

### 3. Failures (When needed)
```
Failed Tool Calls: 2
├─ Naveen/analyze_school: DB timeout (3 retries)
└─ Storage/upload: Auth failure (1x)
```

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| No agent.run spans | Not wrapped | Add `with agent_run(...)` |
| No tool spans | Tools not tracked | Add `with tool_call(...)` |
| Spans orphaned | No parent span | Ensure agent_run wraps entire method |
| Tool input too large | Dict too big | Helpers auto-truncate to 1000 chars |
| Telemetry errors | Missing tracer | Helpers degrade gracefully |

## Reference Documents

1. **AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md**
   - Complete analysis of what's tracking and what's missing
   - Why agent runs and tool calls are important
   - Three implementation options

2. **TELEMETRY_IMPLEMENTATION_GUIDE.md**
   - Step-by-step implementation instructions
   - Code examples for all patterns
   - Database and storage instrumentation patterns
   - Testing procedures

3. **This File (Quick Reference)**
   - At-a-glance summary
   - Implementation checklist
   - Quick API reference
   - Common patterns

## Git Commits Related to This Work

```
Latest: docs: Add agent telemetry summary report
↑
feat: Add agent telemetry helpers and implementation guide
├─ src/agents/telemetry_helpers.py (NEW)
├─ AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md (NEW)
├─ TELEMETRY_IMPLEMENTATION_GUIDE.md (NEW)
├─ src/agents/belle_document_analyzer.py (UPDATED)
└─ src/agents/tiana_application_reader.py (UPDATED)
↑
Fix: Azure Storage authentication - prioritize account key over Azure AD
↑
Fix: agent initialization signature mismatches in Belle and Bashful
```

## Next Steps

1. Read [TELEMETRY_IMPLEMENTATION_GUIDE.md](../TELEMETRY_IMPLEMENTATION_GUIDE.md) for details
2. Copy the pattern from Belle or Tiana
3. Apply to next agent on P1 list
4. Test in development
5. Verify in Application Insights
6. Repeat for remaining agents

---

**Status**: Ready to implement  
**Effort**: ~2-3 hours for all agents  
**Risk**: None (helpers are self-contained)  
**Impact**: High (complete call graph visibility)
