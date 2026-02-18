---
title: OpenTelemetry & Application Insights Monitoring Guide
description: Complete guide to monitoring all agents with OpenTelemetry and Azure Application Insights
tags: observability, monitoring, azure, opentelemetry, application-insights
---

# OpenTelemetry & Application Insights Monitoring Guide

Complete end-to-end monitoring of all agents using Azure Application Insights and OpenTelemetry standards.

## Quick Start

### 1. Get Application Insights Connection String

```bash
# In Azure Portal:
1. Open Application Insights resource
2. Click "Overview"
3. Copy "Connection String" (starts with "InstrumentationKey=...")
```

### 2. Add to .env.local (Development)

```bash
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=xx;IngestionEndpoint=...
ENABLE_INSTRUMENTATION=true
```

### 3. Run Application

```bash
python app.py
```

Telemetry data will automatically flow to Application Insights!

---

## What Gets Monitored Automatically

### Agent Executions

Every time an agent runs:
- ✓ Agent name and ID
- ✓ Model used (gpt-4 vs gpt-4-mini)
- ✓ Processing time (milliseconds)
- ✓ Success/failure status
- ✓ Execution span trace ID (for debugging)

### Model API Calls  

Every LLM call is tracked:
- ✓ Model name
- ✓ Input tokens
- ✓ Output tokens  
- ✓ Total tokens (for cost tracking)
- ✓ Latency (how long the request took)
- ✓ Request parameters (temperature, max_tokens, etc.)
- ✓ Response ID

### Application Events

- ✓ API endpoints hit
- ✓ School enrichment operations
- ✓ Dataset processing  
- ✓ Errors and exceptions

### Spans & Context

Each operation creates a hierarchical span tree:

```
invoke_agent [Rapunzel]
├── chat_completion_grade_analysis
│   ├── [OpenAI API call]
│   └── [Telemetry attributes: model, tokens, latency]
├── parse_grades [parsing logic]
└── [timestamps and trace ID]
```

---

## Architecture: How It Works

### 1. OpenTelemetry Setup (`src/observability.py`)

```python
from src.observability import configure_observability

# Called once at startup
configure_observability(
    service_name="agent-framework",
    enable_azure_monitor=True,  # Use Application Insights
    capture_sensitive_data=False,  # Don't log prompts in prod
)
```

**What it does:**
- Reads Azure Application Insights connection string
- Configures OTLP exporters (gRPC or HTTP)
- Sets up trace and metric providers
- Enables OpenTelemetry instrumentation

### 2. Telemetry Wrapper (`src/telemetry.py`)

```python
from src.telemetry import telemetry, init_telemetry

# Initialize at app startup
init_telemetry(service_name="nextgen-agents-web")

# Throughout the app, use telemetry methods:
telemetry.log_agent_execution(
    agent_name="Rapunzel",
    model="gpt-4",
    success=True,
    processing_time_ms=2340,
    tokens_used=1200
)

telemetry.log_model_call(
    model="gpt-4",
    input_tokens=850,
    output_tokens=350,
    duration_ms=2100,
    success=True
)
```

### 3. Agent Integration (`src/agents/base_agent.py`)

Base agent automatically tracks:
- Chat completions with GenAI semantic conventions
- Token usage and latency
- Agent context and application data

```python
# In base_agent.py _create_chat_completion():
response = self.client.chat.completions.create(
    model=model,
    messages=messages,
    **kwargs
)

# Automatically:
# - Creates span with "gen_ai.*" attributes
# - Records token usage metrics
# - Captures latency and status
# - Logs to Application Insights
```

### 4. Azure Application Insights Export

All telemetry automatically exported to Azure:
- Traces: OpenTelemetry spans for distributed tracing
- Metrics: Token usage, latency histograms, counters
- Logs: Structured logs with context
- Failures: Exceptions and error tracking

---

## Monitoring in Azure Portal

### View Live Metrics

```
Application Insights → Live Metrics
```

Shows in real-time:
- Requests/sec
- Response time
- Dependency calls
- Failed requests
- Server exceptions

### Query Spans & Traces

```
Application Insights → Logs → Kusto Query Language (KQL)
```

**View agent executions:**
```kusto
traces 
| where tostring(customDimensions.["agent_name"]) == "Rapunzel"
| summarize count() by tostring(customDimensions.["model"])
```

**Track token usage over time:**
```kusto
customMetrics
| where name == "gen_ai.client.token.usage"
| summarize TotalTokens=sum(value) by bin(timestamp, 1h)
| render timechart
```

