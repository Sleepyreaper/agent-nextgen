"""Gunicorn configuration — single source of truth for all deployment paths.

Environment variables override defaults so the same config file works in both
App Service (2 workers / 4 threads) and container mode (1 worker / 2 threads,
scale via replicas).

  GUNICORN_WORKERS  — number of worker processes  (default: 2)
  GUNICORN_THREADS  — threads per worker           (default: 4)
  GUNICORN_TIMEOUT  — request timeout in seconds   (default: 300)
  PORT              — bind port                    (default: 8000)
"""
import os

# ── Worker / thread configuration ──────────────────────────────────
# App Service: 4 workers × 4 threads = 16 concurrent requests.
# Agent processing blocks a thread for 2-5 minutes, so we need enough
# headroom that the site stays responsive during evaluation runs.
workers = int(os.environ.get("GUNICORN_WORKERS", "4"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# ── Networking ─────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Must exceed Azure Front Door origin timeout (240s) so the worker stays
# alive long enough for Front Door to receive a response or its own timeout.
# Agent pipelines (Rapunzel, Belle, Merlin) can take 2-5 min per student.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "300"))

# ── Logging ────────────────────────────────────────────────────────
accesslog = "-"
errorlog = "-"
