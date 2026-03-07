"""Flask web application for application evaluation system.

This module creates the Flask app, registers blueprints, and holds routes
that have not yet been extracted into their own blueprint modules.
Shared state (csrf, limiter, agent factories, helpers) lives in extensions.py.

See also: routes/ directory for extracted blueprints.
"""

import os
import json
import secrets
import logging

from datetime import datetime, timedelta, timezone
from flask import Flask, flash, g, jsonify, render_template, redirect, url_for, request, session
from flask_wtf.csrf import CSRFError
from src.config import config
from src.telemetry import init_telemetry
from src.database import db

from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared extensions (created in extensions.py, initialised here)
# ---------------------------------------------------------------------------
from extensions import csrf, limiter

# Initialize Flask app
app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
if config.flask_secret_key:
    app.secret_key = config.flask_secret_key
elif os.getenv('FLASK_ENV') == 'production':
    raise RuntimeError("FLASK_SECRET_KEY must be configured in production (set in Key Vault)")
else:
    app.secret_key = os.urandom(32).hex()  # random per-start in dev only
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['UPLOAD_FOLDER'] = 'uploads'

# ---------------------------------------------------------------------------
# Session cookie hardening
# ---------------------------------------------------------------------------
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# ---------------------------------------------------------------------------
# CSRF & Rate Limiting — initialise extensions from extensions.py
# ---------------------------------------------------------------------------
csrf.init_app(app)
limiter.init_app(app)


# ---------------------------------------------------------------------------
# Session lifetime
# ---------------------------------------------------------------------------
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=config.auth_session_hours)


# ---------------------------------------------------------------------------
# Authentication - simple Key Vault-backed username / password
# ---------------------------------------------------------------------------
_AUTH_WHITELIST = {
    'auth.login',            # login page itself (blueprint-prefixed)
    'login',                 # login page itself (legacy endpoint)
    'static',                # CSS / JS / images
    'health_check',          # optional health probe endpoint
    'healthz',               # Azure Front Door health probe
}

# ---------------------------------------------------------------------------
# Role-based authorization
# ---------------------------------------------------------------------------
# Currently single-user (admin only).  When multi-user auth is added, assign
# roles during login and protect sensitive routes with @require_role().
VALID_ROLES = {'admin', 'reviewer', 'readonly'}


def require_role(*roles):
    """Decorator: restrict a route to users whose session role is in *roles*.

    Usage:
        @app.route('/admin/settings')
        @require_role('admin')
        def admin_settings(): ...
    """
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_role = session.get('role', 'readonly')
            if user_role not in roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Insufficient permissions'}), 403
                return '<h1>403 — Forbidden</h1>', 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def require_login():
    """Redirect unauthenticated requests to the login page."""
    # Generate a CSP nonce for this request
    g.csp_nonce = secrets.token_urlsafe(16)

    # ---------------------------------------------------------------
    # Front Door validation — reject requests that bypass the WAF.
    # The X-Azure-FDID header is set by Azure Front Door and cannot
    # be spoofed when App Service IP restrictions limit traffic to
    # the AzureFrontDoor.Backend service tag.
    # ---------------------------------------------------------------
    if config.azure_front_door_id:
        request_fdid = request.headers.get('X-Azure-FDID', '')
        if request_fdid != config.azure_front_door_id:
            # Allow Azure health probes (they use the same header but
            # we also accept requests to the healthz endpoint)
            if request.endpoint not in ('health_check', 'healthz'):
                return '<h1>403 — Forbidden</h1>', 403

    # Skip auth check if credentials are not configured
    if not config.auth_username or not config.auth_password_hash:
        if os.getenv('FLASK_ENV') == 'production':
            return jsonify({'error': 'Authentication not configured'}), 503
        return  # auth disabled in dev only

    # Allow whitelisted endpoints through
    if request.endpoint in _AUTH_WHITELIST:
        return

    # Check session
    if session.get('authenticated'):
        login_time = session.get('login_time')
        if login_time:
            elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(login_time)
            if elapsed < timedelta(hours=config.auth_session_hours):
                return  # session still valid
        # Session expired
        session.clear()

    # Not authenticated - redirect HTML requests, return 401 for API calls
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Authentication required'}), 401
    return redirect(url_for('auth.login', next=request.path))



