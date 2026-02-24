"""Backfill per-agent `human_summary` fields from existing Merlin/agent fields.

This script does NOT call the model. It synthesizes a short 2-3 sentence
summary from available fields (recommendation, overall_score, rationale,
key_strengths, key_risks) so historical rows have readable summaries.

Usage:
  PYTHONPATH=. python3 scripts/backfill_agent_human_summaries_from_merlin.py --dry-run --application-id 477
  PYTHONPATH=. python3 scripts/backfill_agent_human_summaries_from_merlin.py --application-id 477

Run from the project root in your environment where DB access is configured.
"""
import json
import argparse
import traceback
from src.database import Database
from src.utils import safe_load_json


def synthesize_from_merlin(merlin: dict) -> str:
    parts = []
    rec = merlin.get('recommendation') or merlin.get('recommendation_text') or None
    score = merlin.get('overall_score') or merlin.get('overallscore')
    rationale = merlin.get('rationale') or merlin.get('explanation') or None
    strengths = merlin.get('key_strengths') or merlin.get('strengths') or []
    risks = merlin.get('key_risks') or merlin.get('risks') or []

    if rec:
        parts.append(f"Recommendation: {rec}.")
    if score is not None:
        parts.append(f"Score: {score}.")
    if rationale:
        # keep only first sentence of rationale to keep summary concise
        first_sent = rationale.split('\n')[0].split('. ')[0].strip()
        if first_sent:
            parts.append(f"Summary: {first_sent}.")

    if strengths:
        try:
            s = strengths if isinstance(strengths, str) else (', '.join(strengths[:3]) if isinstance(strengths, (list, tuple)) else str(strengths))
            parts.append(f"Strengths: {s}.")
        except Exception:
            pass

    if risks:
        try:
            r = risks if isinstance(risks, str) else (', '.join(risks[:3]) if isinstance(risks, (list, tuple)) else str(risks))
            parts.append(f"Risks: {r}.")
        except Exception:
            pass

    # join into 2-3 sentences maximum
    if not parts:
        return "No summary available."
    # prefer up to first 3 parts
    summary = ' '.join(parts[:3])
    return summary


def main(dry_run=False, application_id=None):
    db = Database()
    try:
        db.connect()
    except Exception as e:
        print(f"Could not connect to DB: {e}")
        return

    if application_id:
        rows = db.execute_query("SELECT application_id, agent_results FROM applications WHERE application_id = %s", (application_id,))
    else:
        rows = db.execute_query("SELECT application_id, agent_results FROM applications")

    updated = 0
    for row in rows:
        app_id = row.get('application_id')
        ar = row.get('agent_results') or {}
        if isinstance(ar, str):
            try:
                ar = safe_load_json(ar)
            except Exception:
                ar = {}

        if not isinstance(ar, dict):
            continue

        changed = False
        for agent_key, agent_res in list(ar.items()):
            if isinstance(agent_res, dict) and agent_res.get('human_summary'):
                continue

            # try to synthesize from merlin when available
            merlin = ar.get('merlin') or ar.get('student_evaluator') or {}
            if merlin and isinstance(merlin, dict):
                fallback = synthesize_from_merlin(merlin)
                # attach to each agent lacking summary so UI shows something
                if isinstance(agent_res, dict):
                    agent_res['human_summary'] = fallback
                    ar[agent_key] = agent_res
                else:
                    ar[agent_key] = {'result': agent_res, 'human_summary': fallback}
                changed = True

        if changed:
            if dry_run:
                print(f"[dry-run] would update app {app_id} with synthesized summaries")
            else:
                try:
                    db.update_application(application_id=app_id, agent_results=json.dumps(ar))
                    updated += 1
                    print(f"Updated app {app_id}")
                except Exception:
                    print(f"Failed to persist app {app_id}")
                    traceback.print_exc()

    print(f"Done. Updated {updated} rows")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--application-id', type=int)
    args = parser.parse_args()
    main(dry_run=args.dry_run, application_id=args.application_id)
