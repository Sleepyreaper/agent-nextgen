"""OpenTelemetry setup for agent tracing - Enhanced with event tracking."""

import os
import json
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
    """Wrapper for application telemetry tracking using OpenTelemetry."""

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
        """Accumulate token usage in memory for the /api/telemetry/token-usage endpoint."""
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

    def get_token_usage(self) -> Dict[str, Any]:
        """Return accumulated token usage statistics.

        Returns a dict with:
          - totals: grand totals across all models/agents
          - by_model: {model_name: {input_tokens, output_tokens, total_tokens, call_count}}
          - by_agent: {agent_name: {input_tokens, output_tokens, total_tokens, call_count}}
          - by_agent_model: {"agent::model": {...}}
          - recent_calls: last N model invocations
          - tracking_since: ISO timestamp when tracking started
        """
        with self._lock:
            return {
                "totals": dict(self._token_total),
                "by_model": {k: dict(v) for k, v in self._token_by_model.items()},
                "by_agent": {k: dict(v) for k, v in self._token_by_agent.items()},
                "by_agent_model": {k: dict(v) for k, v in self._token_by_agent_model.items()},
                "recent_calls": list(self._recent_calls[-50:]),
                "tracking_since": self._tracking_since,
            }

    def reset_token_usage(self) -> None:
        """Reset all accumulated token usage counters."""
        with self._lock:
            self._token_by_model.clear()
            self._token_by_agent.clear()
            self._token_by_agent_model.clear()
            self._token_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "call_count": 0}
            self._recent_calls.clear()
            self._tracking_since = datetime.now(timezone.utc).isoformat()

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


