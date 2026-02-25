"""Import historical scores from Excel spreadsheet into the database.

Usage:
    python scripts/import_historical_scores.py <path_to_xlsx> [--cohort-year 2024] [--clear-first]

The spreadsheet is expected to have these columns (A-Q):
    A: Applicant
    B: Status
    C: Preliminary Score
    D: Quick Notes
    E: Reviewer Name
    F: Did you score? (Y/N)
    G: Academic record (0-3)
    H: Interest/Enthusiasm for STEM career (0-3)
    I: Personal Essay / Video (0-3)
    J: Letters of recommendation (0-2)
    K: Bonus (0-1)
    L: Total rating
    M: Eligibility Notes
    N: Previous research experience
    O: Advanced (coursework)
    P: Overall rating (yes, no, maybe for advancing candidate)
    Q: (additional column, captured as-is)
"""

import argparse
import os
import sys

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import openpyxl
except ImportError:
    print("openpyxl is required: pip install openpyxl")
    sys.exit(1)


def parse_numeric(value, max_val=None):
    """Parse a numeric cell value, returning float or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        if max_val and result > max_val:
            return None
        return result
    try:
        cleaned = str(value).strip()
        if not cleaned or cleaned.lower() in ('n/a', 'na', '-', ''):
            return None
        result = float(cleaned)
        if max_val and result > max_val:
            return None
        return result
    except (ValueError, TypeError):
        return None


def parse_boolean(value):
    """Parse Y/N/True/False to boolean."""
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ('y', 'yes', 'true', '1')


def _normalize_name(name: str) -> str:
    """Lowercase, strip whitespace/punctuation for dedup matching."""
    import re
    return re.sub(r'[^a-z0-9 ]', '', name.lower()).strip()


def _score_richness(record: dict) -> tuple:
    """Return a sort key so the richest record wins during dedup.
    Priority: was_scored=True > has total_rating > has more non-null rubric fields.
    """
    scored = 1 if record.get('was_scored') else 0
    total = record.get('total_rating') or 0
    filled = sum(1 for k in ('academic_record', 'stem_interest', 'essay_video',
                              'recommendation', 'bonus', 'total_rating',
                              'overall_rating', 'preliminary_score')
                  if record.get(k) is not None)
    return (scored, filled, total)


def parse_xlsx(filepath, cohort_year=2024):
    """Parse Excel file and return list of score dictionaries."""
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(min_row=1, values_only=True))
    if not rows:
        print("No rows found in spreadsheet")
        return []

    # Try to detect header row (look for "Applicant" in first few rows)
    header_row_idx = 0
    for i, row in enumerate(rows[:5]):
        for cell in row:
            if cell and 'applicant' in str(cell).lower():
                header_row_idx = i
                break

    headers = rows[header_row_idx]
    print(f"Header row {header_row_idx + 1}: {[str(h)[:30] if h else '' for h in headers[:17]]}")

    scores = []
    source_filename = os.path.basename(filepath)

    for row_num, row in enumerate(rows[header_row_idx + 1:], start=header_row_idx + 2):
        # Skip completely empty rows
        if not row or all(cell is None or str(cell).strip() == '' for cell in row[:6]):
            continue

        # Column mapping (0-indexed):
        # A=0: Applicant, B=1: Status, C=2: Preliminary Score, D=3: Quick Notes
        # E=4: Reviewer Name, F=5: Did you score?, G=6: Academic record
        # H=7: STEM Interest, I=8: Essay/Video, J=9: Recommendation
        # K=10: Bonus, L=11: Total rating, M=12: Eligibility Notes
        # N=13: Previous research exp, O=14: Advanced, P=15: Overall rating
        # Q=16: column Q
        def cell(idx):
            if idx < len(row):
                return row[idx]
            return None

        applicant_name = str(cell(0) or '').strip()
        if not applicant_name:
            continue

        score_data = {
            'cohort_year': cohort_year,
            'applicant_name': applicant_name,
            'status': str(cell(1) or '').strip() or None,
            'preliminary_score': str(cell(2) or '').strip() or None,
            'quick_notes': str(cell(3) or '').strip() or None,
            'reviewer_name': str(cell(4) or '').strip() or None,
            'was_scored': parse_boolean(cell(5)),
            'academic_record': parse_numeric(cell(6), max_val=3),
            'stem_interest': parse_numeric(cell(7), max_val=3),
            'essay_video': parse_numeric(cell(8), max_val=3),
            'recommendation': parse_numeric(cell(9), max_val=2),
            'bonus': parse_numeric(cell(10), max_val=1),
            'total_rating': parse_numeric(cell(11), max_val=12),
            'eligibility_notes': str(cell(12) or '').strip() or None,
            'previous_research_experience': str(cell(13) or '').strip() or None,
            'advanced_coursework': str(cell(14) or '').strip() or None,
            'overall_rating': str(cell(15) or '').strip() or None,
            'column_q': str(cell(16) or '').strip() if len(row) > 16 and cell(16) else None,
            'import_source': source_filename,
            'row_number': row_num,
        }

        # Clean up "None" strings
        for key in score_data:
            if score_data[key] == 'None':
                score_data[key] = None

        scores.append(score_data)

    wb.close()

    # Deduplicate: keep one record per student name (the richest row wins)
    seen: dict = {}  # normalized_name -> best record
    for record in scores:
        key = _normalize_name(record.get('applicant_name', ''))
        if not key:
            continue
        if key not in seen or _score_richness(record) > _score_richness(seen[key]):
            seen[key] = record

    deduped = list(seen.values())
    if len(deduped) < len(scores):
        print(f"  Deduplication: {len(scores)} rows → {len(deduped)} unique students "
              f"({len(scores) - len(deduped)} duplicate rows merged)")

    return deduped


def import_scores(filepath, cohort_year=2024, clear_first=False):
    """Parse and import scores into the database."""
    from src.database import db

    scores = parse_xlsx(filepath, cohort_year)
    if not scores:
        print("No scores to import")
        return

    print(f"\nParsed {len(scores)} applicant rows from {os.path.basename(filepath)}")

    # Show sample
    sample = scores[0]
    print(f"  Sample: {sample['applicant_name']} | Status: {sample['status']} | "
          f"Academic: {sample['academic_record']} | STEM: {sample['stem_interest']} | "
          f"Essay: {sample['essay_video']} | Rec: {sample['recommendation']} | "
          f"Total: {sample['total_rating']}")

    scored_count = sum(1 for s in scores if s.get('was_scored'))
    eligible_count = sum(1 for s in scores if s.get('status') and s['status'].lower() == 'accepted')
    print(f"  Scored: {scored_count}/{len(scores)} | Eligible (met requirements): {eligible_count}/{len(scores)}")
    print(f"  Note: 'Eligible' = had correct files, age, submitted on time. NOT who was selected.")

    if clear_first:
        deleted = db.clear_historical_scores(cohort_year)
        print(f"  Cleared {deleted} existing records for cohort {cohort_year}")

    result = db.bulk_insert_historical_scores(scores)
    print(f"\n✅ Import complete: {result['inserted']} inserted, {result['errors']} errors")

    # Show stats
    stats = db.get_historical_stats(cohort_year)
    if stats:
        print(f"\nCohort {cohort_year} stats:")
        print(f"  Total applicants: {stats.get('total_applicants', 0)}")
        print(f"  Eligible (met requirements): {stats.get('eligible', 0)}")
        print(f"  Selected for program: {stats.get('selected', 0)}")
        print(f"  Scored: {stats.get('scored_count', 0)}")
        if stats.get('avg_total_rating'):
            print(f"  Avg total rating (scored): {stats['avg_total_rating']:.1f}")
        if stats.get('avg_selected_total'):
            print(f"  Avg selected total: {stats['avg_selected_total']:.1f}")
        if stats.get('avg_not_selected_total'):
            print(f"  Avg not-selected total: {stats['avg_not_selected_total']:.1f}")

    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Import historical scores from Excel')
    parser.add_argument('filepath', help='Path to .xlsx file')
    parser.add_argument('--cohort-year', type=int, default=2024, help='Cohort year (default: 2024)')
    parser.add_argument('--clear-first', action='store_true', help='Clear existing data for this cohort year before importing')
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"File not found: {args.filepath}")
        sys.exit(1)

    import_scores(args.filepath, args.cohort_year, args.clear_first)
