"""Configuration management for Azure AI Foundry agents using Azure Key Vault."""

import os
from typing import Optional, Dict
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# Load environment variables from .env file (fallback for local development)
load_dotenv()


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
        
        # Determine Key Vault name
        self.key_vault_name = key_vault_name or os.getenv("AZURE_KEY_VAULT_NAME")
        
        # Initialize Key Vault client if name is provided
        if self.key_vault_name:
            try:
                credential = DefaultAzureCredential()
                vault_url = f"https://{self.key_vault_name}.vault.azure.net/"
                self._secret_client = SecretClient(vault_url=vault_url, credential=credential)
                print(f"✓ Connected to Azure Key Vault: {self.key_vault_name}")
            except Exception as e:
                print(f"⚠ Warning: Could not connect to Key Vault: {e}")
                print("  Falling back to environment variables from .env file")
                self._secret_client = None
        else:
            print("ℹ No Key Vault configured. Using environment variables from .env file")
        
        # Load configuration
        self.azure_openai_endpoint: str = self._get_secret("azure-openai-endpoint", "AZURE_OPENAI_ENDPOINT")
        self.deployment_name: str = self._get_secret("azure-deployment-name", "AZURE_DEPLOYMENT_NAME")
        self.api_version: str = self._get_secret("azure-api-version", "AZURE_API_VERSION") or "2024-12-01-preview"
        self.subscription_id: str = self._get_secret("azure-subscription-id", "AZURE_SUBSCRIPTION_ID")
        self.resource_group: str = self._get_secret("azure-resource-group", "AZURE_RESOURCE_GROUP")
        
        # SQL Database configuration
        self.sql_server: str = self._get_secret("sql-server", "SQL_SERVER")
        self.sql_database: str = self._get_secret("sql-database", "SQL_DATABASE")
        
        # Flask configuration
        self.flask_secret_key: str = self._get_secret("flask-secret-key", "FLASK_SECRET_KEY")
        
        # Legacy compatibility
        self.azure_openai_api_key: Optional[str] = None  # We use Azure AD instead
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
        if self._secret_client:
            try:
                secret = self._secret_client.get_secret(key_vault_secret_name)
                value = secret.value
                self._secrets_cache[key_vault_secret_name] = value
                return value
            except Exception as e:
                print(f"  Could not retrieve '{key_vault_secret_name}' from Key Vault: {e}")
        
        # Fall back to environment variable
        value = os.getenv(env_var_name)
        if value:
            self._secrets_cache[key_vault_secret_name] = value
        return value
    
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
        if not self.sql_server:
            missing.append("sql-server (Key Vault) or SQL_SERVER (env)")
        if not self.sql_database:
            missing.append("sql-database (Key Vault) or SQL_DATABASE (env)")
        
        return missing
    
    def get_config_summary(self) -> str:
        """Get a summary of configuration (without exposing sensitive values)."""
        return f"""
Configuration Summary:
  Source: {'Azure Key Vault (' + self.key_vault_name + ')' if self._secret_client else 'Environment Variables (.env)'}
  Azure OpenAI Endpoint: {self.azure_openai_endpoint[:30] + '...' if self.azure_openai_endpoint else 'Not set'}
  Deployment Name: {self.deployment_name or 'Not set'}
  API Version: {self.api_version}
  SQL Server: {self.sql_server[:30] + '...' if self.sql_server else 'Not set'}
  SQL Database: {self.sql_database or 'Not set'}
"""


# Global config instance - uses Key Vault by default
config = Config(key_vault_name="nextgen-agents-kv")

