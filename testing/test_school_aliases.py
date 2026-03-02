"""Test database school field aliasing for CSV/agent compatibility."""
import pytest
from src.database import Database


class TestSchoolFieldAliases:
    """Verify _add_school_field_aliases works for all consumers."""

    def _base_record(self):
        """Simulate a SELECT * row from school_enriched_data."""
        return {
            'school_enrichment_id': 1,
            'school_name': 'Test High School',
            'school_district': 'Test District',
            'state_code': 'GA',
            'county_name': 'Test County',
            'total_students': 1200,
            'college_acceptance_rate': 85.5,
            'ap_course_count': 12,
            'ap_exam_pass_rate': 60.0,
            'stem_program_available': True,
            'ib_program_available': False,
            'honors_course_count': 8,
            'dual_enrollment_available': True,
            'web_sources_analyzed': '["http://example.com"]',
            'updated_at': '2025-01-01T00:00:00',
            'free_lunch_percentage': 62.0,
            'graduation_rate': 90.0,
            'opportunity_score': 55.0,
            'data_confidence_score': 80.0,
            'analysis_status': 'complete',
            'human_review_status': 'pending',
        }

    # ---- Simple alias tests ----

    def test_enrollment_size_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['enrollment_size'] == 1200
        assert r['total_students'] == 1200  # original untouched

    def test_college_placement_rate_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['college_placement_rate'] == 85.5
        assert r['college_acceptance_rate'] == 85.5

    def test_ap_classes_count_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['ap_classes_count'] == 12
        assert r['ap_course_count'] == 12

    def test_stem_programs_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['stem_programs'] is True

    def test_ib_offerings_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['ib_offerings'] is False

    def test_honors_programs_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['honors_programs'] == 8

    def test_web_sources_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['web_sources'] == '["http://example.com"]'

    def test_analysis_date_alias(self):
        r = Database._add_school_field_aliases(self._base_record())
        assert r['analysis_date'] == '2025-01-01T00:00:00'

    # ---- Computed fields ----

    def test_socioeconomic_level_low(self):
        rec = self._base_record()
        rec['free_lunch_percentage'] = 80.0
        r = Database._add_school_field_aliases(rec)
        assert r['socioeconomic_level'] == 'low'

    def test_socioeconomic_level_low_medium(self):
        rec = self._base_record()
        rec['free_lunch_percentage'] = 55.0
        r = Database._add_school_field_aliases(rec)
        assert r['socioeconomic_level'] == 'low-medium'

    def test_socioeconomic_level_medium(self):
        rec = self._base_record()
        rec['free_lunch_percentage'] = 30.0
        r = Database._add_school_field_aliases(rec)
        assert r['socioeconomic_level'] == 'medium'

    def test_socioeconomic_level_medium_high(self):
        rec = self._base_record()
        rec['free_lunch_percentage'] = 10.0
        r = Database._add_school_field_aliases(rec)
        assert r['socioeconomic_level'] == 'medium-high'

    def test_socioeconomic_level_unknown_when_null(self):
        rec = self._base_record()
        rec['free_lunch_percentage'] = None
        r = Database._add_school_field_aliases(rec)
        assert r['socioeconomic_level'] == 'unknown'

    def test_academic_programs_computed(self):
        r = Database._add_school_field_aliases(self._base_record())
        prog = r['academic_programs']
        assert '12 AP courses' in prog
        assert 'STEM program' in prog
        assert 'Dual enrollment' in prog
        assert 'IB' not in prog  # IB is False

    def test_academic_programs_none_when_no_programs(self):
        rec = self._base_record()
        rec['ap_course_count'] = 0
        rec['ib_program_available'] = False
        rec['stem_program_available'] = False
        rec['dual_enrollment_available'] = False
        r = Database._add_school_field_aliases(rec)
        assert r['academic_programs'] is None

    # ---- Edge cases ----

    def test_none_record_passthrough(self):
        assert Database._add_school_field_aliases(None) is None

    def test_empty_record(self):
        r = Database._add_school_field_aliases({})
        assert r.get('socioeconomic_level') == 'unknown'
        assert r.get('academic_programs') is None

    def test_alias_does_not_overwrite_existing(self):
        """If a record already has the alias key, don't clobber it."""
        rec = self._base_record()
        rec['enrollment_size'] = 9999  # pre-existing (e.g. from Naveen)
        r = Database._add_school_field_aliases(rec)
        assert r['enrollment_size'] == 9999  # kept original
        assert r['total_students'] == 1200   # DB column untouched

    # ---- CSV-imported record simulation ----

    def test_csv_imported_record(self):
        """Simulate a record written by csv_school_importer."""
        rec = {
            'school_name': 'Lagrange High School',
            'school_district': 'Troup County',
            'state_code': 'GA',
            'total_students': 800,
            'free_lunch_percentage': 72.5,
            'college_acceptance_rate': 0,
            'ap_course_count': 0,
            'stem_program_available': False,
            'ib_program_available': False,
            'dual_enrollment_available': False,
            'honors_course_count': None,
            'graduation_rate': 0,
            'opportunity_score': 0,
            'analysis_status': 'csv_imported',
            'human_review_status': 'pending',
            'data_confidence_score': 0,
            'web_sources_analyzed': None,
            'updated_at': '2025-07-01',
            'is_title_i': True,
            'student_teacher_ratio': 16.5,
            'reduced_lunch_percentage': 5.0,
        }
        r = Database._add_school_field_aliases(rec)
        # Aliases work
        assert r['enrollment_size'] == 800
        assert r['socioeconomic_level'] == 'low-medium'  # 72.5% FRPL (50-75 range)
        assert r['academic_programs'] is None  # no programs
        assert r['web_sources'] is None
        assert r['analysis_date'] == '2025-07-01'
        # Original columns intact
        assert r['total_students'] == 800
        assert r['is_title_i'] is True
