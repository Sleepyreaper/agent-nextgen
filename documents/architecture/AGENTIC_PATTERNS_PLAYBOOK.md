# Agentic Architecture Patterns — Springfield Core Team Playbook

> Battle-tested patterns from building and operating a multi-agent AI team on Azure AI Foundry.
> These patterns are portable — apply them to any agentic solution.

---

## 1. The Orchestrator is a Manager, Not a Router

**Pattern:** The orchestrator agent (Marge) doesn't just dispatch tasks — she reads the brief, understands each agent's strengths and weaknesses, writes tailored instructions per agent, manages context flow, handles feedback loops, and summarizes results.

**Why it matters:** A dumb router sends the same context to everyone and hopes for the best. A manager thinks about what each person needs to succeed.

**Implementation:**
- The orchestrator's planning prompt includes team profiles with strengths, weaknesses, and when to use each agent
- The `task` field in each step is Marge's specific instructions to that agent, not a generic assignment
- The orchestrator decides scope (code/ui/full/security/research) based on the brief — the user doesn't pick

**Anti-pattern:** Hardcoding workflows in Python code instead of letting the orchestrator reason about what's needed.

---

## 2. Feedback Loops Are Where Quality Happens

**Pattern:** After a builder produces code, a reviewer grades it. If the grade is below threshold, the builder revises. This cycle repeats up to N times. The reviewer and builder maintain conversation context across iterations.

**Why it matters:** First-draft code is demo quality. Reviewed-and-revised code is production quality. The feedback loop is the difference.

**Implementation:**
- `FEEDBACK_LOOPS` config: reviewer role, builder role(s), trigger keywords, max iterations
- Trigger keywords: "grade: d", "grade: f", "critical", "must be fixed"
- Builders list supports multiple targets — reviewer feedback routes to whoever wrote the code
- `chat_with_memory()` chains response IDs so agents remember the full thread during revisions
- `FEEDBACK_TEMPLATE` includes the original project context so builders understand why they're revising

**Key numbers:**
- Quality feedback: up to 2 cycles
- Security feedback: up to 1 cycle
- Each cycle = builder revision + reviewer re-review

---

## 3. Context Routing — Not Everyone Sees Everything

**Pattern:** Each agent only receives output from the agents they need to read. Reviewers see full code. Builders see architecture. Researchers see nothing (they go first). Docs see everything (they go last).

**Why it matters:** Dumping all context on every agent causes timeouts, truncation, and unfocused output. Smart routing keeps agents focused and prompts manageable.

**Implementation:**
- `CONTEXT_ROUTING` dict: maps each role to the list of roles whose output they receive
- `CONTEXT_LIMITS` dict: per-role character limits for context passed to downstream agents
- Builders (engineer/frontend): 25,000 chars — reviewers must see ALL the code
- Researchers: 6,000 chars — summaries are sufficient
- The orchestrator request text is capped at 15,000 chars for all agents — Marge's task descriptions carry the specific instructions

**Anti-pattern:** Passing the full project request (with entire repo context) to every agent. This caused 408 timeouts.

---

## 4. Token Management is Architecture

**Pattern:** Deliberately design how much context each agent receives, how much output they're expected to produce, and how feedback is sized. These are architecture decisions, not afterthoughts.

**Key limits:**
| What | Chars | ~Tokens |
|------|-------|---------|
| Engineer/Frontend output → reviewers | 25,000 | 6,250 |
| Architect output → builders | 15,000 | 3,750 |
| Reviewer output → builders (feedback) | 8,000 | 2,000 |
| Builder output → reviewer (revision) | 15,000 | 3,750 |
| Summary per agent | 4,000 | 1,000 |
| Full 7-agent pipeline | ~77,000 | 19,250 |
| With 2 feedback cycles | +23,000 | +5,750 |

**All within 128K+ context windows of modern models.**

---

## 5. Trust and Evaluation Must Be Built In

**Pattern:** Every agent response produces a `response_id`. After a job completes, evaluate those responses using Foundry's built-in evaluators. Aggregate into per-agent trust scores. Flag anomalies.

**Evaluators used:**
- Quality: coherence, fluency
- Safety: violence, hate/unfairness, self-harm, code vulnerability
- Agent: task adherence

**Implementation:**
- `evaluations.py`: `evaluate_job()` fires automatically after every orchestration
- Results stored in blob storage, aggregated by `get_trust_dashboard()`
- Trust score: 0-100 composite of quality metrics × safety pass rate
- Anomaly flags: trust < 60, safety pass rate < 90%

**Why it matters:** You can't govern what you don't measure. If Bob starts producing violent content or Gil's code quality drops, you see it immediately.

---

## 6. The Code Formatting Contract

