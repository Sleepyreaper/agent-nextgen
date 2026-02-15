#!/usr/bin/env python3
"""Test the training route directly"""
from app import app, db

with app.test_client() as client:
    print("Testing /training route...\n")
    
    try:
        # Create some test training data first
        app_id = db.create_application(
            applicant_name="Sample Training Student",
            email="sample@training.com",
            application_text="Sample training application",
            file_name="sample.pdf",
            file_type="pdf",
            is_training=True,
            was_selected=True
        )
        print(f"✅ Created sample training data (ID: {app_id})")
        
        # Test the training route
        response = client.get('/training')
        print(f"\n✅ Response status: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Training page loads successfully!")
            print(f"   Response length: {len(response.data)} bytes")
        else:
            print(f"❌ Error response:")
            print(response.data.decode('utf-8')[:500])
        
        # Clean up
        db.execute_non_query("DELETE FROM Applications WHERE application_id = %s", (app_id,))
        print(f"\n✅ Cleaned up test data")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
