# OpenTelemetry Monitoring Implementation Checklist

## ✅ Completed: Core Implementation

### Files Created
- ✓ `src/observability.py` - OpenTelemetry configuration (follows Microsoft patterns)
- ✓ `src/telemetry.py` - Enhanced telemetry module with OpenTelemetry integration
- ✓ `OPENTELEMETRY_MONITORING_GUIDE.md` - Complete monitoring documentation

### Files Modified
- ✓ `src/agents/base_agent.py` - Updated to use OpenTelemetry properly
- ✓ `requirements.txt` - Added all necessary OpenTelemetry packages
- ✓ `.env.example` - Added Application Insights configuration documentation

### Validation
- ✓ Python syntax check: All files compile
- ✓ No dependency issues
- ✓ Backwards compatible with existing code
- ✓ `app.py` already calls `init_telemetry()`

---

## 🚀 Deployment Checklist

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

**Expected packages added:**
- `azure-monitor-opentelemetry>=1.0.0`
- `opentelemetry-api>=1.20.0`
- `opentelemetry-sdk>=1.20.0`
- `opentelemetry-semantic-conventions-ai>=0.4.13`
- `opentelemetry-exporter-otlp-proto-grpc>=0.41b0`
- `opentelemetry-instrumentation-*` (Flask, requests, SQLAlchemy, etc.)

### Step 2: Configure Application Insights (Azure Portal)

**For local development:**
```bash
# Copy template
cp .env.example .env.local

# Edit .env.local and add:
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...
ENABLE_INSTRUMENTATION=true
ENABLE_SENSITIVE_DATA=false  # ⚠️ NEVER true in production!
```

**For Azure Web App deployment:**
1. Azure Portal → Application Insights resource
2. Copy "Connection String"
3. Web App → Configuration → Application settings
4. Add: `APPLICATIONINSIGHTS_CONNECTION_STRING`
5. Restart the app

### Step 3: Environment Variables

```bash
# Required for production
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...

# Recommended
ENABLE_INSTRUMENTATION=true
OTEL_SERVICE_NAME=agent-framework
OTEL_SERVICE_VERSION=1.0.0

# Development only
ENABLE_SENSITIVE_DATA=false          # Set to true for debugging
ENABLE_CONSOLE_EXPORTERS=false       # Set to true to see telemetry in console
```

### Step 4: Verify Monitoring is Active

**Option A: Check Agent Logs**
```bash
python app.py 2>&1 | grep -i "observability\|telemetry"
```

Expected output:
```
✓ Azure Monitor observability configured for 'nextgen-agents-web'
```

**Option B: Check in Application Insights Portal**
1. Azure Portal → Application Insights
2. Click "Live Metrics"
3. Run an API request (e.g., `/api/evaluate`)
4. Should see graph spike in 5 seconds

**Option C: Query Recent Data**
```kusto
// In Application Insights Logs
traces  
| where timestamp > ago(5m)
| limit 100
```

### Step 5: Test Each Agent Type

Run through each agent to ensure telemetry works:

```bash
# Test Rapunzel (grade reader)
curl -X POST http://localhost:5000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{"transcript": "...", "school": "..."}'

# Check telemetry in Application Insights within 5 seconds
```

Then query:
```kusto
traces | where tostring(customDimensions.["agent_name"]) == "Rapunzel"
```

### Step 6: Create Monitoring Dashboard

In Application Insights:

1. **Live Metrics**: Real-time request/sec, response times
2. **Performance**: Track model call duration by agent
3. **Failures**: Error rate by agent
4. **Alerts**: Notify on error spike or latency threshold

**Example alert query:**
```kusto
requests
| where timestamp > ago(5m)
| where tostring(customDimensions.["agent_name"]) contains "Error"
| summarize ErrorCount=count() by name
| where ErrorCount > 10
```

---

## 📊 Monitoring Data Structure

### Automatically Captured Per Agent Call

```
Trace ID: f2258b51421fe9cf...
├─ Span: invoke_agent_Rapunzel (150ms)
│  ├─ gen_ai.agent.name: "Rapunzel"
│  ├─ gen_ai.model: "gpt-4"
│  ├─ success: true
│  └─ Child Span: chat_completion (140ms)
│     ├─ gen_ai.usage.prompt_tokens: 850
│     ├─ gen_ai.usage.completion_tokens: 350
│     ├─ gen_ai.latency_ms: 2100
│     └─ gen_ai.system: "azure_openai"
```

