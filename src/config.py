"""Configuration management for Azure AI Foundry agents using Azure Key Vault."""

import os
import sys
import logging
import signal
from typing import Optional, Dict
from dotenv import load_dotenv
from pathlib import Path

# Suppress Azure SDK warnings for local development
logging.getLogger('azure').setLevel(logging.ERROR)

# Timeout handler for Key Vault initialization
def _timeout_handler(signum, frame):
    raise TimeoutError("Key Vault initialization timeout")

# Load environment variables from .env file (fallback for local development)
# Try .env.local first for local dev, then .env
env_local = Path(".env.local")
if env_local.exists():
    load_dotenv(env_local)
else:
    load_dotenv()

# Import Azure SDK components after loading env (may fail gracefully)
try:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient
    AZURE_SDK_AVAILABLE = True
except ImportError:
    AZURE_SDK_AVAILABLE = False


class Config:
    """Configuration for Azure AI Foundry connection with Azure Key Vault integration."""
    
    def __init__(self, key_vault_name: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            key_vault_name: Name of the Azure Key Vault (without .vault.azure.net).
                           If None, will try to get from AZURE_KEY_VAULT_NAME env var.
                           If still None, falls back to .env file (local dev mode).
        """
        self._secrets_cache: Dict[str, str] = {}
        self._secret_client: Optional[SecretClient] = None
        self._key_vault_enabled = True
        self._key_vault_error_logged = False
        
        # Determine Key Vault name - skip if using local dev env file
        env_local_path = Path(".env.local")
        if env_local_path.exists() or os.getenv("AZURE_KEY_VAULT_DISABLED") == "1":
            # Local development mode - use environment variables only
            self.key_vault_name = None
            self._secret_client = None
            self._key_vault_enabled = False
        else:
            # Production/Staging mode - try Key Vault
            self.key_vault_name = key_vault_name or os.getenv("AZURE_KEY_VAULT_NAME")
            
            # Initialize Key Vault client if name is provided
            if self.key_vault_name and AZURE_SDK_AVAILABLE:
                try:
                    from azure.identity import DefaultAzureCredential
                    from azure.keyvault.secrets import SecretClient
                    
                    # Redirect stderr to suppress credential error output
                    old_stderr = sys.stderr
                    sys.stderr = open(os.devnull, 'w')
                    
                    # Set a timeout for Key Vault initialization (10 seconds max)
                    signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.alarm(10)
                    
                    try:
                        credential = DefaultAzureCredential()
                        vault_url = f"https://{self.key_vault_name}.vault.azure.net/"
                        self._secret_client = SecretClient(vault_url=vault_url, credential=credential)
                        signal.alarm(0)  # Cancel alarm
                        sys.stderr = old_stderr
                        # print(f"✓ Connected to Azure Key Vault: {self.key_vault_name}")
                    except TimeoutError:
                        signal.alarm(0)  # Cancel alarm
                        sys.stderr = old_stderr
                        self._secret_client = None
                        self._key_vault_enabled = False
                    finally:
                        sys.stderr = old_stderr
                except Exception as e:
                    # Silently fall back to env variables in local dev
                    self._secret_client = None
                    self._key_vault_enabled = False
            else:
                self._secret_client = None
                self._key_vault_enabled = False
        
        # Load configuration
        self.azure_openai_endpoint: str = self._get_secret("azure-openai-endpoint", "AZURE_OPENAI_ENDPOINT")
        self.deployment_name: str = self._get_secret("azure-deployment-name", "AZURE_DEPLOYMENT_NAME")
        self.api_version: str = self._get_secret("azure-api-version", "AZURE_API_VERSION") or "2024-12-01-preview"
        self.azure_openai_api_key: Optional[str] = self._get_secret("azure-openai-api-key", "AZURE_OPENAI_API_KEY")
        self.subscription_id: str = self._get_secret("azure-subscription-id", "AZURE_SUBSCRIPTION_ID")
        self.resource_group: str = self._get_secret("azure-resource-group", "AZURE_RESOURCE_GROUP")

        # Azure AI Foundry project dataset configuration
        self.foundry_project_endpoint: Optional[str] = self._get_secret(
            "foundry-project-endpoint",
            "FOUNDRY_PROJECT_ENDPOINT"
        )
        if not self.foundry_project_endpoint:
            self.foundry_project_endpoint = os.getenv("PROJECT_ENDPOINT")
        self.foundry_dataset_name: Optional[str] = self._get_secret(
            "foundry-dataset-name",
            "FOUNDRY_DATASET_NAME"
        )
        self.foundry_dataset_connection_name: Optional[str] = self._get_secret(
            "foundry-dataset-connection-name",
            "FOUNDRY_DATASET_CONNECTION_NAME"
        )
        
        # PostgreSQL Database configuration (primary - now using Azure PostgreSQL)
        self.postgres_url: str = self._get_secret("postgres-connection-string", "DATABASE_URL")
        if not self.postgres_url:
            # Backward-compatible secret name used in this vault
            self.postgres_url = self._get_secret("postgres-url", "DATABASE_URL")
        self.postgres_host: str = self._get_secret("postgres-host", "POSTGRES_HOST")
        self.postgres_port: str = self._get_secret("postgres-port", "POSTGRES_PORT") or "5432"
        self.postgres_database: str = self._get_secret("postgres-database", "POSTGRES_DB")
        self.postgres_username: str = self._get_secret("postgres-username", "POSTGRES_USER")
        self.postgres_password: str = self._get_secret("postgres-password", "POSTGRES_PASSWORD")
        
        # Legacy: Azure SQL Database configuration (deprecated - no longer used)
        self.sql_server: str = self._get_secret("sql-server", "SQL_SERVER")
        self.sql_database: str = self._get_secret("sql-database", "SQL_DATABASE")
        self.sql_username: str = self._get_secret("sql-username", "SQL_USERNAME")
        self.sql_password: str = self._get_secret("sql-password", "SQL_PASSWORD")
        
        # Azure Storage configuration
        self.storage_account_name: str = self._get_secret("storage-account-name", "AZURE_STORAGE_ACCOUNT_NAME") or "nextgendata2452"
        self.storage_account_key: str = self._get_secret("storage-account-key", "AZURE_STORAGE_ACCOUNT_KEY")
        self.storage_container_name: str = self._get_secret("storage-container-name", "AZURE_STORAGE_CONTAINER_NAME") or "student-uploads"

        # Content Processing Accelerator configuration
        self.content_processing_endpoint: str = self._get_secret(
            "content-processing-endpoint",
            "CONTENT_PROCESSING_ENDPOINT"
        )
        self.content_processing_api_key: str = self._get_secret(
            "content-processing-api-key",
            "CONTENT_PROCESSING_API_KEY"
        )
        self.content_processing_api_key_header: str = self._get_secret(
            "content-processing-api-key-header",
            "CONTENT_PROCESSING_API_KEY_HEADER"
        ) or "x-api-key"
        enabled_value = self._get_secret(
            "content-processing-enabled",
            "CONTENT_PROCESSING_ENABLED"
        )
        self.content_processing_enabled: bool = bool(
            self.content_processing_endpoint
            and (enabled_value or "true").lower() in {"1", "true", "yes"}
        )
        
        # Flask configuration
        self.flask_secret_key: str = self._get_secret("flask-secret-key", "FLASK_SECRET_KEY")

        # App metadata
        self.app_version: str = self._read_version_file() or os.getenv("APP_VERSION") or "0.1"

        # GitHub feedback tracking (Key Vault first, then env)
        self.github_repo: str = (
            self._get_secret("github-repo", "GITHUB_REPO")
            or "Sleepyreaper/agent-nextgen"
        )
        self.github_token: Optional[str] = (
            self._get_secret("github-token", "GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )
        
        # Legacy compatibility
        self.connection_string: Optional[str] = None
        self.project_name: Optional[str] = None
        self.region: str = "westus2"
    
    def _get_secret(self, key_vault_secret_name: str, env_var_name: str) -> Optional[str]:
        """
        Get a secret from Key Vault or fall back to environment variable.
        
        Args:
            key_vault_secret_name: Name of the secret in Key Vault (using hyphens)
            env_var_name: Name of the environment variable (using underscores)
        
        Returns:
            The secret value or None if not found
        """
        # Check cache first
        if key_vault_secret_name in self._secrets_cache:
            return self._secrets_cache[key_vault_secret_name]
        
        # Try Key Vault first
        if self._secret_client and self._key_vault_enabled:
            try:
                secret = self._secret_client.get_secret(key_vault_secret_name)
                value = secret.value
                self._secrets_cache[key_vault_secret_name] = value
                return value
            except Exception as e:
                # If the secret is missing, keep Key Vault enabled for other secrets.
                error_code = getattr(e, "error_code", "")
                is_not_found = error_code == "SecretNotFound" or "SecretNotFound" in str(e)
                if not is_not_found:
                    # Disable Key Vault after connection/auth failures to avoid repeated crashes/log spam.
                    self._key_vault_enabled = False
                    self._secret_client = None
                    if not self._key_vault_error_logged:
                        logging.warning(
                            "Key Vault access failed; falling back to environment variables.",
                            exc_info=True
                        )
                        self._key_vault_error_logged = True
        
        # Fall back to environment variable
        value = os.getenv(env_var_name)
        if value:
            self._secrets_cache[key_vault_secret_name] = value
        return value

    def _read_version_file(self) -> Optional[str]:
        try:
            version_path = Path("VERSION")
            if version_path.exists():
                return version_path.read_text(encoding="utf-8").strip()
            repo_root = Path(__file__).resolve().parents[1]
            repo_version = repo_root / "VERSION"
            if repo_version.exists():
                return repo_version.read_text(encoding="utf-8").strip()
        except Exception:
            return None
        return None
    
    def validate(self) -> bool:
        """Validate that required configuration is present."""
        return bool(self.azure_openai_endpoint and self.deployment_name)
    
    def get_missing_config(self) -> list[str]:
        """Return list of missing configuration items."""
        missing = []
        
        if not self.azure_openai_endpoint:
            missing.append("azure-openai-endpoint (Key Vault) or AZURE_OPENAI_ENDPOINT (env)")
        if not self.deployment_name:
            missing.append("azure-deployment-name (Key Vault) or AZURE_DEPLOYMENT_NAME (env)")
        
        # Check PostgreSQL Database configuration (primary)
        if not self.postgres_url and not self.postgres_host:
            missing.append("postgres-connection-string (Key Vault) or DATABASE_URL (env) OR postgres-host + credentials")
        if self.postgres_host and not self.postgres_database:
            missing.append("postgres-database (Key Vault) or POSTGRES_DB (env)")
        if self.postgres_host and not self.postgres_username:
            missing.append("postgres-username (Key Vault) or POSTGRES_USER (env)")
        if self.postgres_host and not self.postgres_password:
            missing.append("postgres-password (Key Vault) or POSTGRES_PASSWORD (env)")
        
        return missing
    
    def get(self, key: str, default: str = None) -> Optional[str]:
        """Get a configuration value by environment variable name (for backwards compatibility)."""
        return os.getenv(key, default)
    
    def get_config_summary(self) -> str:
        """Get a summary of configuration (without exposing sensitive values)."""
        return f"""Configuration Summary:
  Source: {'Azure Key Vault (' + self.key_vault_name + ')' if self._secret_client else 'Environment Variables (.env)'}
  Azure OpenAI Endpoint: {self.azure_openai_endpoint[:30] + '...' if self.azure_openai_endpoint else 'Not set'}
  Deployment Name: {self.deployment_name or 'Not set'}
  API Version: {self.api_version}
  Postgres Host: {self.postgres_host or 'Not set'}
  Postgres DB: {self.postgres_database or 'Not set'}
  Postgres URL: {'Set' if self.postgres_url else 'Not set'}
"""


# Global config instance - resolves Key Vault name from environment
config = Config()

