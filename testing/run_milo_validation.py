#!/usr/bin/env python3
"""Run Milo model validation against production.

Uses the async validation endpoint:
  POST /api/milo/validate  -> starts the job
  GET  /api/milo/validate  -> polls for results
"""

import requests
import json
import time
import sys

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://nextgen-agents-web.azurewebsites.net"
THRESHOLD = int(sys.argv[2]) if len(sys.argv) > 2 else 65
s = requests.Session()

# Login
r = s.post(
    f"{BASE}/login",
    data={"username": "nextgen-admin", "password": "NextGen2026!"},
    allow_redirects=False,
    timeout=120,
)
print(f"Login: {r.status_code}")
if r.status_code not in (200, 302):
    print("Login failed")
    sys.exit(1)

# Start validation
print(f"Starting Milo validation (threshold={THRESHOLD})...")
r = s.post(f"{BASE}/api/milo/validate", json={"threshold": THRESHOLD}, timeout=30)
print(f"Start: {r.status_code} - {r.json().get('status', '?')}")

if r.status_code != 200:
    print(r.text[:1000])
    sys.exit(1)

# Poll for results
print("Polling for results...")
poll_interval = 10
max_polls = 60  # 10 minutes max
for attempt in range(max_polls):
    time.sleep(poll_interval)
    r = s.get(f"{BASE}/api/milo/validate", timeout=30)
    data = r.json()
    status = data.get("status", "?")

    if status == "running":
        elapsed = data.get("elapsed_seconds", 0)
        progress = data.get("progress", "")
        print(f"  [{elapsed:.0f}s] {progress}")
        continue

    if status == "error":
        print(f"  ERROR: {data.get('error', '?')}")
        sys.exit(1)

    if status == "success":
        print(f"  Done! Completed in {data.get('elapsed_seconds', '?')}s")
        break

    # idle or unexpected
    print(f"  Unexpected status: {status}")
    if attempt > 3:
        sys.exit(1)
else:
    print("  Timed out waiting for validation to complete")
    sys.exit(1)

# Save full results
with open("testing/milo_validation_results.json", "w") as f:
    json.dump(data, f, indent=2, default=str)
print("Full results saved to testing/milo_validation_results.json")

# Print summary
print()
print("=" * 60)
print("MILO MODEL VALIDATION RESULTS")
print("=" * 60)
print(f"Model: {data.get('model_display', '?')}")
print(f"Threshold: {data.get('threshold')}")
print(f"Total students: {data.get('total_training_students')}")
print(f"  Accepted: {data.get('accepted_count')}")
print(f"  Not selected: {data.get('not_selected_count')}")

metrics = data.get("metrics", {})
print()
print("--- Metrics ---")
acc = metrics.get("accuracy", 0)
prec = metrics.get("precision", 0)
rec = metrics.get("recall", 0)
f1 = metrics.get("f1_score", 0)
print(f"  Accuracy:  {acc:.1%}")
print(f"  Precision: {prec:.1%}")
print(f"  Recall:    {rec:.1%}")
print(f"  F1 Score:  {f1:.1%}")

cm = data.get("confusion_matrix", {})
print()
print("--- Confusion Matrix ---")
print(f"  True Positives  (correctly identified accepted):  {cm.get('true_positives')}")
print(f"  True Negatives  (correctly identified rejected):  {cm.get('true_negatives')}")
print(f"  False Positives (predicted accepted, was not):    {cm.get('false_positives')}")
print(f"  False Negatives (predicted rejected, was accept): {cm.get('false_negatives')}")

dist = data.get("score_distribution", {})
print()
print("--- Score Distribution ---")
print(
    f"  Accepted students:     mean={dist.get('accepted_mean')}, "
    f"median={dist.get('accepted_median')}, "
    f"range=[{dist.get('accepted_min')}-{dist.get('accepted_max')}]"
)
print(
    f"  Not-selected students: mean={dist.get('not_selected_mean')}, "
    f"median={dist.get('not_selected_median')}, "
    f"range=[{dist.get('not_selected_min')}-{dist.get('not_selected_max')}]"
)
print(f"  Score separation:      {dist.get('separation')} points")

# Per-student breakdown
students = data.get("students", [])
print()
print("--- All Students (ranked by score) ---")
header = f"{'Rank':<6} {'Score':<8} {'Tier':<16} {'Actual':<14} {'OK':<4} Name"
print(header)
print("-" * len(header))
for st in students:
    ok = "Y" if st.get("predicted_correct") else "N"
    name = st.get("name", "Unknown")[:30]
    print(
        f"{st['rank']:<6} "
        f"{st.get('score', 0):<8} "
        f"{st.get('tier', '?'):<16} "
        f"{st['actual']:<14} "
        f"{ok:<4} "
        f"{name}"
    )

# Token usage
print()
print("--- Token Usage After Validation ---")
try:
    r2 = s.get(f"{BASE}/api/telemetry/token-usage", timeout=30)
    if r2.status_code == 200:
        tu = r2.json()
        totals = tu.get("totals", {})
        print(f"  Total calls:   {totals.get('call_count', 0)}")
        print(f"  Input tokens:  {totals.get('input_tokens', 0):,}")
        print(f"  Output tokens: {totals.get('output_tokens', 0):,}")
        print(f"  Total tokens:  {totals.get('total_tokens', 0):,}")
except Exception:
    print("  (unavailable)")

print()
print("=" * 60)
print("Validation complete.")
