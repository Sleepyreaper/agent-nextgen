"""Quick cleanup script for contaminated test data - runs on Azure."""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database
from src.logger import app_logger as logger

def cleanup_contaminated_records():
    """Identify and flag contaminated test records."""
    
    db = Database()
    conn = db.connect()
    cursor = conn.cursor()
    
    try:
        # Step 1: Find contaminated records
        logger.info("🔍 Scanning for contaminated test records...")
        
        cursor.execute("""
            SELECT 
                application_id,
                applicant_name,
                COALESCE(is_test_data, FALSE) as is_test_data,
                COALESCE(is_training_example, FALSE) as is_training_example,
                uploaded_date
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
        
        if not contaminated:
            logger.info("✓ No contaminated records found.")
            
            # Fix any NULL flags
            cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
            test_fixed = cursor.rowcount
            cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
            training_fixed = cursor.rowcount
            conn.commit()
            
            if test_fixed > 0 or training_fixed > 0:
                logger.info(f"✓ Fixed NULL flags: is_test_data={test_fixed}, is_training_example={training_fixed}")
            
            logger.info("✓ Data cleanup completed - no contamination detected.")
            return
        
        # Step 2: Flag contaminated records as test data
        logger.info(f"⚠️  Found {len(contaminated)} contaminated records:")
        
        record_ids = []
        for row in contaminated:
            app_id, name, is_test, is_training, uploaded = row
            logger.info(f"  - ID {app_id}: {name} (uploaded: {uploaded})")
            record_ids.append(app_id)
        
        # Step 3: Update the records
        logger.info("\n📝 Flagging contaminated records as test data...")
        
        placeholders = ','.join(['%s'] * len(record_ids))
        cursor.execute(f"""
            UPDATE applications
            SET is_test_data = TRUE, is_training_example = FALSE
            WHERE application_id IN ({placeholders})
        """, record_ids)
        
        updated_count = cursor.rowcount
        conn.commit()
        
        logger.info(f"✓ Successfully flagged {updated_count} records as test data.")
        
        # Step 4: Fix any remaining NULL flags
        cursor.execute("UPDATE applications SET is_test_data = FALSE WHERE is_test_data IS NULL")
        test_fixed = cursor.rowcount
        cursor.execute("UPDATE applications SET is_training_example = FALSE WHERE is_training_example IS NULL")
        training_fixed = cursor.rowcount
        conn.commit()
        
        if test_fixed > 0 or training_fixed > 0:
            logger.info(f"✓ Fixed NULL flags: is_test_data={test_fixed}, is_training_example={training_fixed}")
        
        # Step 5: Verify results
        logger.info("\n🔍 Verifying data isolation...")
        
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE (is_training_example IS NULL OR is_training_example = FALSE)
            AND (is_test_data IS NULL OR is_test_data = FALSE)
        """)
        production_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE is_training_example = TRUE
            AND (is_test_data IS NULL OR is_test_data = FALSE)
        """)
        training_count = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM applications
            WHERE is_test_data = TRUE
            AND (is_training_example IS NULL OR is_training_example = FALSE)
        """)
        test_count = cursor.fetchone()[0]
        
        logger.info(f"  2026 Production: {production_count} records")
        logger.info(f"  Training Data: {training_count} records")
        logger.info(f"  Test Data: {test_count} records")
        
        # Check for any remaining contamination
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
        
        remaining = cursor.fetchone()[0]
        
        if remaining == 0:
            logger.info("\n✅ SUCCESS: Data isolation verified - no contamination detected!")
        else:
            logger.warning(f"\n⚠️  Warning: Still {remaining} test-like names in production view.")
        
        cursor.close()
        return True
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Cleanup failed: {e}")
        cursor.close()
        return False


if __name__ == "__main__":
    logger.info("=" * 80)
    logger.info("TEST DATA CLEANUP SCRIPT")
    logger.info("=" * 80)
    
    try:
        cleanup_contaminated_records()
        logger.info("\n✓ Cleanup script completed successfully.")
    except Exception as e:
        logger.error(f"❌ Script failed: {e}")
        sys.exit(1)
