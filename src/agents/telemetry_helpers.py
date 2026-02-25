"""Telemetry helpers aligned with OpenTelemetry GenAI Semantic Conventions.

Span names and attributes follow the Microsoft Agent Framework observability spec:
  https://learn.microsoft.com/en-us/agent-framework/agents/observability

Spans emitted:
  invoke_agent <agent_name>  – top-level span wrapping an agent invocation
  chat <model_name>          – LLM / chat-completion call
  execute_tool <tool_name>   – function / tool execution
"""

import time
from contextlib import contextmanager
from typing import Optional, Any, Dict
from opentelemetry.trace import SpanKind, StatusCode
from src.observability import get_tracer


class AgentTelemetry:
    """Helper class for tracking agent runs and tool calls with OpenTelemetry.

    Span naming follows GenAI Semantic Conventions used by the Microsoft Agent
    Framework so that traces rendered in Application Insights / Aspire Dashboard
    are consistent with the ``invoke_agent``, ``chat`` and ``execute_tool``
    convention documented at:
    https://learn.microsoft.com/en-us/agent-framework/agents/observability#spans-and-metrics
    """
    
    @staticmethod
    @contextmanager
    def record_agent_run(
        agent_name: str,
        action: str,
        context_data: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        instructions: Optional[str] = None,
    ):
        """Context manager that creates an ``invoke_agent <name>`` span.

        This is the top-level span for each agent invocation.  All child LLM
        calls (``chat``) and tool executions (``execute_tool``) will nest
        underneath automatically via OpenTelemetry context propagation.

        Args:
            agent_name: Human-readable agent name (e.g. "Tiana Application Reader").
            action: The action being performed (e.g. "parse_application").
            context_data: Optional dict of extra attributes to attach.
            agent_id: Stable identifier for this agent type (defaults to
                      lower-cased, hyphenated agent_name).
            instructions: Optional system-prompt / instruction summary to attach
                          when sensitive-data capture is enabled.

        Example::

            with agent_run("Tiana", "parse_application") as span:
                result = agent.parse_application(app_data)
        """
        tracer = get_tracer()
        start_time = time.time()
        exception_occurred = False
        resolved_id = agent_id or agent_name.lower().replace(" ", "-")
        
        if not tracer:
            yield None
            return
        
        try:
            with tracer.start_as_current_span(
                f"invoke_agent {agent_name}",
                kind=SpanKind.CLIENT,
            ) as span:
                # GenAI Semantic Convention attributes
                span.set_attribute("gen_ai.operation.name", "invoke_agent")
                span.set_attribute("gen_ai.system", "azure_openai")
                span.set_attribute("gen_ai.agent.id", resolved_id)
                span.set_attribute("gen_ai.agent.name", agent_name)
                span.set_attribute("gen_ai.agent.action", action)
                
                if instructions:
                    span.set_attribute("gen_ai.request.instructions", instructions[:500])
                
                # Add caller-supplied context data
                if context_data:
                    for key, value in context_data.items():
                        if value is not None and isinstance(value, (str, int, float, bool)):
                            span.set_attribute(f"agent.context.{key}", str(value))
                
                try:
                    yield span
                except Exception as e:
                    exception_occurred = True
                    span.set_status(StatusCode.ERROR, str(e)[:500])
                    span.set_attribute("error.type", type(e).__name__)
                    raise
                finally:
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("gen_ai.agent.duration_ms", duration_ms)
                    if not exception_occurred:
                        span.set_status(StatusCode.OK)
        except Exception:
            raise
    
    @staticmethod
    @contextmanager
    def record_tool_call(
        tool_name: str,
        tool_type: str,
        tool_input: Optional[Dict[str, Any]] = None
    ):
        """Context manager that creates an ``execute_tool <name>`` span.

        Wraps database queries, storage operations, API calls, etc.

        Args:
            tool_name: Name of the tool (e.g. "save_application", "upload_blob").
            tool_type: Type of tool (e.g. "database", "storage", "api", "web").
            tool_input: Optional dict with tool input parameters.

        Example::

            with tool_call("save_application", "database") as span:
                result = db.save_application(...)
                span.set_attribute("tool.output.rows_affected", 1)
        """
        tracer = get_tracer()
        start_time = time.time()
        exception_occurred = False
        
        if not tracer:
            yield None
            return
        
        try:
            with tracer.start_as_current_span(
                f"execute_tool {tool_name}",
                kind=SpanKind.INTERNAL,
            ) as span:
                # GenAI Semantic Convention attributes
                span.set_attribute("gen_ai.operation.name", "execute_tool")
                span.set_attribute("gen_ai.tool.name", tool_name)
                span.set_attribute("gen_ai.tool.type", tool_type)
                
                # Add input parameters as attributes (truncated)
                if tool_input:
                    input_str = str(tool_input)
                    if len(input_str) > 1000:
                        input_str = input_str[:1000] + "..."
                    span.set_attribute("gen_ai.tool.input", input_str)
                
                try:
                    yield span
                except Exception as e:
                    exception_occurred = True
                    span.set_status(StatusCode.ERROR, str(e)[:500])
                    span.set_attribute("error.type", type(e).__name__)
                    raise
                finally:
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("gen_ai.tool.duration_ms", duration_ms)
                    if not exception_occurred:
                        span.set_status(StatusCode.OK)
        except Exception:
            raise
    
    @staticmethod
    @contextmanager
    def record_lm_call(
        model: str,
        operation: str,
        system_prompt: Optional[str] = None
    ):
        """Context manager that creates a ``chat <model>`` span.

        Use this when making LLM calls outside of ``BaseAgent._create_chat_completion``
        (which already creates its own ``chat`` span automatically).

        Args:
            model: Model / deployment name (e.g. "gpt-4.1").
            operation: Operation name (e.g. "tiana.parse_application").
            system_prompt: Optional system prompt preview for tracking.

        Example::

            with lm_call("gpt-4.1", "tiana.parse_application") as span:
                response = client.chat.completions.create(...)
                span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)
        """
        tracer = get_tracer()
        start_time = time.time()
        
        if not tracer:
            yield None
            return
        
        try:
            with tracer.start_as_current_span(
                f"chat {model}",
                kind=SpanKind.CLIENT,
            ) as span:
                # GenAI Semantic Convention attributes
                span.set_attribute("gen_ai.operation.name", "chat")
                span.set_attribute("gen_ai.system", "azure_openai")
                span.set_attribute("gen_ai.request.model", model)
                
                if system_prompt:
                    span.set_attribute("gen_ai.request.instructions", system_prompt[:500])
                
                try:
                    yield span
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e)[:500])
                    span.set_attribute("error.type", type(e).__name__)
                    raise
                finally:
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("gen_ai.client.operation.duration_ms", duration_ms)
        except Exception:
            raise


# ── Convenience functions (importable shorthand) ─────────────────────

def agent_run(
    agent_name: str,
    action: str,
    context_data: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    instructions: Optional[str] = None,
):
    """Shorthand for ``AgentTelemetry.record_agent_run()``."""
    return AgentTelemetry.record_agent_run(
        agent_name, action, context_data,
        agent_id=agent_id, instructions=instructions,
    )


def tool_call(tool_name: str, tool_type: str, tool_input: Optional[Dict[str, Any]] = None):
    """Shorthand for ``AgentTelemetry.record_tool_call()``."""
    return AgentTelemetry.record_tool_call(tool_name, tool_type, tool_input)


def lm_call(model: str, operation: str, system_prompt: Optional[str] = None):
    """Shorthand for ``AgentTelemetry.record_lm_call()``."""
    return AgentTelemetry.record_lm_call(model, operation, system_prompt)
