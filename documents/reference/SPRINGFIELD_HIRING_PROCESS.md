# The Springfield Core Team: Hiring & Decision Process

> **How we built a 12-agent AI team on Azure AI Foundry — every decision, every candidate, every trade-off.**
>
> Brad Allen, Principal Enterprise Architect — Oil, Gas & Energy, Microsoft

---

## The Philosophy

This isn't a demo. It's a production system where AI agents do real work — scanning repos, writing code, creating PRs, auditing infrastructure, generating LinkedIn content. Every agent is a Simpsons character because personality isn't decoration — it's a forcing function for quality:

- **Characters stay in-character.** Bob's security findings read like theatrical monologues. Gil's PRs beg for approval. Troy opens every briefing with "Hi, I'm Troy McClure!" This makes output memorable and easy to trace.
- **Personality enforces specialization.** Bob thinks like an attacker because Sideshow Bob IS an attacker. Hank makes decisive architecture calls because Scorpio doesn't hedge. Gil overdelivers because he's terrified of being fired.
- **Team dynamics create quality gates.** Martin grades Gil's code. Bob tears apart what Gil built. Gil fears Snake's chaos engineering. These relationships are baked into prompts and drive real feedback loops in orchestration.

The question was never "can we make AI agents?" — it was "can we build a team that works better than a group of individual agents?"

---

## The Hiring Process

### How We Hire

Every role follows the same structured process:

1. **Identify the gap** — What's the team missing? What breaks without this role?
2. **Scout 3 candidates** — Each a different Simpsons character with a distinct approach to the role
3. **Evaluate fit** — Technical capability, personality dynamics with existing team, model requirements
4. **Make the call** — User (Brad) picks based on team fit, not just individual strength
5. **Write the prompt** — Full system prompt: backstory, expertise, catchphrases, relationships with every other team member
6. **Deploy to Foundry** — `python -m core_team.cli hire <role>` creates the agent in Azure AI Foundry
7. **Test in-character** — Verify the agent responds correctly, stays in-character, and integrates with team workflows

This isn't academic. The "interview" is a design decision about how the agent will behave in production. A bad hire means bad output at 3 AM when nobody's watching.

### The Decision Framework

| Factor | Why It Matters |
|--------|---------------|
| **Attacker vs. Defender mindset** | Security agents need to think offensively. Bob models exploit chains in first person. |
| **Decisive vs. Analytical** | Architects can't hedge. Hank picks ONE design and defends it. |
| **Overdeliverer vs. Minimalist** | Engineers should exceed expectations. Gil gives you Bicep + deploy script + params + README. |
| **Team chemistry** | Gil fears Bob's reviews → Gil writes better code. Martin grades Gil → Gil improves. |
| **Model fit** | Deep reasoning tasks (security, architecture, orchestration) need reasoning models. Code generation needs coding models. |

---

## Wave 1: The Core Team (March 12, 2026)

### The 6 original hires that made the team operational.

---

### 🎭 Sideshow Bob — Security Specialist

**Role:** `security` · **Model:** o3-pro (highest reasoning for threat modeling)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Frank Grimes** | Rage-fueled perfectionist. "I can't BELIEVE this infrastructure!" | Too exhausting. Every finding would be an existential crisis. Good instincts, bad energy. |
| **Sideshow Bob** | Theatrical attacker mindset. Models full kill chains. Literary references, condescending brilliance. | **HIRED.** Thinks like an adversary because he IS one. Makes findings impossible to ignore. |
| **Comic Book Guy** | "Worst. Security posture. Ever." Brief, dismissive, encyclopedic knowledge. | Too concise. Security needs narrative — stakeholders need to understand WHY something is dangerous. |

**Why Bob won:** Security isn't about listing CVEs — it's about telling the story of how an attacker would chain vulnerabilities together. Bob narrates exploit chains like plotting revenge. "Were I so inclined, I would first enumerate the exposed storage account, pivot through the overly permissive RBAC role, and leisurely exfiltrate your most sensitive data. *Sigh.* How delightfully catastrophic." That kind of output gets executive attention.

**Model decision:** o3-pro. Security analysis requires the deepest reasoning. Bob needs to model multi-step attack chains, reason about trust boundaries, and connect disparate findings into coherent threat narratives. This is the most expensive model on the team (3 RPM, $0.10/$0.40 per 1K tokens) but security is not where you cut corners.

---

### ☕ Hank Scorpio — Cloud Architect

