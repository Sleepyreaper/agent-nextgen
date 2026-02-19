"""Diagnostic script to identify and clean up contaminated test records."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.database import Database
from src.logger import app_logger as logger
import psycopg

def identify_contaminated_records(db):
    """Find records that appear to be test data but aren't properly flagged."""
    conn = db.connect()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("SCANNING FOR CONTAMINATED TEST RECORDS")
    print("="*80)
    
    # Query 1: Records with test-like names but not flagged as test data
    print("\n1. Records with 'test' in name but is_test_data = FALSE or NULL:")
    print("-" * 80)
    
    cursor.execute("""
        SELECT 
            application_id,
            applicant_name,
            COALESCE(is_test_data, FALSE) as is_test_data,
            COALESCE(is_training_example, FALSE) as is_training_example,
            uploaded_date,
            (SELECT COUNT(*) FROM rapunzel_grades WHERE rapunzel_grades.application_id = applications.application_id) as rapunzel_count,
            (SELECT COUNT(*) FROM tiana_applications WHERE tiana_applications.application_id = applications.application_id) as tiana_count
        FROM applications
        WHERE (is_test_data IS NULL OR is_test_data = FALSE)
        AND (is_training_example IS NULL OR is_training_example = FALSE)
        AND (
            LOWER(applicant_name) LIKE '%test%'
            OR LOWER(applicant_name) LIKE '%demo%'
            OR LOWER(applicant_name) LIKE '%sample%'
        )
        ORDER BY uploaded_date DESC
    """)
    
    contaminated = cursor.fetchall()
    
    if contaminated:
        print(f"Found {len(contaminated)} potentially contaminated records:\n")
        for row in contaminated:
            app_id, name, is_test, is_training, uploaded, rapunzel_ct, tiana_ct = row
            print(f"  ID: {app_id}")
            print(f"  Name: {name}")
            print(f"  is_test_data: {is_test}, is_training_example: {is_training}")
            print(f"  Uploaded: {uploaded}")
            print(f"  Agent records: Rapunzel={rapunzel_ct}, Tiana={tiana_ct}")
            print()
    else:
        print("✓ No contaminated records found with test-like names.\n")
    
    # Query 2: Any records with NULL flags (should have explicit TRUE/FALSE)
    print("\n2. Records with NULL data isolation flags:")
    print("-" * 80)
    
    cursor.execute("""
        SELECT 
            COUNT(*) as count,
            COUNT(CASE WHEN is_test_data IS NULL THEN 1 END) as null_test_data,
            COUNT(CASE WHEN is_training_example IS NULL THEN 1 END) as null_training
        FROM applications
        WHERE is_test_data IS NULL OR is_training_example IS NULL
    """)
    
    null_counts = cursor.fetchone()
    if null_counts[0] > 0:
        print(f"Found {null_counts[0]} records with NULL flags:")
        print(f"  - NULL is_test_data: {null_counts[1]}")
        print(f"  - NULL is_training_example: {null_counts[2]}")
        print("\nThese should be fixed to have explicit FALSE values.")
    else:
        print("✓ All records have explicit TRUE/FALSE flags.\n")
    
    # Query 3: Count records in each category
    print("\n3. Current data distribution:")
    print("-" * 80)
    
    cursor.execute("""
        SELECT 
            CASE 
                WHEN is_test_data = TRUE THEN 'Test Data'
                WHEN is_training_example = TRUE THEN 'Training Data'
                WHEN (COALESCE(is_test_data, FALSE) = FALSE AND COALESCE(is_training_example, FALSE) = FALSE) THEN '2026 Production'
                ELSE 'Unknown'
            END as category,
            COUNT(*) as count
        FROM applications
        GROUP BY category
        ORDER BY category
    """)
    
    distribution = cursor.fetchall()
    print()
    for category, count in distribution:
        print(f"  {category}: {count} records")
    
    cursor.close()
    return len(contaminated) > 0


def generate_cleanup_sql(db):
    """Generate SQL statements to clean up contaminated records."""
    conn = db.connect()
    cursor = conn.cursor()
    
    # Get the contaminated record IDs
    cursor.execute("""
        SELECT application_id, applicant_name
        FROM applications
        WHERE (is_test_data IS NULL OR is_test_data = FALSE)
        AND (is_training_example IS NULL OR is_training_example = FALSE)
        AND (
            LOWER(applicant_name) LIKE '%test%'
            OR LOWER(applicant_name) LIKE '%demo%'
            OR LOWER(applicant_name) LIKE '%sample%'
        )
        ORDER BY application_id
    """)
    
    records = cursor.fetchall()
    cursor.close()
    
    if not records:
        return None
    
    print("\n" + "="*80)
    print("CLEANUP OPTIONS")
    print("="*80)
    
    print("\n--- OPTION A: Flag as Test Data (Recommended) ---")
    print("This will move these records to the /test-data view:\n")
    
    ids = [str(row[0]) for row in records]
    print(f"UPDATE applications")
    print(f"SET is_test_data = TRUE, is_training_example = FALSE")
    print(f"WHERE application_id IN ({', '.join(ids)});")
    
    print("\n--- OPTION B: Delete Permanently (Use with caution!) ---")
    print("This will permanently delete these records and all related agent data:\n")
    
    print(f"-- First delete from agent tables")
    print(f"DELETE FROM rapunzel_grades WHERE application_id IN ({', '.join(ids)});")
    print(f"DELETE FROM tiana_applications WHERE application_id IN ({', '.join(ids)});")
    print(f"DELETE FROM mulan_recommendations WHERE application_id IN ({', '.join(ids)});")
    print(f"DELETE FROM merlin_evaluations WHERE application_id IN ({', '.join(ids)});")
    print(f"DELETE FROM aurora_evaluations WHERE application_id IN ({', '.join(ids)});")
    print(f"-- Then delete the applications")
    print(f"DELETE FROM applications WHERE application_id IN ({', '.join(ids)});")
    
    print("\n--- OPTION C: Fix NULL flags for all records ---")
    print("Set explicit FALSE for any NULL values:\n")
    
    print("UPDATE applications")
    print("SET is_test_data = FALSE")
    print("WHERE is_test_data IS NULL;")
    print()
    print("UPDATE applications")
    print("SET is_training_example = FALSE")
    print("WHERE is_training_example IS NULL;")
    
    return ids


