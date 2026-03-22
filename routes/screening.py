"""Screening routes — fast Merlin-only evaluation for bulk processing.

Phase 1: One o3 call per student. Reads everything, makes the decision.
Phase 2 (deep dive): Full multi-agent pipeline for top candidates only.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from extensions import csrf, get_ai_client
from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

screening_bp = Blueprint('screening', __name__)

# ---------------------------------------------------------------------------
# Screening state (in-memory + DB persistence)
# ---------------------------------------------------------------------------
_screening_state: Dict[str, Any] = {
    'status': 'idle',  # idle | running | completed
    'started_at': None,
    'completed_at': None,
    'total': 0,
    'processed': 0,
    'results': [],  # list of {application_id, name, score, recommendation, ...}
    'errors': [],
}
_screening_lock = threading.Lock()

# Merlin screening prompt — everything in one pass
MERLIN_SCREEN_PROMPT = """You are Merlin, the Synthesis Evaluator for the Emory NextGen High School Internship Program.

You are running on o3 (reasoning model). Use extended reasoning to think deeply about this student.

MISSION: Find the Diamond in the Rough — the student whose contextual potential exceeds their raw metrics.

You will receive the COMPLETE raw text extracted from a student's application PDF. This may include:
- Application form fields (personal info, activities, goals)
- Essay or personal statement (may be labeled "essay/video" — if text is present, it IS the essay)
- Academic transcript (courses, grades, GPA)
- Recommendation letter(s)
- Any other supporting documents

REASONING PROCESS:
1. Read ALL the text. Identify what sections are present and what's missing.
2. Extract key facts: name, school, GPA, courses, activities, essay themes, recommendation highlights.
3. Answer the five fairness questions:
   a. Is this student performing near the CEILING of what their school offers?
   b. Would I penalize this student for something their school couldn't provide?
   c. What would this student accomplish with MORE opportunity?
   d. Are recommendation letters generic because teachers are overloaded?
   e. Does the essay lack polish because of limited access to editing help?
4. Make your decision. Own it.

ELIGIBILITY:
- Rising junior or senior in high school
- Must be 16 by June 1, 2026
- Must demonstrate interest in advancing STEM education to underrepresented groups

Return JSON:
{
  "student_name": "",
  "school": "",
  "overall_score": 0-100,
  "recommendation": "STRONG ADMIT|ADMIT|WAITLIST|DECLINE",
  "confidence": "high|medium|low",
  "nextgen_match": 0-100,
  "key_strengths": ["Top 3 with specific evidence from the application"],
  "key_risks": ["Top 3 concerns or missing information"],
  "rationale": "3-5 sentences. Be decisive. This is what the committee reads.",
  "diamond_assessment": {
    "diamond_score": 0-10,
    "diamond_label": "Undiscovered Gem|High Potential|Solid Candidate|Standard Applicant",
    "what_committee_might_miss": "The single most important insight"
  },
  "committee_card": {
    "headline": "One-line summary (e.g., 'First-gen scientist maxing out a rural school')",
    "three_word": "e.g., 'Authentic STEM Explorer'",
    "strongest_evidence": "Single most compelling evidence for admission",
    "biggest_question": "One thing committee should discuss"
  },
  "sections_found": ["essay", "transcript", "recommendation", ...],
  "sections_missing": ["list what's absent or unreadable"],
  "eligibility": {
    "quick_pass": true,
    "age_eligible": "true|false|unknown",
    "stem_interest": "true|false|unknown"
  },
  "needs_deep_dive": true
}