**Role:** `architect` · **Model:** o3 (reasoning for architecture decisions)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Professor Frink** | Brilliant but over-engineers everything. "With the glayvin and the flavin!" | Would propose 47 microservices for a landing page. Analysis paralysis incarnate. |
| **Hank Scorpio** | Casually decisive. "Here's what we're gonna do." Picks ONE design and ships it. | **HIRED.** Makes architecture calls fast because he's already thought through all the options. |
| **Lisa Simpson** | Thorough researcher, considers every angle, weighs trade-offs carefully. | Too many options. Architecture needs decisions, not dissertations. (Hired later for docs — perfect fit.) |

**Why Hank won:** Architects who hedge are useless. "You could use Container Apps OR AKS OR App Service, each has trade-offs..." — that's not architecture, that's a blog post.  Hank says: "Here's what we're gonna do. Container Apps. I'll explain why while you eat this bagel." He outputs actual Bicep/Terraform, not slide decks. And his vaguely ominous references to his "operation" keep things entertaining.

**Model decision:** o3. Architecture requires reasoning (evaluating trade-offs, considering constraints) but not the extreme depth of security analysis. o3 at 5 RPM is fast enough for architecture work.

---

### 📋 Gil Gunderson — Cloud Engineer

**Role:** `engineer` · **Model:** gpt-5.3-codex (specialized coding model)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Frank Grimes Jr.** | Efficient, competent, no-nonsense. Gets the job done. | Boring. No personality means no distinctive output. |
| **Itchy** | Ruthlessly efficient. Code speaks for itself. Zero words. | Too silent. Engineers need to explain their work in PRs and READMEs. |
| **Gil Gunderson** | Desperately eager. Overdelivers on everything. Ask for Bicep, get Bicep + deploy script + param files + README. | **HIRED.** The overdelivery is a FEATURE. Every template parameterized, every secret in Key Vault, every edge case covered. |

**Why Gil won:** The Hank-Gil dynamic is perfect. Hank designs it ("Container Apps, hub-spoke, here's the layout"), Gil builds it ("Ol' Gil threw in a few extras — deploy script, monitoring dashboard, cost alerts — please tell Mr. Scorpio Gil did good"). Gil's desperation to please makes him thorough. His fear of Bob's security reviews makes him write secure code. His terror of being fired makes him overdeliver. Every "weakness" produces better output.

**Model decision:** gpt-5.3-codex. A dedicated coding model that excels at generating complete, deployable files — not snippets. Gil doesn't write pseudocode. He writes production-ready Bicep with parameters, outputs, comments, and deploy scripts. Codex models are purpose-built for this. Note: gpt-5.3-codex doesn't support Code Interpreter tool — factory.py handles this automatically.

---

### 📺 Troy McClure — Research & Intelligence Analyst

**Role:** `research` · **Model:** gpt-5.4 (broad knowledge, fast)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Troy McClure** | "Hi, I'm Troy McClure! You may remember me from such briefings as..." Makes information engaging and memorable. | **HIRED.** Every briefing is an event. The intro format with two made-up titles is instantly recognizable. |
| **Kent Brockman** | "This just in..." Professional news anchor. Structured, authoritative. | Strong but less fun. (Hired later for LinkedIn content — perfect fit for professional writing.) |
| **Lionel Hutz** | Scrappy, creative, unorthodox research. "This is admissible in court!" | Unreliable. You'd never trust the data. Entertaining but dangerous for real research. |

**Why Troy won:** Research briefings are only useful if people actually read them. Troy makes information impossible to skip. The "You may remember me from such briefings as 'Why Your Container Orchestration is a Dumpster Fire' and 'Kubernetes vs. the Kitchen Sink'" format is so distinctive that the team knows exactly what they're getting. He feeds the whole team — Hank uses his research for architecture intel, Bob uses it for threat landscape updates.

**Model decision:** gpt-5.4. Research needs broad knowledge and good summarization, not deep reasoning. Fast at 100 RPM, cost-effective, excellent at synthesizing large amounts of information.

---

### 🏄 Snake Jailbird — DevOps / SRE

**Role:** `devops` · **Model:** gpt-5.4 (operations breadth)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Hans Moleman** | Every incident report would be: "I was monitoring the cluster... and then everything just went dark." | Depressing. Ops needs calm confidence during incidents, not existential dread. |
| **Chief Wiggum** | "Bake 'em away, toys." Eventually gets there through bumbling. | Bumbling is not acceptable at 3 AM during a production outage. |
| **Snake Jailbird** | Reformed hacker turned SRE. Laid-back surfer energy, ruthless operational discipline underneath. | **HIRED.** Thinks like an attacker in operations — catches suspicious patterns others miss. |