def apply_cleanup(db, option: str, record_ids: list):
    """Apply the selected cleanup option."""
    conn = db.connect()
    cursor = conn.cursor()
    
    try:
        if option == 'A':
            # Flag as test data
            cursor.execute(f"""
                UPDATE applications
                SET is_test_data = TRUE, is_training_example = FALSE
                WHERE application_id IN ({', '.join(record_ids)})
            """)
            conn.commit()
            print(f"\n✓ Successfully flagged {len(record_ids)} records as test data.")
            
        elif option == 'B':
            # Delete permanently
            for table in ['rapunzel_grades', 'tiana_applications', 'mulan_recommendations', 
                         'merlin_evaluations', 'aurora_evaluations']:
                cursor.execute(f"""
                    DELETE FROM {table}
                    WHERE application_id IN ({', '.join(record_ids)})
                """)
            
            cursor.execute(f"""
                DELETE FROM applications
                WHERE application_id IN ({', '.join(record_ids)})
            """)
            conn.commit()
            print(f"\n✓ Successfully deleted {len(record_ids)} records and their related data.")
            
        elif option == 'C':
            # Fix NULL flags
            cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
            test_updated = cursor.rowcount
            cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
            training_updated = cursor.rowcount
            conn.commit()
            print(f"\n✓ Fixed NULL flags:")
            print(f"  - is_test_data: {test_updated} records updated")
            print(f"  - is_training_example: {training_updated} records updated")
        
        cursor.close()
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\n❌ Cleanup failed: {e}")
        cursor.close()
        return False


def verify_isolation(db):
    """Verify that data isolation is working correctly."""
    conn = db.connect()
    cursor = conn.cursor()
    
    print("\n" + "="*80)
    print("VERIFYING DATA ISOLATION")
    print("="*80)
    
    queries = {
        "2026 Production (/students)": """
            SELECT COUNT(*) FROM applications
            WHERE (is_training_example IS NULL OR is_training_example = FALSE)
            AND (is_test_data IS NULL OR is_test_data = FALSE)
        """,
        "Training Data (/training)": """
            SELECT COUNT(*) FROM applications
            WHERE is_training_example = TRUE
            AND (is_test_data IS NULL OR is_test_data = FALSE)
        """,
        "Test Data (/test-data)": """
            SELECT COUNT(*) FROM applications
            WHERE is_test_data = TRUE
            AND (is_training_example IS NULL OR is_training_example = FALSE)
        """
    }
    
    print()
    for view_name, query in queries.items():
        cursor.execute(query)
        count = cursor.fetchone()[0]
        print(f"  {view_name}: {count} records")
    
    # Check for any records with test-like names in production view
    cursor.execute("""
        SELECT COUNT(*) FROM applications
        WHERE (is_training_example IS NULL OR is_training_example = FALSE)
        AND (is_test_data IS NULL OR is_test_data = FALSE)
        AND (
            LOWER(applicant_name) LIKE '%test%'
            OR LOWER(applicant_name) LIKE '%demo%'
            OR LOWER(applicant_name) LIKE '%sample%'
        )
    """)
    
    contaminated_count = cursor.fetchone()[0]
    
    print(f"\n  Test-like names in 2026 Production: {contaminated_count}")
    
    if contaminated_count == 0:
        print("\n✓ Data isolation verified - no contamination detected!")
    else:
        print("\n⚠️  Warning: Still found test-like names in production view.")
    
    cursor.close()


def main():
    """Main diagnostic and cleanup workflow."""
    print("\n🔍 Test Data Contamination Diagnostic Tool")
    print("=" * 80)
    
    db = Database()
    
    # Step 1: Identify contaminated records
    has_contamination = identify_contaminated_records(db)
    
    if not has_contamination:
        print("\n✓ No contamination detected. Verifying data isolation...")
        verify_isolation(db)
        return
    
    # Step 2: Generate cleanup SQL
    record_ids = generate_cleanup_sql(db)
    
    if not record_ids:
        return
    
    # Step 3: Ask user for cleanup action
    print("\n" + "="*80)
    print("CLEANUP ACTIONS")
    print("="*80)
    print("\nWhat would you like to do?")
    print("  A - Flag contaminated records as test data (recommended)")
    print("  B - Delete contaminated records permanently")
    print("  C - Fix NULL flags for all records")
    print("  V - Verify data isolation only (no changes)")
    print("  Q - Quit without making changes")
    
    choice = input("\nEnter your choice (A/B/C/V/Q): ").strip().upper()
    
    if choice == 'Q':
        print("\n👋 Exiting without making changes.")
        return
    
    if choice == 'V':
        verify_isolation(db)
        return
    
    if choice in ['A', 'B', 'C']:
        if choice == 'B':
            confirm = input("\n⚠️  Are you sure you want to DELETE these records? Type 'DELETE' to confirm: ")
            if confirm != 'DELETE':
                print("\n❌ Delete cancelled.")
                return
        
        success = apply_cleanup(db, choice, record_ids)
        
        if success:
            print("\n🔍 Verifying results...")
            verify_isolation(db)
    else:
        print("\n❌ Invalid choice. Exiting.")


if __name__ == "__main__":
    main()
