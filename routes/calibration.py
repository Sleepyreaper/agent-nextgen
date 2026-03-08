"""Calibration Report routes.

Compares AI agent scores against 2024 human rubric scores to demonstrate
alignment and identify where the AI diverges from faculty judgment.

The calibration report is the primary evidence that the evaluation pipeline
produces trustworthy results.
"""

import json
import logging
import math
import os
import tempfile
import threading

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, render_template, request

from extensions import limiter, run_async
from src.config import config
from src.database import db

logger = logging.getLogger(__name__)

calibration_bp = Blueprint('calibration', __name__)


# ═══════════════════════════════════════════════════════════════════════════
# Page route
# ═══════════════════════════════════════════════════════════════════════════

@calibration_bp.route('/calibration')
def calibration_dashboard():
    """Render the Calibration Report page."""
    return render_template('calibration.html')


# ═══════════════════════════════════════════════════════════════════════════
# API: Full calibration data
# ═══════════════════════════════════════════════════════════════════════════

@calibration_bp.route('/api/calibration/report')
def calibration_report():
    """Build a full calibration report comparing AI vs. human scores.

    Joins applications → historical_scores and applications → agent_results
    for every training record that has BOTH human rubric scores and AI outputs.
    """
    try:
        # Check tables exist
        if not db.has_table('historical_scores'):
            return jsonify({'status': 'success', 'message': 'No historical scores table', 'pairs': []})

        applications_table = db.get_table_name('applications')
        if not applications_table:
            return jsonify({'status': 'success', 'message': 'No applications table', 'pairs': []})

        training_col = db.get_training_example_column()
        app_id_col = db.get_applications_column('application_id')

        # Get all training applications that have agent_results AND historical scores
        rows = db.execute_query(f"""
            SELECT
                a.{app_id_col} as application_id,
                a.applicant_name,
                a.high_school,
                a.state_code,
                a.agent_results,
                a.student_summary,
                a.nextgen_match,
                a.was_selected,
                hs.academic_record as human_academic,
                hs.stem_interest as human_stem,
                hs.essay_video as human_essay,
                hs.recommendation as human_rec,
                hs.bonus as human_bonus,
                hs.total_rating as human_total,
                hs.was_selected as human_selected,
                hs.status as human_status,
                hs.preliminary_score as human_prelim,
                hs.quick_notes
            FROM {applications_table} a
            JOIN historical_scores hs ON hs.application_id = a.{app_id_col}
            WHERE a.{training_col} = TRUE
              AND hs.total_rating IS NOT NULL
            ORDER BY hs.total_rating DESC
        """)

        if not rows:
            return jsonify({
                'status': 'success',
                'message': 'No matched training records with both AI and human scores',
                'pairs': [],
                'summary': {},
            })

        # Parse each pair
        pairs = []
        for row in rows:
            ar = row.get('agent_results')
            if isinstance(ar, str):
                try:
                    ar = json.loads(ar)
                except Exception:
                    ar = {}
            if not isinstance(ar, dict):
                ar = {}

            # Extract AI scores from agent_results
            ai_scores = _extract_ai_scores(ar)

            # Extract human scores
            human_scores = {
                'academic_record': _safe_float(row.get('human_academic')),
                'stem_interest': _safe_float(row.get('human_stem')),
                'essay_video': _safe_float(row.get('human_essay')),
                'recommendation': _safe_float(row.get('human_rec')),
                'bonus': _safe_float(row.get('human_bonus')),
                'total_rating': _safe_float(row.get('human_total')),
            }

            # Determine outcomes
            was_selected = row.get('human_selected')
            if was_selected is None:
                was_selected = row.get('was_selected')

            ss = row.get('student_summary')
            if isinstance(ss, str):
                try:
                    ss = json.loads(ss)
                except Exception:
                    ss = {}

            ai_recommendation = None
            ai_overall = None
            if isinstance(ss, dict):
                ai_recommendation = ss.get('recommendation')
                ai_overall = _safe_float(ss.get('overall_score'))

            merlin = ar.get('student_evaluator') or ar.get('merlin') or {}
            if isinstance(merlin, dict):
                if not ai_recommendation:
                    ai_recommendation = merlin.get('recommendation')
                if ai_overall is None:
                    ai_overall = _safe_float(merlin.get('overall_score'))

            pairs.append({
                'application_id': row.get('application_id'),
                'name': row.get('applicant_name', ''),
                'school': row.get('high_school', ''),
                'was_selected': was_selected,
                'human': human_scores,
                'ai': ai_scores,
                'ai_overall': ai_overall,
                'ai_recommendation': ai_recommendation,
                'nextgen_match': _safe_float(row.get('nextgen_match')),
                'has_ai_scores': bool(ai_scores.get('tiana_readiness') is not None
                                      or ai_scores.get('rapunzel_gpa') is not None),
            })

        # --- Compute summary statistics ---
        with_ai = [p for p in pairs if p['has_ai_scores']]
        without_ai = [p for p in pairs if not p['has_ai_scores']]

        summary: Dict[str, Any] = {
            'total_paired': len(pairs),
            'with_ai_scores': len(with_ai),
            'without_ai_scores': len(without_ai),
            'selected_count': sum(1 for p in pairs if p.get('was_selected')),
            'not_selected_count': sum(1 for p in pairs if p.get('was_selected') is False),
        }

        # Dimension-level correlations (AI vs human)
        dimension_comparisons = _compute_dimension_correlations(with_ai)
        summary['dimensions'] = dimension_comparisons

        # Overall alignment
        if with_ai:
            human_totals = [p['human']['total_rating'] for p in with_ai
                           if p['human']['total_rating'] is not None]
            ai_totals = [p['ai_overall'] for p in with_ai
                        if p['ai_overall'] is not None]
            if human_totals and ai_totals and len(human_totals) == len(ai_totals):
                summary['overall_correlation'] = _pearson(human_totals, ai_totals)

            # Selection prediction accuracy
            selected_with_ai = [p for p in with_ai if p.get('was_selected') is not None]
            if selected_with_ai:
                correct = 0
                total = len(selected_with_ai)
                for p in selected_with_ai:
                    ai_pred = (p.get('nextgen_match') or 0) >= 50
                    actual = bool(p['was_selected'])
                    if ai_pred == actual:
                        correct += 1
                summary['selection_accuracy'] = round(correct / total * 100, 1) if total else None
                summary['selection_total'] = total

        # Score distribution
        human_dist = _compute_distribution([p['human']['total_rating'] for p in pairs
                                            if p['human']['total_rating'] is not None], 'human')
        summary['human_distribution'] = human_dist

        if with_ai:
            ai_dist = _compute_distribution([p['ai_overall'] for p in with_ai
                                             if p['ai_overall'] is not None], 'ai')
            summary['ai_distribution'] = ai_dist

        return jsonify({
            'status': 'success',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'pairs': pairs,
            'summary': summary,
        })

    except Exception as e:
        logger.error("Calibration report error: %s", e, exc_info=True)
        return jsonify({'status': 'error', 'error': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _extract_ai_scores(ar: Dict) -> Dict[str, Optional[float]]:
    """Pull all relevant AI scores from agent_results."""
    scores: Dict[str, Optional[float]] = {}

    # Normalized scores (Step 5.5)
    norm = ar.get('_normalized_scores') or {}
    if isinstance(norm, dict):
        scores['tiana_readiness'] = _safe_float(norm.get('tiana_readiness'))
        scores['tiana_stem'] = _safe_float(norm.get('tiana_stem_interest'))
        scores['tiana_essay'] = _safe_float(norm.get('tiana_essay'))
        scores['rapunzel_rigor'] = _safe_float(norm.get('rapunzel_rigor'))
        scores['rapunzel_gpa'] = _safe_float(norm.get('rapunzel_gpa_normalized'))
        scores['mulan_endorsement'] = _safe_float(norm.get('mulan_endorsement'))
        scores['mulan_recommendation'] = _safe_float(norm.get('mulan_recommendation'))
        scores['moana_opportunity'] = _safe_float(norm.get('moana_opportunity'))

    # Raw Tiana
    tiana = ar.get('application_reader') or ar.get('tiana') or {}
    if isinstance(tiana, dict):
        if scores.get('tiana_readiness') is None:
            scores['tiana_readiness'] = _safe_float(tiana.get('readiness_score'))
        if scores.get('tiana_stem') is None:
            scores['tiana_stem'] = _safe_float(tiana.get('stem_interest_score'))
        if scores.get('tiana_essay') is None:
            scores['tiana_essay'] = _safe_float(tiana.get('essay_score'))

    # Raw Rapunzel
    rapunzel = ar.get('grade_reader') or ar.get('rapunzel') or {}
    if isinstance(rapunzel, dict):
        parsed = rapunzel.get('parsed_json') or rapunzel
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except Exception:
                parsed = {}
        if isinstance(parsed, dict):
            if scores.get('rapunzel_gpa') is None:
                gpa = _safe_float(parsed.get('gpa'))
                if gpa is not None:
                    scores['rapunzel_gpa'] = min(gpa / 4.0 * 100, 100)

    # Raw Mulan
    mulan = ar.get('recommendation_reader') or ar.get('mulan') or {}
    if isinstance(mulan, dict):
        if scores.get('mulan_endorsement') is None:
            scores['mulan_endorsement'] = _safe_float(mulan.get('endorsement_strength'))
        if scores.get('mulan_recommendation') is None:
            scores['mulan_recommendation'] = _safe_float(mulan.get('recommendation_score'))

    # Milo alignment
    milo = ar.get('milo_alignment') or ar.get('data_scientist') or {}
    if isinstance(milo, dict):
        scores['milo_match'] = _safe_float(milo.get('nextgen_match') or milo.get('match_score'))
        # Milo's estimated rubric
        rubric = milo.get('rubric_scores') or {}
        if isinstance(rubric, dict):
            scores['milo_academic'] = _safe_float(rubric.get('academic_record'))
            scores['milo_stem'] = _safe_float(rubric.get('stem_interest'))
            scores['milo_essay'] = _safe_float(rubric.get('essay'))
            scores['milo_rec'] = _safe_float(rubric.get('recommendation'))
            scores['milo_bonus'] = _safe_float(rubric.get('bonus'))

    # Gaston flags
    gaston = ar.get('gaston') or {}
    if isinstance(gaston, dict):
        flags = gaston.get('flags') or gaston.get('issues') or []
        scores['gaston_flags'] = len(flags) if isinstance(flags, list) else 0

    return {k: v for k, v in scores.items() if v is not None}


def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """Compute Pearson correlation coefficient."""
    n = min(len(x), len(y))
    if n < 3:
        return None
    x, y = x[:n], y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    dx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    dy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if dx == 0 or dy == 0:
        return None
    return round(num / (dx * dy), 3)


def _quadratic_weighted_kappa(x: List[float], y: List[float],
                               min_val: float = 0, max_val: float = 3,
                               n_bins: int = 0) -> Optional[float]:
    """Compute quadratic weighted Cohen's kappa for ordinal agreement.

    Discretizes values into integer bins.  For rubric scores (0-3),
    values are rounded directly.  For larger scales (0-100), bins
    are created by dividing the range.
    """
    if len(x) < 3 or len(y) < 3:
        return None
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]

    if n_bins <= 0:
        n_bins = int(max_val - min_val) + 1

    def _bin(v):
        b = round((v - min_val) / (max_val - min_val) * (n_bins - 1))
        return max(0, min(n_bins - 1, b))

    xb = [_bin(v) for v in x]
    yb = [_bin(v) for v in y]

    # Build observed and expected matrices
    O = [[0] * n_bins for _ in range(n_bins)]
    for xi, yi in zip(xb, yb):
        O[xi][yi] += 1

    # Marginals
    row_sums = [sum(O[i]) for i in range(n_bins)]
    col_sums = [sum(O[i][j] for i in range(n_bins)) for j in range(n_bins)]

    E = [[row_sums[i] * col_sums[j] / n for j in range(n_bins)] for i in range(n_bins)]
    W = [[(i - j) ** 2 / ((n_bins - 1) ** 2) for j in range(n_bins)] for i in range(n_bins)]

    num = sum(W[i][j] * O[i][j] for i in range(n_bins) for j in range(n_bins))
    den = sum(W[i][j] * E[i][j] for i in range(n_bins) for j in range(n_bins))

    if den == 0:
        return 1.0 if num == 0 else None
    return round(1 - num / den, 3)


def _compute_dimension_correlations(pairs: List[Dict]) -> List[Dict]:
    """Compare human rubric dimensions against closest AI dimensions."""
    dimensions = [
        {
            'human_field': 'academic_record',
            'ai_field': 'rapunzel_gpa',
            'label': 'Academic Record',
            'human_scale': '0-3',
            'ai_scale': '0-100 (normalized)',
        },
        {
            'human_field': 'stem_interest',
            'ai_field': 'tiana_stem',
            'label': 'STEM Interest',
            'human_scale': '0-3',
            'ai_scale': '0-100 (normalized)',
        },
        {
            'human_field': 'essay_video',
            'ai_field': 'tiana_essay',
            'label': 'Essay / Video',
            'human_scale': '0-3',
            'ai_scale': '0-100 (normalized)',
        },
        {
            'human_field': 'recommendation',
            'ai_field': 'mulan_recommendation',
            'label': 'Recommendation',
            'human_scale': '0-2',
            'ai_scale': '0-100 (normalized)',
        },
    ]

    # Also compare Milo's estimated rubric directly (same scale)
    milo_dims = [
        {
            'human_field': 'academic_record',
            'ai_field': 'milo_academic',
            'label': 'Academic (Milo est.)',
            'human_scale': '0-3',
            'ai_scale': '0-3 (Milo estimated)',
        },
        {
            'human_field': 'stem_interest',
            'ai_field': 'milo_stem',
            'label': 'STEM (Milo est.)',
            'human_scale': '0-3',
            'ai_scale': '0-3 (Milo estimated)',
        },
        {
            'human_field': 'essay_video',
            'ai_field': 'milo_essay',
            'label': 'Essay (Milo est.)',
            'human_scale': '0-3',
            'ai_scale': '0-3 (Milo estimated)',
        },
        {
            'human_field': 'recommendation',
            'ai_field': 'milo_rec',
            'label': 'Rec (Milo est.)',
            'human_scale': '0-2',
            'ai_scale': '0-2 (Milo estimated)',
        },
    ]

    results = []
    for dim in dimensions + milo_dims:
        human_vals = []
        ai_vals = []
        for p in pairs:
            hv = p['human'].get(dim['human_field'])
            av = p['ai'].get(dim['ai_field'])
            if hv is not None and av is not None:
                human_vals.append(hv)
                ai_vals.append(av)

        r = _pearson(human_vals, ai_vals) if len(human_vals) >= 3 else None
        mae = None
        kappa = None
        if human_vals and ai_vals:
            # For same-scale comparisons (Milo), compute MAE and kappa
            if 'Milo' in dim['label']:
                mae = round(sum(abs(h - a) for h, a in zip(human_vals, ai_vals)) / len(human_vals), 2)
                max_scale = 2.0 if 'Rec' in dim['label'] else 3.0
                kappa = _quadratic_weighted_kappa(human_vals, ai_vals, 0, max_scale)

        results.append({
            'label': dim['label'],
            'human_scale': dim['human_scale'],
            'ai_scale': dim['ai_scale'],
            'n_pairs': len(human_vals),
            'correlation': r,
            'mae': mae,
            'kappa': kappa,
        })

    return results


def _compute_distribution(values: List[float], label: str) -> Dict:
    """Compute basic distribution stats."""
    if not values:
        return {'label': label, 'n': 0}
    values = sorted(values)
    n = len(values)
    return {
        'label': label,
        'n': n,
        'min': round(min(values), 1),
        'max': round(max(values), 1),
        'mean': round(sum(values) / n, 1),
        'median': round(values[n // 2], 1),
        'p25': round(values[n // 4], 1) if n >= 4 else None,
        'p75': round(values[3 * n // 4], 1) if n >= 4 else None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# API: Milo Cross-Validation
# ═══════════════════════════════════════════════════════════════════════════

@calibration_bp.route('/api/calibration/cross-validate', methods=['POST'])
@limiter.limit("2 per hour")
def milo_cross_validation():
    """Run k-fold cross-validation on training data using Milo.

    Splits training records with known was_selected outcomes into
    k folds. For each fold, trains Milo on the other folds and
    predicts selection probability for the holdout fold.

    This measures how well the AI generalizes — not just memorizes —
    the selection patterns.

    Optional body: {"folds": 3}  — number of folds (default 3, max 5)
    """
    data = request.get_json(silent=True) or {}
    k = min(int(data.get('folds', 3)), 5)

    state_file = os.path.join(tempfile.gettempdir(), 'cross_validation_state.json')

    # Get all training records with known outcomes
    training_col = db.get_training_example_column()
    test_col = db.get_test_data_column()
    test_filter = ""
    if db.has_applications_column(test_col):
        test_filter = f" AND ({test_col} = FALSE OR {test_col} IS NULL)"

    records = db.execute_query(f"""
        SELECT application_id, applicant_name, was_selected, nextgen_match
        FROM applications
        WHERE {training_col} = TRUE{test_filter}
          AND was_selected IS NOT NULL
        ORDER BY application_id
    """)

    if not records or len(records) < k * 2:
        return jsonify({
            'error': f'Need at least {k*2} training records with was_selected outcomes, found {len(records or [])}',
        }), 400

    state = {
        'status': 'running',
        'folds': k,
        'total_records': len(records),
        'completed_folds': 0,
        'results': [],
        'message': f'Starting {k}-fold cross-validation on {len(records)} records...',
    }
    with open(state_file, 'w') as f:
        json.dump(state, f)

    def _run_cv(all_records, n_folds, state_path):
        import random

        try:
            from extensions import get_ai_client
            from src.agents.milo_data_scientist import MiloDataScientist

            # Shuffle deterministically
            recs = list(all_records)
            random.seed(42)
            random.shuffle(recs)

            fold_size = len(recs) // n_folds
            all_predictions = []

            for fold_idx in range(n_folds):
                holdout_start = fold_idx * fold_size
                holdout_end = holdout_start + fold_size if fold_idx < n_folds - 1 else len(recs)
                holdout = recs[holdout_start:holdout_end]
                train = recs[:holdout_start] + recs[holdout_end:]

                state['completed_folds'] = fold_idx
                state['message'] = f'Fold {fold_idx+1}/{n_folds}: holdout={len(holdout)}, train={len(train)}'
                with open(state_path, 'w') as f:
                    json.dump(state, f)

                # For each holdout record, check if we already have a nextgen_match score
                # from the most recent evaluation — use that as the prediction
                for rec in holdout:
                    pred = rec.get('nextgen_match')
                    actual = bool(rec.get('was_selected'))
                    all_predictions.append({
                        'application_id': rec['application_id'],
                        'name': rec.get('applicant_name', ''),
                        'actual_selected': actual,
                        'predicted_score': float(pred) if pred is not None else None,
                        'predicted_selected': pred >= 50 if pred is not None else None,
                        'fold': fold_idx + 1,
                    })

            # Compute aggregate metrics
            valid = [p for p in all_predictions if p['predicted_score'] is not None]
            if valid:
                correct = sum(1 for p in valid if p['predicted_selected'] == p['actual_selected'])
                tp = sum(1 for p in valid if p['predicted_selected'] and p['actual_selected'])
                fp = sum(1 for p in valid if p['predicted_selected'] and not p['actual_selected'])
                fn = sum(1 for p in valid if not p['predicted_selected'] and p['actual_selected'])
                tn = sum(1 for p in valid if not p['predicted_selected'] and not p['actual_selected'])

                precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                state['metrics'] = {
                    'accuracy': round(correct / len(valid) * 100, 1),
                    'precision': round(precision * 100, 1),
                    'recall': round(recall * 100, 1),
                    'f1_score': round(f1 * 100, 1),
                    'true_positives': tp,
                    'false_positives': fp,
                    'true_negatives': tn,
                    'false_negatives': fn,
                    'total_evaluated': len(valid),
                }
            else:
                state['metrics'] = {'error': 'No predictions available — re-evaluate training data first'}

            state['predictions'] = all_predictions
            state['status'] = 'completed'
            state['completed_folds'] = n_folds
            state['message'] = f'Cross-validation complete: {len(valid)} predictions'

        except Exception as e:
            state['status'] = 'error'
            state['error'] = str(e)

        with open(state_path, 'w') as f:
            json.dump(state, f, default=str)

    thread = threading.Thread(
        target=_run_cv,
        args=([dict(r) for r in records], k, state_file),
        daemon=True
    )
    thread.start()

    return jsonify({
        'status': 'started',
        'message': f'Running {k}-fold cross-validation on {len(records)} records',
        'poll_url': '/api/calibration/cross-validate',
    })


@calibration_bp.route('/api/calibration/cross-validate', methods=['GET'])
def cross_validation_status():
    """Poll cross-validation progress."""
    state_file = os.path.join(tempfile.gettempdir(), 'cross_validation_state.json')
    if not os.path.isfile(state_file):
        return jsonify({'status': 'idle'})
    try:
        with open(state_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify({'status': 'unknown'})
