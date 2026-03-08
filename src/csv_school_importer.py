"""CSV School Importer — Reads GA high-school SES data and collapses multi-year rows
into one record per school for the school_enriched_data table.

Usage:
    # As a module (from app.py endpoint or standalone):
    from src.csv_school_importer import import_schools_from_csv
    result = import_schools_from_csv('/path/to/ga_highschools_all_ses.csv', db)

    # Standalone CLI:
    python -m src.csv_school_importer /path/to/ga_highschools_all_ses.csv

Design decisions:
  - Dedup key is NCES school ID (ncessch).  This is the national identifier
    that stays stable even when a school is renamed.
  - For schools sharing a name but with different NCES IDs (e.g. two
    "Woodland High School" in different counties), each gets its own record.
  - Latest year wins for scalar fields (enrollment, address, phone, etc.)
  - Averages for rate fields (frpl_pct, district_poverty_pct)
  - Trend arrays built for enrollment and frpl_pct across years
  - School name taken from the most recent year (handles renames)
  - Sentinel values (-1, -2) and empty strings are treated as NULL
"""

import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── CSV column name constants ──────────────────────────────────────────────
CSV_SCHOOL_YEAR = 'school_year'
CSV_NCESSCH = 'ncessch'
CSV_SCHOOL_NAME = 'school_name'
CSV_LEA_NAME = 'lea_name'
CSV_STREET = 'street_location'
CSV_CITY = 'city_location'
CSV_STATE = 'state_location'
CSV_ZIP = 'zip_location'
CSV_PHONE = 'phone'
CSV_LAT = 'latitude'
CSV_LON = 'longitude'
CSV_COUNTY = 'county_code'
CSV_CHARTER = 'charter'
CSV_MAGNET = 'magnet'
CSV_VIRTUAL = 'virtual'
CSV_SCHOOL_TYPE = 'school_type'
CSV_SCHOOL_STATUS = 'school_status'
CSV_LOCALE = 'urban_centric_locale'
CSV_TITLE_I = 'title_i_eligible'
CSV_TEACHERS_FTE = 'teachers_fte'
CSV_ENROLLMENT = 'enrollment'
CSV_FREE_LUNCH = 'free_lunch'
CSV_REDUCED_LUNCH = 'reduced_price_lunch'
CSV_FRPL = 'free_or_reduced_price_lunch'
CSV_FRPL_PCT = 'frpl_pct'
CSV_DIRECT_CERT = 'direct_certification'
CSV_DISTRICT_POP = 'district_est_population'
CSV_DISTRICT_POVERTY_PCT = 'district_poverty_pct'
CSV_DISTRICT_EXP_PP = 'district_exp_per_pupil'
CSV_DISTRICT_REV_PP = 'district_rev_per_pupil'
CSV_DISTRICT_EXP_INST_PP = 'district_exp_instruction_per_pupil'
CSV_DISTRICT_REV_FED = 'district_rev_federal_pct'
CSV_DISTRICT_REV_STATE = 'district_rev_state_pct'
CSV_DISTRICT_REV_LOCAL = 'district_rev_local_pct'

# School-type code mapping (NCES CCD codes)
SCHOOL_TYPE_MAP = {
    '1': 'public',
    '2': 'public_special',
    '4': 'public_alternative',
    'private': 'private',
}

# School year sort key: "2023-24" → 2023
def _year_sort_key(year_str: str) -> int:
    """Extract leading year for sorting, e.g. '2023-24' → 2023."""
    try:
        return int(year_str.split('-')[0])
    except (ValueError, IndexError):
        return 0


def _safe_float(val: Any, allow_negative: bool = False) -> Optional[float]:
    """Parse a float, returning None for sentinels (-1, -2) and blanks.
    
    Args:
        val: Value to parse
        allow_negative: If True, allow all negative values.  If False,
                        treat negatives as NCES "data not available" sentinels.
    """
    if val is None or val == '':
        return None
    try:
        f = float(val)
        if not allow_negative and f < 0:  # -1 and -2 are NCES "data not available" sentinels
            return None
        return f
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any, allow_negative: bool = False) -> Optional[int]:
    """Parse an int, returning None for sentinels and blanks."""
    f = _safe_float(val, allow_negative=allow_negative)
    if f is None:
        return None
    return int(round(f))


