"""Diagnostic endpoints for NextGen migration validation."""
from flask import Blueprint, jsonify

diag_bp = Blueprint('diag', __name__, url_prefix='/api/diag')


@diag_bp.route('/foundry')
def foundry():
    """Test Foundry/OpenAI connectivity."""
    try:
        from src.config import config
        return jsonify({
            'status': 'ok',
            'endpoint': config.foundry_project_endpoint or config.azure_openai_endpoint,
            'model': config.foundry_model_name or config.deployment_name,
            'provider': config.model_provider,
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@diag_bp.route('/postgres')
def postgres():
    """Test Postgres connectivity."""
    try:
        from src.database import db
        result = db.execute_query('SELECT NOW() as ts, current_database() as db_name')
        row = result[0] if result else {}
        return jsonify({
            'status': 'ok',
            'timestamp': str(row.get('ts', '')),
            'database': str(row.get('db_name', '')),
        }), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@diag_bp.route('/storage')
def storage():
    """Test Azure Blob Storage connectivity."""
    try:
        from src.config import config
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        account = config.storage_account_name
        client = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=DefaultAzureCredential()
        )
        containers = [c.name for c in client.list_containers(results_per_page=5)]
        return jsonify({'status': 'ok', 'account': account, 'containers': containers[:5]}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@diag_bp.route('/keyvault')
def keyvault():
    """Test Key Vault connectivity."""
    try:
        from src.config import config
        from azure.keyvault.secrets import SecretClient
        from azure.identity import DefaultAzureCredential
        vault_url = f"https://{config.key_vault_name}.vault.azure.net"
        client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
        # Just list secrets (don't read values)
        names = [s.name for s in client.list_properties_of_secrets(max_page_size=5)]
        return jsonify({'status': 'ok', 'vault': config.key_vault_name, 'secrets': names[:5]}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