**Find slow agents:**
```kusto
traces
| where customDimensions.["operation"] == "agent_execution"
| extend DurationMs = tonumber(customDimensions.["processing_time_ms"])
| where DurationMs > 5000  // More than 5 seconds
| project timestamp, Agent=customDimensions.["agent_name"], DurationMs
| sort by DurationMs desc
```

**Monitor API response times:**
```kusto
requests
| where name contains "evaluate"
| summarize Avg=avg(duration), P95=percentile(duration,95), P99=percentile(duration,99)
  by name
```

**Track errors by agent:**
```kusto
exceptions
| extend Agent=tostring(customDimensions.["agent_name"])
| summarize ErrorCount=count() by Agent
| sort by ErrorCount desc
```

### Create Alerts

```
Application Insights → Alerts → New Alert Rule
```

**Example: Alert if error rate > 5%**

```kusto
requests
| where timestamp > ago(5m)
| summarize FailedCount=sumif(itemCount, success == false), TotalCount=sum(itemCount)
| extend ErrorRate = FailedCount * 100.0 / TotalCount
| where ErrorRate > 5
```

**Example: Alert if average latency > 2 seconds**

```kusto
requests
| where timestamp > ago(5m)
| summarize AvgDuration=avg(duration)
| where AvgDuration > 2000
```

---

## Configuration Reference

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | ✓ (for Azure) | | Application Insights connection |
| `ENABLE_INSTRUMENTATION` | | `true` | Enable OpenTelemetry spans |
| `ENABLE_SENSITIVE_DATA` | | `false` | Log prompts/responses (dev only!) |
| `ENABLE_CONSOLE_EXPORTERS` | | `false` | Show telemetry in console |
| `OTEL_SERVICE_NAME` | | `agent-framework` | Service identifier |
| `OTEL_SERVICE_VERSION` | | `1.0.0` | Service version |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | (for non-Azure) | | OTLP collector endpoint |

### For Azure Web App Deployment

Set in Configuration → Application Settings:

```
APPLICATIONINSIGHTS_CONNECTION_STRING = InstrumentationKey=...
ENABLE_INSTRUMENTATION = true
```

---

## Common Telemetry Patterns

### Pattern 1: Custom Agent Execution Tracking

```python
from src.telemetry import telemetry
import time

async def analyze_grades(self, transcript):
    start = time.time()
    
    try:
        result = await self.extract_grades(transcript)
        
        telemetry.log_agent_execution(
            agent_name=self.name,
            model=self.model,
            success=True,
            processing_time_ms=int((time.time() - start) * 1000),
            tokens_used=result.get('tokens_used', 0),
            confidence="High",
            result_summary={'grades_count': len(result.get('grades', []))}
        )
        
        return result
        
    except Exception as e:
        telemetry.log_agent_execution(
            agent_name=self.name,
            model=self.model,
            success=False,
            processing_time_ms=int((time.time() - start) * 1000),
            confidence="None"
        )
        raise
```

### Pattern 2: School Enrichment Tracking

```python
from src.telemetry import telemetry

def enrich_school_data(school_name, opportunities):
    start = time.time()
    score = calculate_opportunity_score(opportunities)
    
    telemetry.log_school_enrichment(
        school_name=school_name,
        opportunity_score=score,
        data_source="web_search",
        confidence=0.95,
        processing_time_ms=int((time.time() - start) * 1000)
    )
    
    return {'score': score, 'opportunities': opportunities}
```

### Pattern 3: API Call Tracking

```python
from src.telemetry import telemetry
import time

@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    start = time.time()
    
    try:
        # ... your logic ...
        status = 200
    except Exception as e:
        status = 500
    
    duration_ms = (time.time() - start) * 1000
    telemetry.log_api_call(
        endpoint="/api/evaluate",
        method="POST",
        status_code=status,
        duration_ms=duration_ms
    )
    
    return result
```

---

## Development: Using Aspire Dashboard  

For local testing without Azure:

### 1. Start Aspire Dashboard

```bash
docker run --rm -it -d \
    -p 18888:18888 \
    -p 4317:18889 \
    --name aspire-dashboard \
    mcr.microsoft.com/dotnet/aspire-dashboard:latest
```

### 2. Configure .env.local

```
ENABLE_INSTRUMENTATION=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
ENABLE_CONSOLE_EXPORTERS=true
```

