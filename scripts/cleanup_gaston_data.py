#!/usr/bin/env python3
"""One-time migration to strip all gaston data from the database."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import db


def main():
    # Find all applications with gaston in agent_results or student_summary
    # Use CAST for PostgreSQL compatibility and plain LIKE for SQLite
    try:
        rows = db.execute_query(
            "SELECT application_id, agent_results, student_summary "
            "FROM applications "
            "WHERE CAST(agent_results AS TEXT) LIKE '%gaston%' "
            "OR CAST(student_summary AS TEXT) LIKE '%gaston%'"
        )
    except Exception:
        rows = db.execute_query(
            "SELECT application_id, agent_results, student_summary "
            "FROM applications "
            "WHERE agent_results LIKE '%gaston%' "
            "OR student_summary LIKE '%gaston%'"
        )
    print(f"Found {len(rows)} rows with gaston data")

    cleaned_ar = 0
    cleaned_ss = 0

    for row in rows:
        app_id = row["application_id"]

        # Clean agent_results
        ar = row.get("agent_results")
        if isinstance(ar, str):
            try:
                ar = json.loads(ar)
            except Exception:
                ar = None
        if isinstance(ar, dict) and "gaston" in ar:
            ar.pop("gaston", None)
            db.execute_non_query(
                "UPDATE applications SET agent_results = %s WHERE application_id = %s",
                (json.dumps(ar), app_id),
            )
            cleaned_ar += 1
            print(f"  Cleaned agent_results for app {app_id}")

        # Clean student_summary
        ss = row.get("student_summary")
        if isinstance(ss, str):
            try:
                ss = json.loads(ss)
            except Exception:
                ss = None
        if isinstance(ss, dict):
            changed = False
            ad = ss.get("agent_details")
            if isinstance(ad, dict) and "gaston" in ad:
                ad.pop("gaston", None)
                changed = True
            ac = ss.get("agents_completed")
            if isinstance(ac, list) and "gaston" in ac:
                ac.remove("gaston")
                changed = True
            if changed:
                db.execute_non_query(
                    "UPDATE applications SET student_summary = %s WHERE application_id = %s",
                    (json.dumps(ss), app_id),
                )
                cleaned_ss += 1
                print(f"  Cleaned student_summary for app {app_id}")

    print(f"\nDone. Cleaned {cleaned_ar} agent_results, {cleaned_ss} student_summaries.")


if __name__ == "__main__":
    main()
