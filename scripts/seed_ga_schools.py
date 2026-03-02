#!/usr/bin/env python3
"""
DEPRECATED — This script previously seeded the database from data/ga_high_schools.json
(web-scraped Wikipedia data).  That file has been removed.  School data is now
imported exclusively via CSV upload on the training page, which populates the
school_enriched_data table directly.

This script is retained only for historical reference.
"""

import sys
print("This script is DEPRECATED. Upload school CSV data via the Training page instead.")
sys.exit(1)


def load_schools() -> list:
    """Load GA high school data from JSON file."""
    if not DATA_FILE.exists():
        print(f"❌ Data file not found: {DATA_FILE}")
        sys.exit(1)
    
    with open(DATA_FILE, "r") as f:
        schools = json.load(f)
    
    print(f"📂 Loaded {len(schools)} schools from {DATA_FILE.name}")
    return schools


def build_school_url(school_name: str, city: str) -> str:
    """Build a reference identifier for the school."""
    # Normalize: lowercase, replace spaces with hyphens, strip non-alpha
    def slugify(text):
        return text.lower().replace(" ", "-").replace(".", "").replace("'", "")
    
    return f"ga/{slugify(city)}/{slugify(school_name)}"


def seed_ga_schools(clear_first: bool = True, dry_run: bool = False):
    """Seed the database with all GA high schools."""
    print("=" * 60)
    print("🏫 Georgia High School Database Seeder")
    print("=" * 60)
    
    schools = load_schools()
    
    if not dry_run:
        db.connect()
    
    # Step 1: Clear existing records
    if clear_first:
        if dry_run:
            print("\n🔍 [DRY RUN] Would delete all existing school records")
        else:
            print("\n🗑️  Clearing existing school records...")
            deleted = db.delete_all_school_enriched_data()
            print(f"   Deleted {deleted} existing records")
    else:
        print("\n⏭️  Skipping delete (--no-clear)")
    
    # Step 2: Seed all GA high schools as skeleton records
    print(f"\n🌱 Seeding {len(schools)} Georgia high schools...")
    
    created = 0
    skipped = 0
    errors = 0
    
    for i, school in enumerate(schools, 1):
        school_name = school["school_name"]
        city = school.get("city", "")
        county = school.get("county", "")
        district = school.get("district", "")
        
        # Build the record — skeleton with NO enrichment data
        # Naveen/Moana will populate the academic/enrichment fields later
        record = {
            "school_name": school_name,
            "school_district": district,
            "state_code": "GA",
            "county_name": county,
            "school_url": build_school_url(school_name, city),
            # All numeric/enrichment fields left at 0/default
            # so the system knows they need enrichment
            "opportunity_score": 0,
            "total_students": 0,
            "graduation_rate": 0,
            "college_acceptance_rate": 0,
            "free_lunch_percentage": 0,
            "ap_course_count": 0,
            "ap_exam_pass_rate": 0,
            "stem_program_available": False,
            "ib_program_available": False,
            "dual_enrollment_available": False,
            "analysis_status": "pending",       # Signals: needs Naveen enrichment
            "human_review_status": "pending",    # Signals: needs human review
            "data_confidence_score": 0,
            "created_by": "ga_seed_script",
            "school_investment_level": "unknown",
            "is_active": True,
        }
        
        if dry_run:
            if i <= 5:
                print(f"   [DRY RUN] Would create: {school_name} ({city}, {county})")
            elif i == 6:
                print(f"   ... and {len(schools) - 5} more")
            continue
        
        try:
            # Check if already exists (in case --no-clear was used)
            existing = db.get_school_enriched_data(
                school_name=school_name,
                state_code="GA"
            )
            
            if existing:
                skipped += 1
                continue
            
            school_id = db.create_school_enriched_data(record)
            if school_id:
                created += 1
                if created <= 10 or created % 50 == 0:
                    print(f"   ✓ [{created}] {school_name} — {city}, {county} (ID: {school_id})")
            else:
                errors += 1
                print(f"   ✗ Failed: {school_name}")
                
        except Exception as e:
            errors += 1
            print(f"   ✗ Error: {school_name} — {e}")
            logger.error(f"Seed error for {school_name}: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Seeding Summary")
    print("=" * 60)
    if dry_run:
        print(f"   Mode:    DRY RUN (no changes made)")
        print(f"   Schools: {len(schools)} would be created")
    else:
        print(f"   Created: {created}")
        print(f"   Skipped: {skipped} (already existed)")
        print(f"   Errors:  {errors}")
        print(f"   Total:   {len(schools)}")
    print("=" * 60)
    
    if not dry_run:
        print(f"\n💡 Next steps:")
        print(f"   • Schools are seeded with analysis_status='pending'")
        print(f"   • Visit /schools dashboard to see all {created} GA schools")
        print(f"   • Click 'Analyze' on individual schools to trigger Naveen enrichment")
        print(f"   • Or use POST /api/schools/enrich-pending to bulk-enrich")


def main():
    parser = argparse.ArgumentParser(description="Seed GA high schools into database")
    parser.add_argument("--no-clear", action="store_true", help="Skip deleting existing records")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()
    
    seed_ga_schools(clear_first=not args.no_clear, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
        print("\n✅ Seeding complete!")
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Seeding failed: {e}")
        logger.error(f"Fatal error during GA school seeding: {e}", exc_info=True)
        sys.exit(1)
