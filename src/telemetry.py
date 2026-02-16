"""OpenTelemetry setup for agent tracing."""

import os
from typing import Optional

from opentelemetry import trace
from azure.monitor.opentelemetry import configure_azure_monitor

_tracer = None
_capture_prompts = True


def init_telemetry(service_name: str, capture_prompts: Optional[bool] = None) -> None:
    """Initialize OpenTelemetry tracing for Application Insights."""
    global _tracer, _capture_prompts

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return

    if capture_prompts is None:
        capture_prompts = os.getenv("NEXTGEN_CAPTURE_PROMPTS", "true").lower() in {
            "1",
            "true",
            "yes",
        }

    _capture_prompts = capture_prompts

    if not os.getenv("OTEL_SERVICE_NAME"):
        os.environ["OTEL_SERVICE_NAME"] = service_name

    configure_azure_monitor(connection_string=connection_string)
    _tracer = trace.get_tracer(service_name)


def get_tracer():
    """Return the configured tracer, or None when telemetry is disabled."""
    return _tracer


def should_capture_prompts() -> bool:
    """Return True when prompt content should be included in spans."""
    return _capture_prompts