### 3. View Dashboard

Open http://localhost:18888 in browser

### 4. Stop Dashboard

```bash
docker stop aspire-dashboard
```

---

## Troubleshooting

### I Don't See Any Telemetry Data

**Check 1: Is telemetry enabled?**
```python
from src.observability import is_observability_enabled
print("Observability enabled:", is_observability_enabled())
```

**Check 2: Is connection string valid?**
```bash
echo $APPLICATIONINSIGHTS_CONNECTION_STRING
# Should output InstrumentationKey=...
```

**Check 3: Enable console exporters for debugging**
```
ENABLE_CONSOLE_EXPORTERS=true
```

Then check app logs for telemetry output.

### I See High Latency on Model Calls

Query Application Insights:
```kusto
traces
| where tostring(customDimensions.["operation"]) == "model_call"
| extend Latency=tonumber(customDimensions.["duration_ms"])
| summarize P95=percentile(Latency, 95), P99=percentile(Latency, 99)
```

If P95 > 5000ms, check:
- Azure OpenAI deployment capacity
- Network latency to Azure
- Token budget (higher tokens = slower)

### Memory Usage Is High

OpenTelemetry can accumulate batches. Configure:

```python
configure_observability(
    # These are recommended defaults:
    service_name="agent-framework",
    enable_azure_monitor=True,
    # Memory-efficient settings:
    # - gRPC batching (more efficient than HTTP)
    # - 5-minute metric intervals
    # - Tail-based sampling for high-volume apps
)
```

### Sensitive Data Accidentally Logged

**If ENABLE_SENSITIVE_DATA was set in production:**

1. Stop the application immediately
2. Disable the setting
3. Purge data from Application Insights (see Azure docs)
4. Review for data leaks

Remember: In production, always set:
```
ENABLE_SENSITIVE_DATA=false
```

---

## Best Practices

### 1. Always Tag Your Data

```python
# ✗ DON'T: Generic event
span.set_attribute("agent_result", "success")

# ✓ DO: Structured, queryable attributes
span.set_attribute("gen_ai.agent.name", "Rapunzel")
span.set_attribute("gen_ai.agent.id", "grade-reader-v1")
span.set_attribute("gen_ai.model", "gpt-4")
```

### 2. Use Semantic Conventions

OpenTelemetry GenAI semantic conventions ensure consistency:

```python
# Standard attributes that every telemetry system understands
span.set_attribute("gen_ai.system", "azure_openai")  # Not "azureopenai" or "azure-openai"
span.set_attribute("gen_ai.model", "gpt-4")  # Not "Gpt-4" or "GPT4"
span.set_attribute("gen_ai.operation.name", "chat")  # Not "Chat" or "CHAT"
span.set_attribute("gen_ai.usage.prompt_tokens", 850)
span.set_attribute("gen_ai.usage.completion_tokens", 350)
```

### 3. Never Ship Prompts in Production

```python
if should_capture_sensitive_data():  # Only if enabled AND dev/test
    span.set_attribute("gen_ai.prompt", json.dumps(messages))
```

### 4. Sample High-Volume Events

For apps with millions of requests:

```python
# Sample 10% of high-volume events to reduce costs
import random

if random.random() < 0.1:  # Only trace 10%
    telemetry.log_api_call(...)
```

### 5. Use Correlation IDs for Debugging

```python
import uuid

request_id = str(uuid.uuid4())
span.set_attribute("request.id", request_id)

# Can then query all spans for a single request
```

---

## Cost Estimation

Application Insights pricing (as of 2024):
- **Free tier**: 5 GB/month ingestion, 7 days retention
- **Pay-as-you-go**: ~$2.50/GB after free tier

**Estimate for 1000 agents/hour:**
- ~2 transactions/sec
- ~1-2 KB per trace
- ~150 GB/month
- **Cost: ~$375/month**

**To reduce costs:**
- Disable ENABLE_SENSITIVE_DATA (reduces span size)
- Use sampling for high-volume endpoints
- Archive old data to blob storage

---

## Next Steps

1. ✓ Set `APPLICATIONINSIGHTS_CONNECTION_STRING` in Azure
2. ✓ Deploy application
3. ✓ Monitor dashboard for 24 hours
4. ✓ Create alerts for key metrics
5. ✓ Set up dashboards for stakeholders

---

**Questions?** Check Application Insights documentation or the comments in `src/observability.py` and `src/telemetry.py`.