# Login/logout routes moved to routes/auth.py (Issue #23)


@app.template_filter('nl2br')
def nl2br_filter(value):
    """Convert newlines to <br> tags after escaping HTML to prevent XSS.
    
    Unlike |replace('\\n','<br>')|safe, this filter escapes the value first,
    so any HTML/JS injected via student uploads is neutralised.
    Fixes: #36, #37
    """
    from markupsafe import Markup, escape
    if not value:
        return value
    return Markup(escape(str(value)).replace('\n', Markup('<br>')))


@app.context_processor
def inject_app_metadata():
    return {
        'app_version': config.app_version,
        'csp_nonce': getattr(g, 'csp_nonce', ''),
    }


@app.after_request
def add_security_headers(response):
    """Add security headers and prevent browser caching of HTML pages."""
    # -- Cache control for HTML pages --
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'

    # -- Security headers --
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = (
        'camera=(), microphone=(), geolocation=(), payment=()'
    )
    response.headers['Strict-Transport-Security'] = (
        'max-age=31536000; includeSubDomains'
    )
    # CSP — nonce-based policy (CSP Level 3).
    #   script-src:      nonce-based for all browsers; 'strict-dynamic' lets
    #                    nonce-approved scripts load additional scripts.
    #   script-src-elem: nonce-based — only <script> tags with the per-request
    #                    nonce (or same-origin src) are allowed.
    #   script-src-attr: 'none' — all inline handlers converted to data-action
    #                    delegated listeners (Issue #77, #91).
    nonce = getattr(g, 'csp_nonce', '')
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}' 'strict-dynamic' https://cdn.tailwindcss.com; "
        f"script-src-elem 'self' 'nonce-{nonce}' https://cdn.tailwindcss.com; "
        "script-src-attr 'none'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ---------------------------------------------------------------------------
# Custom error handlers — never leak framework details
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return '<h1>404 — Page Not Found</h1>', 404


@app.errorhandler(500)
def internal_server_error(e):
    logger.error("Unhandled 500 error: %s", e, exc_info=True)
    if request.path.startswith('/api/'):
        return jsonify({'error': f'Internal server error: {e}'}), 500
    return '<h1>500 — Internal Server Error</h1>', 500


@app.errorhandler(CSRFError)
def csrf_error(e):
    logger.warning("CSRF error on %s: %s", request.path, e.description)
    if request.path.startswith('/api/'):
        return jsonify({'error': f'CSRF validation failed: {e.description}'}), 400
    return '<h1>400 — CSRF Error</h1><p>Session expired. Please refresh the page.</p>', 400


