# Agent Telemetry Implementation Guide

**Status**: 🟢 Ready to implement  
**Date**: 2026-02-18  
**Purpose**: Enable visibility into agent runs and tool calls in Application Insights Agents view

## Quick Start

### Step 1: Import Telemetry Helpers

```python
from src.agents.telemetry_helpers import agent_run, tool_call

# Or use the class directly:
from src.agents.telemetry_helpers import AgentTelemetry
```

### Step 2: Wrap Agent Methods

```python
# Before (without telemetry)
async def parse_application(self, application: Dict[str, Any]) -> Dict[str, Any]:
    response = self._create_chat_completion(...)
    data = json.loads(response.choices[0].message.content)
    if self.db:
        self.db.save_tiana_application(...)
    return data

# After (with telemetry)
async def parse_application(self, application: Dict[str, Any]) -> Dict[str, Any]:
    applicant_name = application.get("applicant_name", "Unknown")
    application_id = application.get("application_id")
    
    with agent_run(self.name, "parse_application", 
                   {"applicant_name": applicant_name, "application_id": application_id}):
        response = self._create_chat_completion(...)
        data = json.loads(response.choices[0].message.content)
        
        if self.db:
            with tool_call("save_tiana_application", "database", 
                          {"application_id": application_id}):
                self.db.save_tiana_application(...)
        return data
```

## Available Helpers

### 1. agent_run() - Track agent execution

```python
from src.agents.telemetry_helpers import agent_run

with agent_run(agent_name, action, context_data) as span:
    # Agent logic here
    # All nested LLM calls and tool calls automatically become child spans
```

**Parameters**:
- `agent_name` (str): Name of agent, e.g., "Tiana Application Reader"
- `action` (str): What the agent is doing, e.g., "parse_application"
- `context_data` (Dict, optional): Additional context like student name, application ID

**Application Insights Result**:
```
agent.run
├─ agent.id: "Tiana Application Reader"
├─ agent.action: "parse_application"
├─ agent.context.applicant_name: "John Smith"
├─ agent.context.application_id: "APP123"
├─ agent.run.duration_ms: 2500
└─ agent.run.success: true
```

### 2. tool_call() - Track tool usage

```python
from src.agents.telemetry_helpers import tool_call

with tool_call(tool_name, tool_type, tool_input) as span:
    result = some_tool_operation()
    if span:
        span.set_attribute("tool.output.rows_affected", result.get("rows", 0))
```

**Parameters**:
- `tool_name` (str): e.g., "save_tiana_application", "query_db", "upload_file"
- `tool_type` (str): e.g., "database", "storage", "api", "web", "cache"
- `tool_input` (Dict, optional): Tool input parameters (auto-sanitized)

**Application Insights Result**:
```
tool.call
├─ tool.name: "save_tiana_application"
├─ tool.type: "database"
├─ tool.input: "{'application_id': 'APP123', ...}"
├─ tool.call.duration_ms: 150
└─ tool.success: true
```

### 3. lm_call() - Alternative LLM tracking

```python
from src.agents.telemetry_helpers import lm_call

with lm_call(model, operation, system_prompt) as span:
    response = client.chat.completions.create(...)
    if span:
        span.set_attribute("gen_ai.usage.prompt_tokens", response.usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.completion_tokens", response.usage.completion_tokens)
```

Note: This is mainly for alternative LLM call tracking. The BaseAgent's `_create_chat_completion` already handles this automatically.

## Implementation Examples

### Example 1: Simple Agent Method

**File**: `src/agents/rapunzel_grade_reader.py`

```python
from src.agents.telemetry_helpers import agent_run, tool_call

async def analyze_transcript(self, transcript: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze student transcript."""
    student_name = transcript.get("student_name", "Unknown")
    student_id = transcript.get("student_id")
    
    with agent_run(self.name, "analyze_transcript", 
                   {"student_name": student_name, "student_id": student_id}):
        # LLM call (auto-tracked as child span)
        response = self._create_chat_completion(
            operation="rapunzel.analyze_transcript",
            model=self.model,
            messages=[
                {"role": "system", "content": "You are Rapunzel, analyzing academic transcripts..."},
                {"role": "user", "content": self._build_prompt(student_name, transcript)}
            ],
            max_completion_tokens=1500
        )
        
        data = json.loads(response.choices[0].message.content)
        
        # Database save (tracked as tool call)
        if self.db and student_id:
            with tool_call("save_rapunzel_analysis", "database", {"student_id": student_id}):
                self.db.save_rapunzel_analysis(
                    student_id=student_id,
                    analysis=json.dumps(data)
                )
        
        return data
```

