# NextGen Agents — Migration Plan: NextGen_Agents → Nextgen_agents2

**Date:** March 17, 2026  
**Author:** Brad Allen + Copilot  
**Status:** DRAFT — Review before executing  

---

## Executive Summary

Migrate the NextGen student evaluation system from `NextGen_Agents` (eastus/westus2) to a new `Nextgen_agents2` resource group, consolidate onto Springfield's Foundry account, upgrade all models, and apply Springfield's proven agent patterns to fix critical gaps in the NextGen pipeline.

**Current state:** 35+ resources across 2 Foundry accounts, Premium Front Door with empty WAF, 7 private endpoints, 9 legacy model deployments on gpt-4.1 era, and an agent pipeline missing checkpoint/resume, quality feedback loops, security review, timeouts, and human oversight.

**Target state:** ~14 resources in Nextgen_agents2, 1 shared Foundry account, latest models, and a phased roadmap to bring Springfield's battle-tested patterns into the evaluation pipeline.

---

## Current Resource Inventory (NextGen_Agents)

### Compute & Web
| Resource | Type | SKU | Verdict |
|----------|------|-----|---------|
| nextgen-webapp-plan | App Service Plan | **P0v3 (Premium v3)** | **KEEP** — P0v3 is right for agent workloads, matches Springfield |
| nextgen-agents-web | App Service (Python 3.12) | — | **RECREATE** in new RG |
| nextgen-agents-web/staging | Deployment Slot | — | **RECREATE** only if needed |

### Front Door + WAF (THE BIG CUT)
| Resource | Type | SKU | Verdict |
|----------|------|-----|---------|
| nextgen-frontdoor | CDN/FrontDoor Profile | **Premium_AzureFrontDoor** | **DELETE** |
| nextgenWAFPolicy | FrontDoor WAF Policy | Premium | **DELETE** |
| nextgen-waf-security | Security Policy | — | **DELETE** |
| nextgen-app endpoint | AFD Endpoint | — | **DELETE** |
| nextgen-staging endpoint | AFD Endpoint | — | **DELETE** |
| prod-origins / staging-origins | Origin Groups | — | **DELETE** |

**Why delete:** Premium AFD costs ~$330/month base + per-request charges. Your WAF has **zero managed rules and zero custom rules** — it's an empty shell doing nothing. The app already has:
- EasyAuth (AAD + Apple login) — `requireAuthentication: true`
- App-level username/password auth with session management (8-hour expiry)
- CSP nonce generation, security headers, CSRF protection, rate limiting
- HTTPS-only enforced

For 5 users, the app's built-in auth stack is more than sufficient. EasyAuth alone is enterprise-grade AAD authentication without a single line of code.

### Networking (THE SECOND BIG CUT)
| Resource | Verdict | Reason |
|----------|---------|--------|
| nextgen-agents-vnet | **RECREATE** (simplified) | 1 VNet with 2 subnets is enough |
| vnet-westus2 | **DELETE** | Duplicate VNet — legacy/orphaned |
| 7× NSGs | **DELETE** most | Recreate only 2: one for app subnet, one for PE subnet |
| 7× Private Endpoints + NICs | **RECREATE** only what's needed (see below) |
| orphaned-test-pip | **DELETE** | Orphaned public IP — not connected to anything |

### Private Endpoints — Keep vs Cut
| PE Name | Target | Verdict |
|---------|--------|---------|
| kv-pe-nextgen | nextgen-agents-kv (Key Vault) | **RECREATE** in new VNet |
| storage-pe-nextgen | nextgendata2452 (Blob Storage) | **RECREATE** in new VNet |
| nextgen-postgres-pe | nextgenagentpostgres (Postgres) | **RECREATE** in new VNet |
| nextgen-foundry-pe | nextgenagentfoundry (CognitiveServices) | **RECREATE** in new VNet |
| nextgen-ai1-pe | NextGenAgentsAI (CognitiveServices) | **DELETE** — confirmed dead |
| nextgen-ai2-pe | NextGenAgentsAI2 (CognitiveServices) | **DELETE** — confirmed dead |
| nextgen-whisper-pe | NextGenAgentsWhisper (CognitiveServices) | **SKIP** — Mirabel planned but not shipped yet |

### Data & Secrets
| Resource | Verdict | Reason |
|----------|---------|--------|
| nextgendata2452 (Storage) | **KEEP in place** — cross-RG reference | Moving storage means migrating blobs. Point from new RG instead. |
| nextgen-agents-kv (Key Vault) | **RECREATE** in new RG | Clean Key Vault, migrate only active secrets |
| nextgenagentpostgres (Postgres) | **KEEP in place** — cross-RG reference | Database migration is risky for zero gain |

### Observability
| Resource | Verdict | Reason |
|----------|---------|--------|
| nextgen-logs (Log Analytics) | **RECREATE** in new RG | Fresh workspace, clean retention |
| nextgen-appinsights (App Insights) | **RECREATE** in new RG | Fresh instrumentation key |

### Junk
| Resource | Verdict | Reason |
|----------|---------|--------|
| old-migration-backup-disk | **DELETE** | Orphaned managed disk from a previous migration |
| orphaned-test-pip | **DELETE** | Public IP connected to nothing |
| sqlvmnextdenagent-nsg | **DELETE** | NSG for a SQL VM that doesn't exist |
| nextgendata2452-*-EventGrid SystemTopic | **DELETE** | EventGrid topic on storage — not used by the app |

### AI Foundry (STAY IN NextGen_Agents)
These CognitiveServices accounts stay where they are. Only `nextgenagentfoundry` needs a PE from the new VNet.

| Resource | Location | Status |
|----------|----------|--------|
| nextgenagentfoundry | westus3 | **ACTIVE** — Main Foundry endpoint, all agents. Keep + PE |
| NextGenAgentsAI | ? | **DEAD** — Delete during cleanup |
| NextGenAgentsAI2 | ? | **DEAD** — Delete during cleanup |
| NextGenAgentsWhisper | ? | **DORMANT** — Keep for future Mirabel feature, no PE needed yet |

---

## Target Architecture (Nextgen_agents2)

