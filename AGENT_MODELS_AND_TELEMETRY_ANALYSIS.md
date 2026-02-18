# Agent Models & Telemetry Analysis

**Status**: ✅ **All agents are correctly configured with proper models**  
**Date**: 2026-02-18

## 1. Model Configuration Review

### ✅ Current State: Model Assignments are CORRECT

Based on `AGENT_SYSTEM_OVERVIEW.md` specifications:

| Agent | Current Model | Correct Model | Status | Notes |
|-------|---------------|---------------|--------|-------|
| **Smee** (Orchestrator) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Tiana** (Application Reader) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Rapunzel** (Grade Reader) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Moana** (School Context) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Mulan** (Recommendation Reader) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Merlin** (Student Evaluator) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Gaston** (Evaluator) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Belle** (Document Analyzer) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Scuttle** (Feedback Triage) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Milo** (Data Scientist) | `config.deployment_name_mini` | GPT-4 mini (o4miniagent) | ✅ | Correct - uses mini model |
| **Naveen** (School Data Scientist) | `config.deployment_name_mini` | GPT-4 mini (o4miniagent) | ✅ | Correct - uses mini model |
| **Bashful** (Supporting Agent) | `config.deployment_name` | GPT-4 (standard) | ✅ | Correct - uses standard model |
| **Fairy Godmother** (Document Generator) | No client needed | Special (no LLM) | ✅ | Template-based, no model needed |
| **Aurora** (Result Formatter) | No client needed | Special (no LLM) | ✅ | Template-based, no model needed |

### Code Locations

**Model Registry** (app.py lines 135-260):
- All agents registered in `get_orchestrator()` function
- Model assignments verified against config:
  - Standard agents: `client=client, model=config.deployment_name`
  - Mini agents: `client=client, model=config.deployment_name_mini`

**Config Definition** (src/config.py lines 101-102):
```python
self.deployment_name: str = self._get_secret("azure-deployment-name", "AZURE_DEPLOYMENT_NAME")
self.deployment_name_mini: str = self._get_secret("azure-deployment-name-mini", "AZURE_DEPLOYMENT_NAME_MINI") or "o4miniagent"
```

## 2. Telemetry Tracking Analysis

### Current Telemetry Implementation ✅

**BaseAgent telemetry** (src/agents/base_agent.py lines 48-150):
- ✅ Agent name tracking (`span.set_attribute("agent.name", self.name)`)
- ✅ Model tracking (`span.set_attribute("gen_ai.model", model)`)
- ✅ Token usage tracking (input_tokens, output_tokens, total_tokens)
- ✅ Latency tracking (`gen_ai.latency_ms`)
- ✅ OpenTelemetry semantic conventions compliance
- ✅ Automatic span creation for LLM calls

### What IS Being Tracked

The system currently tracks:

1. **Per-LLM-Call Metrics** (every `_create_chat_completion` call):
   - ```
     - gen_ai.system: "azure_openai"
     - gen_ai.model: <model_name>
     - gen_ai.operation.name: "chat"
     - agent.name: <agent_name>
     - gen_ai.request.max_tokens: <max_tokens>
     - gen_ai.request.temperature: <temperature>
     - gen_ai.request.top_p: <top_p>
     - gen_ai.usage.prompt_tokens: <tokens>
     - gen_ai.usage.completion_tokens: <tokens>
     - gen_ai.usage.total_tokens: <tokens>
     - gen_ai.latency_ms: <duration>
     - gen_ai.response.id: <response_id>
   ```

2. **Span Names**:
   - Format: `chat_completion_{operation}` (e.g., `chat_completion_tiana.parse_application`)
   - Automatically created in ApplicationInsights

3. **Telemetry Events** (src/telemetry.py):
   - Custom event tracking via `NextGenTelemetry.track_event()`
   - Agent execution logging via `ngtelemetry.log_agent_execution()`

### What's NOT Being Tracked ❌

Based on user observation, the following are missing:

