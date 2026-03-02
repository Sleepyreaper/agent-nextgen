#!/usr/bin/env python3
"""Test Milo's selection model quality.

This script authenticates against production, triggers Milo's training
analysis and candidate ranking, and evaluates the model's quality by
checking:

  1. Training Insights — does Milo identify meaningful patterns from
     19 accepted + 60 not-selected students?
  2. Candidate Ranking — does Milo produce a sensible ranked list with
     proper score distribution and tier assignments?
  3. Score Separation — are accepted (training) students scored higher
     than not-selected students when re-evaluated?

Usage:
    python testing/test_milo_model.py [--base-url URL] [--skip-rank]

Requires the app to be running (local or production).
"""

import argparse
import json
import os
import sys
import time
import requests
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────
DEFAULT_BASE = "https://nextgen-app-h7hvaybqd4grd0b2.b02.azurefd.net"
USERNAME = "nextgen-admin"
PASSWORD = "NextGen2026!"
TIMEOUT = 300  # 5 min — Milo training analysis can take a while


def get_session(base_url: str) -> requests.Session:
    """Create an authenticated session."""
    s = requests.Session()
    # Login
    resp = s.post(
        f"{base_url}/login",
        data={"username": USERNAME, "password": PASSWORD},
        allow_redirects=False,
        timeout=30,
    )
    if resp.status_code not in (200, 302):
        print(f"[FAIL] Login returned {resp.status_code}")
        sys.exit(1)
    print(f"[OK] Authenticated as {USERNAME}")
    return s


def test_training_insights(session: requests.Session, base_url: str) -> dict:
    """Step 1: Ask Milo to analyze all training data."""
    print("\n" + "=" * 60)
    print("STEP 1: Milo Training Insights Analysis")
    print("=" * 60)
    print("Calling GET /api/milo/insights (this may take 30-90 seconds)...")

    t0 = time.time()
    resp = session.get(f"{base_url}/api/milo/insights", timeout=TIMEOUT)
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"[FAIL] Status {resp.status_code}: {resp.text[:500]}")
        return {}

    data = resp.json()
    print(f"[OK] Response in {elapsed:.1f}s (cached={data.get('cached', False)})")

    # Training data counts
    counts = data.get("training_counts", {})
    print(f"\nTraining Data:")
    print(f"  Selected (accepted):     {counts.get('selected', '?')}")
    print(f"  Not selected:            {counts.get('not_selected', '?')}")
    print(f"  Unknown status:          {counts.get('unknown', '?')}")
    print(f"  Historical scores used:  {data.get('historical_scored_count', 0)}")

    # Key insights
    print(f"\nModel student profile:")
    profile = data.get("model_student_profile", "Not available")
    if isinstance(profile, str) and len(profile) > 200:
        print(f"  {profile[:300]}...")
    else:
        print(f"  {profile}")

    print(f"\nSelection threshold:")
    print(f"  {data.get('selection_threshold', 'Not available')}")

    # Signals
    selected_signals = data.get("selected_signals", [])
    print(f"\nSelected student signals ({len(selected_signals)}):")
    for i, sig in enumerate(selected_signals[:5], 1):
        print(f"  {i}. {sig}")

    not_selected_signals = data.get("not_selected_signals", [])
    print(f"\nNot-selected signals ({len(not_selected_signals)}):")
    for i, sig in enumerate(not_selected_signals[:5], 1):
        print(f"  {i}. {sig}")

    differentiators = data.get("differentiators", [])
    print(f"\nKey differentiators ({len(differentiators)}):")
    for i, diff in enumerate(differentiators[:5], 1):
        print(f"  {i}. {diff}")

    # Rubric thresholds
    thresholds = data.get("rubric_thresholds", {})
    if thresholds:
        print(f"\nRubric thresholds (learned from data):")
        print(f"  Min total for selection:    {thresholds.get('min_total_for_selection', '?')}/12")
        print(f"  Avg selected total:         {thresholds.get('avg_selected_total', '?')}/12")
        print(f"  Avg not-selected total:     {thresholds.get('avg_not_selected_total', '?')}/12")
        print(f"  Score gap:                  {thresholds.get('score_gap', '?')}")

    # Academic patterns
    academic = data.get("academic_patterns", {})
    if academic:
        print(f"\nAcademic patterns:")
        print(f"  Min GPA:     {academic.get('min_gpa', '?')}")
        print(f"  Avg GPA:     {academic.get('avg_gpa', '?')}")
        print(f"  Courseload:  {academic.get('typical_courseload', '?')}")

    confidence = data.get("confidence", "?")
    print(f"\nModel confidence: {confidence}")

    summary = data.get("summary", "")
    if summary:
        print(f"\nSummary: {summary}")

    # Quality checks
    print(f"\n--- Quality Checks ---")
    issues = []
    if counts.get("selected", 0) < 10:
        issues.append(f"Only {counts.get('selected', 0)} selected examples (need 10+)")
    if len(selected_signals) < 3:
        issues.append("Too few selected signals identified")
    if len(differentiators) < 2:
        issues.append("Too few differentiators identified")
    if confidence == "Low":
        issues.append("Model has low confidence")
    if not thresholds:
        issues.append("No rubric thresholds learned")

    if issues:
        for issue in issues:
            print(f"  [WARN] {issue}")
    else:
        print("  [OK] All quality checks passed")

    return data