```
┌─────────────────────────────────────────────────────┐
│  Nextgen_agents2 (westus2)                          │
│                                                     │
│  ┌──────────────────┐  ┌────────────────────────┐   │
│  │ nextgen2-plan    │  │ nextgen2-web            │   │
│  │ (P0v3)           │  │ (Python 3.12, Flask)   │   │
│  │                  │  │ EasyAuth (AAD)         │   │
│  └──────────────────┘  │ App-level auth         │   │
│                        │ VNET integrated        │   │
│                        └──────────┬─────────────┘   │
│                                   │                 │
│  ┌────────────────────────────────▼──────────────┐  │
│  │ nextgen2-vnet                                 │  │
│  │   ├── app-subnet (10.1.0.0/24)              │  │
│  │   └── pe-subnet  (10.1.1.0/24)              │  │
│  │         ├── PE → Key Vault (nextgen2-kv)     │  │
│  │         ├── PE → Storage (nextgendata2452)*  │  │
│  │         ├── PE → Postgres*                   │  │
│  │         └── PE → Foundry (nextgenagentfoundry)* │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────┐  ┌────────────────────────────┐   │
│  │ nextgen2-kv  │  │ nextgen2-logs              │   │
│  │ (Key Vault)  │  │ (Log Analytics)            │   │
│  └──────────────┘  │ nextgen2-appinsights       │   │
│                    │ (App Insights)              │   │
│                    └────────────────────────────┘   │
│                                                     │
│  * Storage, Postgres, Foundry stay in               │
│    NextGen_Agents — cross-RG private endpoints      │
└─────────────────────────────────────────────────────┘
```

**Resource count: ~14** (plan, web app + staging slot, vnet, 2 NSGs, KV, LA, AppInsights, 4 PEs + NICs)  
vs current **35+ resources** (plus hidden FD, WAF, WAF policy, 2 dead CogServices accounts)

---

## What Replaces Front Door

Nothing external. The app's existing security layers are sufficient:

| Layer | What It Does | Already Built? |
|-------|------------|----------------|
| **EasyAuth v2** | AAD + Apple sign-in, requireAuthentication=true, redirect to login | YES — configured today |
| **App-level auth** | Username/password from Key Vault, bcrypt hash, 8-hour sessions | YES — in app.py |
| **CSRF** | Flask-WTF CSRF protection on all forms | YES |
| **Rate limiting** | Flask-Limiter on all endpoints | YES |
| **CSP + Security Headers** | Nonce-based CSP, X-Frame-Options, HSTS, etc. | YES — add_security_headers() |
| **HTTPS-only** | App Service httpsOnly=true | YES |
| **VNET + PEs** | Backend services unreachable from internet | YES (will recreate) |

**What you lose:** DDoS protection from Azure's front-end network. For 5 users on an internal MSFT tenant, this is not a real risk. Azure App Service has basic DDoS protection built in.

**Cost saved:** ~$330/month base + per-request (Premium AFD) + WAF charges = **~$400-500/month**

---

## Springfield Learnings Applied

| Springfield Pattern | How It Applies to NextGen |
|---------------------|--------------------------|
| **AlwaysOn for Premium** | nextgen-agents-web has `alwaysOn: false` — **ENABLE IT**. You're on P0v3, pay for it. |
| **deploy.sh, not GitHub Actions** | FDPO blocks SP creation. The GitHub Actions workflows in the repo **will never work**. Remove them or document they're local-only. |
| **DefaultAzureCredential everywhere** | Already using it (Key Vault, Storage, Foundry). Good. |
| **Diagnostic endpoints first** | Add a `/api/test/foundry` and `/api/test/postgres` endpoint before migrating. Prove connectivity works. |
| **Fresh Key Vault** | Don't migrate the old KV — create new, copy only active secrets. Old KVs accumulate cruft. |
| **1 VNet, 2 subnets** | Springfield pattern works. Don't overcomplicate. |
| **Observability from day 1** | Fresh App Insights + Log Analytics. Wire OTEL before anything else. |
| **Ghost cleanup on startup** | The app should mark stale state as failed on restart (already in Flask?). Verify. |

---

## Migration Phases

### Phase 0: Pre-Flight (before touching Azure)
- [ ] **Verify which CognitiveServices accounts are actually used**: Check app config and code for `NextGenAgentsAI`, `NextGenAgentsAI2`, `NextGenAgentsWhisper` references. If any are dead, no PE needed.
- [ ] **Confirm Postgres is alive**: The server `nextgenagentpostgres` didn't show up in `az postgres flexible-server list` — verify it exists and is accessible from the current web app.
- [ ] **Document all Key Vault secrets actually in use**: `az keyvault secret list --vault-name nextgen-agents-kv`
- [ ] **Export current app settings**: Save the full appsettings JSON as a migration reference.
- [ ] **Add diagnostic endpoints to the app**: `/api/test/foundry`, `/api/test/postgres`, `/api/test/storage`

### Phase 1: Create New Resource Group + Base Infrastructure
```bash
# 1. Create RG
az group create -n Nextgen_agents2 -l westus2

# 2. Create VNet with 2 subnets
az network vnet create -g Nextgen_agents2 -n nextgen2-vnet \
  --address-prefix 10.1.0.0/16 \
  --subnet-name app-subnet --subnet-prefix 10.1.0.0/24

az network vnet subnet create -g Nextgen_agents2 --vnet-name nextgen2-vnet \
  -n pe-subnet --address-prefix 10.1.1.0/24 \
  --disable-private-endpoint-network-policies true

# 3. NSGs
az network nsg create -g Nextgen_agents2 -n app-subnet-nsg
az network nsg create -g Nextgen_agents2 -n pe-subnet-nsg

# 4. Log Analytics + App Insights
az monitor log-analytics workspace create -g Nextgen_agents2 \
  -n nextgen2-logs --retention-in-days 30

az monitor app-insights component create -g Nextgen_agents2 \
  -a nextgen2-appinsights -l westus2 \
  --workspace nextgen2-logs

# 5. Key Vault
az keyvault create -g Nextgen_agents2 -n nextgen2-kv -l westus2 \
  --enable-rbac-authorization true
```

### Phase 2: Create App Service + Connect
```bash
# 1. App Service Plan
az appservice plan create -g Nextgen_agents2 -n nextgen2-plan \
  --sku P0v3 --is-linux

# 2. Web App
az webapp create -g Nextgen_agents2 -p nextgen2-plan \
  -n nextgen2-web --runtime "PYTHON:3.12"

# 3. VNET Integration
az webapp vnet-integration add -g Nextgen_agents2 \
  -n nextgen2-web --vnet nextgen2-vnet --subnet app-subnet

# 4. AlwaysOn + HTTPS
az webapp config set -g Nextgen_agents2 -n nextgen2-web \
  --always-on true --ftps-state Disabled

az webapp update -g Nextgen_agents2 -n nextgen2-web --https-only true

# 5. EasyAuth (replicate current config)
# Copy AAD app registration settings from current setup
```

