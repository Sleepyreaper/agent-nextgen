"""Shared extensions, agent factories, and helpers used across Flask blueprints.

This module holds objects that are created once and shared by all route
modules.  ``csrf`` and ``limiter`` are initialised lazily via ``init_app()``
in ``app.py``; everything else is usable as soon as it's imported.
"""

import asyncio
import difflib
import hashlib
import json
import logging
import os
import re
import threading
import time
import uuid

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from flask import current_app, jsonify, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

from src.config import config
from src.database import db
from src.storage import storage
from src.telemetry import telemetry
from src.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask extensions (lazy-init via init_app in app.py)
# ---------------------------------------------------------------------------
csrf = CSRFProtect()
limiter = Limiter(
    get_remote_address,
    default_limits=["200 per minute"],
    storage_uri=f"redis://{config.redis_host}:6379/0",  # Changed to Redis for shared rate limiter storage
)


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------
VALID_ROLES = {'admin', 'reviewer', 'readonly'}


def require_role(*roles):
    """Decorator: restrict a route to users whose session role is in *roles*."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_role = session.get('role', 'readonly')
            if user_role not in roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Insufficient permissions'}), 403
                return '<h1>403 — Forbidden</h1>', 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator

# ---------------------------------------------------------------------------
# Shared background event loop (Issue #52)
# ---------------------------------------------------------------------------
_bg_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()


def _start_bg_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


_bg_thread = threading.Thread(target=_start_bg_loop, args=(_bg_loop,), daemon=True)
_bg_thread.start()


def run_async(coro, timeout: float = 1800.0):
    """Submit a coroutine to the shared event loop and block until done."""
    future = asyncio.run_coroutine_threadsafe(coro, _bg_loop)
    return future.result(timeout=timeout)


# ---------------------------------------------------------------------------
# Agent singletons
# ---------------------------------------------------------------------------
evaluator_agent = None
orchestrator_agent = None
belle_analyzer = None
mirabel_analyzer = None
feedback_agent = None

# In-memory tracking for test sessions
test_submissions: Dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Agent imports
# ---------------------------------------------------------------------------
try:
    from src.agents.ariel_adapter import ArielQAAgent
except Exception as _e:
    ArielQAAgent = None
    logger.warning("ArielQAAgent not available: %s", _e)

try:
    from src.agents.aurora_agent import AuroraAgent
except Exception as _e:
    AuroraAgent = None
    logger.warning("AuroraAgent not available: %s", _e)

from src.agents.foundry_client import FoundryClient
from src.agents.smee_orchestrator import SmeeOrchestrator
from src.agents.tiana_application_reader import TianaApplicationReader
from src.agents.rapunzel_grade_reader import RapunzelGradeReader
from src.agents.mulan_recommendation_reader import MulanRecommendationReader
from src.agents.merlin_student_evaluator import MerlinStudentEvaluator
from src.agents.gaston_evaluator import GastonEvaluator
from src.agents.bashful_agent import BashfulAgent
from src.agents.belle_document_analyzer import BelleDocumentAnalyzer
from src.agents.mirabel_video_analyzer import MirabelVideoAnalyzer
from src.agents.milo_data_scientist import MiloDataScientist
from src.agents.naveen_school_data_scientist import NaveenSchoolDataScientist
from src.agents.pocahontas_cohort_analyst import PocahontasCohortAnalyst
from src.agents.moana_school_context import MoanaSchoolContext
from src.agents.fairy_godmother_document_generator import FairyGodmotherDocumentGenerator
from src.agents.feedback_triage_agent import ScuttleFeedbackTriageAgent, FeedbackTriageAgent
from src.agents.agent_monitor import get_agent_monitor

# Aurora agent singleton
if AuroraAgent is not None:
    aurora = AuroraAgent()
else:
    aurora = None


# ---------------------------------------------------------------------------
# AI client helpers
# ---------------------------------------------------------------------------
def get_ai_client(api_version: str = None, azure_deployment: str = None):
    """Get Azure OpenAI / Foundry client."""
    if api_version is None:
        api_version = config.api_version
    if azure_deployment is None:
        azure_deployment = config.deployment_name

    if config.model_provider and config.model_provider.lower() == "foundry":
        return FoundryClient(endpoint=config.foundry_project_endpoint)

    if config.azure_openai_api_key:
        try:
            from openai import AzureOpenAI
        except ImportError as e:
            raise RuntimeError("AzureOpenAI client requested but openai package is not installed") from e
        return AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=api_version,
            azure_endpoint=config.azure_openai_endpoint,
            azure_deployment=azure_deployment,
        )

    from 