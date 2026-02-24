"""OpenTelemetry setup for agent tracing - Enhanced with event tracking."""

import os
import json
import time
from typing import Optional, Dict, Any
from datetime import datetime

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
        success: bool = True
    ) -> None:
        """
        Log a call to the AI model.
        
        Args:
            model: Model name
            input_tokens: Input token count
            output_tokens: Output token count
            duration_ms: Duration in milliseconds
            success: Whether the call succeeded
        """
        tracer = get_tracer()
        
        if tracer:
            with tracer.start_as_current_span("model_call") as span:
                span.set_attribute("gen_ai.model", model)
                span.set_attribute("gen_ai.system", "azure_openai")
                span.set_attribute("gen_ai.usage.prompt_tokens", input_tokens)
                span.set_attribute("gen_ai.usage.completion_tokens", output_tokens)
                span.set_attribute("gen_ai.usage.total_tokens", input_tokens + output_tokens)
                span.set_attribute("duration_ms", float(duration_ms))
                span.set_attribute("success", success)
        
        try:
            token_ctr = self._get_counter("model_tokens_used")
            if token_ctr:
                token_ctr.add(input_tokens + output_tokens, {"model": model, "type": "total"})
            
            duration_ctr = self._get_counter("model_call_duration_ms")
            if duration_ctr:
                duration_ctr.add(duration_ms, {"model": model})
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


