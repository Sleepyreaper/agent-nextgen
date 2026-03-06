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
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if (username == config.auth_username and
                check_password_hash(config.auth_password_hash, password)):
            session.clear()
            session.permanent = True
            session['authenticated'] = True
            session['username'] = username
            session['role'] = 'admin'
            session['login_time'] = datetime.now(timezone.utc).isoformat()
            logger.info("User '%s' logged in successfully", username)
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
