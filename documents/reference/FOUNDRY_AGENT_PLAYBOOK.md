# Azure AI Foundry Agent Playbook

> Hard-won operational knowledge from building and running the Springfield Core Team —
> 12 production AI agents on Azure AI Foundry. Every lesson here was learned the expensive way.
> Use this when building new agent solutions.

---

## 1. Model Selection & Deployment

### The Model Tier Hierarchy

| Tier | Models | Best For | Characteristics |
|------|--------|----------|-----------------|
| **Deep Reasoning** | o3-pro | Security analysis, attacker modeling, multi-step logic chains | Slowest, most expensive. Genuinely thinks deeper. Use sparingly for roles that need it. |
| **Reasoning** | o3 | Architecture design, orchestration planning, complex routing | Good balance of depth and speed. Best for "boss" and "architect" roles. |
| **Pro Knowledge** | gpt-5.4-pro | Quality reviews, code analysis, deep evaluation | Extended thinking for quality assessment. Higher latency than standard. |
| **Coding** | gpt-5.3-codex | Code generation, IaC authoring, pipeline writing | Optimized for code output. Highest RPM per TPM ratio. |
| **General** | gpt-5.4 | Research, ops monitoring, documentation, content creation | Fastest, cheapest, highest throughput. The workhorse for most agents. |

### Capacity Planning Formula

**Critical rule:** A single agent call's total token consumption (input + output) must fit within the model's per-minute TPM allocation — or the call will throttle/timeout.

```
Total tokens per call = system_prompt + context_from_teammates + user_request + handoff_template + output
```

Example for a code reviewer:
- System prompt: ~1,300 tokens
- Builder context (code to review): ~5,000 tokens
- Original request: ~750 tokens
- Handoff template: ~125 tokens
- Output (grade + findings + corrected code): ~8,000 tokens
- **Total: ~15,175 tokens**

If your TPM is 10K, this single call takes 1.5 minutes of quota. At 80K TPM, it takes 11 seconds. **Size your TPM to your heaviest single-call consumer.**

### Quota Allocation Strategy

1. **Check available quota first:** `az cognitiveservices usage list -l <region> -o json`
2. **Find your Foundry account:** `az rest --method get --url "https://management.azure.com/subscriptions/{sub}/providers/Microsoft.CognitiveServices/accounts?api-version=2024-10-01"`
3. **Scale deployments:** `az cognitiveservices account deployment create -g {rg} -n {account} --deployment-name {name} --model-name {model} --model-version {version} --model-format OpenAI --sku-capacity {units} --sku-name GlobalStandard`
4. **Verify:** `az cognitiveservices account deployment list -g {rg} -n {account} -o table`

**GlobalStandard scaling:** Each capacity unit = 1K TPM. RPM scales proportionally but varies by model:
- gpt-5.4: 10 RPM per 1K TPM (very generous)
- o3-pro: 1 RPM per 10K TPM (very tight)
- gpt-5.4-pro: 1 RPM per 1K TPM (moderate)

**FDPO/Corporate tenants:** Key auth may be disabled on storage. Use `DefaultAzureCredential` only. Service principal creation may be blocked — plan for manual deployments.

---

## 2. Agent Prompt Engineering

### The Token Budget

Every token in a system prompt is paid on EVERY call. A 2,000-token prompt on an agent that runs 50 times/day = 100K tokens/day just on instructions. Multiply by 12 agents = 1.2M tokens/day on prompts alone.

### What Earns Its Place in a System Prompt

| Include | Why |
|---------|-----|
| **Role definition** (2-3 sentences) | Agent needs to know WHO it is |
| **Core personality traits** (3-5 bullets) | Shapes tone and approach |
| **Key catchphrases** (1-2 lines, condensed) | Character voice — but condense, don't list 10 individually |
| **Technical expertise** (bullet list) | What the agent KNOWS and should apply |
| **Output format rules** | How to structure the response (grades, sections, code blocks) |
| **Hard rules** (5-8 bullets) | Non-negotiable behaviors |

### What Does NOT Belong in a System Prompt