SCORING: 90-100 Exceptional | 80-89 Strong Admit | 70-79 Competitive | 60-69 Borderline | <60 Below threshold
If data is thin, score what you CAN see and note gaps honestly. Never hallucinate.
BE DECISIVE. WAITLIST is not a safe harbor."""


def _screen_one(application_id: int, client, model: str) -> Dict[str, Any]:
    """Screen a single application with one Merlin o3 call."""
    start = time.time()

    application = db.get_application(application_id)
    if not application:
        return {'application_id': application_id, 'status': 'error', 'error': 'Not found'}

    # Gather ALL text
    text_parts = []
    for field in ('application_text', 'transcript_text', 'recommendation_text'):
        val = application.get(field) or ''
        if val and len(val.strip()) > 20:
            text_parts.append(f"=== {field.upper()} ===\n{val}")

    if not text_parts:
        # Fallback: use whatever text exists
        for key in ('applicationtext', 'ApplicationText', 'transcripttext', 'recommendationtext'):
            val = application.get(key) or ''
            if val and len(val.strip()) > 20:
                text_parts.append(val)

    full_text = '\n\n'.join(text_parts)
    if len(full_text.strip()) < 50:
        return {
            'application_id': application_id,
            'applicant_name': application.get('applicant_name', 'Unknown'),
            'status': 'error',
            'error': 'Insufficient text content',
            'text_length': len(full_text),
        }

    # Truncate to ~30K chars to stay within token limits
    if len(full_text) > 30000:
        full_text = full_text[:30000] + '\n\n[TRUNCATED — document exceeds 30K chars]'

    applicant_name = application.get('applicant_name') or application.get('applicantname') or 'Unknown'

    try:
        # One o3 call — the whole evaluation
        if model.startswith('o3') or model.startswith('o4'):
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": f"{MERLIN_SCREEN_PROMPT}\n\n=== STUDENT APPLICATION ===\n\n{full_text}"}
                ],
                max_completion_tokens=4000,
                response_format={"type": "json_object"},
            )
        else:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": MERLIN_SCREEN_PROMPT},
                    {"role": "user", "content": f"=== STUDENT APPLICATION ===\n\n{full_text}"}
                ],
                max_tokens=4000,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

        content = response.choices[0].message.content if response.choices else ''
        elapsed = round(time.time() - start, 1)
        tokens = getattr(response.usage, 'total_tokens', None)

        # Parse the JSON result
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            result = {'raw_response': content[:500], 'parse_error': True}

        result['application_id'] = application_id
        result['applicant_name'] = applicant_name
        result['status'] = 'completed'
        result['elapsed_seconds'] = elapsed
        result['tokens_used'] = tokens
        result['model'] = model
        result['text_length'] = len(full_text)

        # Persist screening result to DB
        try:
            screening_data = {
                'screening_score': result.get('overall_score'),
                'screening_recommendation': result.get('recommendation'),
                'screening_result': json.dumps(result),
            }
            db.update_application_fields(application_id, screening_data)
        except Exception:
            pass

        return result

    except Exception as e:
        elapsed = round(time.time() - start, 1)
        return {
            'application_id': application_id,
            'applicant_name': applicant_name,
            'status': 'error',
            'error': str(e)[:200],
            'elapsed_seconds': elapsed,
        }


def _run_screening(app_ids: List[int], model: str, max_concurrent: int = 4):
    """Run bulk screening in background thread."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = get_ai_client()

    with _screening_lock:
        _screening_state['status'] = 'running'
        _screening_state['started_at'] = datetime.now(timezone.utc).isoformat()
        _screening_state['total'] = len(app_ids)
        _screening_state['processed'] = 0
        _screening_state['results'] = []
        _screening_state['errors'] = []

    def _process_one(app_id):
        result = _screen_one(app_id, client, model)
        with _screening_lock:
            _screening_state['processed'] += 1
            if result.get('status') == 'completed':
                _screening_state['results'].append(result)
            else:
                _screening_state['errors'].append(result)
        return result

    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        futures = {pool.submit(_process_one, aid): aid for aid in app_ids}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error("Screening thread error: %s", e)

    with _screening_lock:
        _screening_state['status'] = 'completed'
        _screening_state['completed_at'] = datetime.now(timezone.utc).isoformat()

    logger.info("Screening complete: %d/%d processed, %d errors",
                _screening_state['processed'], _screening_state['total'],
                len(_screening_state['errors']))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@screening_bp.route('/screening')
def screening_dashboard():
    """Screening dashboard page."""
    if not session.get('authenticated'):
        return redirect(url_for('auth.login'))
    return render_template('screening.html')


@screening_bp.route('/api/screening/start', methods=['POST'])
@csrf.exempt
def start_screening():
    """Start bulk screening.
    
    Body: {"application_ids": [...]} or {"status_filter": "Uploaded"} or {} for all unscreened.
    Optional: {"model": "o3"} to override model.
    """
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401

    with _screening_lock:
        if _screening_state['status'] == 'running':
            return jsonify({'error': 'Screening already running', 'state': _screening_state}), 409

    data = request.get_json() or {}
    model = data.get('model', config.model_tier_merlin)  # Default: o3
    max_concurrent = min(int(data.get('concurrent', 4)), 8)

    app_ids = data.get('application_ids', [])

    if not app_ids:
        status_filter = data.get('status_filter', '')
        try:
            all_apps = db.get_all_applications()
            for a in (all_apps or []):
                aid = a.get('application_id') or a.get('applicationid')
                # Skip already-screened apps (have screening_score) unless forced
                if a.get('screening_score') and not data.get('force'):
                    continue
                if status_filter:
                    if (a.get('status') or '').lower() != status_filter.lower():
                        continue
                app_ids.append(int(aid))
        except Exception as e:
            return jsonify({'error': f'Failed to query apps: {e}'}), 500

    if not app_ids:
        return jsonify({'error': 'No applications to screen'}), 400

    # Launch background screening
    threading.Thread(
        target=_run_screening,
        args=(app_ids, model, max_concurrent),
        daemon=True
    ).start()

    return jsonify({
        'launched': len(app_ids),
        'model': model,
        'concurrent': max_concurrent,
        'message': f'Screening {len(app_ids)} applications with {model}'
    }), 202


@screening_bp.route('/api/screening/status')
def screening_status():
    """Get screening progress and results."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401

    with _screening_lock:
        state = dict(_screening_state)
        # Sort results by score descending
        results = sorted(
            state.get('results', []),
            key=lambda r: r.get('overall_score', 0),
            reverse=True
        )
        state['results'] = results

    # Count pending (unscreened) applications
    try:
        all_apps = db.get_all_applications()
        pending = []
        for a in (all_apps or []):
            aid = a.get('application_id') or a.get('applicationid')
            name = a.get('applicant_name') or a.get('applicantname') or ''
            status = a.get('status') or ''
            has_text = bool((a.get('application_text') or a.get('applicationtext') or '').strip())
            # Show all apps that could be screened
            if has_text and not a.get('screening_score'):
                pending.append({'id': aid, 'name': name, 'status': status})
        state['pending_count'] = len(pending)
        state['pending'] = pending[:20]  # Show first 20
    except Exception:
        state['pending_count'] = 0
        state['pending'] = []

    return jsonify(state)


@screening_bp.route('/api/screening/screen-one/<int:application_id>', methods=['POST'])
@csrf.exempt
def screen_one_api(application_id):
    """Screen a single application (synchronous, returns result)."""
    if not session.get('authenticated'):
        return jsonify({'error': 'Not authenticated'}), 401

    data = request.get_json() or {}
    model = data.get('model', config.model_tier_merlin)

    client = get_ai_client()
    result = _screen_one(application_id, client, model)
    return jsonify(result)