### Example 2: Multiple Tool Calls

**File**: `src/agents/naveen_school_data_scientist.py`

```python
from src.agents.telemetry_helpers import agent_run, tool_call

async def analyze_school(self, school_name: str, state_code: str) -> Dict[str, Any]:
    """Deep analysis of school data."""
    
    with agent_run(self.name, "analyze_school", 
                   {"school_name": school_name, "state_code": state_code}):
        
        # Tool 1: Database lookup
        with tool_call("lookup_school_enrichment", "database", 
                      {"school_name": school_name}):
            school_data = self.db.get_school_enriched_data(school_name, state_code)
        
        if school_data:
            return school_data  # Cache hit
        
        # Tool 2: Web scraping
        with tool_call("scrape_school_sources", "web", 
                      {"school_name": school_name}):
            sources = await self._scrape_school_info(school_name)
        
        # LLM call (auto-tracked)
        response = self._create_chat_completion(
            operation="naveen.analyze_school",
            model=self.model,
            messages=[...],
            max_completion_tokens=2000
        )
        
        analysis = json.loads(response.choices[0].message.content)
        
        # Tool 3: Database save
        with tool_call("store_school_enrichment", "database", 
                      {"school_name": school_name}):
            self.db.create_school_enriched_data(
                school_name=school_name,
                analysis=json.dumps(analysis)
            )
        
        # Tool 4: Storage upload
        with tool_call("upload_school_profile", "storage", 
                      {"school_name": school_name}):
            storage_result = self.storage.upload_file(
                json.dumps(analysis).encode(),
                f"{school_name}_profile.json"
            )
        
        return analysis
```

### Example 3: Database Module Instrumentation

**File**: `src/database.py`

```python
from src.agents.telemetry_helpers import tool_call

def save_tiana_application(self, application_id, agent_name, **kwargs):
    """Save Tiana analysis to database."""
    with tool_call("save_tiana_application", "database", 
                  {"application_id": application_id, "agent": agent_name}):
        query = """
            INSERT INTO tiana_application_analysis 
            (application_id, agent_name, essay_summary, readiness_score, created_at)
            VALUES (%s, %s, %s, %s, NOW())
        """
        cursor = self.connection.cursor()
        cursor.execute(query, (
            application_id,
            agent_name,
            kwargs.get("essay_summary"),
            kwargs.get("readiness_score")
        ))
        self.connection.commit()
        return {"success": True, "rows_affected": cursor.rowcount}
```

### Example 4: Storage Module Instrumentation

**File**: `src/storage.py`

```python
from src.agents.telemetry_helpers import tool_call

def upload_file(self, file_content: bytes, filename: str, student_id: str, 
                application_type: str = "2026") -> Dict[str, Any]:
    """Upload file to Azure Storage."""
    with tool_call("upload_blob", "storage", 
                  {"filename": filename, "student_id": student_id}):
        container_name = self._get_container_name(application_type)
        blob_path = f"{student_id}/{filename}"
        
        container_client = self.client.get_container_client(container_name)
        blob_client = container_client.upload_blob(
            name=blob_path,
            data=file_content,
            overwrite=True
        )
        
        blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_path}"
        
        return {
            'success': True,
            'blob_url': blob_url,
            'blob_path': blob_path
        }
```

## Application Insights Visualization

### Before (Current State)

Individual LLM call traces scattered in Traces view:
```
Trace 1: chat_completion_tiana.parse_application (2.5s)
Trace 2: chat_completion_rapunzel.analyze_transcript (1.8s)
Trace 3: chat_completion_merlin.evaluate_student (3.2s)
...
```

### After (With Agent Run Tracking)