@app.errorhandler(429)
def rate_limit_exceeded(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
    return '<h1>429 — Too Many Requests</h1><p>Please slow down and try again.</p>', 429


# Initialize telemetry FIRST so the TracerProvider is set before instrumentors run.
# When Azure Monitor is configured, configure_azure_monitor() auto-instruments
# Flask, requests, psycopg, and urllib — so manual instrumentors are a safe no-op.
init_telemetry(service_name=os.getenv("OTEL_SERVICE_NAME", "agent-framework"))

# Instrument Flask and outbound HTTP calls for App Insights.
# (When azure-monitor-opentelemetry is present these are already instrumented;
#  calling instrument_app again is harmless — OTel deduplicates.)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

# ---------------------------------------------------------------------------
# Register Blueprints (Issue #23)
# ---------------------------------------------------------------------------
from routes.auth import auth_bp
from routes.feedback import feedback_bp
from routes.telemetry import telemetry_bp
from routes.admin import admin_bp
from routes.upload import upload_bp
from routes.applications import applications_bp
from routes.training import training_bp
from routes.testing import testing_bp
from routes.schools import schools_bp

app.register_blueprint(auth_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(telemetry_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(applications_bp)
app.register_blueprint(training_bp)
app.register_blueprint(testing_bp)
app.register_blueprint(schools_bp)

# Start retention scheduler (moved from module-level to explicit call)
from routes.admin import start_retention_scheduler
start_retention_scheduler()

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
logger.info("Flask app initialized", extra={'upload_folder': app.config['UPLOAD_FOLDER']})

# Gaston cleanup migration removed (Issue #90) — data was cleaned in v1.0.x.
# Agent was removed from the workflow; no new gaston data is created.

# Agent factories, OCR callback, and processing helpers moved to extensions.py (Issue #23)

@app.route('/healthz')
def healthz():
    """Health check endpoint for Azure Front Door probes.
    Excluded from EasyAuth — returns 200 with no sensitive data."""
    version = "unknown"
    try:
        with open(os.path.join(os.path.dirname(__file__), 'VERSION')) as f:
            version = f.read().strip()
    except Exception:
        pass
    return jsonify({"status": "ok", "version": version}), 200


@app.route('/')
def index():
    """Home page - Dashboard."""
    # import here to guarantee availability even if globals fail
    from src.database import db
    from flask import flash
    try:
        applications_table = db.get_table_name("applications")
        training_col = db.get_training_example_column()
        test_col = db.get_test_data_column()
        app_id_col = db.get_applications_column("application_id")
        applicant_col = db.get_applications_column("applicant_name")
        email_col = db.get_applications_column("email")
        status_col = db.get_applications_column("status")
        uploaded_col = db.get_applications_column("uploaded_date")
        test_filter = ""
        if db.has_applications_column(test_col):
            test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

        # Simplified query to avoid timeout - just get basic count with a limit
        status_expr = f"LOWER(a.{status_col})"
        query = f"""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN {status_expr} = 'pending' THEN 1 ELSE 0 END) as pending,
                   SUM(CASE WHEN {status_expr} <> 'pending' THEN 1 ELSE 0 END) as evaluated
            FROM {applications_table} a
            WHERE a.{training_col} = FALSE{test_filter}
        """
        result = db.execute_query(query)
        
        if result and len(result) > 0:
            total_count = result[0].get('total', 0)
            pending_count = result[0].get('pending', 0)
            evaluated_count = result[0].get('evaluated', 0)
        else:
            total_count = pending_count = evaluated_count = 0
        
        # Get recent students with a simple query
        recent_query = f"""
            SELECT
                a.{app_id_col} as application_id,
                a.{applicant_col} as applicant_name,
                a.{email_col} as email,
                a.{status_col} as status,
                a.{uploaded_col} as uploaded_date
            FROM {applications_table} a
            WHERE a.{training_col} = FALSE{test_filter}
            ORDER BY a.{uploaded_col} DESC
            LIMIT 10
        """
        recent_results = db.execute_query(recent_query)
        
        # Format results
        recent_students = []
        for row in recent_results:
            parts = row.get('applicant_name', '').strip().split()
            recent_students.append({
                'application_id': row.get('application_id'),
                'first_name': parts[0] if len(parts) > 0 else '',
                'last_name': parts[-1] if len(parts) > 1 else '',
                'full_name': row.get('applicant_name'),
                'email': row.get('email'),
                'status': row.get('status'),
                'uploaded_date': row.get('uploaded_date')
            })
        
        return render_template('index.html', 
                             students=recent_students,
                             pending_count=pending_count,
                             evaluated_count=evaluated_count,
                             total_count=total_count,
                             app_version=config.app_version)
    except Exception as e:
        logger.error(f"Index page error: {e}", exc_info=True)
        logger.error('Error loading applications: %s', e, exc_info=True); flash('An error occurred while loading applications', 'error')
        return render_template('index.html', students=[], pending_count=0, evaluated_count=0, total_count=0)


@app.route('/health')
def health():
    """Health check endpoint for Azure App Service."""
    return jsonify({
        'status': 'healthy',
        'app': 'NextGen Agent System',
        'version': config.app_version
    }), 200


# Feedback routes moved to routes/feedback.py (Issue #23)


if __name__ == '__main__':
    # Debug mode requires explicit opt-in (never default to True)
    debug_mode = os.getenv('FLASK_DEBUG', '').lower() in ('1', 'true')
    port = int(os.getenv('PORT', 5002))  # Changed to 5002 to avoid port conflict
    print(f" * Starting Flask on port {port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
