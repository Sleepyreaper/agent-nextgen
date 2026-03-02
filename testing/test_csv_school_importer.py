"""Tests for src/csv_school_importer.py — offline aggregation logic.

These tests exercise the CSV parsing and dedup logic *without* a database.
They use a small in-memory CSV to validate the aggregation rules.
"""

import csv
import io
import json
import os
import tempfile
import unittest

# Adjust path so we can import from src/
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.csv_school_importer import (
    _safe_float,
    _safe_int,
    _safe_bool,
    _avg,
    _aggregate_school,
    _compute_student_teacher_ratio,
    read_and_group_csv,
)


# ── Helpers ────────────────────────────────────────────────────────────────

HEADER = (
    "school_year,ncessch,school_name,lea_name,leaid,street_location,"
    "city_location,state_location,zip_location,phone,latitude,longitude,"
    "county_code,lowest_grade_offered,highest_grade_offered,charter,magnet,"
    "virtual,school_type,school_status,urban_centric_locale,title_i_eligible,"
    "title_i_schoolwide,teachers_fte,enrollment,free_lunch,reduced_price_lunch,"
    "free_or_reduced_price_lunch,frpl_pct,direct_certification,lunch_program,"
    "district_est_population,district_pop_5_17,district_pop_5_17_poverty,"
    "district_poverty_pct,district_rev_total,district_exp_total,"
    "district_exp_per_pupil,district_rev_per_pupil,"
    "district_exp_instruction_per_pupil,district_rev_federal_pct,"
    "district_rev_state_pct,district_rev_local_pct"
)


def _make_row(**overrides):
    """Return a dict with sensible defaults for one CSV row."""
    defaults = {
        'school_year': '2022-23',
        'ncessch': '999999999999',
        'school_name': 'Test High School',
        'lea_name': 'Test District',
        'leaid': '9999999',
        'street_location': '123 Main St',
        'city_location': 'Atlanta',
        'state_location': 'GA',
        'zip_location': '30301',
        'phone': '4045551234',
        'latitude': '33.749',
        'longitude': '-84.388',
        'county_code': '13121',
        'lowest_grade_offered': '9',
        'highest_grade_offered': '12',
        'charter': '0',
        'magnet': '0',
        'virtual': '0',
        'school_type': '1',
        'school_status': '1',
        'urban_centric_locale': '11',
        'title_i_eligible': '0',
        'title_i_schoolwide': '0',
        'teachers_fte': '50',
        'enrollment': '1000',
        'free_lunch': '400',
        'reduced_price_lunch': '50',
        'free_or_reduced_price_lunch': '450',
        'frpl_pct': '45.0',
        'direct_certification': '200',
        'lunch_program': '',
        'district_est_population': '50000',
        'district_pop_5_17': '10000',
        'district_pop_5_17_poverty': '2500',
        'district_poverty_pct': '25.0',
        'district_rev_total': '100000000',
        'district_exp_total': '95000000',
        'district_exp_per_pupil': '10000',
        'district_rev_per_pupil': '11000',
        'district_exp_instruction_per_pupil': '5500',
        'district_rev_federal_pct': '10.0',
        'district_rev_state_pct': '45.0',
        'district_rev_local_pct': '45.0',
    }
    defaults.update(overrides)
    return defaults


