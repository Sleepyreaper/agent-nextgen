#!/usr/bin/env python3
"""CLI script to run agent quality evaluations.

Usage:
    python scripts/run_agent_evaluations.py                    # All agents, all students
    python scripts/run_agent_evaluations.py --agents Merlin Tiana
    python scripts/run_agent_evaluations.py --max-students 5   # Quick test
    python scripts/run_agent_evaluations.py --consistency-only  # No AI calls
"""

import argparse
import json
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import config
from src.database import db
from src.logger import get_logger
from src.evaluations.agent_evaluator import AgentEvaluator, AGENT_EVAL_CONFIG

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run agent quality evaluations")
    parser.add_argument(
        "--agents",
        nargs="+",
        choices=list(AGENT_EVAL_CONFIG.keys()),
        help="Agents to evaluate (default: all)",
    )
    parser.add_argument(
        "--max-students",
        type=int,
        default=0,
        help="Max training students to evaluate (0 = all)",
    )
    parser.add_argument(
        "--consistency-only",
        action="store_true",
        help="Only compute consistency metrics (no AI judge calls)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    evaluator = AgentEvaluator(db)

    if args.consistency_only:
        print("Computing consistency metrics (no AI calls)...")
        metrics = evaluator.compute_consistency_metrics()
        if args.json:
            print(json.dumps(metrics, indent=2, default=str))
        else:
            _print_consistency(metrics)
        return

    print(f"Starting agent quality evaluation...")
    print(f"  Agents: {', '.join(args.agents) if args.agents else 'ALL'}")
    print(f"  Max students: {args.max_students or 'ALL'}")
    print()

    def progress(state):
        prog = state.get("progress", "")
        agent = state.get("agent", "")
        idx = state.get("student_index", "")
        total = state.get("total_students", "")
        if idx and total:
            print(f"  [{agent}] {idx}/{total} — {prog}", flush=True)
        else:
            print(f"  {prog}", flush=True)

    start = time.time()
    result = evaluator.run_batch_evaluation(
        agents=args.agents,
        max_students=args.max_students,
        progress_callback=progress,
    )
    elapsed = time.time() - start

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\n{'=' * 60}")
        print(f"Evaluation complete in {elapsed:.1f}s")
        print(f"  Batch ID: {result.get('batch_id', '—')}")
        print(f"  Status:   {result.get('status', '—')}")
        print(f"  Students: {result.get('total_students', 0)}")
        print(f"  Evals:    {result.get('total_evaluations', 0)}")
        print()

        # Per-agent summary
        per_agent = result.get("per_agent", {})
        if per_agent:
            print("Per-Agent Quality Scores (1-5 scale):")
            print(f"  {'Agent':<12} {'Ground.':<10} {'Coher.':<10} {'Relev.':<10} {'Fluency':<10} {'Count':<8}")
            print(f"  {'─' * 60}")
            for agent, data in per_agent.items():
                g = data.get("groundedness", {}).get("avg", "—")
                c = data.get("coherence", {}).get("avg", "—")
                r = data.get("relevance", {}).get("avg", "—")
                f = data.get("fluency", {}).get("avg", "—")
                n = data.get("evaluations", 0)
                g_str = f"{g:.1f}" if isinstance(g, float) else str(g)
                c_str = f"{c:.1f}" if isinstance(c, float) else str(c)
                r_str = f"{r:.1f}" if isinstance(r, float) else str(r)
                f_str = f"{f:.1f}" if isinstance(f, float) else str(f)
                print(f"  {agent:<12} {g_str:<10} {c_str:<10} {r_str:<10} {f_str:<10} {n:<8}")
            print()

        # Consistency
        consistency = result.get("consistency", {})
        if consistency:
            _print_consistency(consistency)

        errors = result.get("errors", [])
        if errors:
            print("Warnings:")
            for e in errors:
                print(f"  ⚠ {e}")


def _print_consistency(metrics):
    print("Consistency Metrics:")
    ag = metrics.get("merlin_gaston_agreement")
    if ag is not None:
        print(f"  Merlin/Gaston Agreement:  {ag}%")
    corr = metrics.get("merlin_gaston_score_correlation")
    if corr is not None:
        print(f"  Merlin/Gaston Correlation: {corr}")

    outcome = metrics.get("outcome_accuracy")
    if outcome:
        print(f"\nOutcome Accuracy (Merlin vs was_selected):")
        print(f"  Accuracy:  {outcome['accuracy']}%")
        print(f"  Precision: {outcome['precision']}%")
        print(f"  Recall:    {outcome['recall']}%")
        print(f"  F1 Score:  {outcome['f1']}%")
        cm = outcome.get("confusion_matrix", {})
        print(f"  Confusion: TP={cm.get('true_positives', 0)} FP={cm.get('false_positives', 0)} "
              f"TN={cm.get('true_negatives', 0)} FN={cm.get('false_negatives', 0)}")

    dist = metrics.get("score_distributions", {})
    if dist:
        print(f"\nScore Distributions:")
        for label, d in dist.items():
            print(f"  {label.title()} (n={d['count']}): "
                  f"μ={d['mean']} med={d['median']} [{d['min']}–{d['max']}]")


if __name__ == "__main__":
    main()