| Exclude | Why |
|---------|-----|
| **Relationships with other agents** | Agents don't choose who to talk to — the orchestrator routes. Wastes 200-500 tokens per agent. |
| **Verbose catchphrase explanations** | "I believe you'll find..." needs no explanation of when to use it. The LLM knows. |
| **Team member bios** | The agent doesn't need to know Gil is nervous. The orchestrator handles team dynamics. |
| **Duplicate context** | If the handoff template says "review this code," the prompt doesn't need to say "you review code." |

### Measured Impact

In our team of 12 agents, removing relationship sections and condensing catchphrases saved **~2,400 tokens per full pipeline run**. Over a day with 20 pipeline runs, that's 48K tokens — roughly $2-5 in pure waste eliminated.

### The Simpsons Rule

Character personality is NOT decoration — it's the user experience. The grading rubric (A-F) IS Martin's output format. Troy's "You may remember me from..." IS his research brief opener. These earn their tokens because they directly shape output quality and consistency.

**Rule of thumb:** If removing a line from the prompt would change the agent's output, keep it. If it wouldn't, cut it.

---

## 3. Orchestration Architecture

### Context Routing (Who Sees What)

Not every agent needs every other agent's output. A context routing map prevents token overload:

```python
CONTEXT_ROUTING = {
    "architect": ["research"],              # Reads research only
    "engineer": ["architect", "quality"],   # Reads design + review feedback
    "quality": ["engineer", "architect"],   # Reads code + design
    "security": ["engineer", "architect"],  # Reads code + design
    "docs": ["architect", "engineer", "security", "quality"],  # Reads everything (goes last)
}
```

### Reviewer Input Optimization

**Key insight:** Reviewers (quality, security) need the CODE, not the user's original brief. The orchestrator's task description tells them what to do — the code is what they review.

```python
# Reviewers get a reduced request cap
if role in ("quality", "security"):
    request_cap = 3000   # Just enough for scope context
else:
    request_cap = 15000  # Full brief for builders
```

### Per-Role Context Limits

Cap how much of each agent's output gets passed downstream. Code producers get higher limits because reviewers need to see all the code, but researchers and ops agents can be summarized:

```python
CONTEXT_LIMITS = {
    "engineer": 25000,   # Reviewers MUST see full code
    "architect": 15000,  # Full architecture
    "research": 6000,    # Summaries are fine
    "quality": 8000,     # Review findings
    "security": 12000,   # Full vulnerability list
    "devops": 6000,      # Ops summaries
}
```

### Feedback Loops

When a reviewer grades code poorly, send it back to the builder automatically:

```python
FEEDBACK_LOOPS = {
    "quality": {
        "reviewer": "quality",
        "builders": ["engineer", "frontend"],
        "trigger_keywords": ["grade: d", "grade: f", "failing"],
        "max_iterations": 2,
    }
}
```

**Warning:** Each feedback iteration is a full agent call for BOTH the builder and reviewer. Budget 2x the tokens per loop.

---

## 4. Rate Limit Management

### The Three-Layer Defense

1. **Model-aware cooldowns** (orchestrator level) — space calls based on actual RPM
2. **Exponential backoff retry** (factory level) — handle transient 429s
3. **Model fallback chains** (factory level) — when primary model fails, call a cheaper model

### Cooldown Calibration

Match cooldowns to actual RPM, not theoretical limits:

```python
MODEL_COOLDOWN = {
    "o3-pro": 8,       # 30 RPM = 1 call every 2s, but give 8s for safety
    "o3": 5,           # 30 RPM
    "gpt-5.4-pro": 5,  # 80 RPM
    "gpt-5.3-codex": 3, # 300 RPM
    "gpt-5.4": 3,       # 800 RPM
}
```

**Rule:** Cooldown = `max(60/RPM * 2, 3)` — double the theoretical minimum, floor at 3 seconds.

### Fallback Chains

When the primary model times out or hits rate limits after all retries, fall back to a faster/cheaper model:

