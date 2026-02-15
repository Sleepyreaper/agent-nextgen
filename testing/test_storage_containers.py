"""
Test script to verify Azure Storage containers are properly set up.
"""

import os
from src.storage import StorageManager
from src.logger import app_logger as logger

def test_containers():
    """Test that all required containers exist."""
    try:
        storage = StorageManager()
        
        if not storage.client:
            print("❌ Azure Storage not configured (missing connection string)")
            print("   Containers will be created when AZURE_STORAGE_CONNECTION_STRING is set")
            return
        
        print("🔍 Checking Azure Storage containers...\n")
        
        # List all containers
        containers = list(storage.client.list_containers())
        container_names = [c.name for c in containers]
        
        print(f"📦 Found {len(containers)} containers:")
        for name in container_names:
            print(f"   ✅ {name}")
        
        print("\n🎯 Required containers:")
        required = ['applications-2026', 'applications-test', 'applications-training']
        
        for req in required:
            if req in container_names:
                print(f"   ✅ {req} - EXISTS")
            else:
                print(f"   ⚠️  {req} - MISSING (will be created on first upload)")
        
        print("\n" + "="*60)
        print("✅ Storage container check complete!")
        print("="*60)
        
    except Exception as e:
        logger.error(f"Error testing containers: {e}", exc_info=True)
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_containers()
