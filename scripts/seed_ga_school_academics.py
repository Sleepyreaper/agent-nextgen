#!/usr/bin/env python3
"""Seed authoritative academic data for Georgia schools.

Connects to the production DB, reads all GA schools from school_enriched_data,
uses the AI model to look up each school's publicly available academic data,
and writes it back via the supplemental import pipeline with provenance tracking.

Usage:
    # From the project root (with .env or Key Vault access):
    python scripts/seed_ga_school_academics.py

    # Dry run (don't write to DB):
    python scripts/seed_ga_school_academics.py --dry-run

    # Limit to N schools (for testing):
    python scripts/seed_ga_school_academics.py --limit 5

The script produces data/ga_school_academics.csv which can also be
imported manually via the Schools → Import Supplemental Academic Data UI.
"""

import argparse
import csv
import json
import logging
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import config
from src.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

SOURCE_NAME = 'AI_Knowledge_GA_2025'
CSV_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'ga_school_academics.csv')

# Fields we want to populate
ACADEMIC_FIELDS = [
    'ncessch',
    'school_name',
    'ap_course_count',
    'ap_exam_pass_rate',
    'honors_course_count',
    'graduation_rate',
    'college_acceptance_rate',
    'stem_program_available',
    'ib_program_available',
    'dual_enrollment_available',
    'school_url',
]


def get_ai_client():
    """Get the AI client using the app's config."""
    if config.model_provider and config.model_provider.lower() == 'foundry':
        from src.agents.foundry_client import FoundryClient
        return FoundryClient(endpoint=config.foundry_project_endpoint)
    if config.azure_openai_api_key:
        from openai import AzureOpenAI
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=config.api_version,
            azure_endpoint=config.azure_openai_endpoint,
        )
    raise RuntimeError("No AI client configured")


