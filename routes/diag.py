"""Diagnostic endpoints for NextGen migration validation."""
import time
import asyncio
import threading
from flask import Blueprint, jsonify, request

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


@diag_bp.route('/recent-apps')
def recent_apps():
    """Show the 5 most recently uploaded applications."""
    try:
        from src.database import db
        rows = db.execute_query(
            "SELECT * FROM applications ORDER BY application_id DESC LIMIT 3"
        )
        # Return just the key fields, safely
        apps = []
        for r in (rows or []):
            apps.append({k: str(v)[:100] if v is not None else None for k, v in r.items() if k in ('application_id', 'applicant_name', 'status', 'is_test_data', 'is_training_example', 'file_name', 'email')})
        return jsonify({'status': 'ok', 'apps': apps, 'columns': list((rows[0] or {}).keys()) if rows else []}), 200
        return jsonify({'status': 'ok', 'apps': rows or []}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@diag_bp.route('/agent-test')
def agent_test():
    """Quick smoke test: call each agent model to verify connectivity.
    
    Optional query params:
      ?agent=belle      — test one agent
      ?agent=all        — test all agents (default)
      ?prompt=hello     — custom test prompt
    """
    from src.config import config
    from extensions import get_ai_client

    target = request.args.get('agent', 'all').lower()
    test_prompt = request.args.get('prompt', 'Respond with exactly: {"status":"ok","agent":"YOUR_NAME"}')

    # Map agent names to their model tier
    agent_models = {
        'smee': ('gpt-5.4', config.model_tier_orchestrator),
        'belle': ('gpt-5.4-mini', config.model_tier_fast),
        'tiana': ('gpt-5.4', config.model_tier_workhorse),
        'rapunzel': ('gpt-5.4-pro', config.model_tier_premium),
        'mulan': ('gpt-5.4', config.model_tier_workhorse),
        'merlin': ('o3', config.model_tier_merlin),
        'gaston': ('o4-mini', config.model_tier_reasoning),
        'aurora': ('gpt-5.4-nano', config.model_tier_lightweight),
        'moana': ('gpt-5.4-mini', config.model_tier_fast),
        'naveen': ('gpt-5.4-nano', config.model_tier_lightweight),
        'pocahontas': ('gpt-5.4', config.model_tier_workhorse),
        'milo': ('gpt-5.4-pro', config.model_tier_premium),
        'bashful': ('gpt-5.4-nano', config.model_tier_lightweight),
        'mirabel': ('gpt-5.4', getattr(config, 'foundry_vision_model_name', 'gpt-5.4')),
    }

    if target != 'all':
        if target not in agent_models:
            return jsonify({'error': f'Unknown agent: {target}', 'available': list(agent_models.keys())}), 400
        agent_models = {target: agent_models[target]}

    results = {}
    client = get_ai_client()

    for agent_name, (expected_model, actual_model) in agent_models.items():
        start = time.time()
        try:
            # Skip o3/o4-mini for basic smoke test (reasoning models don't do simple prompts well)
            if actual_model.startswith('o3') or actual_model.startswith('o4'):
                resp = client.chat.completions.create(
                    model=actual_model,
                    messages=[{"role": "user", "content": f"You are {agent_name}. Say OK."}],
                    max_completion_tokens=50,
                )
            else:
                resp = client.chat.completions.create(
                    model=actual_model,
                    messages=[
                        {"role": "system", "content": f"You are {agent_name}. {test_prompt}"},
                        {"role": "user", "content": "Test"}
                    ],
                    max_tokens=100,
                    temperature=0,
                )
            elapsed = round(time.time() - start, 2)
            content = resp.choices[0].message.content[:200] if resp.choices else 'no response'
            results[agent_name] = {
                'status': 'ok',
                'model': actual_model,
                'response_preview': content,
                'elapsed_seconds': elapsed,
                'tokens': getattr(resp.usage, 'total_tokens', None),
            }
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            results[agent_name] = {
                'status': 'error',
                'model': actual_model,
                'error': str(e)[:200],
                'elapsed_seconds': elapsed,
            }

    ok_count = sum(1 for r in results.values() if r['status'] == 'ok')
    return jsonify({
        'summary': f'{ok_count}/{len(results)} agents responding',
        'results': results,
    })