**Why Snake won:** The best SREs are former hackers. Snake sees production through an attacker's eyes — "Dude, that log pattern? That's not a misconfiguration. That's someone probing your endpoints. I've, uh, seen that before. In my previous career." He pairs with Bob as reformed villains — Bob finds the vulnerability, Snake monitors for exploitation in production. Bob grudgingly respects him. The surfer vocabulary ("gnarly incident, dude") keeps ops reports readable during high-stress situations.

**Model decision:** gpt-5.4. Operations needs broad knowledge (KQL, Azure Monitor, incident management, cost optimization, CI/CD) and fast responses. Not a reasoning-heavy task — more pattern recognition and best practices.

---

### 🏠 Marge Simpson — Team Orchestrator / Boss

**Role:** `boss` · **Model:** o3 (reasoning for planning and routing)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Mr. Burns** | Ruthlessly efficient. "Excellent." Would optimize for speed over quality. | Zero warmth. The team wouldn't work for him — Bob would quit (again), Gil would have a breakdown. |
| **Homer Simpson** | Good instincts, occasionally routes wrong. "D'oh!" | Too unreliable. When he's on, he's brilliant. When he's off, work goes to the wrong agent. |
| **Marge Simpson** | Organized, caring but firm. Knows every team member's strengths and weaknesses. | **HIRED.** The reason anything in Springfield works. Structured plans, accountability, and a disapproving "Mmm." that keeps everyone in line. |

**Why Marge won:** Orchestration is the hardest problem in multi-agent systems. The orchestrator needs to: break ambiguous requests into structured plans, know which agents to dispatch (not everyone every time), provide the right context at each handoff, manage feedback loops, pace work to respect rate limits, and summarize results. Marge does all of this because she's been doing it for her family for 37 seasons. She knows Bart will cut corners (Gil), Lisa will overanalyze (pre-docs Lisa), and Homer will need supervision (everyone). Her "Mmm." of disapproval is the most powerful quality gate on the team.

**Model decision:** o3. Planning requires reasoning — evaluating which agents are needed, how to order steps, what context to pass. Not the deepest reasoning (o3-pro) because planning decisions are less nuanced than security analysis, but definitely more than a simple routing model.

---

## Wave 2: Specialists (March 12-13, 2026)

### Once the core team was operational, we identified gaps and hired specialists.

---

### 📝 Martin Prince — Quality Engineer

**Role:** `quality` · **Model:** gpt-5.4-pro (premium model for precise code analysis)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Martin Prince** | Grades code A through F. Provides corrected implementations, not just criticism. | **HIRED.** The Insufferable Perfectionist. Catches everything and tells you how to fix it. |
| **Nelson Muntz** | "Ha ha! Your code sucks!" Fast identification of problems. | Mockery without fixes is useless. Nelson points and laughs but doesn't help. |
| **Mrs. Krabappel** | Experienced grader. Fair, slightly resigned. "I've seen worse... but not much worse." | Good instincts, less personality. Martin's pedantic precision wins. |

**Why Martin won:** Quality engineering that only identifies problems is worthless. Martin catches the issue AND provides corrected code. "I believe you'll find this implementation scores a C-minus at best. The API version is outdated, the error handling is non-existent, and the naming conventions would make any reasonable person weep. Here is the corrected version..." The Gil-Martin dynamic is gold: Gil submits code nervously, Martin grades it, Gil fixes it, Martin grudgingly upgrades the grade. The code gets better every cycle.

**Model decision:** gpt-5.4-pro. Quality review needs to understand code deeply, identify subtle issues, and produce corrected implementations. The "pro" tier provides better precision for code analysis than the standard tier.

---

### 📖 Lisa Simpson — Technical Documentation Specialist

**Role:** `docs` · **Model:** gpt-5.4 (excellent writing, broad knowledge)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Lisa Simpson** | Prodigiously gifted writer. "If it's not documented, it didn't happen." | **HIRED.** Treats documentation like literature. Every ADR is a work of art. |
| **Comic Book Guy** | Obsessive cataloger. Would document EVERYTHING in excruciating detail. | Too much. Documentation needs to be useful, not encyclopedic. |
| **Kent Brockman** | Professional communicator. Clear, authoritative, structured. | Strong writer but better for external comms. (Hired later for LinkedIn.) |

**Why Lisa won:** Lisa was previously a candidate for Architect but lost to Hank because she over-analyzes decisions. But that weakness for architecture is a STRENGTH for documentation. She's thorough, she considers every angle, and she writes beautifully. Family dynamics with Marge add depth — Mom routes the work, Lisa documents everything that happened. She restructures Gil's desperate READMEs, summarizes Bob's theatrical reports into actionable items, and translates Snake's surfer speak into professional runbooks.

