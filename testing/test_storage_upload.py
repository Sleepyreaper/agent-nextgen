"""Test Azure Storage upload and download functionality."""

from src.storage import StorageManager
from src.logger import app_logger as logger

def test_upload_download():
    """Test file upload and download."""
    storage = StorageManager()
    
    if not storage.client:
        print("❌ Storage not configured")
        return
    
    print("🧪 Testing Azure Storage upload/download...\n")
    
    # Test data
    test_content = b"This is a test document for the NextGen Agent System"
    test_filename = "test_document.txt"
    test_student_id = "student_test123"
    
    # Test each container type
    for app_type in ['2026', 'test', 'training']:
        print(f"\n📦 Testing '{app_type}' container...")
        
        # Upload
        try:
            result = storage.upload_file(
                file_content=test_content,
                filename=test_filename,
                student_id=test_student_id,
                application_type=app_type
            )
            
            if result['success']:
                print(f"  ✅ Upload successful")
                print(f"     URL: {result.get('blob_url', 'N/A')[:70]}...")
            else:
                print(f"  ❌ Upload failed: {result.get('error')}")
                continue
        except Exception as e:
            print(f"  ❌ Upload error: {e}")
            continue
        
        # Download
        try:
            downloaded = storage.download_file(
                student_id=test_student_id,
                filename=test_filename,
                application_type=app_type
            )
            
            if downloaded:
                if downloaded == test_content:
                    print(f"  ✅ Download successful - content verified")
                else:
                    print(f"  ⚠️  Downloaded but content mismatch")
            else:
                print(f"  ❌ Download failed")
        except Exception as e:
            print(f"  ❌ Download error: {e}")
        
        # Cleanup
        try:
            storage.delete_student_files(test_student_id, app_type)
            print(f"  ✅ Cleanup successful")
        except Exception as e:
            print(f"  ⚠️  Cleanup error: {e}")
    
    print("\n" + "="*60)
    print("✅ Storage functionality test complete!")
    print("="*60)

if __name__ == "__main__":
    test_upload_download()
