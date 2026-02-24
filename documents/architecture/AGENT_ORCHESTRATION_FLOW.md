# Agent Orchestration Flow

This document describes the orchestration flow executed by the `smee_orchestrator` and the expected persistence points for each agent. Use this as the source of truth when reviewing sequencing, parallelism, and persistence behavior.

## Overview

- Start processing request (HTTP `/api/process/<application_id>` or upload-trigger).
- If `application_id` is missing, the orchestrator creates a placeholder application record so downstream agents always have an `application_id` to persist into.
- `BELLE` extracts structured data and canonicalizes high-school (name/city/state).
- Enrichment step augments or matches students / high-school data.
- Core agents run in parallel: `Tiana` (fields), `Rapunzel` (grades), `Moana` (school context), `Mulan` (recommendations).
- Each core agent persists its structured result via `db.save_*` helper functions.
- Orchestrator waits for core agents to finish, then runs `Merlin` (evaluation/scoring).
- `Milo` runs training/analysis asynchronously — its async method must be awaited (do not wrap without awaiting).
- `Aurora` formats the final report and the orchestrator persists the final formatted evaluation.
- Orchestrator logs progress via `log_agent_interaction()` and emits SSE progress events for the UI.

## Mermaid flow

```mermaid
flowchart TD
  A([Start processing request]) --> B{application_id present?}
  B -- no --> C[/create placeholder application/]
  B -- yes --> D[Belle (extract & canonicalize HS)]
  C --> D
  D --> E[Enrichment / match student / HS enrichment]
  E --> P[Run core agents in parallel]
  P --> T[Tiana: parse application fields]
  P --> R[Rapunzel: parse grades / GPA]
  P --> M[Moana: school context & canonical match]
  P --> U[Mulan: parse recommendations]
  T --> DB_T[/db.save_tiana_application()/]
  R --> DB_R[/db.save_rapunzel_grades()/]
  M --> DB_M[/db.save_moana_school_context()/]
  U --> DB_U[/db.save_mulan_recommendation()/]
  DB_T --> W[Wait for core agents]
  DB_R --> W
  DB_M --> W
  DB_U --> W
  W --> N[Merlin: evaluate & score] --> DB_N[/db.save_merlin_evaluation()/]
  N --> Q[Aurora: format final report] --> DB_Q[/db.save_aurora_evaluation()/]
  N --> O[Milo: analyze_training_insights() — async & must be awaited]
  O --> DB_O[/db.log_agent_interaction() or db.save_milo()/]
  Q --> Z([Workflow complete])
```

  ## Clarified explanation: persistence behavior

  The orchestrator persists core agent outputs as soon as each agent finishes processing. Concretely:

  - Each core agent (`Tiana`, `Rapunzel`, `Moana`, `Mulan`) calls its `db.save_*` helper immediately after producing its structured result.
  - The orchestrator waits for the completion of the core agents (the wait point in the flow) but the database rows are already written by the time the orchestrator proceeds to `Merlin`.
  - This design ensures the UI and any downstream steps can reliably read persisted rows even if the orchestrator crashes or a later step fails.
  - If you prefer eventual persistence or transactional batching (persist only after all core agents succeed), we can modify the orchestrator to buffer results in-memory and write them in a single commit — but that introduces a period where results are not durable.

  Recommendation: keep immediate persistence for resilience, and add compensating transactions or cleanup logic if partial failures need coordinated rollback.

## Where to look in the code

- Orchestrator: [src/agents/smee_orchestrator.py](src/agents/smee_orchestrator.py)
- Belle (extraction): [src/agents/belle_document_analyzer.py](src/agents/belle_document_analyzer.py)
- Agent persistence helpers: [src/database.py](src/database.py)
- Core agents: [src/agents/tiana_agent.py](src/agents/) (Tiana), [src/agents/rapunzel_agent.py](src/agents/) (Rapunzel), [src/agents/moana_agent.py](src/agents/) (Moana), [src/agents/mulan_agent.py](src/agents/) (Mulan)
- Merlin: [src/agents/merlin_agent.py](src/agents/)
- Milo: [src/agents/milo_data_scientist.py](src/agents/milo_data_scientist.py)
- Aurora: [src/agents/aurora_agent.py](src/agents/aurora_agent.py)

> Note: some agent filenames may differ; search under `src/agents/` for exact names used in your repo.

## Reviewer checklist

- [ ] Confirm the orchestrator creates a placeholder application early when `application_id` is missing (necessary so agents can call `db.save_*`).
- [ ] Verify each core agent calls its corresponding `db.save_*` function and that rows are present after processing a rich test input (e.g., application 284).
- [ ] Ensure `Milo.analyze_training_insights()` and any other async agent methods are awaited (avoid storing coroutine objects in result payloads).
- [ ] Confirm SSE events and `log_agent_interaction()` calls are emitted at meaningful checkpoints (start, after BELLE, after core agents, after Merlin, after Aurora).
- [ ] Review UI rendering in `/application/<id>` to confirm it reads persisted rows (not ephemeral in-memory objects).

## Known fixes applied

- Awaited `milo.analyze_training_insights()` in `smee_orchestrator` to avoid the `Object of type coroutine is not JSON serializable` error.
- Added placeholder application creation in the orchestrator when `application_id` is missing.
- Tightened `BELLE` high-school extraction heuristics (`src/agents/belle_document_analyzer.py`).

## Next steps I can run for you

- Run processing for application 284 and stream SSE logs to confirm core agents persisted outputs.
- Query the DB tables for `application_id=284` and report back which agent outputs are present/missing.

Please review this doc and tell me any edits or additional details you'd like included.