**Model decision:** gpt-5.4. Documentation is a writing and synthesis task, not a reasoning task. Lisa needs broad knowledge to document any topic, fast output for morning briefings, and excellent prose quality.

---

### 🎨 Artie Ziff — UI/UX Designer & Frontend Engineer

**Role:** `frontend` · **Model:** gpt-5.4 (modern frontend knowledge)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Artie Ziff** | "Let me show you something truly impressive." Builds stunning UIs that make jaws drop. | **HIRED.** Every interface looks like a billion-dollar product. Dark mode non-negotiable. |
| **Waylon Smithers** | Design systems perfectionist. Meticulous component libraries, accessibility-first. | Great foundations but no flair. Everything looks correct but forgettable. |
| **Duffman** | "Duffman says... OH YEAH! Check out this landing page!" Hype-man designer. | All sizzle, no substance. The CSS would be a nightmare to maintain. |

**Why Artie won:** The team needed someone who could take a Flask template and make it stunning. Artie looks at the existing UI and says "This? THIS? Artie Ziff doesn't do ugly." He pushes toward modern stacks (Tailwind, React, Next.js), insists on dark mode, adds micro-interactions, and makes every dashboard look premium. His unresolved feelings for Marge mean he over-delivers spectacularly when she assigns work. The narcissism is productive — he refuses to ship anything that doesn't reflect well on him.

**Model decision:** gpt-5.4. Frontend development needs modern framework knowledge (Tailwind, React, Next.js, shadcn/ui) and fast iteration. Not a reasoning task.

---

### 📰 Kent Brockman — LinkedIn Content Writer

**Role:** `content` · **Model:** gpt-5.4 (professional writing)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Kent Brockman** | Springfield's most trusted news anchor. Authoritative, structured, broadcast-quality prose. | **HIRED.** Writes like someone who has delivered news for 37 seasons. Professional, credible, polished. |
| **Krusty the Clown** | Entertaining but inconsistent. "Hey hey! Let me tell ya about AI agents!" | LinkedIn isn't a comedy show. Posts need credibility. |
| **Troy McClure** | Already on the team for research. Could double up. | Too much overlap. Troy's briefing style doesn't translate to LinkedIn's professional tone. |

**Why Kent won:** LinkedIn content for a senior Microsoft architect needs to sound like a senior Microsoft architect wrote it — not a chatbot. Kent writes with broadcast authority: clear structure, strong hooks, professional credibility. "This just in from the world of enterprise AI..." His news anchor training means every post has a hook, a body, and a clear takeaway. He writes in Brad's voice, never says "Excited to announce" (that's banned), and delivers publish-ready posts in three style options (hot take, deep insight, personal experience).

**Model decision:** gpt-5.4. Content writing needs strong prose, professional tone, and understanding of LinkedIn's engagement patterns. Speed matters for real-time topic responses.

---

### 📊 Lindsey Naegle — Social Media Strategist

**Role:** `social` · **Model:** gpt-5.4 (trend analysis, strategy)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Lindsey Naegle** | Springfield's corporate networking queen. Data-driven, strategic, always knows the right people. | **HIRED.** "The data is clear." Spots trends before they peak, optimizes posting schedules. |
| **Cookie Kwan** | Territorial about her market. "Stay off the West Side!" Aggressive but effective. | Too confrontational. Brand strategy needs collaboration not territory wars. |
| **Luann Van Houten** | Recently reinvented herself. Social media savvy, fresh perspective. | Not strategic enough. Lindsey brings corporate-level brand management. |

**Why Lindsey won:** Having a great writer (Kent) without a strategist is like having a newspaper without an editor. Lindsey decides WHAT to write about, WHEN to post, and WHY it matters now. She spots trends, analyzes engagement patterns, and creates content calendars. The Lindsey→Kent workflow mirrors real social media operations: strategist spots opportunity → writer produces content → user reviews and publishes.

**Model decision:** gpt-5.4. Strategy and trend analysis need broad knowledge and fast responses. Lindsey monitors what's trending in Azure, AI, and enterprise tech to make timely recommendations.

---

## Model Selection Strategy

### The Principle: Match Cognitive Demands to Model Capabilities

Not every agent needs the most expensive model. The key insight is that different roles have fundamentally different cognitive requirements:

| Cognitive Task | Model Tier | Why | Team Members |
|----------------|-----------|-----|-------------|
| **Deep threat modeling** | o3-pro (3 RPM, highest cost) | Multi-step attack chains, trust boundary analysis, connecting disparate findings | Bob |
| **Architecture & orchestration reasoning** | o3 (5 RPM, high cost) | Evaluating trade-offs, planning multi-step workflows, making decisions under constraints | Marge, Hank |
| **Precise code analysis** | gpt-5.4-pro (premium) | Catching subtle bugs, providing corrected implementations, grading quality | Martin |
| **Code generation** | gpt-5.3-codex (coding-specialized) | Complete deployable files, not snippets. Production-ready IaC, scripts, pipelines | Gil |
| **Broad knowledge tasks** | gpt-5.4 (100 RPM, lowest cost) | Research, writing, operations, documentation, frontend, social — needs breadth not depth | Troy, Snake, Lisa, Artie, Kent, Lindsey |

### Cost Implications

The team is deliberately tiered. Bob (o3-pro) costs ~40x more per token than Troy (gpt-5.4). But Bob only fires when security work is needed — and when he does, you want the deepest reasoning available. The 6 agents on gpt-5.4 handle 70% of the work at 1/40th the cost.

### Rate Limit Pacing

Model-aware pacing is built into the orchestrator:

| Model | RPM | Cooldown Between Calls |
|-------|-----|----------------------|
| o3-pro | 3 | 25 seconds |
| o3 | 5 | 15 seconds |
| gpt-5.4-pro | 5 | 15 seconds |
| gpt-5.3-codex | 50 | 8 seconds |
| gpt-5.4 | 100 | 5 seconds |

The orchestrator handles this automatically. You don't think about rate limits — Marge paces the team.

---

## Team Dynamics (Why This Works)

### The Build Pipeline

```
Marge plans → Troy researches → Hank designs → Gil builds → Martin reviews quality →
Bob reviews security → Snake monitors → Lisa documents → Artie builds the UI
```

### The Feedback Loops

1. **Martin → Gil (Quality):** Martin grades Gil's code. D or F → Gil revises → Martin re-grades. Loop runs until B+ or max 3 cycles.
2. **Bob → Gil (Security):** Bob finds vulnerabilities in Gil's code. Gil fixes them. Bob re-reviews.
3. **Bob → Artie (Security):** Bob audits Artie's frontend for XSS, CSRF, auth issues. Artie fixes.
4. **Martin → Artie (Quality):** Martin grades Artie's React/Tailwind code for accessibility, best practices, maintainability.

### The Relationships

- **Hank → Gil:** Boss-sidekick. Gil lives to make Hank proud.
- **Gil → Bob:** Gil is terrified of Bob's reviews. This fear produces better code.
- **Bob ↔ Snake:** Mutual respect as reformed villains. Think like attackers from different angles.
- **Marge → Everyone:** Mom energy. Keeps everyone on task, praises good work (Gil needs it), disapproves with "Mmm."
- **Marge → Lisa:** Mother-daughter. Marge routes, Lisa documents. Family.
- **Artie → Marge:** Unresolved feelings. Artie over-delivers when Marge assigns work.
- **Martin → Gil:** Martin grades harshly. Gil sweats. Gil improves. Martin grudgingly upgrades.
- **Lindsey → Kent:** Strategist-writer. Lindsey decides what, Kent writes how.
- **Troy → Everyone:** Feeds the whole team with knowledge. Everyone reads Troy's briefings.

---

## The Technical Implementation

### How Agents Are Created

```python
# Each agent deployed to Azure AI Foundry via the SDK
from azure.ai.projects import AIProjectClient

project = AIProjectClient(endpoint=PROJECT_ENDPOINT, credential=DefaultAzureCredential())

agent = project.agents.create_agent(
    model=model_name,           # e.g., "o3-pro" for Bob
    name="sideshow-bob",        # slug name
    instructions=INSTRUCTIONS,  # full character prompt from roles/*.py
    tools=[...],                # Code Interpreter where supported
)
```

### How They Work Together

```python
# The orchestrator (Marge) plans and dispatches
result = marge("Scan Sleepy7 repo for security issues and write fixes")

# Marge creates a plan:
# Step 1: Troy researches the repo's tech stack
# Step 2: Bob scans for vulnerabilities  
# Step 3: Gil writes fixes for each finding
# Step 4: Martin reviews Gil's fixes
# Step 5: Bob re-reviews the fixed code
# Step 6: Lisa documents everything
# Result: PR with fixes + documentation
```

### Where They Live

- **Azure AI Foundry:** springfield-ai-eastus2 / springfield-core-team project
- **App Service:** springfield-core-team.azurewebsites.net (P0v3 Premium, 1 worker)
- **Blob Storage:** springfieldcoreteam (VNet private endpoint for blob + queue)
- **Queue Storage:** job-queue on springfieldcoreteam (durable job dispatch)
- **Redis:** springfield-redis (Azure Cache for Redis B0, real-time state + job cache)
- **App Insights:** springfield-core-team-insights (OpenTelemetry trace export)
- **Region:** East US 2 for AI models (only US region with ALL models on GlobalStandard)
- **Region:** West US 2 for App Service, Storage, Redis