def _safe_bool(val: Any) -> bool:
    """Parse a boolean flag (1/0, '1'/'0', True/False)."""
    if val is None or val == '':
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip() in ('1', 'True', 'true', 'yes')


def _avg(values: List[Optional[float]]) -> Optional[float]:
    """Average of non-None values, rounded to 1 decimal."""
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 1)


def _compute_student_teacher_ratio(enrollment: Optional[int], teachers: Optional[float]) -> Optional[float]:
    """Compute student-teacher ratio from enrollment and FTE teachers."""
    if enrollment and teachers and teachers > 0:
        return round(enrollment / teachers, 1)
    return None


# ── Main aggregation logic ─────────────────────────────────────────────────

def _aggregate_school(nces_id: str, rows: List[Dict[str, str]]) -> Dict[str, Any]:
    """Collapse multiple year-rows for one school into a single record.

    Strategy:
      - Scalar/identity fields → latest year
      - Enrollment, FRPL counts → latest year with valid data
      - Rate percentages → average across all valid years
      - Trends → JSON arrays keyed by year for enrollment & frpl_pct
      - Boolean flags (charter, magnet, etc.) → True if ANY year says True
    """
    # Sort rows by year (ascending) so latest is last
    sorted_rows = sorted(rows, key=lambda r: _year_sort_key(r.get(CSV_SCHOOL_YEAR, '')))
    latest = sorted_rows[-1]

    # ── Build trend arrays ──
    # Note: frpl_pct == 0.0 in 2021-22 is a data artifact from universal
    # school meals (USDA waiver), not a real value.  We exclude it from
    # averages but keep it in the trend array with a None marker.
    enrollment_trend = {}
    frpl_trend = {}
    for r in sorted_rows:
        yr = r.get(CSV_SCHOOL_YEAR, '')
        e = _safe_int(r.get(CSV_ENROLLMENT))
        if e is not None and e > 0:
            enrollment_trend[yr] = e
        fp = _safe_float(r.get(CSV_FRPL_PCT))
        if fp is not None:
            # Mark 0.0 as suspect but still record in trend
            frpl_trend[yr] = fp

    # ── Latest valid enrollment ──
    latest_enrollment = None
    latest_teachers = None
    for r in reversed(sorted_rows):
        e = _safe_int(r.get(CSV_ENROLLMENT))
        if e is not None and e > 0:
            latest_enrollment = e
            latest_teachers = _safe_float(r.get(CSV_TEACHERS_FTE))
            break

    # ── Averages for rate fields ──
    # Exclude frpl_pct == 0.0 from averages (universal meals artifact)
    frpl_pcts = [_safe_float(r.get(CSV_FRPL_PCT)) for r in sorted_rows]
    frpl_pcts_clean = [v for v in frpl_pcts if v is not None and v > 0]
    district_poverty_pcts = [_safe_float(r.get(CSV_DISTRICT_POVERTY_PCT)) for r in sorted_rows]
    district_exp_pps = [_safe_float(r.get(CSV_DISTRICT_EXP_PP)) for r in sorted_rows]
    district_rev_pps = [_safe_float(r.get(CSV_DISTRICT_REV_PP)) for r in sorted_rows]
    district_exp_inst_pps = [_safe_float(r.get(CSV_DISTRICT_EXP_INST_PP)) for r in sorted_rows]
    district_rev_feds = [_safe_float(r.get(CSV_DISTRICT_REV_FED)) for r in sorted_rows]
    district_rev_states = [_safe_float(r.get(CSV_DISTRICT_REV_STATE)) for r in sorted_rows]
    district_rev_locals = [_safe_float(r.get(CSV_DISTRICT_REV_LOCAL)) for r in sorted_rows]

    # ── Compute reduced lunch % from latest year with data ──
    reduced_lunch_pct = None
    for r in reversed(sorted_rows):
        rl = _safe_int(r.get(CSV_REDUCED_LUNCH))
        enr = _safe_int(r.get(CSV_ENROLLMENT))
        if rl is not None and enr and enr > 0:
            reduced_lunch_pct = round(rl / enr * 100, 1)
            break

    # ── Direct certification % (raw count ÷ enrollment) ──
    direct_cert_pcts = []
    for r in sorted_rows:
        dc = _safe_float(r.get(CSV_DIRECT_CERT))
        enr = _safe_int(r.get(CSV_ENROLLMENT))
        if dc is not None and enr and enr > 0:
            direct_cert_pcts.append(round(dc / enr * 100, 1))

    # ── Boolean flags: True if any year says True ──
    is_charter = any(_safe_bool(r.get(CSV_CHARTER)) for r in sorted_rows)
    is_magnet = any(_safe_bool(r.get(CSV_MAGNET)) for r in sorted_rows)
    is_virtual = any(_safe_bool(r.get(CSV_VIRTUAL)) for r in sorted_rows)
    is_title_i = any(_safe_bool(r.get(CSV_TITLE_I)) for r in sorted_rows)

    # ── School type ──
    raw_type = latest.get(CSV_SCHOOL_TYPE, '').strip()
    school_type = SCHOOL_TYPE_MAP.get(raw_type, raw_type)

    # ── District population (latest) ──
    district_pop = None
    for r in reversed(sorted_rows):
        dp = _safe_int(r.get(CSV_DISTRICT_POP))
        if dp is not None:
            district_pop = dp
            break

    avg_frpl = _avg(frpl_pcts_clean)

    return {
        'school_name': latest.get(CSV_SCHOOL_NAME, '').strip(),
        'school_district': latest.get(CSV_LEA_NAME, '').strip(),
        'state_code': 'GA',
        'county_name': latest.get(CSV_COUNTY, '').strip(),  # county FIPS code
        'nces_id': nces_id,
        'city': latest.get(CSV_CITY, '').strip(),
        'zip_code': latest.get(CSV_ZIP, '').strip(),
        'latitude': _safe_float(latest.get(CSV_LAT), allow_negative=True),
        'longitude': _safe_float(latest.get(CSV_LON), allow_negative=True),
        'phone': latest.get(CSV_PHONE, '').strip() or None,
        'school_type': school_type,
        'is_charter': is_charter,
        'is_magnet': is_magnet,
        'is_virtual': is_virtual,
        'is_title_i': is_title_i,
        'locale_code': latest.get(CSV_LOCALE, '').strip() or None,
        'total_students': latest_enrollment,
        'teachers_fte': latest_teachers,
        'student_teacher_ratio': _compute_student_teacher_ratio(latest_enrollment, latest_teachers),
        'free_lunch_percentage': avg_frpl,
        'reduced_lunch_percentage': reduced_lunch_pct,
        'direct_certification_pct': _avg(direct_cert_pcts),
        'district_poverty_pct': _avg(district_poverty_pcts),
        'district_population': district_pop,
        'district_exp_per_pupil': _avg(district_exp_pps),
        'district_rev_per_pupil': _avg(district_rev_pps),
        'district_exp_instruction_per_pupil': _avg(district_exp_inst_pps),
        'district_rev_federal_pct': _avg(district_rev_feds),
        'district_rev_state_pct': _avg(district_rev_states),
        'district_rev_local_pct': _avg(district_rev_locals),
        'enrollment_trend_json': json.dumps(enrollment_trend) if enrollment_trend else None,
        'frpl_trend_json': json.dumps(frpl_trend) if frpl_trend else None,
        'years_of_data': len(sorted_rows),
        'latest_school_year': latest.get(CSV_SCHOOL_YEAR, ''),
        'csv_import_date': datetime.now(timezone.utc),
        # defaults for existing columns
        'school_url': '',
        'opportunity_score': 0,
        'graduation_rate': 0,
        'college_acceptance_rate': 0,
        'ap_course_count': 0,
        'ap_exam_pass_rate': 0,
        'stem_program_available': False,
        'ib_program_available': False,
        'dual_enrollment_available': False,
        'analysis_status': 'csv_imported',
        'human_review_status': 'pending',
        'data_confidence_score': 0,
        'created_by': 'csv_import',
        'school_investment_level': 'unknown',
        'is_active': True,
    }


