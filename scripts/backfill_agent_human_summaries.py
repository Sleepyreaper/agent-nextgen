"""Backfill per-agent `human_summary` fields in `applications.agent_results`.

Run this script from the project root (inside the virtualenv with model creds):

    python scripts/backfill_agent_human_summaries.py

The script will iterate application rows and for the critical agents
(`tiana`, `rapunzel`, `moana`, `mulan`, `merlin`) generate a short
human-friendly summary using the same prompt the orchestrator uses,
then persist the updated `agent_results` back to the DB.
"""
import json
import sys
import traceback

from src.config import config
from src.database import Database
from src.utils import safe_load_json
import argparse
import os

# Defer heavy agent imports (SmeeOrchestrator / model clients) until we
# actually need to call the model so this script can run in environments
# that don't have all optional dependencies installed.
SmeeOrchestrator = None
client = None


def main(dry_run=False, application_id=None):
    db = Database()
    try:
        db.connect()
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        sys.exit(1)

    required_agents = ['tiana', 'rapunzel', 'moana', 'mulan', 'merlin']

    # Only import orchestrator and model client when not doing a dry-run
    orchestrator = None
    model_client_available = False
    if not dry_run:
        try:
            from src.agents.smee_orchestrator import SmeeOrchestrator as _Smee
            SmeeOrchestrator = _Smee
            # lightweight client selection mirroring app.get_ai_client
            if config.model_provider and config.model_provider.lower() == 'foundry':
                from src.agents.foundry_client import FoundryClient
                client = FoundryClient(endpoint=config.foundry_project_endpoint)
            else:
                try:
                    from openai import AzureOpenAI
                    client = AzureOpenAI(
                        api_key=config.azure_openai_api_key or None,
                        api_version=config.api_version,
                        azure_endpoint=config.azure_openai_endpoint,
                        azure_deployment=config.deployment_name,
                    )
                except Exception:
                    try:
                        from src.agents.foundry_client import FoundryClient
                        client = FoundryClient(endpoint=config.foundry_project_endpoint)
                    except Exception:
                        client = None
            model_name = config.foundry_model_name if getattr(config, 'model_provider', None) == 'foundry' else config.deployment_name
            orchestrator = SmeeOrchestrator(name='smee-backfill', client=client, model=model_name, db_connection=db)
            model_client_available = True
        except Exception as e:
            print(f"Model client or orchestrator import failed; proceeding in dry-run-like mode: {e}")

    if application_id:
        rows = db.execute_query("SELECT application_id, agent_results FROM applications WHERE application_id = %s", (application_id,))
    else:
        rows = db.execute_query("SELECT application_id, agent_results FROM applications")
    total = len(rows)
    print(f"Found {total} application rows to inspect")

    updated = 0
    for idx, row in enumerate(rows, start=1):
        app_id = row.get('application_id')
        ar = row.get('agent_results') or {}
        if isinstance(ar, str):
            try:
                ar = safe_load_json(ar)
            except Exception:
                ar = {}

        if not isinstance(ar, dict) or not ar:
            continue

        changed = False
        for agent_key in required_agents:
            agent_res = ar.get(agent_key)
            if not agent_res:
                continue

            # if dict and has non-empty human_summary, skip
            if isinstance(agent_res, dict) and agent_res.get('human_summary'):
                continue

            # Build prompt context as the orchestrator does
            ctx = agent_res if isinstance(agent_res, (dict, list, str)) else str(agent_res)
            ctx_text = json.dumps(ctx, ensure_ascii=False) if not isinstance(ctx, str) else ctx
            prompt = [
                {
                    "role": "user",
                    "content": (
                        f"You are given the output from the agent '{agent_key}'. "
                        "Produce a concise (1-3 sentences) human-friendly executive summary that could be shown on a student evaluation page. "
                        "Keep it neutral, factual, and suitable for a non-technical audience. "
                        "If available, include the agent's top recommendation or key risk in one sentence.\n\n"
                        "Agent output (JSON):\n" + str(ctx_text)
                    )
                }
            ]

            if dry_run or not model_client_available:
                # Report what would be done
                print(f"[{idx}/{total}] app:{app_id} agent:{agent_key} -> MISSING human_summary (would generate)")
                continue

            # Generate summary using orchestrator helper
            try:
                resp = orchestrator._create_chat_completion(f"{agent_key}.summary", None, prompt, max_completion_tokens=140, refinements=0)
                summ = orchestrator._normalize_agent_result(resp)
                if isinstance(summ, (dict, list)):
                    try:
                        summ_text = json.dumps(summ, ensure_ascii=False)
                    except Exception:
                        summ_text = str(summ)
                else:
                    summ_text = str(summ)
            except Exception as e:
                print(f"[{idx}/{total}] app:{app_id} agent:{agent_key} summarization failed: {e}")
                traceback.print_exc()
                continue

            if not summ_text:
                continue

            # attach summary
            if isinstance(agent_res, dict):
                agent_res['human_summary'] = summ_text
                ar[agent_key] = agent_res
            else:
                ar[agent_key] = {'result': agent_res, 'human_summary': summ_text}

            try:
                db.update_application(application_id=app_id, agent_results=json.dumps(ar))
                changed = True
                print(f"[{idx}/{total}] app:{app_id} agent:{agent_key} -> human_summary added")
            except Exception as e:
                print(f"Failed to persist human_summary for app:{app_id} agent:{agent_key}: {e}")
                traceback.print_exc()

        if changed:
            updated += 1

    print(f"Backfill complete. Updated {updated} application rows")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Backfill per-agent human_summary fields")
    parser.add_argument('--dry-run', action='store_true', help='Do not call model or persist changes; just report missing summaries')
    parser.add_argument('--application-id', type=int, help='Only process a single application id')
    args = parser.parse_args()
    main(dry_run=args.dry_run, application_id=args.application_id)
