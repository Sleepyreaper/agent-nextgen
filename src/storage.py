"""Azure Storage utilities for managing student files."""

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import logging
from src.config import config

logger = logging.getLogger(__name__)


class StorageManager:
    """Manage file uploads to Azure Storage with organized folder structure."""
    
    # Base container names for different application types.
    # A prefix (e.g. "staging-") is prepended at runtime via config so
    # staging and production use fully isolated containers.
    _BASE_CONTAINERS = {
        '2026': 'applications-2026',
        'test': 'applications-test',
        'training': 'applications-training'
    }
    
    def __init__(self):
        """Initialize Azure Storage connection using Azure AD authentication.
        
        Note: Key-based authentication is disabled on the storage account.
        Uses Entra ID (Azure AD) via DefaultAzureCredential.
        """
        self.account_name = getattr(config, 'storage_account_name', None)
        self._prefix = getattr(config, 'storage_container_prefix', '') or ''
        # Build the actual container map: prefix + base name
        self.CONTAINERS = {
            k: f"{self._prefix}{v}" for k, v in self._BASE_CONTAINERS.items()
        }
        if self._prefix:
            logger.info("📦 Storage container prefix: '%s' → %s", self._prefix, list(self.CONTAINERS.values()))
        
        # Initialize blob service client
        if self.account_name:
            try:
                from azure.storage.blob import BlobServiceClient
                from azure.identity import DefaultAzureCredential
                from azure.core.exceptions import ClientAuthenticationError, AzureError
                
                # Use Azure AD (Entra ID) authentication exclusively
                # Storage account has "Shared Key access not permitted" enabled
                credential = DefaultAzureCredential()
                self.client = BlobServiceClient(
                    account_url=f"https://{self.account_name}.blob.core.windows.net",
                    credential=credential
                )
                logger.info("✅ Azure Storage client created, verifying access...")
                # perform a quick check to catch RBAC/permission issues early
                try:
                    # Try to get properties of our primary container instead of
                    # listing all containers — this succeeds with Storage Blob
                    # Data Contributor role (no account-level list permission needed)
                    primary = self.CONTAINERS.get('documents', 'student-documents')
                    if self._prefix:
                        primary = f"{self._prefix}{primary}"
                    self.client.get_container_client(primary).get_container_properties()
                    logger.info("✅ Azure Storage access verified (container: %s)", primary)
                except Exception:
                    # Container may not exist yet — that's fine, _ensure_containers will create it
                    logger.info("ℹ Primary container not found yet, will create during init")
                
                # Ensure containers exist
                self._ensure_containers()
            except Exception as e:
                logger.warning(f"⚠ Warning: Could not initialize Azure Storage: {e}")
                logger.info("  Falling back to local file storage for uploads")
                self.client = None
        else:
            logger.info("ℹ Azure Storage not configured (storage_account_name blank). Using local file storage.")
            self.client = None
    
    def _ensure_containers(self):
        """Ensure all required containers exist."""
        if not self.client:
            return
        
        for container_name in self.CONTAINERS.values():
            try:
                container_client = self.client.get_container_client(container_name)
                if not container_client.exists():
                    container_client.create_container()
                    logger.info(f"Created container: {container_name}")
            except Exception as e:
                logger.debug(f"Container {container_name} setup: {e}")
    
    def generate_student_id(self) -> str:
        """Generate a unique student ID."""
        return f"student_{uuid.uuid4().hex[:12]}"
    
    def _get_container_name(self, application_type: str) -> str:
        """Get the appropriate container name for the application type."""
        return self.CONTAINERS.get(application_type, self.CONTAINERS['2026'])
    
    def upload_file(self, file_content: bytes, filename: str, 
                   student_id: str, application_type: str = "2026") -> Dict[str, Any]:
        """
        Upload file to Azure Storage with organized folder structure.
        
        Folder structure:
        /applications-{type}/{student_id}/{filename}
        
        Examples:
        - /applications-2026/student_abc123def456/application.pdf
        - /applications-training/student_xyz789uvw012/essay.docx
        - /applications-test/student_mno345pqr678/form.txt
        
        Args:
            file_content: File contents as bytes
            filename: Original filename
            student_id: Unique student identifier
            application_type: "2026", "training", or "test"
            
        Returns:
            Dict with upload details (url, path, etc.)
        """
        if not self.client:
            logger.warning("Azure Storage not available, skipping upload")
            return {
                'success': False,
                'error': 'Azure Storage not configured',
                'student_id': student_id
            }
        
        try:
            container_name = self._get_container_name(application_type)
            # Build blob path: student_id/filename
            blob_path = f"{student_id}/{filename}"
            
            # Get container client
            container_client = self.client.get_container_client(container_name)
            
            # Infer content type from filename extension
            import mimetypes
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            from azure.storage.blob import ContentSettings
            blob_content_settings = ContentSettings(content_type=content_type)
            
            # Upload blob with content type
            try:
                blob_client = container_client.upload_blob(
                    name=blob_path,
                    data=file_content,
                    overwrite=True,
                    content_settings=blob_content_settings
                )
            except Exception as upload_err:
                # capture authorization failures specifically
                logger.error(f"Azure Storage upload failed: {upload_err}")
                raise
            
            # Build full URL
            blob_url = f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_path}"
            
            logger.info(f"Uploaded {filename} to {container_name}/{blob_path}")
            
            return {
                'success': True,
                'student_id': student_id,
                'blob_path': blob_path,
                'blob_url': blob_url,
                'container': container_name,
                'filename': filename,
                'application_type': application_type,
                'uploaded_at': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            # Log auth failures but do NOT permanently disable the client —
            # the credential may recover (e.g. token refresh, transient 403).
            if hasattr(e, 'status_code') and e.status_code in (403, 401):
                logger.warning("Azure Storage authorization failure (status %s) — will retry on next request", e.status_code)
            return {
                'success': False,
                'error': str(e),
                'student_id': student_id
            }
    
    def download_file(self, student_id: str, filename: str, 
                     application_type: str = "2026") -> Optional[bytes]:
        """
        Download file from Azure Storage.
        
        Args:
            student_id: Unique student identifier
            filename: Name of the file to download
            application_type: "2026", "training", or "test"
            
        Returns:
            File content as bytes, or None if not found
        """
        if not self.client:
            return None
        
        try:
            container_name = self._get_container_name(application_type)
            blob_path = f"{student_id}/{filename}"
            
            container_client = self.client.get_container_client(container_name)
            blob_client = container_client.get_blob_client(blob_path)
            
            # Download the blob
            downloader = blob_client.download_blob()
            return downloader.readall()
            
        except Exception as e:
            logger.error(f"Error downloading file {filename}: {e}")
            return None
    
    def get_file_url(self, student_id: str, filename: str, 
                     application_type: str = "2026") -> Optional[str]:
        """Get the URL for a stored file."""
        if not self.client:
            return None
        
        container_name = self._get_container_name(application_type)
        blob_path = f"{student_id}/{filename}"
        return f"https://{self.account_name}.blob.core.windows.net/{container_name}/{blob_path}"
    
    def list_student_files(self, student_id: str, 
                          application_type: str = "2026") -> list:
        """List all files for a specific student."""
        if not self.client:
            return []
        
        try:
            container_name = self._get_container_name(application_type)
            container_client = self.client.get_container_client(container_name)
            prefix = f"{student_id}/"
            
            blobs = container_client.list_blobs(name_starts_with=prefix)
            return [blob.name for blob in blobs]
            
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return []
    
    def delete_student_files(self, student_id: str, 
                            application_type: str = "2026") -> bool:
        """Delete all files for a specific student."""
        if not self.client:
            return False
        
        try:
            container_name = self._get_container_name(application_type)
            container_client = self.client.get_container_client(container_name)
            prefix = f"{student_id}/"
            
            blobs = container_client.list_blobs(name_starts_with=prefix)
            for blob in blobs:
                container_client.delete_blob(blob.name)
                logger.info(f"Deleted {blob.name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting files: {e}")
            return False


# Global storage manager instance
storage = StorageManager()