def read_and_group_csv(csv_path: str) -> Dict[str, List[Dict[str, str]]]:
    """Read the CSV file and group rows by NCES school ID.

    Returns:
        dict mapping ncessch → list of row dicts
    """
    groups: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nces_id = row.get(CSV_NCESSCH, '').strip()
            if not nces_id:
                continue
            groups[nces_id].append(row)
    return dict(groups)


def import_schools_from_csv(
    csv_path: str,
    db,
    purge_first: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Import GA high-school CSV into school_enriched_data.

    Args:
        csv_path: Path to the CSV file
        db: Database instance with create_school_enriched_data / delete_all_school_enriched_data
        purge_first: If True, delete all existing school_enriched_data before importing
        dry_run: If True, parse and aggregate but don't write to DB

    Returns:
        dict with import statistics
    """
    logger.info(f"📚 Starting CSV school import from {csv_path}")
    start = datetime.utcnow()

    # Step 1: Read & group
    groups = read_and_group_csv(csv_path)
    total_rows = sum(len(v) for v in groups.values())
    total_schools = len(groups)
    logger.info(f"  Read {total_rows} CSV rows → {total_schools} unique schools (by NCES ID)")

    # Step 2: Aggregate
    records = []
    for nces_id, rows in groups.items():
        try:
            rec = _aggregate_school(nces_id, rows)
            records.append(rec)
        except Exception as e:
            logger.error(f"  Error aggregating school {nces_id}: {e}")

    logger.info(f"  Aggregated {len(records)} school records")

    if dry_run:
        return {
            'status': 'dry_run',
            'csv_rows': total_rows,
            'unique_schools': total_schools,
            'aggregated': len(records),
            'sample': records[:3],
        }

    # Step 3: Purge if requested
    purged = 0
    if purge_first:
        purged = db.delete_all_school_enriched_data()
        logger.info(f"  🗑️  Purged {purged} existing school records")

    # Step 4: Insert
    created = 0
    errors = 0
    for rec in records:
        try:
            school_id = db.create_school_enriched_data(rec)
            if school_id:
                created += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            logger.error(f"  Error inserting {rec.get('school_name')}: {e}")

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(f"✅ CSV import complete: {created} created, {errors} errors, {elapsed:.1f}s")

    return {
        'status': 'success',
        'csv_rows': total_rows,
        'unique_schools': total_schools,
        'purged': purged,
        'created': created,
        'errors': errors,
        'elapsed_seconds': round(elapsed, 1),
    }


# ── Supplemental CSV import (merges academic data onto existing records) ────

# Flexible column name mapping: many possible header names → canonical DB field
_SUPPLEMENT_FIELD_MAP = {
    # AP courses
    'ap_course_count': 'ap_course_count',
    'ap_courses': 'ap_course_count',
    'ap_count': 'ap_course_count',
    'num_ap_courses': 'ap_course_count',
    'ap_classes': 'ap_course_count',
    'number_of_ap_courses': 'ap_course_count',
    # AP pass rate
    'ap_exam_pass_rate': 'ap_exam_pass_rate',
    'ap_pass_rate': 'ap_exam_pass_rate',
    'pct_ap_pass': 'ap_exam_pass_rate',
    # Honors
    'honors_course_count': 'honors_course_count',
    'honors_courses': 'honors_course_count',
    'num_honors': 'honors_course_count',
    # Graduation rate
    'graduation_rate': 'graduation_rate',
    'grad_rate': 'graduation_rate',
    'cohort_graduation_rate': 'graduation_rate',
    'four_year_grad_rate': 'graduation_rate',
    # College acceptance/placement
    'college_acceptance_rate': 'college_acceptance_rate',
    'college_readiness_rate': 'college_acceptance_rate',
    'college_placement_rate': 'college_acceptance_rate',
    'college_going_rate': 'college_acceptance_rate',
    # STEM / IB / Dual
    'stem_program_available': 'stem_program_available',
    'stem': 'stem_program_available',
    'has_stem': 'stem_program_available',
    'ib_program_available': 'ib_program_available',
    'ib': 'ib_program_available',
    'has_ib': 'ib_program_available',
    'dual_enrollment_available': 'dual_enrollment_available',
    'dual_enrollment': 'dual_enrollment_available',
    'has_dual_enrollment': 'dual_enrollment_available',
    # School URL
    'school_url': 'school_url',
    'website': 'school_url',
    'url': 'school_url',
    # ACT scores
    'act_composite_avg': 'act_composite_avg',
    'act_composite': 'act_composite_avg',
    'act_avg': 'act_composite_avg',
    'act_english_avg': 'act_english_avg',
    'act_english': 'act_english_avg',
    'act_math_avg': 'act_math_avg',
    'act_math': 'act_math_avg',
    'act_reading_avg': 'act_reading_avg',
    'act_reading': 'act_reading_avg',
    'act_science_avg': 'act_science_avg',
    'act_science': 'act_science_avg',
    'act_students_tested': 'act_students_tested',
    # SAT scores
    'sat_total_avg': 'sat_total_avg',
    'sat_total': 'sat_total_avg',
    'sat_ebrw_avg': 'sat_ebrw_avg',
    'sat_ebrw': 'sat_ebrw_avg',
    'sat_math_avg': 'sat_math_avg',
    'sat_math': 'sat_math_avg',
    'sat_students_tested': 'sat_students_tested',
    # College going
    'college_going_rate': 'college_going_rate',
    'college_going': 'college_going_rate',
    'college_going_2yr_rate': 'college_going_2yr_rate',
    'college_going_4yr_rate': 'college_going_4yr_rate',
    # HOPE
    'hope_eligible_pct': 'hope_eligible_pct',
    'hope_eligible': 'hope_eligible_pct',
    'hope_pct': 'hope_eligible_pct',
    # Dropout
    'dropout_rate': 'dropout_rate',
    # Milestones
    'milestones_ela_proficient_pct': 'milestones_ela_proficient_pct',
    'milestones_math_proficient_pct': 'milestones_math_proficient_pct',
    # AP extended
    'ap_students_tested': 'ap_students_tested',
    'ap_tests_administered': 'ap_tests_administered',
    'ap_tests_3plus': 'ap_tests_3plus',
    'ap_tests_3_or_higher': 'ap_tests_3plus',
    # EOC Milestones — map subject-specific to our two DB columns
    'eoc_algebra_proficient_pct': 'milestones_math_proficient_pct',
    'eoc_biology_proficient_pct': 'milestones_ela_proficient_pct',  # reuse as general proficiency
    'eoc_amlit_proficient_pct': 'milestones_ela_proficient_pct',
    # School expenditure
    'instruction_expenditure_per_fte': 'instruction_expenditure_per_fte',
    # Educator quality
    'inexperienced_teacher_pct': 'inexperienced_teacher_pct',
    # FESR / PPE
    'school_ppe': 'school_ppe',
    'fesr_star_rating': 'fesr_star_rating',
    'fesr_academic_score': 'fesr_academic_score',
    # Direct certification
    'direct_cert_pct': 'direct_certification_pct',
}

# Fields to match on — any of these can be the school identifier
_MATCH_COLUMNS = ['ncessch', 'nces_id', 'nces_school_id', 'school_id']


def import_supplemental_csv(
    csv_path: str,
    db,
    source_name: str = 'supplemental_csv',
    dry_run: bool = False,
    create_if_missing: bool = False,
    default_state: str = '',
) -> Dict[str, Any]:
    """Import supplemental academic data and merge onto existing schools by NCES ID.

    By default only UPDATES existing records. Set create_if_missing=True to
    also INSERT new school records for unmatched names (useful for GOSA data
    that has school names not present in the NCES CCD import).

    The CSV must have a column matching one of: ncessch, nces_id, nces_school_id.
    All other columns are matched flexibly against known field names.

    Args:
        csv_path: Path to supplemental CSV
        db: Database instance
        source_name: Provenance label (e.g., 'CRDC_2020-21', 'GA_DOE_Report_Card_2024')
        dry_run: Parse only, don't write

    Returns:
        dict with merge statistics
    """
    import csv as csv_mod

    logger.info(f"📚 Starting supplemental CSV import from {csv_path} (source={source_name})")
    start = datetime.utcnow()

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv_mod.DictReader(f)
        headers = [h.strip().lower().replace(' ', '_') for h in (reader.fieldnames or [])]

        # Find the NCES ID column
        nces_col = None
        for col in _MATCH_COLUMNS:
            if col in headers:
                nces_col = col
                break
        # Also check original (un-lowered) headers
        if not nces_col:
            for orig in (reader.fieldnames or []):
                if orig.strip().lower().replace(' ', '_') in _MATCH_COLUMNS:
                    nces_col = orig.strip()
                    break

        if not nces_col:
            # Fall back to school name matching
            name_col = None
            name_candidates = ['school_name', 'instn_name', 'institution_name', 'school']
            for col in name_candidates:
                if col in headers:
                    name_col = col
                    break
            if not name_col:
                for orig in (reader.fieldnames or []):
                    if orig.strip().lower().replace(' ', '_') in name_candidates:
                        name_col = orig.strip()
                        break
            if not name_col:
                return {
                    'status': 'error',
                    'error': f'No NCES ID or school name column found. '
                             f'Expected NCES: {_MATCH_COLUMNS} or name: {name_candidates}. '
                             f'Found: {headers[:20]}',
                }

        # Map CSV columns to DB fields
        col_mapping = {}
        for header in headers:
            canonical = _SUPPLEMENT_FIELD_MAP.get(header)
            if canonical:
                col_mapping[header] = canonical

        if not col_mapping:
            return {
                'status': 'error',
                'error': f'No recognized data columns found. Known fields: '
                         f'{sorted(set(_SUPPLEMENT_FIELD_MAP.values()))}. '
                         f'Your columns: {headers}',
            }

        match_mode = 'nces' if nces_col else 'name'
        logger.info(f"  Match mode: {match_mode}")

        # Pre-check which DB columns actually exist
        valid_db_cols = set()
        try:
            col_rows = db.execute_query(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'school_enriched_data'"
            )
            valid_db_cols = {r['column_name'] for r in (col_rows or [])}
        except Exception:
            valid_db_cols = set()

        # Filter col_mapping to only include columns that exist in DB
        if valid_db_cols:
            filtered_mapping = {}
            for csv_col, db_col in col_mapping.items():
                if db_col in valid_db_cols:
                    filtered_mapping[csv_col] = db_col
                else:
                    logger.warning(f"  Skipping column {db_col} — not found in school_enriched_data")
            col_mapping = filtered_mapping
        if nces_col:
            logger.info(f"  NCES ID column: {nces_col}")
        else:
            logger.info(f"  School name column: {name_col}")
        logger.info(f"  Mapped columns: {col_mapping}")

        # Reset reader to re-read with original headers
        f.seek(0)
        reader = csv_mod.DictReader(f)

        matched = 0
        updated = 0
        created = 0
        not_found = 0
        errors = 0
        total_rows = 0
        fields_updated_count = {}

        for row in reader:
            total_rows += 1

            # Find existing school
            existing = None
            if match_mode == 'nces':
                nces_id = (row.get(nces_col) or '').strip()
                if not nces_id:
                    continue
                try:
                    existing = db.execute_query(
                        "SELECT school_enrichment_id, data_source_notes FROM school_enriched_data WHERE nces_id = %s",
                        (nces_id,)
                    )
                except Exception:
                    existing = None
            else:
                school_name = (row.get(name_col) or '').strip()
                if not school_name:
                    continue
                # Try exact match first
                try:
                    existing = db.execute_query(
                        "SELECT school_enrichment_id, data_source_notes FROM school_enriched_data "
                        "WHERE LOWER(school_name) = LOWER(%s) AND state_code = 'GA'",
                        (school_name,)
                    )
                except Exception:
                    existing = None
                # Fuzzy fallback
                if not existing:
                    try:
                        fuzzy = db.get_school_enriched_data_fuzzy(school_name, state_code='GA', threshold=0.7)
                        if fuzzy:
                            existing = [{'school_enrichment_id': fuzzy['school_enrichment_id'],
                                         'data_source_notes': fuzzy.get('data_source_notes')}]
                    except Exception:
                        pass

            if not existing:
                if create_if_missing and match_mode == 'name':
                    # Create a new school record from this CSV row
                    school_name_val = (row.get(name_col) or '').strip()
                    if not school_name_val:
                        not_found += 1
                        continue
                    try:
                        new_data = {
                            'school_name': school_name_val,
                            'state_code': default_state or 'GA',
                            'analysis_status': 'csv_imported',
                            'human_review_status': 'pending',
                            'created_by': 'csv_import',
                        }
                        new_id = db.create_school_enriched_data(new_data)
                        if new_id:
                            existing = [{'school_enrichment_id': new_id, 'data_source_notes': '{}'}]
                            created += 1
                        else:
                            not_found += 1
                            continue
                    except Exception as ce:
                        logger.warning(f"Could not create school '{school_name_val}': {ce}")
                        not_found += 1
                        continue
                else:
                    not_found += 1
                    continue

            matched += 1
            sid = existing[0]['school_enrichment_id']

            # Build update
            updates = {}
            provenance_updates = {}
            for csv_col, db_col in col_mapping.items():
                raw_val = (row.get(csv_col) or '').strip()
                if not raw_val or raw_val.lower() in ('', 'na', 'n/a', '-', '.', '–'):
                    continue

                # Parse value
                if db_col in ('stem_program_available', 'ib_program_available', 'dual_enrollment_available'):
                    val = raw_val.lower() in ('true', 'yes', '1', 'y')
                else:
                    val = _safe_float(raw_val)
                    if val is None:
                        continue
                    if db_col in ('ap_course_count', 'honors_course_count'):
                        val = int(val)

                updates[db_col] = val
                provenance_updates[db_col] = source_name
                fields_updated_count[db_col] = fields_updated_count.get(db_col, 0) + 1

            if not updates or dry_run:
                continue

            # Merge provenance
            existing_notes = existing[0].get('data_source_notes') or '{}'
            try:
                provenance = json.loads(existing_notes) if isinstance(existing_notes, str) and existing_notes.startswith('{') else {}
            except (json.JSONDecodeError, TypeError):
                provenance = {}
            if not isinstance(provenance, dict):
                provenance = {'_legacy_notes': str(provenance)} if provenance else {}
            provenance.update(provenance_updates)

            # Build UPDATE
            set_parts = []
            values = []
            for col, val in updates.items():
                set_parts.append(f"{col} = %s")
                values.append(val)
            set_parts.append("data_source_notes = %s")
            values.append(json.dumps(provenance))
            set_parts.append("updated_at = CURRENT_TIMESTAMP")
            values.append(sid)

            try:
                db.execute_non_query(
                    f"UPDATE school_enriched_data SET {', '.join(set_parts)} WHERE school_enrichment_id = %s",
                    tuple(values)
                )
                updated += 1
            except Exception as e:
                errors += 1
                logger.error(f"  Error updating {nces_id}: {e}")

    elapsed = (datetime.utcnow() - start).total_seconds()
    logger.info(f"✅ Supplemental import complete: {matched} matched, {created} created, "
                f"{updated} updated, {not_found} not found, {errors} errors, {elapsed:.1f}s")

    return {
        'status': 'success',
        'source': source_name,
        'csv_rows': total_rows,
        'matched': matched,
        'created': created,
        'updated': updated,
        'not_found': not_found,
        'errors': errors,
        'fields_updated': fields_updated_count,
        'column_mapping': col_mapping,
        'elapsed_seconds': round(elapsed, 1),
    }


# ── CLI entry point ────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python -m src.csv_school_importer <csv_path> [--dry-run]")
        sys.exit(1)

    csv_path = sys.argv[1]
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        # Dry run doesn't need DB
        groups = read_and_group_csv(csv_path)
        records = [_aggregate_school(nid, rows) for nid, rows in groups.items()]
        print(f"\nDry run: {len(records)} schools would be imported")
        print(f"\nSample record:")
        print(json.dumps(records[0], indent=2, default=str))
    else:
        from src.database import db
        result = import_schools_from_csv(csv_path, db)
        print(json.dumps(result, indent=2, default=str))