### Phase 3: Private Endpoints (cross-RG)
Create PEs in the new VNet pointing to existing resources in NextGen_Agents:
```bash
# Key Vault PE
az network private-endpoint create -g Nextgen_agents2 \
  -n pe-kv --vnet-name nextgen2-vnet --subnet pe-subnet \
  --private-connection-resource-id "/subscriptions/.../NextGen_Agents/.../nextgen2-kv" \
  --group-ids vault --connection-name kv-connection

# Storage PE (blob)
az network private-endpoint create -g Nextgen_agents2 \
  -n pe-storage --vnet-name nextgen2-vnet --subnet pe-subnet \
  --private-connection-resource-id "/subscriptions/.../NextGen_Agents/.../nextgendata2452" \
  --group-ids blob --connection-name storage-connection

# Postgres PE
az network private-endpoint create -g Nextgen_agents2 \
  -n pe-postgres --vnet-name nextgen2-vnet --subnet pe-subnet \
  --private-connection-resource-id "/subscriptions/.../nextgenagentpostgres" \
  --group-ids postgresqlServer --connection-name postgres-connection

# Foundry PE
az network private-endpoint create -g Nextgen_agents2 \
  -n pe-foundry --vnet-name nextgen2-vnet --subnet pe-subnet \
  --private-connection-resource-id "/subscriptions/.../nextgenagentfoundry" \
  --group-ids account --connection-name foundry-connection

# Whisper PE (if still used)
# Same pattern for NextGenAgentsWhisper
```

### Phase 4: Configure App + Deploy Code
```bash
# 1. Migrate Key Vault secrets (only active ones)
# Script to copy from nextgen-agents-kv to nextgen2-kv

# 2. Set app settings (from exported reference)
# Remove AZURE_FRONT_DOOR_ID — no longer needed
# Update AZURE_KEY_VAULT_NAME → nextgen2-kv
# Update APPLICATIONINSIGHTS_CONNECTION_STRING → new App Insights
# Keep POSTGRES_*, FOUNDRY_*, AZURE_OPENAI_* pointing to same backends

# 3. Remove Front Door IP restrictions from App Service
az webapp config access-restriction remove ... 
# No IP restrictions needed — EasyAuth protects the endpoint

# 4. Deploy code
# Standard zip deploy from the repo

# 5. Remove Front Door validation from app.py
# The `if config.azure_front_door_id:` block in require_login() can stay
# (it's a no-op when the env var isn't set), but clean it up eventually
```

### Phase 4b: Hire Springfield Agents into Foundry (eastus2)

This is the big value-add — bring the proven Springfield team into the `springfield-ai-eastus2` Foundry (which the NextGen app will now point to), and upgrade the model tier for each agent.

#### Current State: Two Separate Worlds

**Springfield (springfield-ai-eastus2, eastus2) — 8 model deployments, 0 Foundry agents:**
Springfield uses the Responses API directly — agents are created as versioned Foundry agents (`project.agents.create_version()`) at runtime via `hire_agent()` in `factory.py`. No persistent agents exist — they're created on demand and referenced by name.

| Model Deployment | Model | TPM | Used By (Springfield) |
|---|---|---|---|
| o3-pro | o3-pro | 30 | Bob (security, deep reasoning) |
| o3 | o3 | 30 | Hank (architect), Marge (boss) |
| gpt-5.4 | gpt-5.4 | 80 | Troy, Snake, Lisa, Artie, CBG, Kent, Lindsey, Willie |
| gpt-5.4-pro | gpt-5.4-pro | 80 | Martin (quality review) |
| gpt-5.3-codex | gpt-5.3-codex | 30 | Gil (engineer) |
| gpt-image-1 | gpt-image-1 | 1 | Artie (images) |
| sora-2 | sora-2 | 50 | Artie (video) |
| text-embedding-3-large | text-embedding-3-large | 1 | (unused) |

**NextGen (nextgenagentfoundry, westus3) — 9 model deployments, 0 Foundry agents:**
NextGen uses a custom `FoundryClient` HTTP adapter that does `chat.completions.create()` directly against deployment endpoints. Agents are Python classes in `src/agents/`, not Foundry-managed.

| Model Deployment | Model | TPM | Used By (NextGen) |
|---|---|---|---|
| gpt-4.1 | gpt-4.1 | 500 | Main workhorse — most Disney agents |
| WorkForce4.1mini | gpt-4.1-mini | 1376 | Lightweight agents |
| MerlinGPT5Mini | gpt-5-mini | 415 | Merlin (synthesis evaluator) |
| LightWork5Nano | gpt-5-nano | 250 | Lightweight tasks |
| gpt-4o | gpt-4o | 50 | Mirabel (vision/video) |
| o4MiniAgent | o4-mini | 10 | Light reasoning |
| o3 | o3 | 1 | (minimal) |
| gpt-5.2 | gpt-5.2 | 1 | (minimal) |
| text-embedding-ada-002 | text-embedding-ada-002 | 500 | Embeddings |

#### The Upgrade Plan

**Step 1: Add new model deployments to `springfield-ai-eastus2`**

The NextGen Disney agents currently run on gpt-4.1 (March 2025 model). That's a full generation behind. We upgrade them to Springfield-proven models:

| NextGen Agent | Current Model | New Model | Why |
|---|---|---|---|
| **Smee** (orchestrator) | gpt-4.1 | **o3** | Orchestrators need reasoning, not speed. Springfield pattern. |
| **Belle** (doc analyzer) | gpt-4.1 | **gpt-5.4** | Broad knowledge, fast. Same as Troy/research tier. |
| **Tiana** (application reader) | gpt-4.1 | **gpt-5.4** | Essay analysis needs nuance. |
| **Rapunzel** (grades) | gpt-4.1 | **gpt-5.4-pro** | Transcript parsing needs precision. Premium tier. |
| **Mulan** (recommendations) | gpt-4.1 | **gpt-5.4** | Letter analysis, workhorse tier. |
| **Moana** (school context) | gpt-4.1 | **gpt-5.4** | Narrative generation, workhorse. |
| **Naveen** (school data) | gpt-4.1 | **gpt-5.4** | NCES scoring, workhorse. |
| **Pocahontas** (cohort) | gpt-4.1 | **gpt-5.4** | Equity analysis, workhorse. |
| **Merlin** (evaluator) | gpt-5-mini | **gpt-5.4-pro** | The critical synthesis step. Needs the best. |
| **Gaston** (counter-eval) | gpt-4.1 | **o3** | Bias detection needs deep reasoning. |
| **Milo** (data scientist) | gpt-4.1 | **gpt-5.4** | ML/analytics, workhorse. |
| **Ariel** (Q&A) | gpt-4.1 | **gpt-5.4** | Conversational, workhorse. |
| **Mirabel** (video) | gpt-4o | **gpt-4o** (keep) | Vision model — no upgrade path yet. Deploy when Mirabel ships. |
| **Bashful** (summarizer) | gpt-4.1-mini | **gpt-5.4** | Output condensation. |
| **FeedbackTriage** | gpt-4.1-mini | **gpt-5.4** | Lightweight but benefits from better model. |

