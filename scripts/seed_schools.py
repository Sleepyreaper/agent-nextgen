#!/usr/bin/env python3
"""
Seed database with initial schools.
Run this after schema is created.

Usage:
    python scripts/seed_schools.py
"""

import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.database import db
from src.logger import app_logger as logger

INITIAL_SCHOOLS = [
    {
        'school_name': 'Lincoln High School',
        'school_district': 'Fulton County Schools',
        'state_code': 'GA',
        'county_name': 'Fulton County',
        'school_url': 'https://lincolnhs.fcschools.us',
        'total_students': 1950,
        'graduation_rate': 92.5,
        'college_acceptance_rate': 85.0,
        'free_lunch_percentage': 28.0,
        'ap_course_count': 24,
        'ap_exam_pass_rate': 78.5,
        'stem_program_available': True,
        'ib_program_available': False,
        'dual_enrollment_available': True,
        'opportunity_score': 81.5,
        'analysis_status': 'complete',
        'human_review_status': 'approved',
        'data_confidence_score': 92.0,
        'web_sources': [
            'https://lincolnhs.fcschools.us',
            'https://www.greatschools.org/georgia/atlanta/lincoln-high-school',
            'https://www.niche.com/k12/search/best-high-schools/s/georgia'
        ],
        'created_by': 'seed_script'
    },
    {
        'school_name': 'Westlake High School',
        'school_district': 'Clayton County Schools',
        'state_code': 'GA',
        'county_name': 'Clayton County',
        'school_url': 'https://www.claytoncountyschools.us/westlake',
        'total_students': 2100,
        'graduation_rate': 88.3,
        'college_acceptance_rate': 78.0,
        'free_lunch_percentage': 42.0,
        'ap_course_count': 18,
        'ap_exam_pass_rate': 71.2,
        'stem_program_available': True,
        'ib_program_available': False,
        'dual_enrollment_available': True,
        'opportunity_score': 72.3,
        'analysis_status': 'complete',
        'human_review_status': 'approved',
        'data_confidence_score': 85.0,
        'web_sources': [
            'https://www.claytoncountyschools.us/westlake',
            'https://www.greatschools.org/georgia/college-park/westlake-high-school'
        ],
        'created_by': 'seed_script'
    },
    {
        'school_name': 'Martin Luther King Jr. High School',
        'school_district': 'DeKalb County Schools',
        'state_code': 'GA',
        'county_name': 'DeKalb County',
        'school_url': 'https://www.dekalbschoolsga.org/mlk',
        'total_students': 1850,
        'graduation_rate': 91.0,
        'college_acceptance_rate': 82.0,
        'free_lunch_percentage': 35.0,
        'ap_course_count': 22,
        'ap_exam_pass_rate': 76.8,
        'stem_program_available': True,
        'ib_program_available': True,
        'dual_enrollment_available': True,
        'opportunity_score': 79.7,
        'analysis_status': 'complete',
        'human_review_status': 'approved',
        'data_confidence_score': 88.5,
        'web_sources': [
            'https://www.dekalbschoolsga.org/mlk',
            'https://www.niche.com/k12/d/martin-luther-king-jr-high-school-decatur-ga'
        ],
        'created_by': 'seed_script'
    },
    {
        'school_name': 'Lakeside High School',
        'school_district': 'DeKalb County Schools',
        'state_code': 'GA',
        'county_name': 'DeKalb County',
        'school_url': 'https://www.dekalbschoolsga.org/lakeside',
        'total_students': 2000,
        'graduation_rate': 94.5,
        'college_acceptance_rate': 88.5,
        'free_lunch_percentage': 18.0,
        'ap_course_count': 28,
        'ap_exam_pass_rate': 82.1,
        'stem_program_available': True,
        'ib_program_available': True,
        'dual_enrollment_available': True,
        'opportunity_score': 86.2,
        'analysis_status': 'complete',
        'human_review_status': 'approved',
        'data_confidence_score': 95.0,
        'web_sources': [
            'https://www.dekalbschoolsga.org/lakeside',
            'https://www.niche.com/k12/d/lakeside-high-school-atlanta-ga'
        ],
        'created_by': 'seed_script'
    },
    {
        'school_name': 'Northside High School',
        'school_district': 'Atlanta Public Schools',
        'state_code': 'GA',
        'county_name': 'Fulton County',
        'school_url': 'https://www.apsstu.org/northside',
        'total_students': 1750,
        'graduation_rate': 89.0,
        'college_acceptance_rate': 77.5,
        'free_lunch_percentage': 52.0,
        'ap_course_count': 16,
        'ap_exam_pass_rate': 68.5,
        'stem_program_available': True,
        'ib_program_available': False,
        'dual_enrollment_available': False,
        'opportunity_score': 68.4,
        'analysis_status': 'complete',
        'human_review_status': 'pending',
        'data_confidence_score': 78.0,
        'web_sources': [
            'https://www.apsstu.org/northside'
        ],
        'created_by': 'seed_script'
    }
]


def seed_schools():
    """Seed the database with initial schools."""
    print("🌱 Starting school database seeding...")
    
    db.connect()
    
    created_count = 0
    skipped_count = 0
    error_count = 0
    
    for school in INITIAL_SCHOOLS:
        try:
            # Check if already exists
            existing = db.get_school_enriched_data(
                school_name=school['school_name'],
                state_code=school['state_code']
            )
            
            if not existing:
                school_id = db.create_school_enriched_data(school)
                if school_id:
                    print(f"✓ Created: {school['school_name']} (ID: {school_id}) - Score: {school.get('opportunity_score', 'N/A')}")
                    created_count += 1
                else:
                    print(f"✗ Failed to create: {school['school_name']}")
                    error_count += 1
            else:
                print(f"- Skipped (exists): {school['school_name']}")
                skipped_count += 1
                
        except Exception as e:
            print(f"✗ Error with {school['school_name']}: {e}")
            error_count += 1
            logger.error(f"Error seeding school {school['school_name']}: {e}")
    
    print("\n" + "="*50)
    print("📊 Seeding Summary:")
    print(f"   Created: {created_count}")
    print(f"   Skipped: {skipped_count}")
    print(f"   Errors:  {error_count}")
    print(f"   Total:   {len(INITIAL_SCHOOLS)}")
    print("="*50)


if __name__ == '__main__':
    try:
        seed_schools()
        print("\n✅ Seeding complete!")
    except Exception as e:
        print(f"\n❌ Seeding failed: {e}")
        logger.error(f"Fatal error during seeding: {e}", exc_info=True)
        sys.exit(1)