def lookup_school_academics(client, model, school_name, district, state, nces_id, enrollment, frpl_pct):
    """Use AI to look up publicly available academic data for a school."""
    prompt = f"""Look up the following Georgia high school and provide its REAL, publicly available academic data.
This data is used for a scholarship program and must be accurate.

School: {school_name}
District: {district}
State: {state}
NCES ID: {nces_id}
Enrollment: {enrollment}
Free/Reduced Lunch %: {frpl_pct}

Return a JSON object with ONLY data you are confident about from public records.
If you are not confident about a field, set it to null (do NOT guess).
Use data from the most recent available school year.

Required JSON keys:
- ap_course_count: integer (number of AP courses offered, from CollegeBoard AP Course Ledger or school profile)
- ap_exam_pass_rate: float (% of AP exams scoring 3+, null if unknown)
- honors_course_count: integer (estimated number of honors courses, null if unknown)
- graduation_rate: float (4-year cohort graduation rate %)
- college_acceptance_rate: float (% of graduates attending college, null if unknown)
- stem_program_available: boolean (does the school have dedicated STEM programs?)
- ib_program_available: boolean (does the school offer IB?)
- dual_enrollment_available: boolean (does the school offer dual enrollment?)
- school_url: string (official school website URL)
- confidence_notes: string (brief note on data sources/confidence)

Return valid JSON only."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are a school data researcher. Look up real, publicly available data "
                    "about Georgia high schools. Only provide data you are confident about "
                    "from public records (Georgia DOE, CollegeBoard, school websites, NCES). "
                    "Return null for fields you cannot verify. Accuracy is critical — this data "
                    "affects scholarship decisions for real students."
                )},
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = json.loads(content)
        return data
    except Exception as e:
        logger.warning(f"  AI lookup failed for {school_name}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Seed GA school academic data')
    parser.add_argument('--dry-run', action='store_true', help='Print data but do not write to DB')
    parser.add_argument('--limit', type=int, default=0, help='Limit to N schools (0 = all)')
    parser.add_argument('--delay', type=float, default=2.0, help='Delay between API calls (seconds)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Georgia School Academic Data Seeder")
    logger.info("=" * 60)

    # Get all GA schools from DB
    schools = db.execute_query(
        """SELECT school_enrichment_id, nces_id, school_name, school_district,
                  state_code, total_students, free_lunch_percentage,
                  ap_course_count, graduation_rate, honors_course_count
           FROM school_enriched_data
           WHERE state_code = 'GA' AND is_active = TRUE
           ORDER BY school_name"""
    )

    if not schools:
        logger.error("No GA schools found in database. Import the CCD CSV first.")
        return

    logger.info(f"Found {len(schools)} GA schools in database")

    if args.limit > 0:
        schools = schools[:args.limit]
        logger.info(f"Limited to {args.limit} schools")

    # Setup AI client
    client = get_ai_client()
    model = config.model_tier_workhorse or config.foundry_model_name or config.deployment_name
    logger.info(f"Using model: {model}")

    # Ensure data/ directory exists
    os.makedirs(os.path.dirname(CSV_OUTPUT), exist_ok=True)

    # Process each school
    results = []
    for idx, school in enumerate(schools):
        name = school['school_name']
        nces_id = school.get('nces_id', '')
        district = school.get('school_district', '')
        enrollment = school.get('total_students', 0)
        frpl = school.get('free_lunch_percentage', 0)

        # Skip if already has real AP data (non-zero)
        existing_ap = school.get('ap_course_count') or 0
        existing_grad = school.get('graduation_rate') or 0
        if existing_ap > 0 and existing_grad > 0:
            logger.info(f"  [{idx+1}/{len(schools)}] {name}: SKIP (already has AP={existing_ap}, grad={existing_grad})")
            continue

        logger.info(f"  [{idx+1}/{len(schools)}] Looking up: {name} (NCES: {nces_id})...")

        data = lookup_school_academics(client, model, name, district, 'GA', nces_id, enrollment, frpl)

        if data:
            row = {
                'ncessch': nces_id,
                'school_name': name,
                'ap_course_count': data.get('ap_course_count'),
                'ap_exam_pass_rate': data.get('ap_exam_pass_rate'),
                'honors_course_count': data.get('honors_course_count'),
                'graduation_rate': data.get('graduation_rate'),
                'college_acceptance_rate': data.get('college_acceptance_rate'),
                'stem_program_available': data.get('stem_program_available'),
                'ib_program_available': data.get('ib_program_available'),
                'dual_enrollment_available': data.get('dual_enrollment_available'),
                'school_url': data.get('school_url'),
            }
            results.append(row)
            ap = row.get('ap_course_count') or '?'
            grad = row.get('graduation_rate') or '?'
            logger.info(f"    ✓ AP={ap}, Grad={grad}%, URL={row.get('school_url', '?')}")
            notes = data.get('confidence_notes', '')
            if notes:
                logger.info(f"    Notes: {notes}")
        else:
            logger.warning(f"    ✗ No data returned")

        if idx < len(schools) - 1:
            time.sleep(args.delay)

    # Write CSV
    logger.info(f"\nWriting {len(results)} records to {CSV_OUTPUT}")
    with open(CSV_OUTPUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=ACADEMIC_FIELDS)
        writer.writeheader()
        for row in results:
            # Convert booleans to strings for CSV
            for key in ('stem_program_available', 'ib_program_available', 'dual_enrollment_available'):
                val = row.get(key)
                if val is True:
                    row[key] = 'true'
                elif val is False:
                    row[key] = 'false'
                else:
                    row[key] = ''
            # Convert None to empty string
            row = {k: (v if v is not None else '') for k, v in row.items()}
            writer.writerow(row)

    logger.info(f"✅ CSV written: {CSV_OUTPUT}")

    # Import to DB if not dry-run
    if not args.dry_run and results:
        logger.info(f"\nImporting supplemental data to database (source={SOURCE_NAME})...")
        from src.csv_school_importer import import_supplemental_csv
        result = import_supplemental_csv(CSV_OUTPUT, db, source_name=SOURCE_NAME)
        logger.info(f"Import result: {json.dumps(result, indent=2)}")
    elif args.dry_run:
        logger.info(f"\n[DRY RUN] Skipping DB import. CSV is at {CSV_OUTPUT}")
        logger.info("To import manually: use Schools → Import Supplemental Academic Data in the UI")

    logger.info("\n✅ Done!")


if __name__ == '__main__':
    main()