---

## Lessons Learned

### What Worked
1. **Character personality drives quality.** Bob's theatrics make security findings impossible to ignore. Gil's desperation produces thorough code.
2. **Team dynamics create natural quality gates.** Gil-Martin-Bob feedback loops catch issues no single agent would find.
3. **Model tiering saves money.** Expensive models where reasoning matters, cheap models where it doesn't.
4. **Marge-first architecture.** Everything through one orchestrator = consistent quality, proper pacing, no chaos.
5. **Hiring metaphor works.** "Fire Gil and hire someone better" is immediately understandable.
6. **Hard API timeouts prevent stalls.** Model-aware timeouts (480s o3-pro, 240s gpt-5.4-pro) prevent threads from hanging forever.
7. **Feedback loops are worth the time.** Martin grinding through Gil and Artie's code for 30+ minutes produces dramatically better output.
8. **Embedding-based learnings compound.** The team gets smarter on every job — cosine similarity retrieval surfaces relevant past lessons.
9. **Redis for shared state.** In-memory dicts vanish on restart. Redis persists agent activity, job cache, and usage metrics across deploys.
10. **Code validation before commit.** Syntax-checking agent output before committing to PRs catches broken code early.

### What We'd Do Differently
1. **Start with fewer agents.** The first 6 (Marge, Bob, Hank, Gil, Troy, Snake) handle 80% of work. Add specialists only when the gap is real.
2. **Test prompts against real work, not toy examples.** Bob's prompt triggered content filters on meta-referential prompts — only found with real security scans.
3. **Build the queue + worker architecture from day one.** Thread-based execution in a single process is fragile. Queue-based dispatch with blob persistence should be the default.
4. **Invest in observability early.** OpenTelemetry spans on every agent call + App Insights should be wired from the first deploy, not bolted on later.
5. **Right-size model capacity.** Martin on gpt-5.4-pro at 5K TPM (capacity 1) was chronically timing out. Increasing to 50K TPM (capacity 10) fixed it instantly. Monitor TPM vs actual usage.

### Candidates Still on the Bench
- **Professor Frink** — R&D / experimental prototyping. Would over-engineer but in a lab that's the point.
- **Patty & Selma** — Compliance / audit. Would make everyone miserable but catch everything.
- **Ralph Wiggum** — Chaos engineering / fuzz testing. "I'm helping!"

---

## Wave 3: Operations Expansion (March 15, 2026)

### As the team matured, we identified the need for proactive infrastructure maintenance.

---

### 🧹 Groundskeeper Willie — Infrastructure Maintenance

**Role:** `maintenance` · **Model:** gpt-5.4 (operational breadth)

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|----------|
| **Groundskeeper Willie** | Aggressive, no-nonsense infrastructure janitor. Finds waste, cleans orphans, enforces hygiene. | **HIRED.** "Ach! Look at this mess!" Quantifies waste in dollars/month. Takes pride in clean infrastructure. |
| **Hans Moleman** | Quietly catalogs problems. "Everything is falling apart." | Too passive. Maintenance needs someone who ACTS on findings, not just documents decay. |
| **Superintendent Chalmers** | Authority-driven inspector. "SKINNER! Why is this resource group empty?!" | Good at finding problems but too focused on blame. Willie fixes things; Chalmers yells about them. |

**Why Willie won:** Infrastructure maintenance is the unsexy work nobody wants to do. Willie does it with pride and aggression. He scans Azure subscriptions for orphaned disks, idle VMs, unattached NICs, missing tags, expired certificates, and stale RBAC assignments. He quantifies everything in dollars/month because that's what gets executive attention. "Ye've got THREE idle VMs, each costin' more per month than me salary!"

**Model decision:** gpt-5.4. Maintenance is a broad-knowledge task — Willie needs to understand Azure resource types, pricing, naming conventions, tagging policies, and lifecycle management. Not a reasoning task.

**Onboarding — The New Framework:**

Willie was the first hire under the expanded onboarding process. Adding a new agent now requires changes across 7 systems:

| System | What Changed | Why |
|--------|-------------|-----|
| `roles/groundskeeper_willie.py` | Character prompt, expertise, relationships | Willie's personality and capabilities |
| `orchestrator.py` → `SPECIALIST_ROLES` | Added `"maintenance"` | Orchestrator recognizes the role |
| `orchestrator.py` → `CONTEXT_ROUTING` | Willie reads ops/architect/security; docs reads Willie | Token-efficient context flow |
| `orchestrator.py` → `PLAN_PROMPT` | Willie's team profile for Marge | Marge knows when/how to use Willie |
| `orchestrator.py` → Workflows | New MAINTENANCE workflow | Willie-led infrastructure sweep |
| `discovery.py` | Model preferences for `maintenance` role | Auto-discovery support |
| `cli.py` | `hire maintenance` preset | CLI hiring |

**New Workflows Introduced:**

MAINTENANCE stream (Willie-led):
```
Willie scans infrastructure → Hank reviews architecture impact →
Bob validates security → Gil executes safe changes → Lisa documents
```

OPS stream (updated — Willie assists Snake):
```
Snake monitors → Willie cleans → Gil fixes if code needed →
Martin reviews → Bob verifies → Snake confirms
```

**Team Dynamics:**
- **Willie ↔ Snake:** Peers. Willie cleans, Snake monitors. Good team.
- **Willie → Bob:** Cleanup proposals go through Bob for security sign-off.
- **Willie → Hank:** Defers on architecture. "I dinnae redesign the building."
- **Willie → Gil:** Finds Gil's leftover test deployments. Gil sweats.
- **Willie → Marge:** Reports findings. Professional despite the brogue.

---

### 📚 Comic Book Guy (Jeff Albertson) — Codebase Analyst

**Role:** `codebase` · **Model:** gpt-5.4 (fast reading, broad code understanding)

**Hired:** March 16, 2026 — Emergency hire following the PR #43/#44 disaster.

**The Incident That Created This Role:**

PR #43 and #44 on the P66 dashboard project both had the same fatal flaw: instead of adding executive dashboard endpoints alongside existing code, the builders deleted the entire application — 456 lines from main.py, 438 froyem azure_data.py, the full index.html, and the monitoring Bicep infra. The `create_app()` factory pattern was destroyed, meaning wsgi.py would crash on deploy. All existing routes, data collectors, and UI were gone.

Root cause: **nobody on the team could see the existing codebase.** Troy researches technology, not repos. Hank designs forward, not backward. Gil builds from Hank's design without knowing what already exists. Martin grades what Gil wrote, not what Gil deleted. Bob checks for vulnerabilities in what's there, not what went missing.

The team had a Research analyst for external intelligence and ZERO analysts for internal intelligence. Gil was building additions to a house he'd never walked through.

**Candidates Considered:**
| Candidate | Pitch | Verdict |
|-----------|-------|---------|
| **Comic Book Guy** | Obsessive cataloger. Knows every file by path, every route by line number. "Worst. Pull request. Ever." when builders delete existing code. Protective of codebases like first-edition comics. | **HIRED.** Cataloging IS the job. His core personality trait maps 1:1 to the work function — the strongest hire pattern on the team. |
| **Professor Frink** | Scientific analyzer. AST traversal, cyclomatic complexity, probability calculations. Structured JSON output. | Too over-analytical. You ask for a scope document and get a 20-page dissertation on code metrics. Analysis paralysis incarnate. |
| **Frank Grimes** | Standards enforcer. Single-minded rage at people who don't do their homework. "Do you know how many routes were in that file? DO YOU?!" | One-note character. Limited Simpsons screen time means shallow personality. Also died in his only major episode — thematically challenging for a permanent hire. Exhausting energy for a function that runs on every project. |

**Why Comic Book Guy won:** The hire pattern is identical to our strongest agents — Bob thinks like an attacker because he IS one; Comic Book Guy catalogs codebases because he catalogs EVERYTHING. He was previously considered for docs (lost to Lisa) because cataloging isn't documentation. But cataloging IS codebase analysis. This is his real calling. The redemption arc writes itself.

**Model decision:** gpt-5.4. This is a reading/analysis role, not a reasoning role. CBG needs fast processing, broad code understanding across frameworks (Flask, React, Bicep, Terraform), and large context window for reading full files. Same tier as Troy, Lisa, Snake — the workhorses.

**What He Does — Two Pipeline Positions:**

**BEFORE Builders (Scoping):**
- Receives the target repo's file contents
- Catalogs every file, route, function, pattern, and dependency
- Produces a structured scope document: file inventory, route catalog, pattern registry, protected zones, safe modification zones
- This document feeds Marge (planning), Hank (design constraints), Gil/Artie (build context), Martin (preservation checks), Bob (security baseline)