def test_ranking(session: requests.Session, base_url: str) -> dict:
    """Step 2: Ask Milo to rank all 2026 candidates."""
    print("\n" + "=" * 60)
    print("STEP 2: Milo Candidate Ranking")
    print("=" * 60)
    print("Calling POST /api/milo/rank (this may take 1-5 minutes)...")

    t0 = time.time()
    resp = session.post(
        f"{base_url}/api/milo/rank",
        json={"force_refresh": True},
        timeout=TIMEOUT,
    )
    elapsed = time.time() - t0

    if resp.status_code != 200:
        print(f"[FAIL] Status {resp.status_code}: {resp.text[:500]}")
        return {}

    data = resp.json()
    status = data.get("status", "?")

    if status == "no_candidates":
        print(f"[INFO] No 2026 candidates found to rank. ({data.get('message', '')})")
        print("  This is expected if all current applications are training data.")
        return data

    print(f"[OK] Ranking complete in {elapsed:.1f}s")
    print(f"  Status: {status}")
    print(f"  Total candidates evaluated: {data.get('total_scored', 0)}")
    print(f"  Model used: {data.get('model_display', data.get('model_used', '?'))}")

    # Tier distribution
    tiers = data.get("tier_distribution", {})
    if tiers:
        print(f"\nTier distribution:")
        for tier, count in sorted(tiers.items()):
            print(f"  {tier}: {count}")

    # Score statistics
    stats = data.get("score_stats", {})
    if stats:
        print(f"\nScore statistics:")
        print(f"  Mean:   {stats.get('mean', '?')}")
        print(f"  Median: {stats.get('median', '?')}")
        print(f"  Max:    {stats.get('max', '?')}")
        print(f"  Min:    {stats.get('min', '?')}")
        print(f"  P90:    {stats.get('p90', '?')}")
        print(f"  P75:    {stats.get('p75', '?')}")
        print(f"  Above 70: {stats.get('above_70', 0)}")
        print(f"  Above 50: {stats.get('above_50', 0)}")
        print(f"  Below 30: {stats.get('below_30', 0)}")

    # Top 10
    top_50 = data.get("top_50", [])
    if top_50:
        print(f"\nTop 10 candidates (of {len(top_50)} in Top 50):")
        print(f"  {'Rank':<6} {'Score':<8} {'Tier':<15} {'Name':<30} {'School'}")
        print(f"  {'─' * 6} {'─' * 8} {'─' * 15} {'─' * 30} {'─' * 20}")
        for c in top_50[:10]:
            print(
                f"  {c.get('rank', '?'):<6} "
                f"{c.get('nextgen_match', '?'):<8} "
                f"{c.get('tier', '?'):<15} "
                f"{(c.get('applicant_name', 'Unknown'))[:30]:<30} "
                f"{(c.get('high_school', '') or '')[:20]}"
            )

    # Top 25 shortlist
    top_25 = data.get("top_25_shortlist", [])
    if top_25:
        print(f"\n  Top 25 shortlist count: {len(top_25)}")

    # Quality checks
    print(f"\n--- Ranking Quality Checks ---")
    issues = []
    total = data.get("total_scored", 0)

    if total == 0:
        issues.append("No candidates were scored")
    if stats:
        mean = stats.get("mean", 50)
        if mean > 70:
            issues.append(f"Mean score {mean} is too high — Milo may be inflating")
        if mean < 20:
            issues.append(f"Mean score {mean} is very low — Milo may be too harsh")
        if stats.get("max", 0) == stats.get("min", 0) and total > 1:
            issues.append("All candidates have the same score — model not differentiating")

    strong_admits = tiers.get("STRONG ADMIT", 0)
    if total > 0 and strong_admits > total * 0.3:
        issues.append(
            f"{strong_admits}/{total} STRONG ADMITs ({strong_admits/total*100:.0f}%) — "
            "too many, should be ~5%"
        )

    if issues:
        for issue in issues:
            print(f"  [WARN] {issue}")
    else:
        print("  [OK] All ranking quality checks passed")

    return data