1. **"Agent Runs"** in Application Insights Agents view
   - ❌ No explicit `agent.runs` counter/metric
   - ❌ No dedicated "run" span type
   - ❌ Each LLM call creates a span, but these aren't aggregated as "runs"

2. **"Tool Calls"** metrics
   - ❌ No `tool.calls` or `function.calls` tracking
   - ❌ No semantic attributes for tools/functions used
   - ❌ Database operations not explicitly tagged as tool calls
   - ❌ File operations not tracked as tool use

### Why They're Missing

**Agent Runs:**
- Current spans track individual LLM calls, not the full agent execution
- Application Insights "Agents" view expects:
  - Span with `agent.id` and `span.kind = INTERNAL` (parent span)
  - Multiple child spans for tools/LLM calls
  - Aggregated metrics at the "run" level (not per-LLM-call)

**Tool Calls:**
- No database operations are wrapped in telemetry spans
- File uploads to Azure Storage not tracked
- No function call instrumentation
- Missing semantic conventions for:
  - `tool.calls` counter
  - `tool.name` attribute
  - `tool.success` or `tool.error` status

## 3. How to Populate Agent Runs & Tool Calls

### Option 1: Implement Proper Agent Run Tracking (RECOMMENDED)

**What needs to change:**

Each agent's main execution method should:

1. **Create a parent span** for the entire "run":
   ```python
   @property
   def identify_document_type(self, document: Dict[str, Any]) -> Dict[str, Any]:
       tracer = get_tracer()
       with tracer.start_as_current_span("agent.run", kind=SpanKind.INTERNAL) as parent_span:
           parent_span.set_attribute("agent.id", self.name)
           parent_span.set_attribute("agent.action", "identify_document_type")
           parent_span.set_attribute("agent.run.start_time", time.time())
           
           # ... agent logic here ...
           # Each LLM call will be a child span automatically
           
           parent_span.set_attribute("agent.run.end_time", time.time())
           parent_span.set_attribute("agent.run.success", True)
   ```

2. **Track tool/function calls**:
   ```python
   # When calling database
   with tracer.start_as_current_span("tool.call") as tool_span:
       tool_span.set_attribute("tool.name", "database_query")
       tool_span.set_attribute("tool.type", "database")
       result = self.db.save_belle_analysis(...)
       tool_span.set_attribute("tool.success", result.get("success", False))
   
   # When uploading file
   with tracer.start_as_current_span("tool.call") as tool_span:
       tool_span.set_attribute("tool.name", "upload_file")
       tool_span.set_attribute("tool.type", "storage")
       upload_result = storage.upload_file(...)
       tool_span.set_attribute("tool.success", upload_result.get("success", False))
   ```

### Option 2: Use Semantic Conventions Helper

Create a utility class for consistent telemetry:

```python
class AgentTelemetry:
    @staticmethod
    def record_agent_run(agent_name: str, action: str):
        """Context manager for agent runs"""
        tracer = get_tracer()
        return tracer.start_as_current_span(
            "agent.run",
            kind=SpanKind.INTERNAL,
            attributes={
                "agent.id": agent_name,
                "agent.action": action
            }
        )
    
    @staticmethod
    def record_tool_call(tool_name: str, tool_type: str):
        """Context manager for tool calls"""
        tracer = get_tracer()
        return tracer.start_as_current_span(
            "tool.call",
            attributes={
                "tool.name": tool_name,
                "tool.type": tool_type,
                "tool.success": False  # Updated in finally block
            }
        )
```

### Option 3: Instrument Database & Storage Modules

Add telemetry to `database.py` and `storage.py`:

```python
# In database.py
def save_belle_analysis(self, ...):
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.call") as span:
        span.set_attribute("tool.name", "save_belle_analysis")
        span.set_attribute("tool.type", "database")
        try:
            result = self._execute_query(...)
            span.set_attribute("tool.success", True)
            return result
        except Exception as e:
            span.set_attribute("tool.success", False)
            span.set_attribute("tool.error", str(e))
            raise

# In storage.py
def upload_file(self, ...):
    tracer = get_tracer()
    with tracer.start_as_current_span("tool.call") as span:
        span.set_attribute("tool.name", "upload_blob")
        span.set_attribute("tool.type", "storage")
        try:
            blob_client = container_client.upload_blob(...)
            span.set_attribute("tool.success", True)
            return {"success": True, ...}
        except Exception as e:
            span.set_attribute("tool.success", False)
            span.set_attribute("tool.error", str(e))
            return {"success": False, "error": str(e)}
```

## 4. Application Insights Visualization

### Current Behavior

**Agents View (Incomplete)**:
- Shows individual LLM calls as separate traces
- Each call appears as standalone span, not aggregated as "runs"
- Token counts visible per call, but not rolled up
- No tool usage data

### After Implementation

**Agents View (Complete)**:
```
Agent Runs:
├─ Agent: Tiana (Application Reader)
│  ├─ Run 1: parse_application
│  │  ├─ Tool: save_tiana_application (DB)
│  │  └─ Tool: chat_completion (LLM)
│  │       └─ Duration: 2.5s, Tokens: 850
│  └─ Run 2: parse_application
│
├─ Agent: Naveen (School Data Scientist)
│  ├─ Run 1: analyze_school
│  │  ├─ Tool: lookup_school_in_database (DB)
│  │  ├─ Tool: web_scraping (external)
│  │  ├─ Tool: upload_school_profile (Storage)
│  │  └─ Tool: chat_completion (LLM)
│  │       └─ Duration: 5.2s, Tokens: 1200
│  └─ Run 2: analyze_school
│
└─ Calls Metrics:
   ├─ Total Agent Runs: 47
   ├─ Tool Calls: 156
   ├─ DB Calls: 89
   ├─ Storage Calls: 12
   ├─ Successful: 140
   └─ Failed: 16
```

## 5. Recommendation

### Priority: HIGH

Implement Option 1 (Proper Agent Run Tracking) because:

1. **Minimal changes required**:
   - Wrap existing agent methods with `tracer.start_as_current_span("agent.run")`
   - Wrap DB/storage calls with tool span helpers

2. **Maximum visibility**:
   - ApplicationInsights Agents view shows full call graphs
   - Tool usage becomes visible
   - Failure root causes easier to identify

3. **Standard approach**:
   - Follows Microsoft Agent Framework best practices
   - Compatible with existing OpenTelemetry setup
   - No additional dependencies

4. **Timeline**:
   - Can be implemented incrementally
   - Start with high-traffic agents (Tiana, Merlin)
   - Then expand to others

### Implementation Order

1. Create `AgentTelemetry` helper class (src/agents/telemetry_helpers.py)
2. Update Belle (document analysis) agent - started task
3. Update Tiana (application parsing) - frequent calls
4. Update Merlin (student evaluation) - important for scoring
5. Update database.py with tool tracking
6. Update storage.py with tool tracking
7. Verify in ApplicationInsights Agents view

## 6. Code References

**Files that need updates:**
- `src/agents/base_agent.py` - Add agent.run span wrapper
- `src/agents/*.py` - Each agent's main method
- `src/database.py` - Tool tracking for DB calls
- `src/storage.py` - Tool tracking for uploads
- `src/telemetry.py` - May add helper methods

**Files that are correct:**
- `src/config.py` - Model configuration ✅
- `src/observability.py` - OpenTelemetry setup ✅
- `app.py` - Agent registration ✅

## Summary

✅ **Models**: All agents are correctly configured  
❌ **Agent Runs**: Missing (but LLM calls are tracked)  
❌ **Tool Calls**: Missing (no instrumentation)  

**Action Items**:
1. Implement agent run parent spans
2. Add tool call tracking to database operations
3. Add tool call tracking to storage operations
4. Verify in ApplicationInsights Agents view