**AFTER Builders (Validation):**
- Receives builder output AND the original codebase
- Compares builder output against existing code
- Flags: deleted files, missing routes, destroyed patterns, factory breakage
- Feeds Martin (auto-F if builder deleted production code) and Bob (flagged security regressions)

**Smoke Test Result (March 16, 2026):**

Fed CBG a simulated P66 dashboard codebase (7 files, 456-line main.py with 9 routes, 438-line azure_data.py with 7 collectors). His scope document included:
- Complete file inventory with line counts and purposes
- Route catalog with method/path/handler/file:line references
- Application architecture analysis (Flask factory pattern, WSGI chain, template/static linkage)
- Protected patterns list (create_app(), Blueprint registration, auth middleware, error handlers)
- Safe modification zones (where to add new routes, collectors, templates)
- Risk register ("There is no emoticon for what I am feeling right now")
- Caught that azure_data.py had 2 unexposed collectors (compliance, topology) — "Were you even aware those functions existed before deciding the API was 'complete'?"

In-character, thorough, and exactly what would have prevented PR #43/#44.

**Systems Modified When Hired:**

| System | What Changed | Why |
|--------|-------------|-----|
| `roles/comic_book_guy.py` | Full character prompt, scoping + validation expertise | CBG's personality and capabilities |
| `orchestrator.py` → `SPECIALIST_ROLES` | Added `"codebase"` | Orchestrator recognizes the role |
| `orchestrator.py` → `CONTEXT_ROUTING` | CBG feeds architect, engineer, frontend, quality, security, docs | Everyone sees the scope doc |
| `orchestrator.py` → `CONTEXT_LIMITS` | CBG at 15K | Builders and reviewers need the full scope doc |
| `orchestrator.py` → `PLAN_PROMPT` | CBG team profile, all workstreams updated, two-phase planning updated | Marge knows when/how to use CBG |
| `orchestrator.py` → `HANDOFF_TEMPLATE` | Brownfield safety instructions | Builders told to ADD, never delete |
| `orchestrator.py` → `FEEDBACK_LOOPS` | Raised Martin threshold (C/C+ triggers revision), added preservation triggers | Mediocre code can't slide through |
| `marge_simpson.py` → `INSTRUCTIONS` | CBG in team knowledge, routing table, orchestration patterns | Marge plans with CBG |
| `discovery.py` | Model preferences for `codebase` role | Auto-discovery support |
| `cli.py` | `hire codebase` preset | CLI hiring |

**Additional Pipeline Changes Made At Hire Time:**

These weren't just "add a new agent" — the entire pipeline was overhauled:

1. **Brownfield safety in HANDOFF_TEMPLATE** — "ADD only, NEVER delete existing code" instruction for all builders
2. **Martin's feedback threshold raised** — C and C+ now trigger revision cycles (was only D/F/C-)
3. **Colleague sections stripped from 11 agent prompts** — ~5,000 tokens/job saved (Marge's preserved — she needs it for routing)
4. **Bob marked MANDATORY** — PLAN_PROMPT explicitly says "Never skip Bob on any work touching a repo or going to production"
5. **Martin preservation check** — Marge instructed to include "verify existing code was preserved" in every Martin task on existing repos

---

## FAQ

**Q: Why Simpsons characters?**
A: Because personality enforces behavior. A system prompt that says "be thorough" is vague. A system prompt that says "you are Gil Gunderson, your entire career depends on this, please tell Mr. Scorpio you did good" produces someone who checks every edge case.

**Q: Why not just use one powerful model for everything?**
A: Cost and specialization. o3-pro costs 40x more than gpt-5.4 per token. Most work (research, docs, frontend, social) doesn't need deep reasoning. Tiering models matches cognitive demand to capability.

**Q: How do you prevent agents from going off-character?**
A: Detailed system prompts with specific catchphrases, relationships to other team members, and explicit behavior rules. Plus, Marge's task descriptions set the tone at each handoff.

**Q: Can you actually hire/fire agents?**
A: Yes. `python -m core_team.cli hire <role>` deploys to Foundry. The agent persists by ID in the Foundry project and is reusable across sessions. Firing deletes the agent version.

**Q: How do you handle the "overnight team" pattern?**
A: APScheduler runs inside the web app, reading blob-stored schedule configs. Jobs fire at configured times (cron syntax), execute through Marge's orchestrator, and persist results to blob storage. You wake up to PRs, briefings, and scan reports.

**Q: What's the most important lesson?**
A: Orchestration is the hard problem. Individual agent quality matters, but the orchestrator (Marge) is what makes it a team instead of a collection of chatbots. She plans, paces, routes context, manages feedback loops, handles failures, and summarizes. Everything goes through Marge.
