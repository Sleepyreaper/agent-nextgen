"""OpenTelemetry setup for agent tracing - Enhanced with event tracking.

Telemetry data is persisted to the ``telemetry_events`` PostgreSQL table so
it survives process restarts and is consistent across gunicorn workers.
In-memory counters are still maintained for sub-second dashboard updates
within a single worker's lifetime.
"""

import os
import json
import logging
import time
import threading
from collections import defaultdict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from opentelemetry import trace, metrics
from opentelemetry.trace import SpanKind
from src.observability import (
    configure_observability,
    get_tracer,
    get_meter,
    should_capture_sensitive_data,
    is_observability_enabled,
)

_logger = logging.getLogger(__name__)

_telemetry_initialized = False


def initialize_telemetry(service_name: str = "agent-framework", capture_sensitive_data: bool = False) -> None:
    """
    Initialize telemetry using OpenTelemetry with Application Insights.
    
    Args:
        service_name: Name of the service for telemetry identification
        capture_sensitive_data: Whether to include prompts and responses in telemetry
    """
    global _telemetry_initialized
    
    if _telemetry_initialized:
        return
    
    configure_observability(
        service_name=service_name,
        enable_azure_monitor=True,
        enable_console_exporters=os.getenv("ENABLE_CONSOLE_EXPORTERS", "false").lower() == "true",
        capture_sensitive_data=capture_sensitive_data or os.getenv("ENABLE_SENSITIVE_DATA", "false").lower() == "true",
    )
    
    _telemetry_initialized = True