def _write_temp_csv(rows):
    """Write a list of row-dicts to a temp CSV and return the path."""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='')
    fieldnames = HEADER.split(',')
    writer = csv.DictWriter(tmp, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    tmp.close()
    return tmp.name


# ── Unit tests ─────────────────────────────────────────────────────────────

class TestSafeFloat(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_safe_float('42.5'), 42.5)

    def test_empty(self):
        self.assertIsNone(_safe_float(''))

    def test_none(self):
        self.assertIsNone(_safe_float(None))

    def test_sentinel_neg1(self):
        self.assertIsNone(_safe_float('-1'))

    def test_sentinel_neg2(self):
        self.assertIsNone(_safe_float('-2'))

    def test_allow_negative(self):
        self.assertEqual(_safe_float('-84.388', allow_negative=True), -84.388)

    def test_non_numeric(self):
        self.assertIsNone(_safe_float('N/A'))


class TestSafeInt(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_safe_int('1000'), 1000)

    def test_float_rounds(self):
        self.assertEqual(_safe_int('1000.7'), 1001)

    def test_empty(self):
        self.assertIsNone(_safe_int(''))


class TestSafeBool(unittest.TestCase):
    def test_one(self):
        self.assertTrue(_safe_bool('1'))

    def test_zero(self):
        self.assertFalse(_safe_bool('0'))

    def test_empty(self):
        self.assertFalse(_safe_bool(''))


class TestAvg(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_avg([10.0, 20.0, 30.0]), 20.0)

    def test_with_nones(self):
        self.assertEqual(_avg([10.0, None, 30.0]), 20.0)

    def test_all_none(self):
        self.assertIsNone(_avg([None, None]))

    def test_empty(self):
        self.assertIsNone(_avg([]))


class TestStudentTeacherRatio(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_compute_student_teacher_ratio(1000, 50.0), 20.0)

    def test_none_teachers(self):
        self.assertIsNone(_compute_student_teacher_ratio(1000, None))

    def test_zero_teachers(self):
        self.assertIsNone(_compute_student_teacher_ratio(1000, 0))


class TestAggregateSchool(unittest.TestCase):
    """Test the core dedup/aggregation logic."""

    def test_single_year(self):
        rows = [_make_row()]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['school_name'], 'Test High School')
        self.assertEqual(rec['state_code'], 'GA')
        self.assertEqual(rec['total_students'], 1000)
        self.assertEqual(rec['free_lunch_percentage'], 45.0)
        self.assertEqual(rec['school_type'], 'public')
        self.assertFalse(rec['is_charter'])

    def test_multi_year_uses_latest_enrollment(self):
        rows = [
            _make_row(school_year='2020-21', enrollment='800'),
            _make_row(school_year='2022-23', enrollment='1200'),
            _make_row(school_year='2021-22', enrollment='1000'),
        ]
        rec = _aggregate_school('999999999999', rows)
        # Latest year is 2022-23 → enrollment=1200
        self.assertEqual(rec['total_students'], 1200)
        self.assertEqual(rec['latest_school_year'], '2022-23')

    def test_multi_year_averages_frpl(self):
        rows = [
            _make_row(school_year='2020-21', frpl_pct='40.0'),
            _make_row(school_year='2021-22', frpl_pct='50.0'),
            _make_row(school_year='2022-23', frpl_pct='60.0'),
        ]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['free_lunch_percentage'], 50.0)

    def test_excludes_zero_frpl_from_avg(self):
        """2021-22 universal meals should not drag down the average."""
        rows = [
            _make_row(school_year='2020-21', frpl_pct='50.0'),
            _make_row(school_year='2021-22', frpl_pct='0.0'),  # universal meals
            _make_row(school_year='2022-23', frpl_pct='50.0'),
        ]
        rec = _aggregate_school('999999999999', rows)
        # Should average 50 and 50, ignoring 0.0
        self.assertEqual(rec['free_lunch_percentage'], 50.0)

    def test_charter_flag_any_year(self):
        rows = [
            _make_row(school_year='2020-21', charter='0'),
            _make_row(school_year='2022-23', charter='1'),
        ]
        rec = _aggregate_school('999999999999', rows)
        self.assertTrue(rec['is_charter'])

    def test_enrollment_trend(self):
        rows = [
            _make_row(school_year='2020-21', enrollment='800'),
            _make_row(school_year='2022-23', enrollment='1000'),
        ]
        rec = _aggregate_school('999999999999', rows)
        trend = json.loads(rec['enrollment_trend_json'])
        self.assertEqual(trend['2020-21'], 800)
        self.assertEqual(trend['2022-23'], 1000)

    def test_school_rename_uses_latest(self):
        rows = [
            _make_row(school_year='2020-21', school_name='Old Name High'),
            _make_row(school_year='2022-23', school_name='New Name High'),
        ]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['school_name'], 'New Name High')

    def test_longitude_negative(self):
        rows = [_make_row(longitude='-84.388')]
        rec = _aggregate_school('999999999999', rows)
        self.assertAlmostEqual(rec['longitude'], -84.388)

    def test_private_school(self):
        rows = [_make_row(school_type='private', frpl_pct='', enrollment='50')]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['school_type'], 'private')
        self.assertIsNone(rec['free_lunch_percentage'])
        self.assertEqual(rec['total_students'], 50)

    def test_years_of_data(self):
        rows = [
            _make_row(school_year='2018-19'),
            _make_row(school_year='2019-20'),
            _make_row(school_year='2020-21'),
        ]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['years_of_data'], 3)

    def test_student_teacher_ratio(self):
        rows = [_make_row(enrollment='1000', teachers_fte='50')]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['student_teacher_ratio'], 20.0)

    def test_direct_cert_pct(self):
        rows = [_make_row(enrollment='1000', direct_certification='200')]
        rec = _aggregate_school('999999999999', rows)
        self.assertEqual(rec['direct_certification_pct'], 20.0)