Organized agent call graph in Agents view:
```
Agent Runs
├─ Tiana Application Reader
│  └─ parse_application (5.2s) ✓
│     ├─ chat_completion (2.5s, 850 tokens)
│     └─ tool.call: save_tiana_application (150ms)
│
├─ Rapunzel Grade Reader
│  └─ analyze_transcript (3.8s) ✓
│     ├─ chat_completion (1.8s, 600 tokens)
│     └─ tool.call: save_rapunzel_analysis (200ms)
│
└─ Naveen School Data Scientist
   └─ analyze_school (18.5s) ✓
      ├─ tool.call: lookup_school_enrichment (50ms)
      ├─ tool.call: scrape_school_sources (8.2s)
      ├─ chat_completion (5.1s, 1200 tokens)
      ├─ tool.call: store_school_enrichment (300ms)
      └─ tool.call: upload_school_profile (400ms)

Metrics:
├─ Total Agent Runs: 47
├─ Total Tool Calls: 156
├─ Avg Run Duration: 4.8s
├─ Successful: 45 (95.7%)
└─ Failed: 2 (4.3%)
```

## Implementation Checklist

**Priority 1 (High-traffic agents)**:
- [ ] Tiana Application Reader (parse_application)
- [ ] Rapunzel Grade Reader (analyze_transcript)
- [ ] Merlin Student Evaluator (evaluate_student)
- [ ] Belle Document Analyzer (analyze_document) ✅

**Priority 2 (Data persistence)**:
- [ ] Naveen School Data Scientist (analyze_school)
- [ ] Moana School Context (analyze_student_school_context)
- [ ] Database module (all save_* methods)
- [ ] Storage module (upload_file, download_file)

**Priority 3 (Supporting agents)**:
- [ ] Gaston Evaluator
- [ ] Bashful Agent
- [ ] Scuttle Feedback Triage
- [ ] Fairy Godmother Document Generator
- [ ] Milo Data Scientist

**Priority 4 (Orchestration)**:
- [ ] Smee Orchestrator (coordinate_evaluation)
- [ ] Aurora Result Formatter
- [ ] School Workflow (get_or_enrich_school_data)

## Testing Changes

After implementing telemetry:

1. **Local testing**:
   ```
   python main.py
   # Monitor console output for span creation
   # Check that no telemetry errors occur
   ```

2. **Azure Application Insights**:
   ```
   App Insights → Agents view
   Look for:
   ├─ Agent Runs populated
   ├─ Tool Count > 0
   ├─ Call Graph shows nested spans
   └─ Duration and success metrics visible
   ```

3. **Verify attributes**:
   ```
   Filter traces for:
   - agent.run spans (should see agent names)
   - tool.call spans (should see tool names and types)
   - Proper parent-child relationships
   ```

## Common Patterns

### Pattern 1: LLM Call (Already Automated)

No additional code needed - `_create_chat_completion` already handles this.

### Pattern 2: Database Operation

```python
with tool_call("operation_name", "database", {"id": some_id}):
    result = self.db.some_operation(some_id)
```

### Pattern 3: Storage Operation

```python
with tool_call("operation_name", "storage", {"file": filename}):
    result = self.storage.upload_file(content, filename)
```

### Pattern 4: Web/API Call

```python
with tool_call("operation_name", "api|web", {"url": endpoint}):
    result = requests.get(endpoint)
```

### Pattern 5: Cached Operation

```python
with tool_call("lookup_cache", "cache", {"key": cache_key}):
    cached_result = cache.get(cache_key)
    if cached_result:
        # Hit - tool.success = True automatically
        return cached_result

# Miss - continue with full operation
with tool_call("full_operation", "database|api", {"key": cache_key}):
    result = expensive_operation()
    cache.set(cache_key, result)
    return result
```

## Reference

**Files Modified**:
- [src/agents/telemetry_helpers.py](../src/agents/telemetry_helpers.py) - NEW
- [src/agents/belle_document_analyzer.py](../src/agents/belle_document_analyzer.py) - UPDATED
- [src/agents/tiana_application_reader.py](../src/agents/tiana_application_reader.py) - UPDATED

**Files to Update**:
- src/agents/rapunzel_grade_reader.py
- src/agents/moana_school_context.py
- src/agents/mulan_recommendation_reader.py
- src/agents/merlin_student_evaluator.py
- src/agents/milo_data_scientist.py
- src/agents/naveen_school_data_scientist.py
- src/agents/gaston_evaluator.py
- src/agents/smee_orchestrator.py
- src/database.py (all save_* methods)
- src/storage.py (upload_file, download_file)

**Documentation**:
- [AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md](../AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md) - Analysis & recommendations

## Questions?

Refer to:
1. [AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md](../AGENT_MODELS_AND_TELEMETRY_ANALYSIS.md) for context
2. [src/agents/telemetry_helpers.py](../src/agents/telemetry_helpers.py) for API reference
3. Examples in this file for implementation patterns
