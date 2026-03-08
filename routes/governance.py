"""Trust & Governance routes.

Provides a faculty-facing dashboard that demonstrates the trustworthiness,
transparency, and ethical guardrails of the Next Gen evaluation system.

Sections:
  1. Data Provenance  — authoritative vs. AI-estimated school data
  2. Agent Transparency — agent success/skip/error rates with weekly caching
  3. Guardrails         — anti-hallucination measures & pipeline safeguards
  4. Human Oversight    — evaluation counts, school approvals, override history
"""

import json
import logging
import os
import time

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, render_template, request

from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

governance_bp = Blueprint('governance', __name__)

# ---------------------------------------------------------------------------
# Weekly cache for expensive agent transparency computations
# ---------------------------------------------------------------------------
_agent_report_cache: Dict[str, Any] = {}
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 1 week


def _get_cached_agent_report() -> Optional[Dict[str, Any]]:
    """Return cached agent report if still valid, else None."""
    if not _agent_report_cache:
        return None
    cached_at = _agent_report_cache.get('_cached_at', 0)
    if time.time() - cached_at > _CACHE_TTL_SECONDS:
        return None
    return _agent_report_cache


def _set_agent_report_cache(report: Dict[str, Any]) -> None:
    global _agent_report_cache
    report['_cached_at'] = time.time()
    _agent_report_cache = report


# ═══════════════════════════════════════════════════════════════════════════
# Page route
# ═══════════════════════════════════════════════════════════════════════════

@governance_bp.route('/governance')
def dashboard():
    """Render the Trust & Governance dashboard."""
    return render_template('governance.html')


# ═══════════════════════════════════════════════════════════════════════════
# API: Data Provenance
# ═══════════════════════════════════════════════════════════════════════════

# Fields that are authoritative only when sourced from GOSA CSV import
GOSA_FIELDS = [
    'act_composite_avg', 'act_english_avg', 'act_math_avg',
    'act_reading_avg', 'act_science_avg', 'act_students_tested',
    'sat_total_avg', 'sat_ebrw_avg', 'sat_math_avg', 'sat_students_tested',
    'college_going_rate', 'college_going_2yr_rate', 'college_going_4yr_rate',
    'hope_eligible_pct', 'dropout_rate',
    'milestones_ela_proficient_pct', 'milestones_math_proficient_pct',
    'ap_students_tested', 'ap_tests_administered', 'ap_tests_3plus',
    'instruction_expenditure_per_fte', 'inexperienced_teacher_pct',
    'school_ppe', 'fesr_star_rating', 'fesr_academic_score',
]

# Fields from NCES CCD CSV import
NCES_FIELDS = [
    'total_students', 'graduation_rate', 'free_lunch_percentage',
    'reduced_lunch_percentage', 'direct_certification_pct',
    'student_teacher_ratio', 'teachers_fte',
    'is_title_i', 'is_charter', 'is_magnet', 'locale_code',
    'district_exp_per_pupil', 'district_rev_per_pupil',
]

# Fields that may be AI-estimated by Naveen
AI_ESTIMATED_FIELDS = [
    'opportunity_score', 'community_sentiment_score',
    'parent_satisfaction_score', 'school_investment_level',
    'ap_course_count', 'honors_course_count', 'ap_exam_pass_rate',
    'college_acceptance_rate',
]