Models already deployed on `springfield-ai-eastus2` that NextGen needs:
- `o3` ✅ (already at 30 TPM)
- `gpt-5.4` ✅ (already at 80 TPM — may need increase for 15+ agents)
- `gpt-5.4-pro` ✅ (already at 80 TPM)

**Models to ADD to `springfield-ai-eastus2`:**
- `gpt-4o` — for Mirabel vision (future, when shipped)
- `text-embedding-3-large` ✅ already deployed (replaces `text-embedding-ada-002`)

**Models NOT needed (kill list from nextgenagentfoundry):**
- `gpt-4.1` — superseded by gpt-5.4
- `gpt-4.1-mini` — superseded by gpt-5.4
- `gpt-5-mini` — superseded by gpt-5.4-pro for Merlin
- `gpt-5-nano` — superseded by gpt-5.4
- `o4-mini` — superseded by o3
- `gpt-5.2` — superseded by gpt-5.4
- `text-embedding-ada-002` — superseded by text-embedding-3-large

**Step 2: Increase TPM quotas on `springfield-ai-eastus2`**

With Springfield + NextGen both using this account, increase `gpt-5.4` from 80 → 200 TPM (GlobalStandard, unused quota costs $0).

```bash
# Increase gpt-5.4 TPM for combined workload
az rest --method patch \
  --url "https://management.azure.com/subscriptions/b1672fa6-8e52-45d0-bf79-ceccc352177d/resourceGroups/NextGen_Agents/providers/Microsoft.CognitiveServices/accounts/springfield-ai-eastus2/deployments/gpt-5.4?api-version=2024-10-01" \
  --body '{"sku": {"name": "GlobalStandard", "capacity": 200}}'
```

**Step 3: Point NextGen app to `springfield-ai-eastus2`**

Update the NextGen web app's config to use the Springfield Foundry endpoint instead of `nextgenagentfoundry`:
```bash
az webapp config appsettings set -g Nextgen_agents2 -n nextgen2-web --settings \
  FOUNDRY_PROJECT_ENDPOINT="https://springfield-ai-eastus2.cognitiveservices.azure.com" \
  AZURE_OPENAI_ENDPOINT="https://springfield-ai-eastus2.cognitiveservices.azure.com"
```

**Step 4: Update agent model references in code**

PR to `agent-nextgen` repo — update `src/config.py` and agent init code to use new deployment names:
- `AZURE_DEPLOYMENT_NAME` → `gpt-5.4` (main workhorse, was `gpt-4.1`)
- `AZURE_DEPLOYMENT_NAME_MINI` → `gpt-5.4` (everything gets the good model now)
- `FOUNDRY_MODEL_NAME` → `gpt-5.4`
- Smee orchestrator model → `o3`
- Merlin evaluator model → `gpt-5.4-pro`
- Gaston counter-evaluator model → `o3`
- Rapunzel grade analyst model → `gpt-5.4-pro`

**Step 5: Consolidate to one Foundry account**

After migration, both Springfield Core Team and NextGen share `springfield-ai-eastus2`:
- Springfield agents use it via `PROJECT_ENDPOINT` (existing)
- NextGen agents use it via `FOUNDRY_PROJECT_ENDPOINT` (updated)
- `nextgenagentfoundry` (westus3) can be decommissioned
- One account, one set of model deployments, one bill, one set of quotas

#### What This Means for the NextGen PE

In Phase 3, instead of creating a PE to `nextgenagentfoundry` (westus3), create the PE to `springfield-ai-eastus2` (eastus2). Both apps share the same Foundry.

```bash
# Foundry PE — point to springfield-ai-eastus2, NOT nextgenagentfoundry
az network private-endpoint create -g Nextgen_agents2 \
  -n pe-foundry --vnet-name nextgen2-vnet --subnet pe-subnet \
  --private-connection-resource-id "/subscriptions/.../NextGen_Agents/.../springfield-ai-eastus2" \
  --group-ids account --connection-name foundry-connection
```

### Phase 5: Validate
- [ ] Hit `/health` and `/healthz` — verify 200
- [ ] Hit diagnostic endpoints: `/api/test/foundry`, `/api/test/postgres`, `/api/test/storage`
- [ ] Login via EasyAuth → AAD redirect works
- [ ] Login via app-level auth → session works
- [ ] Process a test student evaluation end-to-end
- [ ] Check App Insights for traces
- [ ] Verify agent calls hit Foundry through PE (check OTEL spans)

### Phase 6: Cutover DNS (if using custom domain)
If the Front Door hostname was the primary entry point, update DNS to point to `nextgen2-web.azurewebsites.net` instead.

### Phase 7: Clean Up Old RG
After validation period (1 week recommended):
```bash
# Delete from NextGen_Agents (keep Foundry accounts):
# - nextgen-frontdoor (CDN profile)
# - nextgenWAFPolicy
# - nextgen-agents-web + staging slot
# - nextgen-webapp-plan
# - nextgen-agents-kv
# - All 7 PEs + NICs
# - All 7 NSGs
# - Both VNets
# - old-migration-backup-disk
# - orphaned-test-pip
# - EventGrid system topic
# - nextgen-logs
# - nextgen-appinsights

# KEEP in NextGen_Agents:
# - nextgendata2452 (Storage) — data lives here, cross-RG PE
# - nextgenagentfoundry (CognitiveServices) — main Foundry, cross-RG PE
# - NextGenAgentsWhisper (CognitiveServices) — dormant, for future Mirabel
# - nextgenagentpostgres (Postgres) — data lives here, cross-RG PE
#
# DELETE from NextGen_Agents (confirmed dead):
# - NextGenAgentsAI (CognitiveServices) — dead
# - NextGenAgentsAI2 (CognitiveServices) — dead
```

---

## Cost Impact Estimate

