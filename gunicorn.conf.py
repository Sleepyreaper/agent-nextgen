"""Gunicorn configuration — single source of truth for all deployment paths.

Environment variables override defaults so the same config file works in both
App Service (2 workers / 4 threads) and container mode (1 worker / 2 threads,
scale via replicas).

  GUNICORN_WORKERS  — number of worker processes  (default: 2)
  GUNICORN_THREADS  — threads per worker           (default: 4)
  GUNICORN_TIMEOUT  — request timeout in seconds   (default: 120)
  PORT              — bind port                    (default: 8000)
"""
import os

# ── Worker / thread configuration ──────────────────────────────────
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

# ── Networking ─────────────────────────────────────────────────────
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))

# ── Logging ────────────────────────────────────────────────────────
accesslog = "-"
errorlog = "-"
