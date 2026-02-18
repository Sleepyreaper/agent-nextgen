"""Telemetry helpers for consistent agent and tool tracking with OpenTelemetry."""

import time
from contextlib import contextmanager
from typing import Optional, Any, Dict
from opentelemetry.trace import SpanKind
from src.observability import get_tracer


class AgentTelemetry:
    """Helper class for tracking agent runs and tool calls with OpenTelemetry."""
    
    @staticmethod
    @contextmanager
    def record_agent_run(
        agent_name: str,
        action: str,
        context_data: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for tracking agent runs.
        
        Creates a parent span for an agent action with child spans for LLM calls and tools.
        
        Args:
            agent_name: Name of the agent (e.g., "Tiana Application Reader")
            action: The action being performed (e.g., "parse_application")
            context_data: Optional dictionary with additional context
            
        Example:
            with AgentTelemetry.record_agent_run("Tiana", "parse_application") as span:
                result = agent.parse_application(app_data)
                # LLM calls and tool calls within will appear as child spans
        """
        tracer = get_tracer()
        start_time = time.time()
        exception_occurred = False
        
        if not tracer:
            yield None
            return
        
        try:
            # Create parent span for agent run
            with tracer.start_as_current_span(
                "agent.run",
                kind=SpanKind.INTERNAL
            ) as span:
                # Set agent identification
                span.set_attribute("agent.id", agent_name)
                span.set_attribute("agent.action", action)
                
                # Add context data as span attributes
                if context_data:
                    for key, value in context_data.items():
                        if value is not None and isinstance(value, (str, int, float, bool)):
                            span.set_attribute(f"agent.context.{key}", str(value))
                
                # Timing
                span.set_attribute("agent.run.start_time_ms", int(start_time * 1000))
                
                try:
                    yield span
                except Exception as e:
                    exception_occurred = True
                    span.set_attribute("agent.run.error", str(e))
                    span.set_attribute("agent.run.success", False)
                    raise
                finally:
                    # Record completion timing
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("agent.run.duration_ms", duration_ms)
                    
                    if not exception_occurred:
                        span.set_attribute("agent.run.success", True)
        except Exception:
            raise
    
    @staticmethod
    @contextmanager
    def record_tool_call(
        tool_name: str,
        tool_type: str,
        tool_input: Optional[Dict[str, Any]] = None
    ):
        """
        Context manager for tracking tool/function calls.
        
        Wraps database queries, storage operations, API calls, etc.
        
        Args:
            tool_name: Name of the tool (e.g., "save_tiana_application", "upload_blob")
            tool_type: Type of tool (e.g., "database", "storage", "api", "web")
            tool_input: Optional dictionary with tool input parameters
            
        Example:
            with AgentTelemetry.record_tool_call("save_tiana_application", "database") as span:
                result = db.save_tiana_application(...)
                if result.get("success"):
                    span.set_attribute("tool.output.rows_affected", result.get("rows_affected", 0))
        """
        tracer = get_tracer()
        start_time = time.time()
        exception_occurred = False
        
        if not tracer:
            yield None
            return
        
        try:
            with tracer.start_as_current_span("tool.call") as span:
                # Set tool identification
                span.set_attribute("tool.name", tool_name)
                span.set_attribute("tool.type", tool_type)
                
                # Add input parameters as attributes (sanitized)
                if tool_input:
                    input_str = str(tool_input)
                    # Limit to 1000 chars to avoid huge spans
                    if len(input_str) > 1000:
                        input_str = input_str[:1000] + "..."
                    span.set_attribute("tool.input", input_str)
                
                # Timing
                span.set_attribute("tool.call.start_time_ms", int(start_time * 1000))
                
                try:
                    yield span
                except Exception as e:
                    exception_occurred = True
                    span.set_attribute("tool.success", False)
                    span.set_attribute("tool.error", str(e)[:500])
                    raise
                finally:
                    # Record completion
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("tool.call.duration_ms", duration_ms)
                    
                    if not exception_occurred:
                        span.set_attribute("tool.success", True)
        except Exception:
            raise
    
    @staticmethod
    @contextmanager
    def record_lm_call(
        model: str,
        operation: str,
        system_prompt: Optional[str] = None
    ):
        """
        Context manager for LLM calls (alternative to _create_chat_completion).
        
        Args:
            model: Model name (e.g., "gpt-4", "gpt-4-mini")
            operation: Operation name (e.g., "tiana.parse_application")
            system_prompt: Optional system prompt for tracking
            
        Example:
            with AgentTelemetry.record_lm_call("gpt-4", "tiana.parse_application") as span:
                response = client.chat.completions.create(...)
                span.set_attribute("gen_ai.usage.prompt_tokens", response.usage.prompt_tokens)
        """
        tracer = get_tracer()
        start_time = time.time()
        
        if not tracer:
            yield None
            return
        
        try:
            with tracer.start_as_current_span("lm.call") as span:
                # Set LLM context
                span.set_attribute("gen_ai.system", "azure_openai")
                span.set_attribute("gen_ai.model", model)
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.request.model", model)
                
                if system_prompt:
                    # Truncate if too long
                    prompt_str = system_prompt[:500]
                    span.set_attribute("gen_ai.system_prompt_preview", prompt_str)
                
                span.set_attribute("lm.call.start_time_ms", int(start_time * 1000))
                
                try:
                    yield span
                finally:
                    # Record completion
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("lm.call.duration_ms", duration_ms)
        except Exception:
            raise


# Convenience functions that can be imported and used directly

def agent_run(agent_name: str, action: str, context_data: Optional[Dict[str, Any]] = None):
    """Shorthand for AgentTelemetry.record_agent_run()."""
    return AgentTelemetry.record_agent_run(agent_name, action, context_data)


def tool_call(tool_name: str, tool_type: str, tool_input: Optional[Dict[str, Any]] = None):
    """Shorthand for AgentTelemetry.record_tool_call()."""
    return AgentTelemetry.record_tool_call(tool_name, tool_type, tool_input)


def lm_call(model: str, operation: str, system_prompt: Optional[str] = None):
    """Shorthand for AgentTelemetry.record_lm_call()."""
    return AgentTelemetry.record_lm_call(model, operation, system_prompt)
