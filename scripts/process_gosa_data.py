#!/usr/bin/env python3
"""Process GOSA downloadable data files into a single merged CSV for import.

Reads AP, ACT, Graduation Rate, HOPE Eligibility, and Dropout Rate CSVs
from the Georgia Governor's Office of Student Achievement (GOSA) and
produces a consolidated per-school CSV with the latest year's data.

The output CSV matches schools by name (since GOSA uses state-specific
institution codes, not NCES IDs). The supplemental importer will
fuzzy-match these to existing school_enriched_data records.

Usage:
    python scripts/process_gosa_data.py --input-dir ~/Downloads --output data/gosa_merged.csv
"""

import argparse
import csv
import glob
import json
import logging
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> Optional[float]:
    """Parse a numeric value, treating TFS/blanks as None."""
    if val is None:
        return None
    s = str(val).strip().strip('"')
    if not s or s.upper() in ('TFS', 'NA', 'N/A', '-', '.', '–', '*'):
        return None
    try:
        return float(s.replace(',', ''))
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> Optional[int]:
    f = _safe_float(val)
    return int(f) if f is not None else None


def _normalize_name(name: str) -> str:
    """Normalize school name for matching."""
    return re.sub(r'\s+', ' ', name.strip().lower())


def _read_csv(path: str) -> List[Dict[str, str]]:
    """Read a CSV, handling comment-style headers (#RPT_NAME,...)."""
    with open(path, 'r', encoding='utf-8-sig') as f:
        first_line = f.readline()
        f.seek(0)
        # Some GOSA files have #RPT_NAME as first header — strip the #
        if first_line.startswith('#'):
            content = f.read()
            content = content[1:]  # Remove leading #
            import io
            reader = csv.DictReader(io.StringIO(content))
        else:
            reader = csv.DictReader(f)
        return list(reader)


# ── AP Processing ────────────────────────────────────────────────────

def process_ap_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process AP score files. Returns {school_name: {year: data}}."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading AP: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            # Get school-level ALL Subjects row
            subject = (row.get('TEST_CMPNT_TYP_NM') or '').strip()
            if subject != 'ALL Subjects':
                continue
            instn = (row.get('INSTN_NUMBER') or row.get('INSTN_NUMBER') or '').strip()
            if instn in ('SCHOOL_ALL', 'ALL', ''):
                continue
            # Skip district-level aggregates
            detail = (row.get('DETAIL_LVL_DESC') or '').strip().upper()
            if detail in ('DISTRICT', 'DISTRICT ALL SUBJECTS', 'STATE'):
                continue

            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            if not name or not year or name == 'SCHOOL_ALL':
                continue

            tested = _safe_int(row.get('NUMBER_OF_STUDENTS_TESTED'))
            taken = _safe_int(row.get('NUMBER_TESTS_TAKEN'))
            three_plus = _safe_int(row.get('NOTESTS_3ORHIGHER') or row.get('NUMBER_TESTS_3_OR_HIGHER'))

            schools[_normalize_name(name)][year] = {
                'name': name,
                'ap_students_tested': tested,
                'ap_tests_administered': taken,
                'ap_tests_3plus': three_plus,
            }

    # Count distinct AP subjects per school (from the latest year with data)
    # Re-read to count subjects
    subject_counts = defaultdict(lambda: defaultdict(set))
    for path in sorted(file_paths):
        rows = _read_csv(path)
        for row in rows:
            subject = (row.get('TEST_CMPNT_TYP_NM') or '').strip()
            if subject == 'ALL Subjects':
                continue
            instn = (row.get('INSTN_NUMBER') or '').strip()
            if instn in ('SCHOOL_ALL', 'ALL', ''):
                continue
            detail = (row.get('DETAIL_LVL_DESC') or '').strip().upper()
            if detail in ('DISTRICT', 'DISTRICT ALL SUBJECTS', 'STATE'):
                continue
            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            if name and year and name != 'SCHOOL_ALL':
                subject_counts[_normalize_name(name)][year].add(subject)

    # Add subject count to schools dict
    for norm_name, year_data in subject_counts.items():
        if norm_name in schools:
            for year, subjects in year_data.items():
                if year in schools[norm_name]:
                    schools[norm_name][year]['ap_course_count'] = len(subjects)

    return schools


# ── ACT Processing ───────────────────────────────────────────────────

