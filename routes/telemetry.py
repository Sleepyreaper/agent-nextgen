"""Telemetry & monitoring routes."""

import logging
import os

from flask import Blueprint, jsonify, render_template, request

from extensions import get_agent_monitor
from src.config import config
from src.telemetry import telemetry
from src.observability import is_observability_enabled, get_observability_status
from src.database import db

logger = logging.getLogger(__name__)

telemetry_bp = Blueprint('telemetry', __name__)


@telemetry_bp.route('/telemetry')
def telemetry_dashboard():
    """Telemetry and observability dashboard."""
    return render_template('telemetry_dashboard.html')


@telemetry_bp.route('/api/telemetry/overview')
def telemetry_overview():
    """Comprehensive telemetry overview for the dashboard."""
    try:
        from src.telemetry import NextGenTelemetry

        db_stats = NextGenTelemetry.query_db_overview_stats()
        agent_summary = NextGenTelemetry.query_db_agent_summary()
        recent_execs = NextGenTelemetry.query_db_recent_executions(limit=20)
        
        # If DB stats are empty, fall back to in-memory token usage
        # which accumulates during the current process lifetime
        if not db_stats or db_stats.get('total_calls', 0) == 0:
            in_mem = telemetry.get_token_usage()
            totals = in_mem.get('totals', {})
            if totals.get('call_count', 0) > 0:
                db_stats = {
                    'total_calls': totals.get('call_count', 0),
                    'total_errors': 0,  # in-memory doesn't track errors separately
                    'avg_duration_ms': 0,
                }
                logger.info("Telemetry: using in-memory stats (DB empty), %d calls tracked", totals.get('call_count', 0))

        monitor = get_agent_monitor()
        live_status = monitor.get_status()

        school_stats = {}
        try:
            rows = db.execute_query(
                "SELECT analysis_status, COUNT(*) as cnt FROM school_enriched_data WHERE is_active = TRUE GROUP BY analysis_status"
            )
        except Exception:
            rows = []
        for r in (rows or []):
            school_stats[r.get('analysis_status') or 'null'] = r.get('cnt', 0)

        moana_stats = {}
        try:
            moana_rows = db.execute_query(
                "SELECT moana_requirements_met, COUNT(*) as cnt FROM school_enriched_data WHERE is_active = TRUE GROUP BY moana_requirements_met"
            )
            for r in (moana_rows or []):
                key = 'validated' if r.get('moana_requirements_met') else ('not_validated' if r.get('moana_requirements_met') is False else 'pending')
                moana_stats[key] = r.get('cnt', 0)
        except Exception:
            pass

        obs_status = get_observability_status()

        from datetime import datetime as _dt_now
        token_usage = telemetry.get_token_usage()
        
        # Build agent summary from in-memory data if DB is empty
        if not agent_summary and token_usage.get('by_agent'):
            for agent_name, stats in token_usage['by_agent'].items():
                agent_summary[agent_name] = {
                    'total': stats.get('call_count', 0),
                    'success': stats.get('call_count', 0),
                    'failed': 0,
                    'avg_duration_ms': 0,
                    'success_rate': 100.0,
                    'total_tokens': stats.get('total_tokens', 0),
                    'models_used': [],
                }
        
        # Build recent executions from in-memory if DB is empty
        if not recent_execs and token_usage.get('recent_calls'):
            recent_execs = token_usage['recent_calls'][-20:]
        return jsonify({
            'status': 'success',
            'timestamp': _dt_now.utcnow().isoformat(),
            'observability': obs_status,
            'agent_monitor': {
                'total_calls': db_stats.get('total_calls', 0),
                'total_errors': db_stats.get('total_errors', 0),
                'currently_running': live_status.get('running_count', 0),
                'avg_duration_ms': round(db_stats.get('avg_duration_ms', 0), 1),
            },
            'agents': agent_summary,
            'token_usage': token_usage.get('totals', {}),
            'token_usage_by_model': token_usage.get('by_model', {}),
            'school_enrichment': {
                'by_status': school_stats,
                'moana_validation': moana_stats,
                'total': sum(school_stats.values()),
            },
            'recent_executions': recent_execs,
        })
    except Exception as e:
        logger.error(f"Telemetry overview error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@telemetry_bp.route('/api/telemetry/token-usage')
def telemetry_token_usage():
    """Detailed token usage breakdown by model and agent."""
    try:
        usage = telemetry.get_token_usage()
        return jsonify({'status': 'success', **usage})
    except Exception as e:
        logger.error(f"Token usage endpoint error: {e}", exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@telemetry_bp.route('/api/telemetry/token-usage/reset', methods=['POST'])
def telemetry_token_usage_reset():
    """Reset accumulated token usage counters."""
    try:
        telemetry.reset_token_usage()
        return jsonify({'status': 'success', 'message': 'Token usage counters reset'})
    except Exception as e:
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@telemetry_bp.route('/debug/agents')
def debug_agents():
    """Real-time agent monitoring dashboard."""
    if os.getenv('WEBSITE_SITE_NAME'):
        return '<h1>404 — Page Not Found</h1>', 404
    return render_template('agent_monitor.html')


@telemetry_bp.route('/api/debug/agent-status')
def get_agent_status():
    """Get current agent execution status."""
    if os.getenv('WEBSITE_SITE_NAME'):
        return jsonify({'error': 'Not found'}), 404
    monitor = get_agent_monitor()
    return jsonify(monitor.get_status())


@telemetry_bp.route('/api/debug/agent-status/clear', methods=['POST'])
def clear_agent_history():
    """Clear agent execution history."""
    if os.getenv('WEBSITE_SITE_NAME'):
        return jsonify({'error': 'Not found'}), 404
    monitor = get_agent_monitor()
    monitor.clear_history()
    return jsonify({'status': 'success', 'message': 'History cleared'})


@telemetry_bp.route('/api/debug/agent/<agent_name>/history')
def get_agent_history(agent_name):
    """Get execution history for a specific agent."""
    if os.getenv('WEBSITE_SITE_NAME'):
        return jsonify({'error': 'Not found'}), 404
    monitor = get_agent_monitor()
    limit = request.args.get('limit', 20, type=int)
    history = monitor.get_agent_history(agent_name, limit=limit)
    return jsonify({'agent_name': agent_name, 'executions': history})


@telemetry_bp.route('/api/telemetry/status')
def get_telemetry_status():
    """Report whether observability is configured."""
    try:
        telemetry_enabled = is_observability_enabled()
        observability_status = get_observability_status()
        return jsonify({
            'telemetry_enabled': telemetry_enabled,
            'app_insights_configured': observability_status.get('connection_string_set'),
            'observability': {
                'configured': observability_status.get('configured'),
                'azure_monitor_available': observability_status.get('azure_monitor_available'),
                'azure_monitor_version': observability_status.get('azure_monitor_version'),
                'last_error': observability_status.get('last_error'),
            }
        })
    except Exception as e:
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500


@telemetry_bp.route('/api/debug/telemetry-status')
def get_telemetry_status_debug():
    """Report detailed observability config — debug only."""
    if os.getenv('WEBSITE_SITE_NAME'):
        return jsonify({'error': 'Not found'}), 404
    try:
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        telemetry_enabled = is_observability_enabled()
        observability_status = get_observability_status()

        endpoint = getattr(config, 'azure_openai_endpoint', '') or ''
        endpoint_hint = endpoint.replace('https://', '').split('/')[0] if endpoint else None

        return jsonify({
            'telemetry_enabled': telemetry_enabled,
            'app_insights_configured': observability_status.get('connection_string_set'),
            'otlp_endpoint_configured': bool(otlp_endpoint),
            'otlp_endpoint': otlp_endpoint if otlp_endpoint else None,
            'observability': observability_status,
            'ai_config': {
                'deployment_name': getattr(config, 'deployment_name', None),
                'deployment_name_mini': getattr(config, 'deployment_name_mini', None),
                'api_version': getattr(config, 'api_version', None),
                'api_version_mini': getattr(config, 'api_version_mini', None),
                'endpoint_host': endpoint_hint,
                'model_tiers': {
                    'premium': getattr(config, 'model_tier_premium', None),
                    'merlin': getattr(config, 'model_tier_merlin', None),
                    'workhorse': getattr(config, 'model_tier_workhorse', None),
                    'lightweight': getattr(config, 'model_tier_lightweight', None),
                    'vision': getattr(config, 'foundry_vision_model_name', None),
                }
            }
        })
    except Exception as e:
        logger.error('Request failed: %s', e, exc_info=True)
        return jsonify({'status': 'error', 'error': 'An internal error occurred'}), 500
