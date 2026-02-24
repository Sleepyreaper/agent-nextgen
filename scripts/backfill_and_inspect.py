#!/usr/bin/env python3
"""Backfill student_summary and inspect a specific application row.

Usage:
  DATABASE_URL=<conn> python3 scripts/backfill_and_inspect.py [APPLICATION_ID]

This script calls the Database.backfill_student_summaries() helper (idempotent)
and then prints the `agent_results` and `student_summary` for the requested
application ID (defaults to 433).
"""
import json
import logging
import sys

from src.database import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    app_id = int(sys.argv[1]) if len(sys.argv) > 1 else 433
    db = Database()

    try:
        updated = db.backfill_student_summaries()
        logger.info(f"backfill_student_summaries: updated {updated} rows")
    except Exception as e:
        logger.error(f"Backfill failed: {e}")

    try:
        row = db.get_application(app_id)
        if not row:
            print(f"Application {app_id} not found")
            return

        print("\n=== agent_results ===")
        print(json.dumps(row.get("agent_results"), indent=2, ensure_ascii=False))

        print("\n=== student_summary ===")
        print(json.dumps(row.get("student_summary"), indent=2, ensure_ascii=False))

    except Exception as e:
        logger.error(f"Failed to fetch application {app_id}: {e}")


if __name__ == "__main__":
    main()
