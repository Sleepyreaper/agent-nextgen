"""Azure Storage utilities for managing student files."""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from azure.storage.blob import BlobServiceClient
from src.config import config


class StorageManager:
    """Manage file uploads to Azure Storage with organized folder structure."""
    
    def __init__(self):
        """Initialize Azure Storage connection."""
        self.account_name = config.storage_account_name
        self.account_key = config.storage_account_key
        self.container_name = config.storage_container_name
        
        # Initialize blob service client
        if self.account_key:
            self.client = BlobServiceClient(
                account_url=f"https://{self.account_name}.blob.core.windows.net",
                credential=self.account_key
            )
        else:
            self.client = None
    
    def generate_student_id(self) -> str:
        """Generate a unique student ID."""
        return f"student_{uuid.uuid4().hex[:12]}"
    
    def upload_file(self, file_content: bytes, filename: str, 
                   student_id: str, application_type: str = "2026") -> Dict[str, Any]:
        """
        Upload file to Azure Storage with organized folder structure.
        
        Folder structure:
        /{container}/{type}/{student_id}/{filename}
        
        Examples:
        - /student-uploads/2026/student_abc123def456/application.pdf
        - /student-uploads/training/student_xyz789uvw012/essay.docx
        - /student-uploads/test/student_mno345pqr678/form.txt
        
        Args:
            file_content: File contents as bytes
            filename: Original filename
            student_id: Unique student identifier
            application_type: "2026", "training", or "test"
            
        Returns:
            Dict with upload details (url, path, etc.)
        """
        if not self.client:
            return {
                'success': False,
                'error': 'Azure Storage not configured',
                'student_id': student_id
            }
        
        try:
            # Build blob path: type/student_id/filename
            blob_path = f"{application_type}/{student_id}/{filename}"
            
            # Get container client
            container_client = self.client.get_container_client(self.container_name)
            
            # Upload blob
            blob_client = container_client.upload_blob(
                name=blob_path,
                data=file_content,
                overwrite=True
            )
            
            # Build full URL
            blob_url = f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{blob_path}"
            
            return {
                'success': True,
                'student_id': student_id,
                'blob_path': blob_path,
                'blob_url': blob_url,
                'filename': filename,
                'application_type': application_type,
                'uploaded_at': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'student_id': student_id
            }
    
    def get_file_url(self, student_id: str, filename: str, 
                     application_type: str = "2026") -> Optional[str]:
        """Get the URL for a stored file."""
        if not self.client:
            return None
        
        blob_path = f"{application_type}/{student_id}/{filename}"
        return f"https://{self.account_name}.blob.core.windows.net/{self.container_name}/{blob_path}"
    
    def list_student_files(self, student_id: str, 
                          application_type: str = "2026") -> list:
        """List all files for a specific student."""
        if not self.client:
            return []
        
        try:
            container_client = self.client.get_container_client(self.container_name)
            prefix = f"{application_type}/{student_id}/"
            
            blobs = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]
            
        except Exception as e:
            print(f"Error listing files: {e}")
            return []


# Global storage manager instance
storage = StorageManager()