| Item | Before (monthly) | After (monthly) | Savings |
|------|------------------|-----------------|---------|
| Premium Front Door | ~$330 base | $0 | **$330** |
| WAF Policy (Premium) | ~$100 | $0 | **$100** |
| App Service Plan (P0v3) | ~$57 | ~$57 (same) | $0 |
| Key Vault | ~$3 | ~$3 | $0 |
| Storage | ~$5 | ~$5 (same account) | $0 |
| Postgres | ~$13 | ~$13 (same server) | $0 |
| Log Analytics + AppInsights | ~$5 | ~$5 | $0 |
| Orphaned disk | ~$2 | $0 | **$2** |
| **Total** | **~$515** | **~$83** | **~$432/month** |

---

## Delivery Recommendation

**Open a migration PR on the agent-nextgen repo** with these changes:
1. Remove Front Door header validation from `app.py` (or make it gracefully optional — it already is)
2. Remove `AZURE_FRONT_DOOR_ID` from `.env.example` and config docs
3. Delete the non-functional GitHub Actions workflows (they can't work in FDPO)
4. Add diagnostic test endpoints for pre/post-migration validation
5. Update deployment docs for the new RG
6. Create a `scripts/migrate.sh` with all the `az` commands above (parameterized)

The infrastructure changes happen via CLI — no ARM template rewrite needed. The existing `azure-deploy.json` only creates CogServices + observability, which is fine.

---

## Resolved Questions (Brad's Answers + Analysis)

### 1. NextGenAgentsAI and NextGenAgentsAI2 → DEAD
**Answer:** Dead. Not used by the app.  
**Action:** No PEs needed. Delete both CogServices accounts from NextGen_Agents during cleanup. Only `nextgenagentfoundry` (main Foundry) needs a PE.

### 2. Whisper (Mirabel video analysis) → PLANNED, NOT DELIVERED
**Answer:** Feature is planned but never shipped.  
**Action:** Skip the Whisper PE for now. When Mirabel ships, create the PE then. Keep `NextGenAgentsWhisper` CogServices account alive but don't wire it up.

### 3. Staging Slot → YES, KEEP
**Answer:** Used for build/test while users work in prod.  
**Action:** Recreate staging slot on `nextgen2-web`. This is the Springfield pattern — you need it.

### 4 & 5. Storage + Postgres — EVALUATION

#### Do You Need Postgres?

**What's in Postgres (20 tables, 4,599-line database.py):**
- `Applications` — core student records, evaluation status, agent results
- `ai_evaluations` — every agent's evaluation output per student
- `tiana_applications`, `mulan_recommendations`, `rapunzel_grades`, `merlin_evaluations` — per-agent structured output tables
- `student_school_context` — enrichment data linking students to schools
- `schools`, `school_socioeconomic_data`, `school_programs` — reference data (NCES)
- `grade_records` — transcript data
- `historical_scores` — past cohort scoring for Milo's ML training
- `agent_interactions`, `agent_audit_logs` — 14 interaction types for compliance audit trail
- `user_feedback`, `training_feedback` — feedback loops
- `file_upload_audit` — document tracking with hash-based dedup
- `test_submissions` — test session management
- `school_enriched_data` with `school_aliases` — fuzzy matching for schools
- `telemetry_events` — agent performance data

**The query patterns are deeply relational:**
- Student matching uses composite key lookups (first_name + last_name + school + state)
- Fuzzy school matching with token-set-ratio algorithms
- JOINs between student_school_context ↔ schools ↔ Applications
- Historical score linking to training applications
- Aggregate queries for dashboards (counts by status, agent, school)
- ILIKE searches, subqueries, LEFT JOINs — this is not JSON-document shaped

**VERDICT: You need Postgres.** This is a genuine relational data model — 20 tables with foreign keys, multi-column indexes, ILIKE text search, aggregate analytics, and audit compliance requirements. Trying to rebuild this on Blob Storage would be a massive regression — you'd be reimplementing a database engine in Python.

**RECOMMENDATION: Keep `nextgenagentpostgres` in place, cross-RG PE.**
- **Why not move it:** Postgres Flexible Server migration means pg_dump → create new server → pg_restore → DNS cutover. Risk of data loss, downtime, and broken connections for zero functional gain.
- **Cross-RG PE works fine:** The PE just needs line of sight from the new VNet to the existing server. Data stays where it is. Connection strings don't change.
- **Cost:** Postgres Flexible Server Burstable B1ms is ~$13/month. It's already paid for. No savings from moving.

#### Storage: Same Approach — Keep in Place
- `nextgendata2452` holds uploaded student documents (PDFs, DOCXs) organized by containers (`applications-2026`, `applications-test`, `applications-training`) with optional staging prefix isolation.
- DefaultAzureCredential auth (key auth disabled by FDPO) — works cross-RG as long as the new web app's managed identity gets `Storage Blob Data Contributor` on the account.
- **Cost:** Standard_LRS, minimal — no reason to duplicate.

**Action:** Cross-RG PEs for both Postgres and Storage. Don't move the data.

### 6. Front Door URL → Security Transition Plan

**Current state:** Users access `nextgen-app-h7hvaybqd4grd0b2.b02.azurefd.net`  
**Target state:** Users access `nextgen2-web.azurewebsites.net` (or a custom domain if desired)

**Security context — what changes and what doesn't:**

| Security Layer | With Front Door | Without Front Door | Delta |
|---|---|---|---|
| **DDoS protection** | Azure FD Premium L7 DDoS | Azure App Service built-in L4 DDoS | Lose L7 DDoS — irrelevant for 5 internal MSFT users |
| **SSL termination** | FD terminates SSL, re-encrypts to origin | App Service terminates SSL directly | No change — `httpsOnly=true` already set |
| **WAF** | Empty ruleset (0 managed, 0 custom rules) | N/A | **Losing nothing** — WAF was never configured |
| **Authentication** | EasyAuth v2 (AAD) on App Service | EasyAuth v2 (AAD) on App Service | **No change** — auth is on the app, not FD |
| **App-level auth** | Username/password + bcrypt + 8hr sessions | Same | **No change** |
| **Bot protection** | Premium FD bot management (if configured) | None | Was likely never configured (empty WAF) |
| **IP filtering** | FD→origin only via service tag | None needed — EasyAuth blocks unauthed | **Simpler** — remove the `AllowFrontDoorOnly` + `Deny all` restriction |
| **CSP/XFO/HSTS** | App generates all headers | Same | **No change** |
| **CSRF** | Flask-WTF | Same | **No change** |
| **Rate limiting** | Flask-Limiter | Same | **No change** |

**The honest assessment:** For 5 users on an internal Microsoft tenant with EasyAuth AAD requiring authentication on every request, Front Door adds nothing. The WAF is empty. The bot protection is unconfigured. The DDoS protection is defending against an attack that would never target an internal 5-user tool. You're paying $430/month for SSL re-termination that App Service does natively.

**The one thing to do:** When you remove the `AllowFrontDoorOnly` IP restriction, EasyAuth becomes your perimeter. Make sure:
1. EasyAuth `requireAuthentication: true` stays ON (it is)
2. `unauthenticatedClientAction: RedirectToLoginPage` stays set (it is)
3. The `/healthz` endpoint stays in the EasyAuth exclusion list (it does — it returns no sensitive data)
4. Give your 5 users the new `*.azurewebsites.net` URL and tell them to bookmark it

### 7. GitHub Actions Workflows → EXPLANATION + RECOMMENDATION

**What they are — 4 workflow files in the repo:**

| Workflow | What It Does | Can It Work in FDPO? |
|---|---|---|
| `azure-deploy.yml` | Auto-deploys to App Service on push to main | **NO** — needs `AZURE_CREDENTIALS` secret (service principal). FDPO blocks SP creation. Dead. |
| `cleanup-sweep-branches.yml` | Weekly cleanup of Willie/Bob/Smithers branches older than 7 days | **YES** — only needs `GITHUB_TOKEN` (built-in), no Azure. Actually works. |
| `ghostwriter-review.yml` | Nightly code review (2 AM ET) — reviews 3 files/night, opens graded issues | **MAYBE** — needs Key Vault access for API keys. If it uses `AZURE_CREDENTIALS` for that, it's dead. If secrets are in GitHub Secrets directly, it works. |
| `jiminy-docs-review.yml` | Nightly docs review (3 AM ET) — reviews 2 docs areas/night, opens issues | **SAME** as Ghostwriter — depends on how secrets are sourced. |

**Recommendation:**
- **Keep** `cleanup-sweep-branches.yml` — it works and is useful
- **Check** Ghostwriter and Jiminy — if they source API keys from GitHub Secrets (not Azure KV via SP), they're live and valuable. Your README says they run nightly. If they work, keep them.
- **Delete** `azure-deploy.yml` — it will never work in FDPO. Deploy via `deploy.sh` (Springfield pattern). Having a dead workflow that looks functional is worse than having none.
- **Add a note** in the repo README: "CI/CD deploys via local `deploy.sh` — GitHub Actions deploy is blocked by FDPO tenant policy"

**UPDATE: Ghostwriter and Jiminy use `azure/login@v2` with workload identity federation (OIDC), NOT a service principal key. They fetch API keys from Key Vault at runtime via `az keyvault secret show`. This means they WORK in FDPO as long as the federated credential is configured. Keep them both.**

---

## Part 2: Apply Springfield Learnings to NextGen Pipeline

### Gap Analysis — What Springfield Has That NextGen Doesn't

After a deep dive into the NextGen codebase (3,062-line Smee orchestrator, 659-line BaseAgent, 513-line FoundryClient, 4,599-line database.py, 940-line school_workflow), here are the critical gaps:

| Pattern | Springfield | NextGen | Severity |
|---------|-------------|---------|----------|
| **Two-Phase Planning** | Phase 1: scope → Phase 2: build | Fixed 8-step pipeline, no planning | CRITICAL |
| **Interleaved Review** | Each builder reviewed separately | One audit (Gaston) at the end, non-blocking | CRITICAL |
| **Quality Feedback Loops** | Grade → revise → re-review (2 cycles) | None — bad output goes straight to Merlin | CRITICAL |
| **Security Agent (Bob)** | Mandatory on all production code | No security agent at all | CRITICAL |
| **Human-in-the-Loop Gate** | Human approves before chaining | Auto-runs to completion, no stop point | CRITICAL |
| **Checkpoint + Resume** | Every step checkpointed to blob | None — crash at step 6 loses everything | HIGH |
| **Ghost Cleanup on Startup** | All "running" marked failed on restart | None — stale state survives restart | HIGH |
| **Fail Fast with Timeouts** | 90-300s per model, configurable | No timeouts on model calls | HIGH |
| **Model Fallback Chains** | Primary → cheaper model with instructions | None — single attempt | HIGH |
| **Rate Limit Handling** | 4 retries + exp backoff + fallback | Only HTTP-level retry (FoundryClient urllib3) | HIGH |
| **Background Job Queue** | Queue + worker + blob results | Synchronous in HTTP request | HIGH |
| **Blob Storage for Files** | Sessions/files persisted to blob | Local `uploads/` folder — lost on redeploy | HIGH |
| **Conversation Continuity** | Response IDs persisted for chaining | No response ID tracking | MEDIUM |
| **Agent Registry** | `team_registry.json` + Foundry agents | Imperative registration in code only | MEDIUM |
| **deploy.sh Pattern** | Validated deploy script | GitHub Actions (partially working) | MEDIUM |

### What NextGen Does Well (DON'T BREAK THESE)

- **Observability** — Best-in-class. OpenTelemetry with Azure Monitor, per-agent spans following Microsoft GenAI Semantic Conventions, token tracking persisted to Postgres + in-memory, Flask instrumentation. Leave this alone.
- **Security Headers** — Nonce-based CSP, HSTS, X-Frame-Options: DENY, script-src-attr 'none'. Very strong. Better than most production apps.
- **Per-Agent Data Isolation** — Each agent gets only its relevant section (transcript → Rapunzel, recommendation → Mulan, etc.). Good context routing.
- **Data Model** — 20 relational tables with proper foreign keys, indexes, fuzzy matching, audit trail. Solid.
- **School Enrichment Workflow** — NAVEEN ↔ MOANA validation loop with 2 remediation attempts. This IS a feedback loop — just limited to school data, not agent quality.
- **Agent Error Isolation** — Individual agent failures don't crash the pipeline. Results include error status. Good.
- **EasyAuth + App-Level Auth Stack** — Double auth layer is solid for 5 users.

---

### Phase 8: Springfield Pattern Adoption (Post-Migration PRs)

These are ordered by impact and dependency. Each is a PR to `agent-nextgen`.

#### Sprint 1: Foundation (Weeks 1-2) — Safety Net

**PR 1: Timeouts + Retry + Fallback** — `base_agent.py`, `foundry_client.py`
- Add configurable timeout per model tier (matches Springfield `MODEL_TIMEOUTS`)
  - o3: 180s, gpt-5.4-pro: 480s, gpt-5.4: 180s
- Add retry with exponential backoff at the agent level (not just HTTP):
  - 4 retries, 20s base delay, doubles each attempt
  - Rate limit (429) and timeout are retryable; content filter is not
- Add model fallback chains:
  - o3 → gpt-5.4, gpt-5.4-pro → gpt-5.4
  - Fallback injects agent instructions as developer message
- **Kill the multi-pass refinement default.** BaseAgent makes 2 model calls per invocation (refinements=2). This doubles cost and latency for marginal quality gain. Set default to 1. Let Merlin/Rapunzel opt into 2 if needed.
- **Why first:** Without timeouts, a single hung model call can block the entire pipeline indefinitely. This is the #1 operational risk.

**PR 2: Checkpoint + Resume** — `smee_orchestrator.py`, new `checkpoint.py`
- After each step completes, save state to Postgres (new `workflow_checkpoints` table):
  - `workflow_id`, `step_number`, `step_name`, `status`, `input_data`, `output_data`, `timestamp`
- On crash/restart, Smee can resume from last successful step
- Add `resume_workflow(workflow_id)` method that loads checkpoint and skips completed steps
- **Do NOT save checkpoint at step 0 on resume** (Springfield hard-learned lesson — it wipes restored outputs)
- **Why second:** Students submit documents once. If a crash at step 6 means re-uploading and re-running steps 1-5 (which cost money and time), that's unacceptable.

**PR 3: Ghost Cleanup on Startup** — `app.py` startup
- On app startup, query `workflow_checkpoints` for status='running'
- Mark all as 'failed_on_restart' with timestamp
- Log count of cleaned ghosts
- **Why third:** Without this, PR 2's checkpoint/resume could accidentally resume weeks-old dead workflows.

**PR 4: Blob Storage for Documents** — `src/storage.py`, `src/file_upload_handler.py`
- Move uploaded files from local `uploads/` to Azure Blob Storage (already have `StorageManager` class that uploads to containers)
- The storage account `nextgendata2452` already exists and has containers
- Currently `StorageManager` uploads AND the local copy exists — make blob the primary, local copy as temp-only
- Reference `blob_storage_path` column in Applications table (already exists but underused)
- **Why:** Documents currently vanish on redeploy. Student PDFs are irreplaceable.

#### Sprint 2: Quality Gates (Weeks 3-4) — Evaluation Integrity

**PR 5: Interleaved Quality Review (Gaston)** — `smee_orchestrator.py`
- Move Gaston from "one post-Merlin audit" to "review after each core agent":
  - After Tiana → Gaston reviews essay analysis quality (A-F grade)
  - After Rapunzel → Gaston reviews transcript parsing accuracy
  - After Mulan → Gaston reviews recommendation analysis
  - After Merlin → Gaston reviews final synthesis
- If Gaston grades below C:
  - Agent re-runs with Gaston's feedback injected into the prompt
  - Up to 1 revision cycle (not 2 — NextGen agents are slower due to document processing)
  - If still below C after revision, flag for human review
- Make Gaston's review **blocking** (currently non-blocking with errors caught and ignored)
- **Why:** Right now, bad agent output flows unchecked into Merlin's synthesis. Gaston exists but does nothing meaningful. This is the single biggest quality improvement.

**PR 6: Human-in-the-Loop Gate** — `smee_orchestrator.py`, new API endpoint
- After the pipeline completes, set status to `pending_review` instead of `completed`
- New API endpoint: `POST /api/evaluation/{id}/approve` — marks as completed
- New API endpoint: `POST /api/evaluation/{id}/reject` — marks for re-evaluation with notes
- Dashboard shows pending reviews with summary + Gaston's grades
- **Why:** The system evaluates real students for a real internship program. Unsupervised auto-completion is a liability. Committee members should see and approve evaluations before they become official.

**PR 7: Validation of Agent OUTPUT (not just input)** — `smee_orchestrator.py`
- Current validation only checks: "does this agent have the data it needs?" (input validation)
- Add output validation after each agent: "did this agent produce meaningful output?"
  - Non-empty response
  - Expected fields present in structured output (e.g., Rapunzel must produce GPA, rigor_index)
  - Score ranges valid (0-100, not negative, not > max)
  - Character limit check (detect agent rambling — if output > 10K chars, flag it)
- If validation fails → retry once → if still fails → flag for manual review

#### Sprint 3: Security + Resilience (Weeks 5-6) — Production Hardening

**PR 8: Security Agent (Bob)** — New `src/agents/sideshow_bob.py`
- Add a security review step after Merlin synthesis:
  - Check for PII leakage in the evaluation output
  - Check for bias indicators (demographic assumptions, stereotyping)
  - Check for hallucinated facts (claims not supported by input documents)
  - Check for prompt injection in student-submitted documents (adversarial applicants)
- Model: o3 (deep reasoning for attack modeling)
- Non-blocking but results persisted — security flags visible in dashboard
- **Why:** Student applications contain PII (names, schools, addresses). The system makes consequential decisions (internship selection). A security review layer is not optional.
- **Naming option:** Keep "Sideshow Bob" for consistency with Springfield, or rename to a Disney villain (Jafar? Scar?) for thematic consistency. Brad's call.

**PR 9: Background Job Queue** — New queue system
- This is the biggest structural change. Currently, document processing runs synchronously in the HTTP request thread. For single documents, this is fine. But:
  - If a user uploads 10 documents, the browser times out
  - If gunicorn gets a SIGTERM during processing, work is lost
  - No parallel processing of multiple students
- Options:
  - **Option A: Springfield pattern** — Azure Queue Storage + worker process. Proven, durable, but adds infra complexity.
  - **Option B: Celery + Redis** — Standard Python approach. More moving parts.
  - **Option C: Database-backed queue** — Use Postgres as the queue (new `job_queue` table). Simplest. Smee polls for work. No new infrastructure.
  - **Recommendation: Option C** for now. NextGen processes ~1000 applications/year. A DB-backed queue with a background thread is sufficient. Migrate to Azure Queue later if volume grows.

**PR 10: deploy.sh** — New deployment script
- Create `deploy.sh` that:
  - Checks for running evaluations before deploying
  - Zips the repo (excluding `uploads/`, `.git/`, `testing/`)
  - Deploys via `az webapp deploy --type zip`
  - Verifies `/healthz` returns 200 after deploy
  - Swaps staging → production if using slots
- Delete `azure-deploy.yml` workflow
- **Why:** Springfield's #1 lesson: controlled deployments. Never deploy during active work.

#### Sprint 4: Intelligence (Weeks 7-8) — Making the Pipeline Smarter

**PR 11: Adaptive Planning (Smee Upgrade)** — `smee_orchestrator.py`
- Currently Smee runs a fixed 8-step pipeline regardless of input
- Add a planning step (Springfield Two-Phase pattern, adapted):
  - **Phase 1: Assess** — Belle extracts → Smee analyzes what documents are present:
    - Full application (transcript + recommendations + essay)? → Full pipeline
    - Just transcript? → Skip Tiana (essay analysis), Mulan (recommendations)
    - Video submission? → Route to Mirabel first
    - Resubmission? → Load previous evaluation, diff against new data
  - **Phase 2: Execute** — Run only the agents needed based on Phase 1 assessment
- This saves cost (no point running Mulan if there's no recommendation letter) and improves quality (agents don't hallucinate when given empty input)

**PR 12: Conversation Continuity** — `smee_orchestrator.py`, `base_agent.py`
- Persist response IDs per agent per student evaluation
- On re-evaluation, chain onto previous conversations
- Agents retain context from their first pass, making revisions more coherent
- Store in `workflow_checkpoints` table (added in PR 2)

---

### Scheduling Summary

| Sprint | Weeks | PRs | Theme | Dependencies |
|--------|-------|-----|-------|-------------|
| **Migration** | 0 | Phases 0-7 | Infrastructure move | None — do first |
| **Sprint 1** | 1-2 | PRs 1-4 | Safety net | Migration complete |
| **Sprint 2** | 3-4 | PRs 5-7 | Quality gates | PR 1 (timeouts) |
| **Sprint 3** | 5-6 | PRs 8-10 | Security + resilience | PR 2 (checkpoint), PR 5 (review) |
| **Sprint 4** | 7-8 | PRs 11-12 | Intelligence | PRs 1-7 stable |

### Estimated Work Per PR

| PR | Size | Risk | Can Copilot/Team Handle? |
|----|------|------|--------------------------|
| PR 1: Timeouts + Retry + Fallback | Medium (3 files) | Low | Yes — pattern exists in Springfield factory.py |
| PR 2: Checkpoint + Resume | Large (new module + Smee changes) | Medium | Yes — pattern exists in Springfield orchestrator.py |
| PR 3: Ghost Cleanup | Small (20 lines in app.py) | Low | Yes — trivial |
| PR 4: Blob Storage for Docs | Medium (2 files, StorageManager exists) | Low | Yes — half the code already exists |
| PR 5: Interleaved Quality Review | Large (Smee refactor) | High | Needs careful testing — Smee is 3,062 lines |
| PR 6: Human-in-the-Loop Gate | Medium (new endpoint + status change) | Medium | Yes |
| PR 7: Output Validation | Medium (new validation module) | Low | Yes — straightforward |
| PR 8: Security Agent (Bob) | Medium (new agent + Smee integration) | Medium | Yes — pattern exists in Springfield |
| PR 9: Background Job Queue | Large (new queue system) | High | Option C (DB-backed) reduces risk |
| PR 10: deploy.sh | Small (1 new file) | Low | Yes — copy Springfield pattern |
| PR 11: Adaptive Planning | Large (Smee architectural change) | High | Needs deep understanding of pipeline |
| PR 12: Conversation Continuity | Medium (response ID plumbing) | Medium | Yes — pattern exists in Springfield |

---

### What NOT to Change

1. **Observability stack** — It's the best part of the codebase. Don't touch it.
2. **Database schema** — 20 tables with proper relational design. Don't try to replace with blob storage.
3. **Disney theming** — The agents have personality. Keep it. (But add Bob/Scar for security.)
4. **Security headers** — CSP is nonce-based, X-Frame-Options DENY. Leave it alone.
5. **School workflow** — The NAVEEN ↔ MOANA validation loop is already a feedback pattern. It works.
6. **Section detection** — Belle's page-level routing (transcript vs. essay vs. recommendation) is smart. Keep it.
7. **File type validation** — Whitelist approach is correct. Don't expand without need.

---

### Full Phase Summary (For Scheduling)

| Phase | What | Key Actions | Blocked By |
|-------|------|-------------|------------|
| **0: Pre-Flight** | Verify resources, export configs, add diagnostic endpoints | Local work + az CLI | Nothing |
| **1: New RG + Base Infra** | Create RG, VNet, NSGs, Log Analytics, App Insights, Key Vault | az CLI commands | Phase 0 |
| **2: App Service** | Create plan, web app, staging slot, VNET integration, AlwaysOn | az CLI commands | Phase 1 |
| **3: Private Endpoints** | PEs to KV, Storage, Postgres, Foundry (eastus2) — cross-RG | az CLI commands | Phase 1 |
| **4: Configure + Deploy** | Migrate KV secrets, set app settings, deploy code, remove FD restrictions | az CLI + zip deploy | Phases 2-3 |
| **4b: Model Upgrade** | Bump gpt-5.4 TPM, point app at springfield-ai-eastus2, update model refs | az CLI + code PR | Phase 4 |
| **5: Validate** | Health checks, diagnostic endpoints, auth flow, test evaluation | Manual testing | Phase 4b |
| **6: URL Cutover** | Give users new *.azurewebsites.net URL | Communication | Phase 5 |
| **7: Cleanup** | Delete FD, WAF, old web app, old PEs, orphaned resources, dead CogServices | az CLI (destructive) | Phase 6 + 1 week soak |
| **S1-PR1** | Timeouts + Retry + Fallback | Code PR to agent-nextgen | Phase 5 |
| **S1-PR2** | Checkpoint + Resume | Code PR | S1-PR1 |
| **S1-PR3** | Ghost Cleanup on Startup | Code PR | S1-PR2 |
| **S1-PR4** | Blob Storage for Documents | Code PR | Phase 4 |
| **S2-PR5** | Interleaved Quality Review (Gaston) | Code PR — largest change | S1-PR1 |
| **S2-PR6** | Human-in-the-Loop Gate | Code PR | S2-PR5 |
| **S2-PR7** | Output Validation | Code PR | S1-PR1 |
| **S3-PR8** | Security Agent (Bob/Scar) | Code PR | S2-PR5 |
| **S3-PR9** | Background Job Queue (DB-backed) | Code PR | S1-PR2 |
| **S3-PR10** | deploy.sh | Code PR | Phase 4 |
| **S4-PR11** | Adaptive Planning | Code PR — Smee architectural change | S2-PR5, S1-PR2 |
| **S4-PR12** | Conversation Continuity | Code PR | S1-PR2 |