**Pattern:** Agents that produce code MUST format it as:
```
### path/to/file.ext
\`\`\`language
[complete file content]
\`\`\`
```

**Why it matters:** The project engine extracts code blocks from agent output, commits them to branches, and opens PRs. Without consistent formatting, extraction fails and PRs are empty.

**Implementation:**
- `HANDOFF_TEMPLATE` says "MANDATORY" — agents are told this is required, not optional
- `_extract_code_blocks()` handles 5 patterns: heading + fence, fence with filename, backtick-path + fence, `// File:` comment inside fence, nearby path reference
- Deduplication keeps the latest version (post-feedback revision)

**Anti-pattern:** Agents writing code as inline descriptions or numbered sections without file paths. Extraction misses it all.

---

## 7. Marge-First Workflow Design

**Pattern:** Every workflow starts and ends with the orchestrator:
```
0. MARGE plans → dispatches team
...agents work, feedback loops fire...
N. MARGE summarizes → delivers to user
```

**Why it matters:** The orchestrator provides continuity. She knows the full picture when no individual agent does.

**Workflows defined:**
| Scope | Pipeline |
|-------|----------|
| Code | Marge → Troy → Hank → Gil → Martin ↔ Gil → Bob ↔ Gil → Snake → Lisa → Marge |
| UI | Marge → Troy → Artie → Gil (APIs) → Martin ↔ builders → Bob ↔ builders → Lisa → Marge |
| Full | Marge → Troy → Hank → Gil ∥ Artie → Martin ↔ each → Bob ↔ each → Snake → Lisa → Marge |
| Security | Marge → Bob → Gil → Martin ↔ Gil → Bob re-review → Lisa → Marge |
| Research | Marge → Troy → Hank → Lisa → Marge |
| Auto | Marge reads the brief and decides which workflow to use |

---

## 8. Persistent Jobs Survive Restarts

**Pattern:** Job state persists to blob storage. The in-memory queue is the fast path; blob is the durable backup. Jobs can be listed, polled, and cancelled across app restarts.

**Implementation:**
- `submit_job()` saves to blob immediately
- `get_job()` checks memory first, falls back to blob
- `list_jobs()` merges in-memory + blob
- `cancel_job()` sets a threading.Event; orchestrator checks `is_cancelled()` between steps
- Job states: running, completed, failed, cancelling, cancelled

---

## 9. Error Resilience

**Pattern:** The system retries transient failures, monitors content filter hits, and continues when individual agents fail.

**Implementation:**
- `chat_with_memory()` retries 408 timeouts AND 429 rate limits with exponential backoff (4 attempts)
- Orchestrator `_execute_step_safe()` retries each step 2 times
- Content filter hits logged to `_content_filter_log` with role, error, timestamp
- Failed agents don't kill the pipeline — the step is marked failed and the job continues

---

## 10. Cost Visibility

**Pattern:** Track token usage per agent, per job. Estimate costs based on model pricing. Make this data available via API.

**Implementation:**
- `_record_usage()` in factory.py logs every call: role, model, input/output tokens, elapsed time
- `get_usage_metrics()` aggregates by agent and total
- `/api/metrics/costs` estimates USD per agent based on Azure AI Foundry pricing
- Job results include `usage` dict with total tokens and elapsed seconds

---

## Applying These Patterns to New Projects

When building a new agentic solution:

1. **Start with the orchestrator.** Define its planning prompt. Give it team profiles. Make it a manager.
2. **Define your workflows.** What agents are needed? In what order? What are the handoff points?
3. **Set up feedback loops.** Who reviews? What triggers revision? How many cycles?
4. **Design context routing.** Who needs to see what? Set per-role limits.
5. **Add trust evaluation.** Wire response IDs to Foundry evals. Build a dashboard.
6. **Define the code contract.** If agents produce artifacts, specify the format.
7. **Make jobs persistent.** Don't lose work on restarts.
8. **Build error resilience.** Retry transient failures. Log content filter hits.
9. **Track costs.** Know what each agent costs per job.
10. **Let the orchestrator decide scope.** Don't make the user pick the workflow.

---

## 11. Hard Timeouts Prevent Ghost Jobs

**Pattern:** Every API call to a model has a hard timeout enforced via `concurrent.futures.ThreadPoolExecutor`. Model-aware: o3-pro gets 8 min, gpt-5.4-pro gets 4 min, gpt-5.4 gets 3 min. Hard timeout retries are capped at 1.

**Why it matters:** Without hard timeouts, a hung API call blocks a thread forever. Your job shows "running" for hours and never completes. Rate limit retries compound the problem.

**Implementation:**
- `MODEL_TIMEOUTS` dict maps model prefixes to timeout seconds
- Each `openai.responses.create()` call runs inside a `ThreadPoolExecutor` with `.result(timeout=timeout_secs)`
- `concurrent.futures.TimeoutError` → raises `TimeoutError` → caught by retry logic
- Hard timeouts only retry once (rate limit timeouts retry up to 4x)