def process_act_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process ACT highest score files."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading ACT: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            subgroup = (row.get('SUBGRP_DESC') or '').strip()
            if subgroup != 'All Students':
                continue
            component = (row.get('TEST_CMPNT_TYP_CD') or '').strip()
            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            if not name or not year:
                continue

            score = _safe_float(row.get('INSTN_AVG_SCORE_VAL'))
            tested = _safe_int(row.get('INSTN_NUM_TESTED_CNT'))

            if score is None:
                continue

            norm = _normalize_name(name)
            if component == 'Composite':
                schools[norm][year]['name'] = name
                schools[norm][year]['act_composite_avg'] = score
                schools[norm][year]['act_students_tested'] = tested
            elif component == 'English':
                schools[norm][year]['act_english_avg'] = score
            elif component == 'Mathematics':
                schools[norm][year]['act_math_avg'] = score
            elif component == 'Reading':
                schools[norm][year]['act_reading_avg'] = score
            elif component == 'Science':
                schools[norm][year]['act_science_avg'] = score

    return schools


# ── Graduation Rate Processing ───────────────────────────────────────

def process_graduation_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process graduation rate files. School-level, ALL Students only."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading Graduation: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            label = (row.get('LABEL_LVL_1_DESC') or '').strip()
            if label != 'Grad Rate -ALL Students':
                continue
            detail = (row.get('DETAIL_LVL_DESC') or '').strip()
            instn_num = (row.get('INSTN_NUMBER') or '').strip()
            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()

            # Prefer school-level; fall back to district if school not available
            if detail == 'School':
                pass  # Use it
            elif detail == 'District' and instn_num == 'ALL':
                # Only use district aggregate if it's a single-school district
                # We'll handle this by preferring school-level when available
                continue
            else:
                continue

            rate = _safe_float(row.get('PROGRAM_PERCENT'))
            if rate is None or not name or not year:
                continue

            norm = _normalize_name(name)
            schools[norm][year] = {
                'name': name,
                'graduation_rate': rate,
            }

    return schools


# ── HOPE Eligibility Processing ──────────────────────────────────────

def process_hope_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process HOPE eligibility files."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading HOPE: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            instn_num = (row.get('INSTN_NUMBER') or '').strip()
            if instn_num == 'ALL':
                continue  # Skip district aggregates
            detail = (row.get('DETAIL_LVL_DESC') or '').strip().upper()
            if detail in ('DISTRICT', 'STATE'):
                continue

            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            pct = _safe_float(row.get('HOPE_ELIGIBLE_PCT'))

            if not name or not year:
                continue

            schools[_normalize_name(name)][year] = {
                'name': name,
                'hope_eligible_pct': pct,
            }

    return schools


# ── Dropout Rate Processing ──────────────────────────────────────────

def process_dropout_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process 9-12 dropout rate files. School-level, ALL Students only."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading Dropout: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            label = (row.get('LABEL_LVL_1_DESC') or '').strip()
            if label != '9-12 Drop Outs -ALL Students':
                continue
            detail = (row.get('DETAIL_LVL_DESC') or '').strip()
            if detail not in ('School',):
                continue

            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            rate = _safe_float(row.get('PROGRAM_PERCENT'))

            if not name or not year:
                continue

            schools[_normalize_name(name)][year] = {
                'name': name,
                'dropout_rate': rate,
            }

    return schools


# ── GA Milestones EOC Processing ─────────────────────────────────────

def process_eoc_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process Georgia Milestones End-of-Course assessment files.
    School-level, ALL Students, ALL GRADES, compute proficient+distinguished %."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading EOC: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            subgroup = (row.get('SUBGROUP_NAME') or '').strip()
            if subgroup != 'All Students':
                continue
            instn = (row.get('INSTN_NUMBER') or '').strip()
            if instn in ('ALL', ''):
                continue
            detail = (row.get('DETAIL_LVL_DESC') or '').strip().upper()
            if detail in ('DISTRICT', 'STATE', 'DISTRICT ALL SUBJECTS'):
                continue

            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            subject = (row.get('TEST_CMPNT_TYP_NM') or '').strip()
            if not name or not year or name in ('ALL', 'SCHOOL_ALL'):
                continue

            prof_pct = _safe_float(row.get('PROFICIENT_PCT') or row.get('Level3_PERCENT') or row.get('ADEQUATE_PERCENT'))
            dist_pct = _safe_float(row.get('DISTINGUISHED_PCT') or row.get('Level4_PERCENT') or row.get('THOROUGH_PERCENT'))

            if prof_pct is None and dist_pct is None:
                continue

            combined = (prof_pct or 0) + (dist_pct or 0)
            norm = _normalize_name(name)
            schools[norm][year]['name'] = name

            subj_lower = subject.lower()
            if 'algebra' in subj_lower:
                schools[norm][year]['eoc_algebra_proficient_pct'] = combined
            elif 'biology' in subj_lower:
                schools[norm][year]['eoc_biology_proficient_pct'] = combined
            elif 'american literature' in subj_lower or 'am lit' in subj_lower:
                schools[norm][year]['eoc_amlit_proficient_pct'] = combined
            elif 'us history' in subj_lower or 'u.s. history' in subj_lower:
                schools[norm][year]['eoc_ushistory_proficient_pct'] = combined

    return schools