```python
MODEL_FALLBACKS = {
    "o3-pro": "o3",           # Deep reasoning → standard reasoning
    "o3": "gpt-5.4",         # Reasoning → general knowledge
    "gpt-5.4-pro": "gpt-5.4",  # Pro → standard
    "gpt-5.3-codex": "gpt-5.4",  # Code → general
}
```

**Critical lesson:** The fallback must ACTUALLY CALL the fallback model. Don't log "trying fallback" and then re-raise. The fallback call should:
1. Get the agent's instructions from the registry
2. Call the OpenAI Responses API directly with `model=fallback_model`
3. Inject the agent's instructions as a `developer` message
4. Track usage metrics for the fallback call

### Timeout Calibration

Set timeouts based on TPM capacity, not arbitrary guesses:

```python
MODEL_TIMEOUTS = {
    "o3-pro": 300,      # 300K TPM — 5 min for deep reasoning
    "o3": 180,           # 30K TPM — 3 min
    "gpt-5.4-pro": 240, # 80K TPM — 4 min for heavy reviews
    "gpt-5.3-codex": 120, # 30K TPM — 2 min
    "gpt-5.4": 90,       # 80K TPM — 90s
}
```

**Formula:** `timeout_seconds = max(total_expected_tokens / (TPM / 60) * 3, 60)` — 3x the theoretical time, minimum 60s.

---

## 5. Foundry SDK Patterns (azure-ai-projects >= 2.0)

### Agent Creation

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import CodeInterpreterTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential

project = AIProjectClient(endpoint=ENDPOINT, credential=DefaultAzureCredential())

agent = project.agents.create_version(
    agent_name="agent-slug-name",
    definition=PromptAgentDefinition(
        model="gpt-5.4",
        instructions="Your system prompt here...",
        tools=[CodeInterpreterTool()],
    ),
)
```

**Key facts:**
- Agents are referenced by NAME, not ID, in the new API
- `create_version()` updates an existing agent if the name matches
- Re-hiring (calling `create_version()` again) pushes new instructions immediately

### Calling Agents via Responses API

```python
openai = project.get_openai_client()

response = openai.responses.create(
    extra_body={
        "agent_reference": {
            "name": "agent-slug-name",
            "type": "agent_reference",
        }
    },
    input="Your message here",
)

text = response.output_text
response_id = response.id  # For conversation chaining
```

### Conversation Chaining

Pass `previous_response_id` to continue a conversation:

```python
response2 = openai.responses.create(
    extra_body={
        "agent_reference": {"name": "agent-slug-name", "type": "agent_reference"},
        "previous_response_id": response.id,
    },
    input="Follow-up message",
)
```

### Fallback Direct Call (No Agent Reference)

When falling back to a different model, call the Responses API directly:

```python
response = openai.responses.create(
    model="gpt-5.4",  # Fallback model
    input=[
        {"role": "developer", "content": agent_instructions},
        {"role": "user", "content": user_message},
    ],
)
```

### Models That Don't Support Code Interpreter

Strip `CodeInterpreterTool` for: `o3-pro`, `gpt-5.3-codex` (and other codex variants).

---

## 6. Infrastructure Patterns

### Storage

- **Azure Blob Storage** with `DefaultAzureCredential` — never key auth
- Containers: `results`, `workflows`, `schedules`, `evaluations`, `learnings`, `agent_memory`, `social`
- Auto-create containers on first write
- Private endpoint + VNET integration for App Service access

### App Service

- **B1 Linux** minimum for always-on (required for APScheduler)
- `gunicorn webapp.app:app --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --keep-alive 120`
- **1 worker only** — APScheduler runs in-process, multiple workers = duplicate jobs
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true` — let Oryx build, don't pip install at startup
- `WEBSITES_CONTAINER_START_TIME_LIMIT=1800` — large dependency tree needs time
- Deploy via ZIP: `az webapp deploy -n {app} -g {rg} --src-path {zip} --type zip`

### Scheduling

- APScheduler `BackgroundScheduler` running inside the FastAPI process
- Schedules stored in blob storage `schedules` container — survives restarts
- Sync from blob every 5 minutes
- Cron expressions for overnight jobs, morning briefs, maintenance sweeps

