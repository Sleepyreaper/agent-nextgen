"""Authentication routes — login / logout."""

import logging
from datetime import datetime, timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from extensions import limiter
from src.config import config

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    """Login page and form handler."""
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        # Multi-user auth: check auth_users dict first
        authenticated = False
        role = 'reviewer'
        display_name = username

        if config.auth_users and username in config.auth_users:
            user_entry = config.auth_users[username]
            stored_hash = user_entry.get('password_hash', '')
            if stored_hash and check_password_hash(stored_hash, password):
                authenticated = True
                role = user_entry.get('role', 'reviewer')
                display_name = user_entry.get('display_name', username)

        # Fallback: single-user auth (backward compatible)
        if not authenticated and config.auth_username:
            if (username == config.auth_username.lower() and
                    check_password_hash(config.auth_password_hash, password)):
                authenticated = True
                role = 'admin'
                display_name = username

        if authenticated:
            session.clear()
            session.permanent = True
            session['authenticated'] = True
            session['username'] = username
            session['role'] = role
            session['display_name'] = display_name
            session['login_time'] = datetime.now(timezone.utc).isoformat()
            logger.info("User '%s' logged in (role=%s)", display_name, role)
            next_url = request.args.get('next') or url_for('index')
            if not next_url.startswith('/') or next_url.startswith('//'):
                next_url = url_for('index')
            return redirect(next_url)
        else:
            error = 'Invalid username or password.'
            logger.warning("Failed login attempt for user '%s'", username)

    return render_template('login.html', error=error, app_version=config.app_version)


@auth_bp.route('/logout')
def logout():
    """Clear the session and redirect to login."""
    username = session.get('username', 'unknown')
    session.clear()
    logger.info("User '%s' logged out", username)
    return redirect(url_for('auth.login'))
