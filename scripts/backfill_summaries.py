#!/usr/bin/env python3
"""Utility script to backfill the ``student_summary`` column.

This should be run after deploying the migration that added the column.  It
scans through all existing application rows and computes a concise summary from
whatever agent_results are already stored.  The process is idempotent and safe
to repeat.

Usage:

    python scripts/backfill_summaries.py

The script will print the number of rows it updated.
"""

from src.database import db


def main():
    print("Starting student_summary backfill...")
    updated = db.backfill_student_summaries()
    print(f"Backfilled {updated} application(s)")


if __name__ == '__main__':
    main()