---

## 7. Content Filter Management

### False Positive Prevention

Security agents (especially on o3-pro) can trigger content filter jailbreak detection when describing attack scenarios. Prevention:

1. Frame prompts as "authorized defensive security analysis"
2. Include a preamble on retry: "You are performing legitimate enterprise security work..."
3. Avoid meta-referencing ("you are an AI agent") — triggers self-awareness filters
4. Use concrete, professional language instead of dramatic exploit narratives in the prompt (the agent will still be dramatic in its response — the personality is baked in)

### Retry Strategy for Content Filter Hits

```python
if is_content_filter and attempt == 0:
    # Retry once with defensive preamble
    message = CONTENT_FILTER_PREAMBLE + message
    time.sleep(5)
    continue
```

Don't retry more than once — if the content filter triggers twice, the prompt itself needs rewording.

---

## 8. Lessons Learned (The Hard Way)

### Model & Rate Limits
- **Always check actual TPM before setting timeouts.** A 360s timeout on a 5K TPM model that needs 25K tokens = guaranteed timeout.
- **TPM is per-minute, not per-request.** A single call CAN exceed TPM — it just takes proportionally longer.
- **RPM is the real bottleneck on reasoning models.** o3-pro at 3 RPM means 20s minimum between calls, even if TPM is high.
- **Scale BEFORE you need it.** Check quota (`az cognitiveservices usage list`), push to the limit. Unused quota costs nothing on GlobalStandard (pay-per-token).

### Agent Design
- **Prompts are code.** Test them. Track their token count. Profile them against your TPM budget.
- **The orchestrator owns routing, not the agents.** Agents shouldn't know who their teammates are — the handoff template provides context.
- **Reviewers need code, not briefs.** Cap the original request for reviewer roles. They review what the builders produced.
- **Fallbacks must be real.** A fallback that logs and re-raises is worse than no fallback — it gives false confidence in the logs.

### Operations
- **Never test locally with production credentials.** Deploy to Azure, test there.
- **Never deploy while a job is running.** The in-process thread dies when the container recycles. Check `/api/jobs/running` first. Checkpoints will survive, but the active step has to restart.
- **1 worker for scheduler workloads.** Multiple gunicorn workers = multiple schedulers = duplicate jobs.
- **DefaultAzureCredential everywhere.** No keys in code, no keys in env vars, no keys in App Settings.
- **Blob storage is the source of truth.** Results, schedules, agent memory — all in blob. Local files are temporary.

### Debugging
- **App Service logs:** `az webapp log download -n {app} -g {rg} --log-file /tmp/logs.zip`
- **Look for `*_default_docker.log`** — that's the application stdout
- **Filter for orchestrator events:** `grep "Marge received\|plan:\|Step.*failed\|Job work.*complete"`
- **Rate limit hits show as:** `Primary model {model} failed for {role}. Trying fallback: {fallback}`

---

## 9. Cost Optimization

### GlobalStandard (Pay-Per-Token) Sweet Spot

On GlobalStandard SKU, you pay per token consumed — **unused capacity costs nothing.** This means:

1. **Max out your quota allocations.** There's zero cost to having 80K TPM allocated if you only use 5K in a given minute.
2. **The only cost driver is actual usage.** Trim prompts, reduce context, and short-circuit unnecessary steps.
3. **Feedback loops are expensive.** A Martin→Gil→Martin loop is 3 full agent calls. Set feedback triggers thoughtfully.

### Token Savings Checklist

- [ ] Remove team relationship sections from agent prompts (-200-500 tokens each)
- [ ] Condense catchphrase lists to 1-2 lines (-100-200 tokens each)
- [ ] Cap reviewer request context to 3K (-3,000 tokens per reviewer call)
- [ ] Set per-role context limits (don't dump all output to all agents)
- [ ] Use context routing (agents only see what they need)
- [ ] Reduce `SUMMARY_PER_AGENT_LIMIT` for Marge's final summary

---

*This playbook is a living document. Update it as the team evolves and new patterns emerge.*
*Last updated: March 15, 2026*