# ── Revenues & Expenditures Processing ───────────────────────────────

def process_expenditure_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process Revenues & Expenditures files. Extract per-school instruction $ per FTE."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading Expenditure: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            rev_exp = (row.get('Revenues/Expenditures') or row.get('REVENUES/EXPENDITURES') or '').strip()
            if rev_exp != 'K-12 Expenditures':
                continue
            desc = (row.get('Description') or row.get('DESCRIPTION') or '').strip()
            if desc != 'Instruction':
                continue

            school_code = (row.get('SCHOOL_CODE') or row.get('INSTN_NUMBER') or '').strip()
            if school_code in ('ALL', '8010', ''):  # Skip district aggregates and central office
                continue
            detail = (row.get('DETAIL_LVL_DESC') or '').strip().upper()
            if detail in ('DISTRICT', 'STATE'):
                continue

            name = (row.get('SCHOOL_NAME') or row.get('INSTN_NAME') or '').strip()
            year = (row.get('SCHOOL_YEAR') or row.get('LONG_SCHOOL_YEAR') or '').strip()
            dollars_per_fte = _safe_float(row.get('Dollars per FTE') or row.get('DOLLARS_PER_FTE'))

            if not name or not year or name in ('All Column Values',):
                continue
            if dollars_per_fte is None or dollars_per_fte <= 0:
                continue
            # Filter out obviously wrong values (some central office rows have per-FTE in millions)
            if dollars_per_fte > 50000:
                continue

            norm = _normalize_name(name)
            schools[norm][year] = {
                'name': name,
                'instruction_expenditure_per_fte': round(dollars_per_fte, 0),
            }

    return schools


# ── Educator Inexperience Processing ─────────────────────────────────