---

## 12. Queue-First, Thread-Fallback Execution

**Pattern:** Jobs are submitted to Azure Queue Storage for durable execution. A separate worker process polls the queue. If the queue is unavailable, jobs fall back to in-process thread execution.

**Why it matters:** Thread-based execution dies on app restarts. Queue-based execution persists messages until a worker processes them. The fallback ensures the system works even when the queue isn't configured.

**Implementation:**
- `submit_job_queued()` tries queue first, falls back to thread
- `QUEUE_ENABLED` env var controls whether queue is active
- Worker process (`core_team.worker`) polls queue, dispatches to handler registry
- Dead letter queue for messages that fail repeatedly
- Visibility timeout = 2h 10min (longer than any job)

---

## 13. Redis for Shared Real-Time State

**Pattern:** Agent activity, job cache, usage metrics, and rate limiting live in Redis instead of in-memory dicts. State survives restarts and is shared between web + worker processes.

**Why it matters:** In-memory state vanishes on every App Service restart. Redis provides sub-millisecond reads for dashboard polling (activity updates every 3s) and persists across deploys.

**Implementation:**
- `redis_state.py` module with graceful fallback to in-memory if Redis unavailable
- Job state read path: Redis cache → in-memory → blob storage (3-tier)
- Agent activity: `activity:{role}` keys, overwritten on each status change
- Rate limiting: `rate:{model}:minute` keys with 60s TTL

---

## 14. Validate Agent Code Before Committing

**Pattern:** Before committing agent-produced code to a GitHub PR, run syntax validation per language. Warnings are logged and included in the PR body, but don't block the commit.

**Why it matters:** Agents produce broken syntax more often than you'd expect — missing imports, unclosed brackets, invalid JSON. Committing broken code wastes review cycles.

**Implementation:**
- `code_validation.py` with registered validators: Python (ast.parse), JSON, YAML, HTML, Bicep
- `validate_code_blocks()` returns per-file results + a markdown warnings block
- Wired into both `run_project()` and `run_project_on_repo()` before commit step
- Validation warnings appear in the PR body so reviewers see them immediately

---

## 15. Content Filter Retry with Defensive Preamble

**Pattern:** When an agent hits Azure's content filter (common with Bob's theatrical exploit narratives), automatically retry once with a defensive preamble explaining the legitimate enterprise context.

**Why it matters:** False positives on content filters kill security agents. Bob describes exploits theatrically — "Were I so inclined, I would exfiltrate..." — which triggers jailbreak detection. The preamble clarifies intent.

**Implementation:**
- On first content filter hit: prepend a preamble to the message and retry
- Preamble: "You are a professional AI assistant performing legitimate enterprise work..."
- Only retries once — if the second attempt also triggers, let it fail
- Content filter hits logged to `_content_filter_log` with role, error, timestamp

---

## 16. Embedding-Based Knowledge Accumulation

**Pattern:** After each job, Lisa extracts learnings (key findings, patterns, mistakes). Each learning gets an embedding vector via `text-embedding-3-large`. Future jobs retrieve relevant learnings via cosine similarity.

**Why it matters:** Keyword matching misses synonyms and conceptual similarity. "VNet configuration" won't match "virtual network setup." Embeddings capture semantic meaning.

**Implementation:**
- Embeddings stored alongside learning records in blob storage
- Query embedding computed at retrieval time, compared via cosine similarity
- Falls back to keyword matching for older records without embeddings
- Top 3 relevant learnings injected into Marge's planning context

---

## Applying These Patterns to New Projects (Updated)

When building a new agentic solution:

1. **Start with the orchestrator.** Make it a manager, not a router.
2. **Define workflows and feedback loops.** Quality happens in the revision cycle.
3. **Design context routing.** Not everyone sees everything.
4. **Add hard timeouts from day one.** Every API call needs a kill switch.
5. **Use queue-based execution.** Threads are fragile. Queues are durable.
6. **Put shared state in Redis.** In-memory state is a restart away from zero.
7. **Add trust evaluation.** Measure quality and safety on every response.
8. **Validate agent output.** Syntax check code before committing.
9. **Track costs per agent.** Know where your budget goes.
10. **Handle content filters.** Defensive preambles reduce false positive failures.
11. **Build embedding-based knowledge.** Your team should get smarter on every job.
12. **Add observability immediately.** OpenTelemetry + App Insights from the first deploy.

---

*This playbook was developed by Brad Allen's Springfield Core Team — 11 AI agents on Azure AI Foundry, battle-tested on real projects in production. March 2026. Brad is a Principal Enterprise Architect at Microsoft, Oil Gas & Energy.*