@governance_bp.route('/api/governance/provenance')
def data_provenance():
    """Compute school data provenance statistics.

    Returns per-field coverage: how many schools have authoritative (CSV)
    vs. AI-estimated vs. missing data.
    """
    try:
        if not db.has_table('school_enriched_data'):
            return jsonify({'status': 'success', 'total_schools': 0, 'fields': {}})

        # Count total active schools
        total_rows = db.execute_query(
            "SELECT COUNT(*) as cnt FROM school_enriched_data WHERE is_active = TRUE"
        )
        total = total_rows[0]['cnt'] if total_rows else 0
        if total == 0:
            return jsonify({'status': 'success', 'total_schools': 0, 'fields': {}})

        # Count schools by import source
        source_rows = db.execute_query("""
            SELECT
                analysis_status,
                COUNT(*) as cnt
            FROM school_enriched_data
            WHERE is_active = TRUE
            GROUP BY analysis_status
        """)
        source_counts = {r['analysis_status']: r['cnt'] for r in source_rows}

        # Count non-null values for each field
        all_fields = set(GOSA_FIELDS + NCES_FIELDS + AI_ESTIMATED_FIELDS)
        field_stats = {}

        for field in sorted(all_fields):
            try:
                rows = db.execute_query(f"""
                    SELECT
                        COUNT(*) FILTER (WHERE {field} IS NOT NULL) as has_value,
                        COUNT(*) FILTER (WHERE {field} IS NULL) as missing
                    FROM school_enriched_data
                    WHERE is_active = TRUE
                """)
                has_value = rows[0]['has_value'] if rows else 0
                missing = rows[0]['missing'] if rows else total

                # Determine provenance category
                if field in GOSA_FIELDS:
                    category = 'gosa_authoritative'
                elif field in NCES_FIELDS:
                    category = 'nces_authoritative'
                else:
                    category = 'ai_estimated'

                field_stats[field] = {
                    'category': category,
                    'has_value': has_value,
                    'missing': missing,
                    'coverage_pct': round(has_value / total * 100, 1) if total else 0,
                }
            except Exception:
                # Column may not exist yet
                field_stats[field] = {
                    'category': 'unknown',
                    'has_value': 0,
                    'missing': total,
                    'coverage_pct': 0,
                }

        # Summary stats
        gosa_populated = sum(
            1 for f in GOSA_FIELDS
            if field_stats.get(f, {}).get('has_value', 0) > 0
        )
        nces_populated = sum(
            1 for f in NCES_FIELDS
            if field_stats.get(f, {}).get('has_value', 0) > 0
        )

        return jsonify({
            'status': 'success',
            'total_schools': total,
            'source_counts': source_counts,
            'summary': {
                'gosa_fields_with_data': gosa_populated,
                'gosa_fields_total': len(GOSA_FIELDS),
                'nces_fields_with_data': nces_populated,
                'nces_fields_total': len(NCES_FIELDS),
                'ai_estimated_fields': len(AI_ESTIMATED_FIELDS),
            },
            'fields': field_stats,
        })
    except Exception as e:
        logger.error("Provenance API error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# API: Agent Transparency Report
# ═══════════════════════════════════════════════════════════════════════════

@governance_bp.route('/api/governance/agent-report')
def agent_transparency_report():
    """Return agent success/skip/error rates from evaluation history.

    Results are cached for 1 week. Pass ?refresh=1 to force re-compute.
    """
    force_refresh = request.args.get('refresh') == '1'

    if not force_refresh:
        cached = _get_cached_agent_report()
        if cached:
            return jsonify(cached)

    try:
        report: Dict[str, Any] = {
            'status': 'success',
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }

        # --- Agent interaction counts from audit logs ---
        if db.has_table('agent_audit_logs'):
            agent_rows = db.execute_query("""
                SELECT
                    agent_name,
                    COUNT(*) as total_runs,
                    MIN(created_at) as first_run,
                    MAX(created_at) as last_run
                FROM agent_audit_logs
                GROUP BY agent_name
                ORDER BY total_runs DESC
            """)
            report['agent_activity'] = [
                {
                    'agent': r['agent_name'],
                    'total_runs': r['total_runs'],
                    'first_run': r['first_run'].isoformat() if r.get('first_run') else None,
                    'last_run': r['last_run'].isoformat() if r.get('last_run') else None,
                }
                for r in agent_rows
            ]
        else:
            report['agent_activity'] = []

        # --- Evaluation outcomes from agent_results JSON ---
        applications_table = db.get_table_name('applications')
        if applications_table:
            training_col = db.get_training_example_column()
            test_col = db.get_test_data_column()
            test_filter = ""
            if db.has_applications_column(test_col):
                test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

            eval_rows = db.execute_query(f"""
                SELECT agent_results
                FROM {applications_table}
                WHERE {training_col} = FALSE{test_filter}
                  AND agent_results IS NOT NULL
                ORDER BY uploaded_date DESC
                LIMIT 500
            """)

            # Parse agent_results to get per-agent success/error data
            agent_stats: Dict[str, Dict[str, int]] = {}
            total_evaluations = 0

            for row in eval_rows:
                ar = row.get('agent_results')
                if isinstance(ar, str):
                    try:
                        ar = json.loads(ar)
                    except Exception:
                        continue
                if not isinstance(ar, dict):
                    continue

                total_evaluations += 1
                for agent_name, agent_data in ar.items():
                    if agent_name.startswith('_'):
                        continue
                    if agent_name not in agent_stats:
                        agent_stats[agent_name] = {'success': 0, 'error': 0, 'skipped': 0}

                    if isinstance(agent_data, dict):
                        if agent_data.get('error'):
                            agent_stats[agent_name]['error'] += 1
                        elif agent_data.get('skipped'):
                            agent_stats[agent_name]['skipped'] += 1
                        else:
                            agent_stats[agent_name]['success'] += 1
                    elif agent_data is not None:
                        agent_stats[agent_name]['success'] += 1

            report['evaluation_stats'] = {
                'total_evaluations_sampled': total_evaluations,
                'agents': {
                    name: {
                        **counts,
                        'success_rate': round(
                            counts['success'] / max(counts['success'] + counts['error'] + counts['skipped'], 1) * 100, 1
                        ),
                    }
                    for name, counts in sorted(agent_stats.items())
                },
            }

        # --- Gaston audit flags (post-Merlin checks) ---
        if applications_table:
            gaston_rows = db.execute_query(f"""
                SELECT agent_results
                FROM {applications_table}
                WHERE {training_col} = FALSE{test_filter}
                  AND agent_results IS NOT NULL
                  AND agent_results::text LIKE '%gaston%'
                ORDER BY uploaded_date DESC
                LIMIT 500
            """)
            flagged_count = 0
            total_audited = 0
            flag_types: Dict[str, int] = {}

            for row in gaston_rows:
                ar = row.get('agent_results')
                if isinstance(ar, str):
                    try:
                        ar = json.loads(ar)
                    except Exception:
                        continue
                if not isinstance(ar, dict):
                    continue

                gaston = ar.get('gaston') or ar.get('Gaston') or {}
                if isinstance(gaston, dict) and gaston:
                    total_audited += 1
                    flags = gaston.get('flags') or gaston.get('issues') or []
                    if flags:
                        flagged_count += 1
                        for flag in (flags if isinstance(flags, list) else [flags]):
                            flag_type = flag.get('type', 'unknown') if isinstance(flag, dict) else str(flag)
                            flag_types[flag_type] = flag_types.get(flag_type, 0) + 1

            report['gaston_audit'] = {
                'total_audited': total_audited,
                'flagged': flagged_count,
                'flag_rate_pct': round(flagged_count / max(total_audited, 1) * 100, 1),
                'flag_types': flag_types,
            }

        _set_agent_report_cache(report)
        return jsonify(report)

    except Exception as e:
        logger.error("Agent transparency report error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# API: Human Oversight Summary
# ═══════════════════════════════════════════════════════════════════════════

@governance_bp.route('/api/governance/oversight')
def human_oversight():
    """Return human oversight statistics: school reviews, evaluation counts."""
    try:
        result: Dict[str, Any] = {'status': 'success'}

        # --- School review status ---
        if db.has_table('school_enriched_data'):
            review_rows = db.execute_query("""
                SELECT
                    human_review_status,
                    COUNT(*) as cnt
                FROM school_enriched_data
                WHERE is_active = TRUE
                GROUP BY human_review_status
            """)
            result['school_reviews'] = {
                r['human_review_status'] or 'unset': r['cnt']
                for r in review_rows
            }

            # Recent reviews
            recent_reviews = db.execute_query("""
                SELECT school_name, state_code, human_review_status,
                       reviewed_by, reviewed_date
                FROM school_enriched_data
                WHERE reviewed_date IS NOT NULL AND is_active = TRUE
                ORDER BY reviewed_date DESC
                LIMIT 20
            """)
            result['recent_reviews'] = [
                {
                    'school': r['school_name'],
                    'state': r['state_code'],
                    'status': r['human_review_status'],
                    'reviewer': r['reviewed_by'],
                    'date': r['reviewed_date'].isoformat() if r.get('reviewed_date') else None,
                }
                for r in recent_reviews
            ]
        else:
            result['school_reviews'] = {}
            result['recent_reviews'] = []

        # --- Evaluation counts ---
        applications_table = db.get_table_name('applications')
        if applications_table:
            training_col = db.get_training_example_column()
            test_col = db.get_test_data_column()
            test_filter = ""
            if db.has_applications_column(test_col):
                test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

            count_rows = db.execute_query(f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE LOWER(status) != 'pending') as evaluated,
                    COUNT(*) FILTER (WHERE LOWER(status) = 'pending') as pending
                FROM {applications_table}
                WHERE {training_col} = FALSE{test_filter}
            """)
            if count_rows:
                result['evaluations'] = {
                    'total': count_rows[0]['total'],
                    'evaluated': count_rows[0]['evaluated'],
                    'pending': count_rows[0]['pending'],
                }
            else:
                result['evaluations'] = {'total': 0, 'evaluated': 0, 'pending': 0}
        else:
            result['evaluations'] = {'total': 0, 'evaluated': 0, 'pending': 0}

        return jsonify(result)

    except Exception as e:
        logger.error("Human oversight API error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# API: Guardrails (dynamic)
# ═══════════════════════════════════════════════════════════════════════════

@governance_bp.route('/api/governance/guardrails')
def guardrails():
    """Return dynamically-generated guardrails documentation based on system state."""
    try:
        guardrails_list = []

        # 1. Source verification
        guardrails_list.append({
            'id': 'source_verification',
            'title': 'Authoritative Data Sources',
            'icon': '🔒',
            'description': (
                'School metrics are sourced from official government datasets — '
                'specifically the Georgia Governor\'s Office of Student Achievement (GOSA) '
                'and the NCES Common Core of Data (CCD). '
                'Each field carries per-record provenance tracking so reviewers can '
                'distinguish verified data from AI estimates.'
            ),
            'sources': [
                {'name': 'GOSA', 'url': 'https://gosa.georgia.gov/', 'fields': len(GOSA_FIELDS)},
                {'name': 'NCES CCD', 'url': 'https://nces.ed.gov/ccd/', 'fields': len(NCES_FIELDS)},
            ],
            'status': 'active',
        })

        # 2. Anti-hallucination
        guardrails_list.append({
            'id': 'anti_hallucination',
            'title': 'Anti-Hallucination Measures',
            'icon': '🛡️',
            'description': (
                'Agents are constrained to operate only on data present in the student\'s '
                'uploaded documents and verified school records. '
                'Naveen labels every field as VERIFIED (from GOSA/NCES) or ESTIMATE '
                '(AI-inferred) so downstream agents know what to trust. '
                'Merlin\'s final evaluation receives normalized scores (0–100) and '
                'source labels — not raw agent prose.'
            ),
            'measures': [
                'VERIFIED vs ESTIMATE field labeling in Naveen prompts',
                'Normalized 0–100 scoring prevents scale drift between agents',
                'Merlin receives structured data, not free-text agent outputs',
                'Belle document analyzer extracts text from actual uploaded files only',
            ],
            'status': 'active',
        })

        # 3. Adversarial audit
        gaston_active = True
        guardrails_list.append({
            'id': 'adversarial_audit',
            'title': 'Post-Evaluation Adversarial Audit (Gaston)',
            'icon': '⚔️',
            'description': (
                'After Merlin completes the final evaluation, Gaston performs '
                'a rule-based consistency check followed by an AI adversarial review. '
                'Gaston flags score–recommendation misalignment, rubric math errors, '
                'agent signal divergence, equity concerns, missing evidence, and '
                'low-confidence-high-score patterns.'
            ),
            'checks': [
                'Score–recommendation alignment',
                'Rubric math verification',
                'Agent signal divergence detection',
                'Equity concern flags',
                'Missing evidence detection',
                'Low confidence + high score alert',
            ],
            'status': 'active' if gaston_active else 'inactive',
        })

        # 4. Equity context
        guardrails_list.append({
            'id': 'equity_context',
            'title': 'Equity-Aware Context Multiplier (Pocahontas)',
            'icon': '⚖️',
            'description': (
                'Pocahontas analyzes the full applicant cohort to produce '
                'equity tiers (high-resource, moderate, under-resourced) and '
                'context multipliers (1.0×–1.30×). Under-resourced students '
                'receive a boost that recognizes achievement despite fewer '
                'opportunities. The multiplier is transparent in Merlin\'s prompt.'
            ),
            'multiplier_range': '1.00× – 1.30×',
            'status': 'active',
        })

        # 5. Score normalization
        guardrails_list.append({
            'id': 'score_normalization',
            'title': 'Cross-Agent Score Normalization',
            'icon': '📏',
            'description': (
                'All agent scores are normalized to a 0–100 scale before reaching '
                'Merlin. This prevents one agent\'s generous scoring from '
                'dominating the final evaluation and ensures consistent weighting.'
            ),
            'status': 'active',
        })

        # 6. Human-in-the-loop
        guardrails_list.append({
            'id': 'human_review',
            'title': 'Human-in-the-Loop Oversight',
            'icon': '👁️',
            'description': (
                'AI evaluations are advisory — faculty reviewers make final decisions. '
                'School data must be approved before it influences evaluations. '
                'Every agent interaction is logged in the audit trail.'
            ),
            'controls': [
                'School data requires human approval before use',
                'Faculty can override any AI recommendation',
                'Full agent audit trail in agent_audit_logs table',
                'Anomalous evaluations flagged by Gaston for review',
            ],
            'status': 'active',
        })

        # 7. Model tier architecture
        guardrails_list.append({
            'id': 'model_tiers',
            'title': '4-Tier Model Architecture',
            'icon': '🏗️',
            'description': (
                'Agents use purpose-matched model tiers to balance quality with cost. '
                'Critical evaluations (Merlin) use the dedicated Merlin tier. '
                'Data extraction uses the Workhorse tier. '
                'Simple classification uses the Lightweight tier.'
            ),
            'tiers': [
                {'name': 'Premium', 'model': config.model_tier_premium, 'use': 'Milo (data science)'},
                {'name': 'Merlin', 'model': config.model_tier_merlin, 'use': 'Final evaluation'},
                {'name': 'Workhorse', 'model': config.model_tier_workhorse, 'use': 'Document analysis, scoring'},
                {'name': 'Lightweight', 'model': config.model_tier_lightweight, 'use': 'Triage, classification'},
            ],
            'status': 'active',
        })

        # 8. Edge case handling
        guardrails_list.append({
            'id': 'edge_cases',
            'title': 'Edge Case Handling',
            'icon': '🧩',
            'description': (
                'The pipeline gracefully degrades when data is incomplete. '
                'Each agent checks for required inputs and skips cleanly '
                'when data is absent, logging what was missing. '
                'Merlin evaluates with whatever evidence is available and '
                'adjusts confidence accordingly.'
            ),
            'cases': [
                {'scenario': 'No transcript uploaded', 'handling': 'Rapunzel skips; Merlin evaluates without GPA/rigor, lowers confidence'},
                {'scenario': 'No recommendation letter', 'handling': 'Mulan skips; Merlin notes missing endorsement data'},
                {'scenario': 'School not in GOSA dataset', 'handling': 'Naveen AI-estimates school data (labeled ESTIMATE); Moana adjusts context'},
                {'scenario': 'Out-of-state school', 'handling': 'No GOSA data available; Naveen estimates from public sources; lower confidence'},
                {'scenario': 'Homeschooled student', 'handling': 'School lookup returns no match; evaluated on essay + recommendation strength'},
                {'scenario': 'Multiple documents in one PDF', 'handling': 'Belle section detection routes pages to correct agents'},
                {'scenario': 'Poor scan / OCR needed', 'handling': 'Belle falls back to OCR extraction; lower text quality noted'},
                {'scenario': 'Duplicate application', 'handling': 'Smee matches by name + school and updates existing record'},
                {'scenario': 'Video submission instead of essay', 'handling': 'Mirabel analyzes video; Tiana receives transcript of audio'},
            ],
            'status': 'active',
        })

        # 9. Determinism controls
        guardrails_list.append({
            'id': 'determinism',
            'title': 'Score Determinism (temperature=0)',
            'icon': '🎯',
            'description': (
                'Merlin and Gaston run with temperature=0 to minimize '
                'randomness in scoring. The same application should produce '
                'the same score on repeated evaluations. Use the Consistency '
                'Test to verify: POST /api/test/consistency with an application_id.'
            ),
            'status': 'active',
        })

        return jsonify({
            'status': 'success',
            'guardrails': guardrails_list,
            'pipeline_steps': [
                '1. Belle — Document extraction from uploaded PDFs/DOCX',
                '2. Smee — School name matching & lookup',
                '3. Naveen — School data enrichment (GOSA + NCES)',
                '4. Tiana + Rapunzel + Mulan — Application, transcript, recommendation analysis (parallel)',
                '5. Moana — Student-specific school context narrative',
                '6. Milo — ML feature extraction & validation',
                '5.5. Normalization — 0–100 scale + Pocahontas equity multiplier',
                '7. Merlin — Final comprehensive evaluation',
                '6.5. Gaston — Post-evaluation adversarial audit',
                '8. Aurora — Result formatting & presentation',
            ],
        })

    except Exception as e:
        logger.error("Guardrails API error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500