class NextGenTelemetry:
    """Wrapper for application telemetry tracking using OpenTelemetry.

    Model-call telemetry is persisted to the ``telemetry_events`` PostgreSQL
    table so the dashboard survives deploys and is consistent across workers.
    """

    _db_table_ready = False  # class-level flag — one-time table creation

    def __init__(self):
        # Cache counters to avoid re-creating on every call
        self._counters = {}
        # In-memory token usage accumulation
        self._lock = threading.Lock()
        self._token_by_model: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )
        self._token_by_agent: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )
        self._token_by_agent_model: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        )
        self._token_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
        self._recent_calls: List[Dict[str, Any]] = []  # last N model calls
        self._max_recent = 200
        self._tracking_since = datetime.now(timezone.utc).isoformat()

    # ── Database persistence ──────────────────────────────────────────

    @classmethod
    def _ensure_db_table(cls) -> bool:
        """Create ``telemetry_events`` table if it doesn't exist (idempotent)."""
        if cls._db_table_ready:
            return True
        try:
            from src.database import db
            db.execute_non_query("""
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    id              SERIAL PRIMARY KEY,
                    event_type      VARCHAR(50) NOT NULL DEFAULT 'model_call',
                    agent_name      VARCHAR(200),
                    model           VARCHAR(200),
                    input_tokens    INTEGER DEFAULT 0,
                    output_tokens   INTEGER DEFAULT 0,
                    total_tokens    INTEGER DEFAULT 0,
                    duration_ms     REAL    DEFAULT 0,
                    success         BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            # Indexes for fast dashboard queries
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_telem_created ON telemetry_events (created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_telem_agent   ON telemetry_events (agent_name)",
                "CREATE INDEX IF NOT EXISTS idx_telem_model   ON telemetry_events (model)",
            ]:
                try:
                    db.execute_non_query(idx_sql)
                except Exception:
                    pass  # OK if index already exists
            cls._db_table_ready = True
            return True
        except Exception as exc:
            _logger.debug("telemetry_events table creation skipped: %s", exc)
            return False

    def _persist_to_db(
        self,
        model: str,
        agent_name: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Write a model call to the DB (fire-and-forget)."""
        try:
            if not self._ensure_db_table():
                _logger.warning("telemetry_events table not available — skipping DB write for %s", agent_name)
                return
            from src.database import db
            db.execute_non_query(
                """INSERT INTO telemetry_events
                       (event_type, agent_name, model,
                        input_tokens, output_tokens, total_tokens,
                        duration_ms, success)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                ('model_call', agent_name, model,
                 input_tokens, output_tokens, input_tokens + output_tokens,
                 round(duration_ms, 1), success),
            )
        except Exception as exc:
            _logger.debug("telemetry DB write failed: %s", exc)

    # ── DB query helpers (for API endpoints) ──────────────────────────

    @classmethod
    def query_db_token_usage(cls) -> Dict[str, Any]:
        """Query aggregated token usage from the ``telemetry_events`` table.

        Returns the same structure as ``get_token_usage()`` but sourced from
        the persistent database instead of in-memory counters.
        """
        empty = {
            "totals": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0},
            "by_model": {},
            "by_agent": {},
            "by_agent_model": {},
            "recent_calls": [],
            "tracking_since": None,
        }
        try:
            if not cls._ensure_db_table():
                return empty
            from src.database import db

            # Grand totals
            rows = db.execute_query("""
                SELECT COALESCE(SUM(input_tokens),0) AS input_tokens,
                       COALESCE(SUM(output_tokens),0) AS output_tokens,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COUNT(*) AS call_count,
                       MIN(created_at) AS first_event
                FROM telemetry_events
            """)
            totals = rows[0] if rows else {}
            empty["totals"] = {
                "input_tokens": int(totals.get("input_tokens", 0)),
                "output_tokens": int(totals.get("output_tokens", 0)),
                "total_tokens": int(totals.get("total_tokens", 0)),
                "call_count": int(totals.get("call_count", 0)),
            }
            if totals.get("first_event"):
                empty["tracking_since"] = str(totals["first_event"])

            # By model
            rows = db.execute_query("""
                SELECT model,
                       COALESCE(SUM(input_tokens),0) AS input_tokens,
                       COALESCE(SUM(output_tokens),0) AS output_tokens,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COUNT(*) AS call_count
                FROM telemetry_events GROUP BY model ORDER BY total_tokens DESC
            """)
            for r in (rows or []):
                empty["by_model"][r["model"] or "unknown"] = {
                    "input_tokens": int(r["input_tokens"]),
                    "output_tokens": int(r["output_tokens"]),
                    "total_tokens": int(r["total_tokens"]),
                    "call_count": int(r["call_count"]),
                }

            # By agent
            rows = db.execute_query("""
                SELECT agent_name,
                       COALESCE(SUM(input_tokens),0) AS input_tokens,
                       COALESCE(SUM(output_tokens),0) AS output_tokens,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COUNT(*) AS call_count
                FROM telemetry_events GROUP BY agent_name ORDER BY total_tokens DESC
            """)
            for r in (rows or []):
                empty["by_agent"][r["agent_name"] or "unknown"] = {
                    "input_tokens": int(r["input_tokens"]),
                    "output_tokens": int(r["output_tokens"]),
                    "total_tokens": int(r["total_tokens"]),
                    "call_count": int(r["call_count"]),
                }

            # By agent+model combo
            rows = db.execute_query("""
                SELECT agent_name, model,
                       COALESCE(SUM(input_tokens),0) AS input_tokens,
                       COALESCE(SUM(output_tokens),0) AS output_tokens,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       COUNT(*) AS call_count
                FROM telemetry_events GROUP BY agent_name, model
                ORDER BY total_tokens DESC
            """)
            for r in (rows or []):
                key = f"{r['agent_name'] or 'unknown'}::{r['model'] or 'unknown'}"
                empty["by_agent_model"][key] = {
                    "input_tokens": int(r["input_tokens"]),
                    "output_tokens": int(r["output_tokens"]),
                    "total_tokens": int(r["total_tokens"]),
                    "call_count": int(r["call_count"]),
                }

            # Recent calls (last 50)
            rows = db.execute_query("""
                SELECT agent_name, model, input_tokens, output_tokens,
                       total_tokens, duration_ms, success, created_at
                FROM telemetry_events
                ORDER BY created_at DESC LIMIT 50
            """)
            for r in (rows or []):
                empty["recent_calls"].append({
                    "timestamp": str(r.get("created_at", "")),
                    "model": r.get("model", "unknown"),
                    "agent": r.get("agent_name", "unknown"),
                    "input_tokens": int(r.get("input_tokens", 0)),
                    "output_tokens": int(r.get("output_tokens", 0)),
                    "total_tokens": int(r.get("total_tokens", 0)),
                    "duration_ms": round(float(r.get("duration_ms", 0)), 1),
                    "success": r.get("success", True),
                })

            return empty
        except Exception as exc:
            _logger.debug("query_db_token_usage failed: %s", exc)
            return empty

    @classmethod
    def query_db_agent_summary(cls) -> Dict[str, Dict[str, Any]]:
        """Query per-agent summary statistics from the DB.

        Returns a dict keyed by agent_name with totals, success rate, avg
        duration, and models used — the same shape the dashboard expects.
        """
        try:
            if not cls._ensure_db_table():
                return {}
            from src.database import db
            rows = db.execute_query("""
                SELECT agent_name,
                       COUNT(*)                     AS total,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) AS fail_count,
                       ROUND(AVG(duration_ms)::numeric, 1)      AS avg_duration_ms,
                       MIN(duration_ms)             AS min_duration_ms,
                       MAX(duration_ms)             AS max_duration_ms,
                       COALESCE(SUM(total_tokens),0) AS total_tokens,
                       MAX(created_at)              AS last_run,
                       ARRAY_AGG(DISTINCT model)    AS models_used
                FROM telemetry_events
                GROUP BY agent_name
                ORDER BY total DESC
            """)
            result: Dict[str, Dict[str, Any]] = {}
            for r in (rows or []):
                name = r.get("agent_name") or "unknown"
                total = int(r.get("total", 0))
                success = int(r.get("success_count", 0))
                result[name] = {
                    "total": total,
                    "success": success,
                    "failed": int(r.get("fail_count", 0)),
                    "total_duration_ms": 0,
                    "min_duration_ms": float(r.get("min_duration_ms") or 0),
                    "max_duration_ms": float(r.get("max_duration_ms") or 0),
                    "avg_duration_ms": float(r.get("avg_duration_ms") or 0),
                    "success_rate": round((success / total) * 100, 1) if total > 0 else 0,
                    "total_tokens": int(r.get("total_tokens", 0)),
                    "last_run": str(r.get("last_run", "")),
                    "models_used": [m for m in (r.get("models_used") or []) if m],
                }
            return result
        except Exception as exc:
            _logger.debug("query_db_agent_summary failed: %s", exc)
            return {}

    @classmethod
    def query_db_recent_executions(cls, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent model calls for the Recent Executions panel."""
        try:
            if not cls._ensure_db_table():
                return []
            from src.database import db
            rows = db.execute_query("""
                SELECT agent_name, model AS model_used,
                       duration_ms, success,
                       created_at AS timestamp
                FROM telemetry_events
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            results = []
            for r in (rows or []):
                results.append({
                    "agent_name": r.get("agent_name", "unknown"),
                    "model_used": r.get("model_used", ""),
                    "duration_ms": round(float(r.get("duration_ms", 0)), 1),
                    "status": "completed" if r.get("success", True) else "failed",
                    "timestamp": str(r.get("timestamp", "")),
                })
            return results
        except Exception as exc:
            _logger.debug("query_db_recent_executions failed: %s", exc)
            return []

    @classmethod
    def query_db_overview_stats(cls) -> Dict[str, Any]:
        """Return aggregate stats for the overview endpoint."""
        try:
            if not cls._ensure_db_table():
                return {}
            from src.database import db
            rows = db.execute_query("""
                SELECT COUNT(*)                     AS total_calls,
                       SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) AS total_errors,
                       ROUND(AVG(duration_ms)::numeric, 1) AS avg_duration_ms
                FROM telemetry_events
            """)
            if rows:
                r = rows[0]
                return {
                    "total_calls": int(r.get("total_calls", 0)),
                    "total_errors": int(r.get("total_errors", 0)),
                    "avg_duration_ms": float(r.get("avg_duration_ms") or 0),
                }
            return {}
        except Exception as exc:
            _logger.debug("query_db_overview_stats failed: %s", exc)
            return {}

    def _get_counter(self, name: str):
        """Get or create a cached counter instrument."""
        if name not in self._counters:
            meter = get_meter()
            if meter:
                self._counters[name] = meter.create_counter(name)
        return self._counters.get(name)
    
    def track_event(self, event_name: str, properties: Dict[str, Any] = None, metrics_data: Dict[str, float] = None) -> None:
        """
        Track a custom event and metrics.
        
        Args:
            event_name: Name of the event
            properties: Event properties/attributes
            metrics_data: Numeric metrics associated with the event
        """
        if not is_observability_enabled():
            return
        
        try:
            if metrics_data:
                for metric_name, value in metrics_data.items():
                    counter = self._get_counter(f"{event_name}.{metric_name}")
                    if counter:
                        counter.add(value, properties or {})
        except Exception:
            pass
    
    def log_agent_execution(
        self,
        agent_name: str,
        model: str,
        success: bool,
        processing_time_ms: float,
        tokens_used: int = 0,
        confidence: str = "Unknown",
        result_summary: Dict[str, Any] = None
    ) -> None:
        """
        Log agent execution with comprehensive telemetry.
        
        Args:
            agent_name: Name of the agent
            model: Model used
            success: Whether execution was successful
            processing_time_ms: Processing time in milliseconds
            tokens_used: Number of tokens used
            confidence: Confidence level
            result_summary: Summary of results
        """
        tracer = get_tracer()
        
        # Create span for agent execution
        if tracer:
            with tracer.start_as_current_span(f"agent_execution_{agent_name}") as span:
                span.set_attribute("agent.name", agent_name)
                span.set_attribute("gen_ai.agent.name", agent_name)
                span.set_attribute("gen_ai.model", model)
                span.set_attribute("gen_ai.operation.name", "agent_execution")
                span.set_attribute("success", success)
                span.set_attribute("processing_time_ms", float(processing_time_ms))
                span.set_attribute("confidence", confidence)
                
                if tokens_used > 0:
                    span.set_attribute("gen_ai.usage.total_tokens", tokens_used)
                
                if result_summary:
                    for key, value in result_summary.items():
                        try:
                            span.set_attribute(f"result.{key}", str(value))
                        except Exception:
                            pass
        
        # Record metrics
        try:
            duration_ctr = self._get_counter("agent_execution_duration_ms")
            if duration_ctr:
                duration_ctr.add(processing_time_ms, {"agent": agent_name, "model": model})
            
            if tokens_used > 0:
                token_ctr = self._get_counter("agent_tokens_used")
                if token_ctr:
                    token_ctr.add(tokens_used, {"agent": agent_name})
            
            status_ctr = self._get_counter("agent_execution_status")
            if status_ctr:
                status_ctr.add(1, {"agent": agent_name, "status": "success" if success else "failure"})
        except Exception:
            pass
    
    def log_model_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        success: bool = True,
        agent_name: str = "",
    ) -> None:
        """
        Log a call to the AI model with token usage tracking.
        
        Args:
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            duration_ms: Duration in milliseconds
            success: Whether the call succeeded
            agent_name: Name of the calling agent
        """
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
        tracer = get_tracer()
        
        if tracer:
            with tracer.start_as_current_span("model_call") as span:
                span.set_attribute("gen_ai.model", model or "")
                span.set_attribute("gen_ai.system", "azure_openai")
                span.set_attribute("gen_ai.usage.prompt_tokens", input_tokens or 0)
                span.set_attribute("gen_ai.usage.completion_tokens", output_tokens or 0)
                span.set_attribute("gen_ai.usage.total_tokens", total_tokens)
                span.set_attribute("duration_ms", float(duration_ms))
                span.set_attribute("success", success)
                if agent_name:
                    span.set_attribute("gen_ai.agent.name", agent_name)
        
        # OpenTelemetry metric counters (split by token type)
        try:
            input_ctr = self._get_counter("gen_ai.client.token.usage.input")
            if input_ctr:
                attrs = {"gen_ai.request.model": model or "unknown", "gen_ai.token.type": "input"}
                if agent_name:
                    attrs["gen_ai.agent.name"] = agent_name
                input_ctr.add(input_tokens or 0, attrs)

            output_ctr = self._get_counter("gen_ai.client.token.usage.output")
            if output_ctr:
                attrs = {"gen_ai.request.model": model or "unknown", "gen_ai.token.type": "output"}
                if agent_name:
                    attrs["gen_ai.agent.name"] = agent_name
                output_ctr.add(output_tokens or 0, attrs)

            duration_ctr = self._get_counter("gen_ai.client.operation.duration_ms")
            if duration_ctr:
                attrs = {"gen_ai.request.model": model or "unknown"}
                if agent_name:
                    attrs["gen_ai.agent.name"] = agent_name
                duration_ctr.add(duration_ms, attrs)

            call_ctr = self._get_counter("gen_ai.client.call.count")
            if call_ctr:
                attrs = {
                    "gen_ai.request.model": model or "unknown",
                    "success": str(success).lower(),
                }
                if agent_name:
                    attrs["gen_ai.agent.name"] = agent_name
                call_ctr.add(1, attrs)
        except Exception:
            pass

        # In-memory accumulation for the app API
        self._accumulate_token_usage(
            model=model or "unknown",
            agent_name=agent_name or "unknown",
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            duration_ms=duration_ms,
            success=success,
        )
    
    # ── In-memory token usage accumulation ────────────────────────────

    def _accumulate_token_usage(
        self,
        model: str,
        agent_name: str,
        input_tokens: int,
        output_tokens: int,
        duration_ms: float,
        success: bool,
    ) -> None:
        """Accumulate token usage in memory AND persist to DB."""
        total = input_tokens + output_tokens
        with self._lock:
            # By model
            m = self._token_by_model[model]
            m["input_tokens"] += input_tokens
            m["output_tokens"] += output_tokens
            m["total_tokens"] += total
            m["call_count"] += 1

            # By agent
            a = self._token_by_agent[agent_name]
            a["input_tokens"] += input_tokens
            a["output_tokens"] += output_tokens
            a["total_tokens"] += total
            a["call_count"] += 1

            # By agent+model combo
            key = f"{agent_name}::{model}"
            am = self._token_by_agent_model[key]
            am["input_tokens"] += input_tokens
            am["output_tokens"] += output_tokens
            am["total_tokens"] += total
            am["call_count"] += 1

            # Grand total
            self._token_total["input_tokens"] += input_tokens
            self._token_total["output_tokens"] += output_tokens
            self._token_total["total_tokens"] += total
            self._token_total["call_count"] += 1

            # Recent calls ring buffer
            self._recent_calls.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "agent": agent_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total,
                "duration_ms": round(duration_ms, 1),
                "success": success,
            })
            if len(self._recent_calls) > self._max_recent:
                self._recent_calls = self._recent_calls[-self._max_recent:]

        # Persist to DB outside the lock (fire-and-forget)
        self._persist_to_db(model, agent_name, input_tokens, output_tokens, duration_ms, success)

    # ---- Cost estimation (per 1M tokens, Azure AI pricing as of 2025-Q2) ----
    _MODEL_COST_PER_1M: Dict[str, Dict[str, float]] = {
        # model-name-prefix → { input $/1M, output $/1M }
        "gpt-4.1":      {"input": 2.00,  "output": 8.00},
        "gpt-4.1-mini": {"input": 0.40,  "output": 1.60},
        "gpt-4.1-nano": {"input": 0.10,  "output": 0.40},
        "gpt-4o":       {"input": 2.50,  "output": 10.00},
        "gpt-4o-mini":  {"input": 0.15,  "output": 0.60},
        "o3-mini":      {"input": 1.10,  "output": 4.40},
        "o3":           {"input": 10.00, "output": 40.00},
        "o1":           {"input": 15.00, "output": 60.00},
        "o1-mini":      {"input": 1.10,  "output": 4.40},
        "gpt-4":        {"input": 30.00, "output": 60.00},
        "gpt-35-turbo": {"input": 0.50,  "output": 1.50},
    }
    _DEFAULT_COST = {"input": 2.00, "output": 8.00}

    @classmethod
    def _estimate_cost(cls, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost for a model call."""
        model_lower = (model or "").lower().strip()
        pricing = cls._DEFAULT_COST
        # Match longest prefix first
        for prefix in sorted(cls._MODEL_COST_PER_1M.keys(), key=len, reverse=True):
            if model_lower.startswith(prefix):
                pricing = cls._MODEL_COST_PER_1M[prefix]
                break
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    @classmethod
    def _enrich_with_cost(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Add estimated_cost_usd fields to token usage data."""
        # Totals cost (use default pricing — model-specific is in by_model)
        totals = data.get("totals", {})
        total_cost = 0.0

        # By-model cost
        for model, stats in data.get("by_model", {}).items():
            c = cls._estimate_cost(model, stats.get("input_tokens", 0), stats.get("output_tokens", 0))
            stats["estimated_cost_usd"] = round(c, 4)
            total_cost += c

        # By-agent cost (sum across models per agent using agent_model breakdown)
        agent_costs: Dict[str, float] = {}
        for key, stats in data.get("by_agent_model", {}).items():
            parts = key.split("::", 1)
            agent = parts[0] if parts else "unknown"
            model = parts[1] if len(parts) > 1 else "unknown"
            c = cls._estimate_cost(model, stats.get("input_tokens", 0), stats.get("output_tokens", 0))
            stats["estimated_cost_usd"] = round(c, 4)
            agent_costs[agent] = agent_costs.get(agent, 0.0) + c
        for agent, stats in data.get("by_agent", {}).items():
            stats["estimated_cost_usd"] = round(agent_costs.get(agent, 0.0), 4)

        totals["estimated_cost_usd"] = round(total_cost, 4)
        return data

    def get_token_usage(self) -> Dict[str, Any]:
        """Return accumulated token usage statistics.

        Prefers the persistent DB data.  Falls back to in-memory counters
        when the DB is unavailable (e.g. local dev / SQLite).
        """
        db_data = self.query_db_token_usage()
        if db_data.get("totals", {}).get("call_count", 0) > 0:
            return self._enrich_with_cost(db_data)
        # Fallback: in-memory
        with self._lock:
            return self._enrich_with_cost({
                "totals": dict(self._token_total),
                "by_model": {k: dict(v) for k, v in self._token_by_model.items()},
                "by_agent": {k: dict(v) for k, v in self._token_by_agent.items()},
                "by_agent_model": {k: dict(v) for k, v in self._token_by_agent_model.items()},
                "recent_calls": list(self._recent_calls[-50:]),
                "tracking_since": self._tracking_since,
            }

    def reset_token_usage(self) -> None:
        """Reset all accumulated token usage counters (in-memory + DB)."""
        with self._lock:
            self._token_by_model.clear()
            self._token_by_agent.clear()
            self._token_by_agent_model.clear()
            self._token_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
            self._recent_calls.clear()
            self._tracking_since = datetime.now(timezone.utc).isoformat()
        # Also truncate the DB table
        try:
            if self._ensure_db_table():
                from src.database import db
                db.execute_non_query("DELETE FROM telemetry_events")
        except Exception:
            pass

    def log_school_enrichment(
        self,
        school_name: str,
        opportunity_score: float = None,
        data_source: str = "unknown",
        confidence: float = 0.0,
        processing_time_ms: float = 0
    ) -> None:
        """Log school enrichment operation."""
        tracer = get_tracer()
        
        if tracer:
            with tracer.start_as_current_span("school_enrichment") as span:
                span.set_attribute("school.name", school_name)
                span.set_attribute("school.data_source", data_source)
                span.set_attribute("school.confidence", float(confidence))
                span.set_attribute("processing_time_ms", float(processing_time_ms))
                
                if opportunity_score is not None:
                    span.set_attribute("school.opportunity_score", float(opportunity_score))
    
    def log_api_call(
        self,
        endpoint: str,
        method: str,
        status_code: int = 200,
        duration_ms: float = 0
    ) -> None:
        """Log API endpoint calls."""
        tracer = get_tracer()
        
        if tracer:
            with tracer.start_as_current_span("http") as span:
                span.set_attribute("http.method", method)
                span.set_attribute("http.url", endpoint)
                span.set_attribute("http.status_code", status_code)
                span.set_attribute("duration_ms", float(duration_ms))


# Global instance
telemetry = NextGenTelemetry()


def init_telemetry(service_name: str = "agent-framework", capture_sensitive_data: bool = False) -> None:
    """Initialize OpenTelemetry tracing for Application Insights."""
    initialize_telemetry(service_name, capture_sensitive_data)


def should_capture_prompts() -> bool:
    """Return True when prompt content should be included in spans."""
    return should_capture_sensitive_data()