def process_educator_files(file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """Process Educator Inexperience files. Extract % inexperienced teachers per school."""
    schools = defaultdict(lambda: defaultdict(dict))

    for path in sorted(file_paths):
        logger.info(f"  Reading Educator: {os.path.basename(path)}")
        rows = _read_csv(path)
        for row in rows:
            role = (row.get('LABEL_LVL_3_DESC') or '').strip()
            if role != 'Teachers':
                continue
            scope = (row.get('LABEL_LVL_2_DESC') or '').strip()
            if scope != 'Total':
                continue

            name = (row.get('INSTN_NAME') or '').strip()
            year = (row.get('LONG_SCHOOL_YEAR') or '').strip()
            if not name or not year:
                continue
            # Skip district aggregates
            if '- All Schools' in name or 'All Column Values' in name:
                continue

            pct = _safe_float(row.get('INEXPERIENCED_FTE_PCT') or row.get('CATEGORY_FTE_PCT'))
            if pct is None:
                continue

            norm = _normalize_name(name)
            schools[norm][year] = {
                'name': name,
                'inexperienced_teacher_pct': pct,
            }

    return schools


# ── Merge & Output ───────────────────────────────────────────────────

def get_latest(year_dict: Dict[str, Dict], field: str) -> Tuple[Optional[Any], Optional[str]]:
    """Get the latest non-None value for a field across years."""
    for year in sorted(year_dict.keys(), reverse=True):
        val = year_dict[year].get(field)
        if val is not None:
            return val, year
    return None, None


def merge_all(ap, act, grad, hope, dropout, eoc, expenditure, educator) -> List[Dict[str, Any]]:
    """Merge all datasets into a single per-school record."""
    # Collect all normalized school names
    all_names = set()
    for d in [ap, act, grad, hope, dropout, eoc, expenditure, educator]:
        all_names.update(d.keys())

    merged = []
    for norm_name in sorted(all_names):
        # Get the best display name
        display_name = None
        for d in [ap, act, grad, hope, dropout, eoc, expenditure, educator]:
            if norm_name in d:
                for year_data in d[norm_name].values():
                    if year_data.get('name'):
                        display_name = year_data['name']
                        break
            if display_name:
                break
        if not display_name:
            continue

        record = {'school_name': display_name}

        # AP data
        if norm_name in ap:
            record['ap_students_tested'], _ = get_latest(ap[norm_name], 'ap_students_tested')
            record['ap_tests_administered'], _ = get_latest(ap[norm_name], 'ap_tests_administered')
            record['ap_tests_3plus'], _ = get_latest(ap[norm_name], 'ap_tests_3plus')
            record['ap_course_count'], _ = get_latest(ap[norm_name], 'ap_course_count')
            # Compute pass rate
            tests = record.get('ap_tests_administered')
            pass3 = record.get('ap_tests_3plus')
            if tests and pass3 and tests > 0:
                record['ap_exam_pass_rate'] = round(pass3 / tests * 100, 1)

        # ACT data
        if norm_name in act:
            record['act_composite_avg'], _ = get_latest(act[norm_name], 'act_composite_avg')
            record['act_english_avg'], _ = get_latest(act[norm_name], 'act_english_avg')
            record['act_math_avg'], _ = get_latest(act[norm_name], 'act_math_avg')
            record['act_reading_avg'], _ = get_latest(act[norm_name], 'act_reading_avg')
            record['act_science_avg'], _ = get_latest(act[norm_name], 'act_science_avg')
            record['act_students_tested'], _ = get_latest(act[norm_name], 'act_students_tested')

        # Graduation rate
        if norm_name in grad:
            record['graduation_rate'], _ = get_latest(grad[norm_name], 'graduation_rate')

        # HOPE
        if norm_name in hope:
            record['hope_eligible_pct'], _ = get_latest(hope[norm_name], 'hope_eligible_pct')

        # Dropout
        if norm_name in dropout:
            record['dropout_rate'], _ = get_latest(dropout[norm_name], 'dropout_rate')

        # EOC Milestones
        if norm_name in eoc:
            record['eoc_algebra_proficient_pct'], _ = get_latest(eoc[norm_name], 'eoc_algebra_proficient_pct')
            record['eoc_biology_proficient_pct'], _ = get_latest(eoc[norm_name], 'eoc_biology_proficient_pct')
            record['eoc_amlit_proficient_pct'], _ = get_latest(eoc[norm_name], 'eoc_amlit_proficient_pct')
            record['eoc_ushistory_proficient_pct'], _ = get_latest(eoc[norm_name], 'eoc_ushistory_proficient_pct')

        # School-level expenditure
        if norm_name in expenditure:
            record['instruction_expenditure_per_fte'], _ = get_latest(expenditure[norm_name], 'instruction_expenditure_per_fte')

        # Educator inexperience
        if norm_name in educator:
            record['inexperienced_teacher_pct'], _ = get_latest(educator[norm_name], 'inexperienced_teacher_pct')

        # Only include if we have at least some data
        has_data = any(v is not None for k, v in record.items() if k != 'school_name')
        if has_data:
            merged.append(record)

    return merged


def main():
    parser = argparse.ArgumentParser(description='Process GOSA data files into merged CSV')
    parser.add_argument('--input-dir', default=os.path.expanduser('~/Downloads'),
                        help='Directory containing downloaded GOSA CSVs')
    parser.add_argument('--output', default='data/gosa_merged.csv',
                        help='Output CSV path')
    args = parser.parse_args()

    input_dir = args.input_dir
    logger.info(f"Scanning GOSA files in: {input_dir}")

    # Find files by pattern
    ap_files = sorted(glob.glob(os.path.join(input_dir, 'AP_*')))
    act_files = sorted(glob.glob(os.path.join(input_dir, 'ACT_*')))
    grad_files = sorted(glob.glob(os.path.join(input_dir, 'Graduation*')) +
                        glob.glob(os.path.join(input_dir, 'GRADUATION*')))
    hope_files = sorted(glob.glob(os.path.join(input_dir, 'HOPE*')) +
                        glob.glob(os.path.join(input_dir, 'Hope*')))
    dropout_files = sorted(glob.glob(os.path.join(input_dir, '9-12*')) +
                           glob.glob(os.path.join(input_dir, '9_12*')))
    eoc_files = sorted(glob.glob(os.path.join(input_dir, 'EOC_*')))
    expenditure_files = sorted(glob.glob(os.path.join(input_dir, 'Revenues*')) +
                               glob.glob(os.path.join(input_dir, 'REVENUES*')))
    educator_files = sorted(glob.glob(os.path.join(input_dir, 'Educator*')) +
                            glob.glob(os.path.join(input_dir, 'EDUCATOR*')))

    logger.info(f"Found: {len(ap_files)} AP, {len(act_files)} ACT, {len(grad_files)} Graduation, "
                f"{len(hope_files)} HOPE, {len(dropout_files)} Dropout, {len(eoc_files)} EOC, "
                f"{len(expenditure_files)} Expenditure, {len(educator_files)} Educator files")

    if not any([ap_files, act_files, grad_files, hope_files, dropout_files]):
        logger.error("No GOSA files found! Check --input-dir")
        return

    logger.info("\n📊 Processing AP scores...")
    ap_data = process_ap_files(ap_files)
    logger.info(f"  {len(ap_data)} schools with AP data")

    logger.info("\n📊 Processing ACT scores...")
    act_data = process_act_files(act_files)
    logger.info(f"  {len(act_data)} schools with ACT data")

    logger.info("\n📊 Processing Graduation rates...")
    grad_data = process_graduation_files(grad_files)
    logger.info(f"  {len(grad_data)} schools with graduation data")

    logger.info("\n📊 Processing HOPE eligibility...")
    hope_data = process_hope_files(hope_files)
    logger.info(f"  {len(hope_data)} schools with HOPE data")

    logger.info("\n📊 Processing Dropout rates...")
    dropout_data = process_dropout_files(dropout_files)
    logger.info(f"  {len(dropout_data)} schools with dropout data")

    logger.info("\n� Processing GA Milestones EOC...")
    eoc_data = process_eoc_files(eoc_files)
    logger.info(f"  {len(eoc_data)} schools with EOC data")

    logger.info("\n📊 Processing Revenues & Expenditures...")
    expenditure_data = process_expenditure_files(expenditure_files)
    logger.info(f"  {len(expenditure_data)} schools with expenditure data")

    logger.info("\n📊 Processing Educator Inexperience...")
    educator_data = process_educator_files(educator_files)
    logger.info(f"  {len(educator_data)} schools with educator data")

    logger.info("\n🔗 Merging all datasets...")
    merged = merge_all(ap_data, act_data, grad_data, hope_data, dropout_data,
                       eoc_data, expenditure_data, educator_data)
    logger.info(f"  {len(merged)} total schools in merged dataset")

    # Write output
    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    fieldnames = [
        'school_name',
        'ap_course_count', 'ap_students_tested', 'ap_tests_administered',
        'ap_tests_3plus', 'ap_exam_pass_rate',
        'act_composite_avg', 'act_english_avg', 'act_math_avg',
        'act_reading_avg', 'act_science_avg', 'act_students_tested',
        'graduation_rate', 'hope_eligible_pct', 'dropout_rate',
        'eoc_algebra_proficient_pct', 'eoc_biology_proficient_pct',
        'eoc_amlit_proficient_pct', 'eoc_ushistory_proficient_pct',
        'instruction_expenditure_per_fte', 'inexperienced_teacher_pct',
    ]
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in merged:
            clean = {}
            for k, v in row.items():
                if v is None:
                    clean[k] = ''
                elif isinstance(v, float):
                    clean[k] = str(round(v, 2))
                else:
                    clean[k] = str(v)
            writer.writerow(clean)

    logger.info(f"\n✅ Output written to: {args.output}")
    logger.info(f"   {len(merged)} schools, {len(fieldnames)} columns")

    # Summary stats
    has_ap = sum(1 for r in merged if r.get('ap_course_count'))
    has_act = sum(1 for r in merged if r.get('act_composite_avg'))
    has_grad = sum(1 for r in merged if r.get('graduation_rate'))
    has_hope = sum(1 for r in merged if r.get('hope_eligible_pct'))
    has_dropout = sum(1 for r in merged if r.get('dropout_rate'))
    has_eoc = sum(1 for r in merged if r.get('eoc_algebra_proficient_pct'))
    has_expend = sum(1 for r in merged if r.get('instruction_expenditure_per_fte'))
    has_educator = sum(1 for r in merged if r.get('inexperienced_teacher_pct'))
    logger.info(f"   AP: {has_ap} | ACT: {has_act} | Grad: {has_grad} | HOPE: {has_hope} | "
                f"Dropout: {has_dropout} | EOC: {has_eoc} | Expenditure: {has_expend} | "
                f"Educator: {has_educator}")


if __name__ == '__main__':
    main()
