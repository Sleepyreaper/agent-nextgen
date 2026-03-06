"""Feedback routes — user feedback submission, triage, GitHub issue creation."""

import json
import logging
import os
import time
import uuid

import requests as http_requests
from flask import Blueprint, flash, jsonify, render_template, request
from typing import Any, Dict, Optional

from extensions import get_feedback_agent, run_async
from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

feedback_bp = Blueprint('feedback', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_feedback_issue_body(
    triage: Dict[str, Any],
    feedback_type: str,
    message: str,
    email: Optional[str],
    page: Optional[str],
    user_agent: Optional[str],
    app_version: Optional[str]
) -> str:
    lines = [
        "## Summary", triage.get("summary") or message, "",
        "## Details",
        f"- Feedback type: {feedback_type}",
        f"- Category: {triage.get('category', 'other')}",
        f"- Priority: {triage.get('priority', 'medium')}", "",
        "## Steps to Reproduce", triage.get("steps_to_reproduce") or "Not provided.", "",
        "## Expected Behavior", triage.get("expected_behavior") or "Not provided.", "",
        "## Actual Behavior", triage.get("actual_behavior") or "Not provided.", "",
        "## User Context",
        f"- Email: {email or 'Not provided'}",
        f"- Page: {page or 'Unknown'}",
        f"- App version: {app_version or 'Unknown'}",
        f"- User agent: {user_agent or 'Unknown'}", "",
        "## Raw Feedback", message
    ]
    return "\n".join(lines)


def _store_feedback_fallback(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs("logs/feedback", exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"logs/feedback/feedback_{timestamp}_{uuid.uuid4().hex[:6]}.json"
        with open(filename, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)
    except Exception as exc:
        logger.error(f"Failed to store feedback fallback: {exc}", exc_info=True)


def _create_github_issue(title: str, body: str, labels: list) -> Dict[str, Any]:
    if not config.github_token:
        raise ValueError("Missing GitHub token for issue creation")
    url = f"https://api.github.com/repos/{config.github_repo}/issues"
    headers = {
        "Authorization": f"Bearer {config.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nextgen-feedback-bot"
    }
    payload = {"title": title, "body": body, "labels": labels}
    response = http_requests.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"GitHub issue creation failed: {response.status_code} {response.text}")
    return response.json()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@feedback_bp.route('/api/github/issues', methods=['GET'])
def github_issues_api():
    """Return open and recently closed GitHub issues for the feedback page."""
    if not config.github_token or not config.github_repo:
        return jsonify({'open': [], 'closed': []})

    headers = {
        "Authorization": f"Bearer {config.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "nextgen-feedback-bot"
    }
    base_url = f"https://api.github.com/repos/{config.github_repo}/issues"

    results = {'open': [], 'closed': []}
    try:
        for state in ('open', 'closed'):
            resp = http_requests.get(
                base_url,
                headers=headers,
                params={'state': state, 'per_page': 20, 'sort': 'updated', 'direction': 'desc'},
                timeout=10,
            )
            if resp.status_code == 200:
                for issue in resp.json():
                    if issue.get('pull_request'):
                        continue
                    results[state].append({
                        'number': issue['number'],
                        'title': issue['title'],
                        'state': issue['state'],
                        'html_url': issue['html_url'],
                        'created_at': issue['created_at'],
                        'updated_at': issue['updated_at'],
                        'labels': [l['name'] for l in issue.get('labels', [])],
                    })
    except Exception as e:
        logger.warning(f"GitHub issues fetch failed: {e}")

    return jsonify(results)


@feedback_bp.route('/feedback', methods=['GET', 'POST'])
def submit_feedback():
    """Capture user feedback (POST) or display the feedback page (GET)."""
    if request.method == 'GET':
        try:
            feedback_items = db.get_recent_user_feedback(limit=50) if db else []
        except Exception:
            feedback_items = []
        return render_template('feedback.html', feedback_items=feedback_items)

    data = request.get_json(silent=True) or {}
    feedback_type = (data.get('type') or '').strip().lower()
    message = (data.get('message') or '').strip()
    email = (data.get('email') or '').strip() or None
    page = (data.get('page') or '').strip() or request.referrer
    app_version = config.app_version
    user_agent = request.headers.get('User-Agent')

    if feedback_type not in {'issue', 'feature'}:
        return jsonify({'error': 'Feedback type must be issue or feature.'}), 400
    if not message:
        return jsonify({'error': 'Feedback message is required.'}), 400

    if config.github_token and not config.github_repo:
        logger.error("GitHub token provided but repository unset")
        return jsonify({'error': 'Feedback service misconfigured (missing GitHub repo).'}), 500

    feedback_id = None
    try:
        if db:
            feedback_id = db.save_user_feedback(
                feedback_type=feedback_type, message=message, email=email,
                page=page, app_version=app_version, user_agent=user_agent, status='received'
            )

        triage_agent = get_feedback_agent()
        triage = run_async(triage_agent.analyze_feedback(
            feedback_type=feedback_type, message=message, email=email,
            page=page, app_version=app_version
        ))
        if feedback_id and db:
            db.update_user_feedback(feedback_id=feedback_id, triage_json=triage, status='triaged')

        issue_body = _build_feedback_issue_body(
            triage=triage, feedback_type=feedback_type, message=message,
            email=email, page=page, user_agent=user_agent, app_version=app_version
        )
        labels = set(triage.get('suggested_labels', []))
        labels.update({'feedback', feedback_type})
        issue = None
        if config.github_token:
            issue = _create_github_issue(
                title=triage.get('title') or f"User feedback: {feedback_type}",
                body=issue_body, labels=sorted(labels)
            )
            if feedback_id and db:
                db.update_user_feedback(feedback_id=feedback_id, issue_url=issue.get('html_url'), status='submitted')
        else:
            if feedback_id and db:
                db.update_user_feedback(feedback_id=feedback_id, status='awaiting_github')
            _store_feedback_fallback({
                "feedback_id": feedback_id, "type": feedback_type, "message": message,
                "email": email, "page": page, "app_version": app_version,
                "user_agent": user_agent, "error": "GitHub token not configured"
            })
            return jsonify({'error': 'GitHub integration is not configured yet. Feedback saved locally.'}), 503

        return jsonify({'status': 'success', 'issue_url': issue.get('html_url')}), 201
    except Exception as exc:
        if db:
            try:
                if feedback_id:
                    db.update_user_feedback(feedback_id=feedback_id, status='error')
            except Exception:
                pass
        _store_feedback_fallback({
            "type": feedback_type, "message": message, "email": email,
            "page": page, "app_version": app_version, "user_agent": user_agent,
            "error": str(exc)
        })
        logger.error(f"Feedback submission failed: {exc}", exc_info=True)
        msg = str(exc)
        return jsonify({'error': 'Unable to submit feedback right now.', 'details': msg}), 500


@feedback_bp.route('/api/feedback/recent')
def feedback_recent_api():
    """JSON endpoint for dynamic feedback polling."""
    try:
        items = db.get_recent_user_feedback(limit=50) if db else []
        serialized = []
        for item in items:
            row = {}
            for k, v in item.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()
                elif k.lower() == 'triage_json' and isinstance(v, str):
                    try:
                        row[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        row[k] = {}
                    continue
                else:
                    row[k] = v
            serialized.append(row)
        return jsonify(serialized)
    except Exception as exc:
        logger.error(f"Feedback API error: {exc}", exc_info=True)
        return jsonify([]), 500


@feedback_bp.route('/feedback/admin')
def feedback_admin():
    """View recent feedback submissions."""
    try:
        feedback_items = db.get_recent_user_feedback(limit=100) if db else []
        return render_template('feedback_admin.html', feedback_items=feedback_items)
    except Exception as exc:
        logger.error(f"Feedback admin error: {exc}", exc_info=True)
        flash('Unable to load feedback right now.', 'error')
        return render_template('feedback_admin.html', feedback_items=[])