### Queryable Metrics

```kusto
// Token usage over time
customMetrics
| where name startswith "agent_tokens_used"
| summarize TotalTokens=sum(value) by bin(timestamp, 15m), name
| render timechart

// Agent performance comparison
traces
| where message contains "agent_execution"
| extend Duration=tonumber(customDimensions.["processing_time_ms"])
| summarize AvgDuration=avg(Duration) by Agent=tostring(customDimensions.["agent_name"])
| sort by AvgDuration desc
```

---

## 🔍 Key Queries for Operations

### Find Slow Requests
```kusto
requests
| where timestamp > ago(1h)
| where duration > 5000
| project timestamp, name, duration, success
| sort by duration desc
```

### Track Token Spent by Agent
```kusto
customMetrics
| where name == "agent_tokens_used"
| extend Agent=tostring(customDimensions.["agent"])
| summarize TotalTokens=sum(value) by Agent
| sort by TotalTokens desc
```

### Find Errors
```kusto
exceptions
| where timestamp > ago(24h)
| project timestamp, type, message, outerMessage
| summarize Count=count() by type
| sort by Count desc
```

### API Performance by Endpoint
```kusto
requests
| where timestamp > ago(1h)
| summarize 
    Count=count(),
    AvgDuration=avg(duration),
    P95=percentile(duration, 95),
    P99=percentile(duration, 99),
    FailureRate=sumif(itemCount, success==false)*100.0/sum(itemCount)
  by name
| sort by AvgDuration desc
```

---

## 🐛 Troubleshooting

### No Data Appearing in Application Insights

**Step 1: Check connection string**
```python
import os
print(os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"))  # Should NOT be empty
```

**Step 2: Check if instrumentation is enabled**
```python
from src.observability import is_observability_enabled
print(is_observability_enabled())  # Should be True
```

**Step 3: Enable console exporters to debug**
```
ENABLE_CONSOLE_EXPORTERS=true
```

Then look for telemetry output in app logs.

**Step 4: Check if data is batched**
OpenTelemetry batches data (waits 5 seconds by default). Make sure app runs for >5 seconds after making requests.

### High Token Usage

Check which agents use most tokens:
```kusto
customMetrics
| where name == "agent_tokens_used"
| summarize TokensUsed=sum(value) by Agent=customDimensions.["agent"]
| sort by TokensUsed desc
```

Then optimize:
- Reduce max_tokens for those agents
- Use GPT-4 Mini for the model (faster, cheaper)
- Implement result caching

### Application Insights Quota

Free tier: 5 GB/month
- Estimated cost per GB after free: $2.50/GB

To reduce data:
1. Disable `ENABLE_SENSITIVE_DATA` (removes prompts/responses)
2. Implement sampling for high-volume endpoints
3. Reduce trace verbosity

---

## 📚 Resources

- [Azure Monitor OpenTelemetry Python](https://learn.microsoft.com/en-us/python/api/overview/azure/monitor-opentelemetry-readme)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [Application Insights Kusto Query Language](https://learn.microsoft.com/en-us/azure/data-explorer/kusto/query/)
- [Agent Framework Observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability)

---

## ✨ Features Enabled After Deployment

### Per-Agent Monitoring
- Track each agent's performance independently
- Identify which agents are slow
- Monitor token usage per agent
- Track success/failure rates

### Model Call Tracking
- See exactly which models are called how often
- Track input/output token usage
- Monitor API latency
- Trace cost per operation

### Application Insights Features
- ✓ Live Metrics Dashboard
- ✓ Performance Diagnostics  
- ✓ Failure Analysis
- ✓ Alerts & Rules
- ✓ Smart Detection
- ✓ Custom Metrics & Dimensions
- ✓ Distributed Tracing

### Dashboard Options
1. **Azure Portal** - Built-in dashboard
2. **Power BI** - Create custom reports
3. **Excel** - Export data for analysis
4. **Grafana** - Third-party visualization

---

**Status**: ✅ Ready for Deployment

All components implemented and validated. Follow the deployment checklist to get started monitoring!
