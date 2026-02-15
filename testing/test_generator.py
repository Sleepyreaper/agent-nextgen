#!/usr/bin/env python3
"""Test the enhanced test data generator."""

from src.test_data_generator import test_data_generator

print("Testing Enhanced Test Data Generator")
print("=" * 60)

# Generate a single high-quality student
student = test_data_generator.generate_student(quality_tier='high')

print(f"\n✓ Generated student: {student['name']}")
print(f"  School: {student['school']}")
print(f"  Email: {student['email']}")
print(f"  GPA: {student['gpa']}")
print(f"  AP Courses: {len(student['ap_courses'])}")
print(f"  Quality Tier: {student['quality_tier']}")

print(f"\n✓ Application Essay Length: {len(student['application_text'])} chars")
print(f"✓ Transcript Length: {len(student['transcript_text'])} chars")
print(f"✓ Recommendation Length: {len(student['recommendation_text'])} chars")

print(f"\n✓ Recommender: {student['recommender_name']} ({student['recommender_role']})")

print(f"\n✓ School Metadata:")
print(f"  - Type: {student['school_data']['type']}")
print(f"  - AP Courses Available: {student['school_data']['ap_courses']}")
print(f"  - IB Available: {student['school_data']['ib_available']}")
print(f"  - STEM Programs: {student['school_data']['stem_programs']}")
print(f"  - Median Income: ${student['school_data']['median_income']:,}")
print(f"  - Free Lunch %: {student['school_data']['free_lunch_pct']}")

print("\n" + "=" * 60)
print("📋 Transcript Preview (first 500 chars):")
print(student['transcript_text'][:500])

print("\n" + "=" * 60)
print("📝 Recommendation Preview (first 400 chars):")
print(student['recommendation_text'][:400])

print("\n" + "=" * 60)
print("✅ All data generated successfully!")
print(f"\nAgent Data Availability:")
print(f"  • Tiana (Application Reader): ✓ {len(student['application_text'])} chars")
print(f"  • Rapunzel (Grade Reader): ✓ {len(student['transcript_text'])} chars") 
print(f"  • Mulan (Recommendation Reader): ✓ {len(student['recommendation_text'])} chars")
print(f"  • Moana (School Context): ✓ {len(str(student['school_data']))} chars metadata")
