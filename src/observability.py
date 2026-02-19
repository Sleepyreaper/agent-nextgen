"""
OpenTelemetry observability setup for Azure Application Insights.
Follows Microsoft Agent Framework best practices.
"""

import os
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

try:
    from azure.monitor.opentelemetry import configure_azure_monitor
except ImportError:
    configure_azure_monitor = None

try:
    from agent_framework.observability import create_resource, enable_instrumentation
except ImportError:
    create_resource = None
    enable_instrumentation = None

AZURE_MONITOR_AVAILABLE = configure_azure_monitor is not None

# Global references
_tracer: Optional[object] = None
_meter: Optional[object] = None
_is_configured = False
_capture_sensitive_data = False


def configure_observability(
    service_name: str = "agent-framework",
    service_version: str = "1.0.0",
    enable_azure_monitor: bool = True,
    enable_console_exporters: bool = False,
    capture_sensitive_data: bool = False,
) -> None:
    """
    Configure OpenTelemetry for the application.
    
    Follows Microsoft Agent Framework observability best practices.
    Supports both Azure Monitor and standard OTLP exporters.
    
    Args:
        service_name: Name of the service for telemetry
        service_version: Service version
        enable_azure_monitor: Use Azure Monitor/Application Insights (recommended)
        enable_console_exporters: Enable console output for debugging
        capture_sensitive_data: Include prompts and responses in telemetry (dev only)
    """
    global _tracer, _meter, _is_configured, _capture_sensitive_data
    
    if _is_configured:
        return
    
    _capture_sensitive_data = capture_sensitive_data
    
    # Set standard OpenTelemetry environment variables
    if not os.getenv("OTEL_SERVICE_NAME"):
        os.environ["OTEL_SERVICE_NAME"] = service_name
    
    if not os.getenv("OTEL_SERVICE_VERSION"):
        os.environ["OTEL_SERVICE_VERSION"] = service_version
    
    if enable_console_exporters:
        os.environ["ENABLE_CONSOLE_EXPORTERS"] = "true"
    
    if capture_sensitive_data:
        os.environ["ENABLE_SENSITIVE_DATA"] = "true"
    
    # Enable Agent Framework instrumentation
    os.environ["ENABLE_INSTRUMENTATION"] = "true"
    
    try:
        # Pattern 3 from Microsoft docs: Azure Monitor + Agent Framework
        if enable_azure_monitor and configure_azure_monitor:
            connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
            
            if connection_string:
                # Configure Azure Monitor with Application Insights
                configure_azure_monitor(
                    connection_string=connection_string,
                    resource=create_resource() if create_resource else None,
                    enable_live_metrics=True,
                )
                
                # Activate Agent Framework instrumentation
                if enable_instrumentation:
                    enable_instrumentation(enable_sensitive_data=capture_sensitive_data)
                
                _tracer = trace.get_tracer(service_name)
                _meter = metrics.get_meter(service_name)
                _is_configured = True
                print(f"✓ Azure Monitor observability configured for '{service_name}'")
                return
        
        # Fallback: Use standard OpenTelemetry with OTLP exporter
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        
        if otlp_endpoint:
            # Configure OTLP exporters
            trace_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint)
            
            resource = Resource.create({
                "service.name": service_name,
                "service.version": service_version,
            })
            
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
            trace.set_tracer_provider(tracer_provider)
            
            metric_reader = PeriodicExportingMetricReader(metric_exporter)
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(meter_provider)
            
            _tracer = trace.get_tracer(service_name)
            _meter = metrics.get_meter(service_name)
            _is_configured = True
            print(f"✓ OTLP observability configured for '{service_name}'")
            return
        
        # No configuration available
        print("⚠ Observability not configured - set APPLICATIONINSIGHTS_CONNECTION_STRING or OTEL_EXPORTER_OTLP_ENDPOINT")
    
    except Exception as e:
        print(f"⚠ Observability configuration failed: {e}")


def get_tracer() -> Optional[object]:
    """Get the global tracer instance."""
    if not _is_configured:
        return None
    return _tracer


def get_meter() -> Optional[object]:
    """Get the global meter instance."""
    if not _is_configured:
        return None
    return _meter


def should_capture_sensitive_data() -> bool:
    """Check if sensitive data (prompts, responses) should be captured."""
    return _capture_sensitive_data


def is_observability_enabled() -> bool:
    """Check if observability is fully configured."""
    return _is_configured