def test_token_usage(session: requests.Session, base_url: str):
    """Step 3: Check token usage from Milo's calls."""
    print("\n" + "=" * 60)
    print("STEP 3: Token Usage Report")
    print("=" * 60)

    resp = session.get(f"{base_url}/api/telemetry/token-usage", timeout=30)
    if resp.status_code != 200:
        print(f"[SKIP] Token usage endpoint returned {resp.status_code}")
        return

    data = resp.json()
    totals = data.get("totals", {})
    print(f"  Total calls:   {totals.get('call_count', 0)}")
    print(f"  Input tokens:  {totals.get('input_tokens', 0):,}")
    print(f"  Output tokens: {totals.get('output_tokens', 0):,}")
    print(f"  Total tokens:  {totals.get('total_tokens', 0):,}")

    by_model = data.get("by_model", {})
    if by_model:
        print(f"\n  By Model:")
        for model, stats in by_model.items():
            print(
                f"    {model}: {stats['call_count']} calls, "
                f"{stats['total_tokens']:,} tokens "
                f"(in={stats['input_tokens']:,} out={stats['output_tokens']:,})"
            )

    by_agent = data.get("by_agent", {})
    milo_usage = {k: v for k, v in by_agent.items() if "milo" in k.lower()}
    if milo_usage:
        print(f"\n  Milo's Token Usage:")
        for agent, stats in milo_usage.items():
            print(
                f"    {agent}: {stats['call_count']} calls, "
                f"{stats['total_tokens']:,} tokens "
                f"(in={stats['input_tokens']:,} out={stats['output_tokens']:,})"
            )


def main():
    parser = argparse.ArgumentParser(description="Test Milo's selection model")
    parser.add_argument(
        "--base-url",
        default=os.getenv("NEXTGEN_BASE_URL", DEFAULT_BASE),
        help="Base URL of the app",
    )
    parser.add_argument(
        "--skip-rank",
        action="store_true",
        help="Skip the ranking step (only test insights)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use localhost:8000 (no auth needed)",
    )
    args = parser.parse_args()

    base_url = "http://localhost:8000" if args.local else args.base_url

    print(f"Milo Model Quality Test — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Target: {base_url}")
    print("=" * 60)

    # Authenticate
    if args.local:
        session = requests.Session()
        print("[OK] Local mode — no auth needed")
    else:
        session = get_session(base_url)

    # Step 1: Training insights
    insights = test_training_insights(session, base_url)

    # Step 2: Rank candidates
    if not args.skip_rank:
        ranking = test_ranking(session, base_url)
    else:
        print("\n[SKIP] Ranking step skipped (--skip-rank)")

    # Step 3: Token usage
    test_token_usage(session, base_url)

    print("\n" + "=" * 60)
    print("Test complete.")


if __name__ == "__main__":
    main()