class TestReadAndGroupCSV(unittest.TestCase):
    def test_groups_by_ncessch(self):
        rows = [
            _make_row(ncessch='AAA', school_year='2020-21'),
            _make_row(ncessch='BBB', school_year='2020-21'),
            _make_row(ncessch='AAA', school_year='2021-22'),
        ]
        path = _write_temp_csv(rows)
        try:
            groups = read_and_group_csv(path)
            self.assertEqual(len(groups), 2)
            self.assertEqual(len(groups['AAA']), 2)
            self.assertEqual(len(groups['BBB']), 1)
        finally:
            os.unlink(path)

    def test_skips_empty_ncessch(self):
        rows = [
            _make_row(ncessch=''),
            _make_row(ncessch='AAA'),
        ]
        path = _write_temp_csv(rows)
        try:
            groups = read_and_group_csv(path)
            self.assertEqual(len(groups), 1)
            self.assertIn('AAA', groups)
        finally:
            os.unlink(path)


class TestWithRealCSV(unittest.TestCase):
    """Integration test against the actual GA CSV file, if available."""

    CSV_PATH = '/data/.openclaw/workspace/ga_highschools_all_ses.csv'

    @unittest.skipUnless(os.path.isfile(CSV_PATH), 'Real CSV not available')
    def test_real_csv_all_schools_aggregate(self):
        groups = read_and_group_csv(self.CSV_PATH)
        self.assertEqual(len(groups), 1249)

        for nces_id, rows in groups.items():
            rec = _aggregate_school(nces_id, rows)
            # Every record should have required fields
            self.assertTrue(rec['school_name'])
            self.assertEqual(rec['state_code'], 'GA')
            self.assertIsNotNone(rec['nces_id'])
            self.assertGreater(rec['years_of_data'], 0)

    @unittest.skipUnless(os.path.isfile(CSV_PATH), 'Real CSV not available')
    def test_lagrange_high_school(self):
        groups = read_and_group_csv(self.CSV_PATH)
        rec = _aggregate_school('130000100608', groups['130000100608'])
        self.assertEqual(rec['school_name'], 'LaGrange High School')
        self.assertEqual(rec['school_district'], 'Troup County')
        self.assertEqual(rec['years_of_data'], 10)
        self.assertIsNotNone(rec['longitude'])
        self.assertLess(rec['longitude'], 0)  # Western hemisphere


if __name__ == '__main__':
    unittest.main()
