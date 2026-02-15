#!/usr/bin/env python3
"""Clear all data from the database - fresh start."""

from src.database import Database

def clear_all_data():
    """Clear all records from all tables."""
    db = Database()
    
    # Check current state
    print("🔍 Checking current database state...")
    apps = db.execute_query("SELECT COUNT(*) as count FROM applications")
    app_count = apps[0]['count'] if apps else 0
    
    training = db.execute_query("SELECT COUNT(*) as count FROM applications WHERE is_training_example = TRUE")
    training_count = training[0]['count'] if training else 0
    
    print(f"\nCurrent database:")
    print(f"  📊 Total applications: {app_count}")
    print(f"  📚 Training examples: {training_count}")
    print(f"  🧪 Test/Production: {app_count - training_count}")
    
    if app_count == 0:
        print("\n✅ Database is already empty!")
        return
    
    # List of all tables to clear (in order to respect foreign keys)
    tables = [
        'aurora_communications',
        'merlin_evaluations',
        'mulan_recommendations',
        'moana_background_analysis',
        'rapunzel_transcript_analysis',
        'tiana_applications',
        'agent_audit_log',
        'applications'
    ]
    
    print(f"\n🗑️  Clearing all data from {len(tables)} tables...")
    
    total_deleted = 0
    for table in tables:
        try:
            # Get count before deletion
            count_result = db.execute_query(f"SELECT COUNT(*) as count FROM {table}")
            count = count_result[0]['count'] if count_result else 0
            
            if count > 0:
                # Delete all records
                rows_affected = db.execute_non_query(f"DELETE FROM {table}")
                total_deleted += rows_affected
                print(f"  ✓ Cleared {table}: {rows_affected} records deleted")
            else:
                print(f"  - {table}: already empty")
        except Exception as e:
            print(f"  ✗ Error clearing {table}: {e}")
    
    # Verify all tables are empty
    print("\n🔍 Verifying tables are empty...")
    all_empty = True
    for table in tables:
        try:
            count_result = db.execute_query(f"SELECT COUNT(*) as count FROM {table}")
            count = count_result[0]['count'] if count_result else 0
            if count > 0:
                print(f"  ⚠️  {table} still has {count} records!")
                all_empty = False
        except Exception as e:
            print(f"  ✗ Error checking {table}: {e}")
    
    if all_empty:
        print("\n✅ SUCCESS! All database tables are now empty.")
        print(f"   Total records deleted: {total_deleted}")
        print("\n📝 Database structure:")
        print("   - Training data (is_training_example = TRUE) - Reserved for training")
        print("   - Test data - Separate from training and production")
        print("   - 2026 Production data - Actual student applications")
        print("\n🎯 Ready to add data when needed!")
    else:
        print("\n⚠️  Some tables still have data. Check errors above.")
    
    db.close()

if __name__ == "__main__":
    try:
        clear_all_data()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
