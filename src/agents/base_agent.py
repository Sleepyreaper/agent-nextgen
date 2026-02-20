"""Base agent class for Azure AI Foundry agents."""

import json
import logging
import time
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.telemetry import telemetry
from src.observability import get_tracer, should_capture_sensitive_data
from opentelemetry.trace import SpanKind

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Base class for all agents in the system."""
    
    def __init__(self, name: str, client: Any):
        """
        Initialize the base agent.
        
        Args:
            name: The name of the agent
            client: Azure AI client instance (OpenAI or AI Foundry)
        """
        self.name = name
        self.client = client
        self.conversation_history = []
        self._trace_context = {}
    
    @abstractmethod
    async def process(self, message: str) -> str:
        """
        Process a message and return a response.
        
        Args:
            message: The input message to process
            
        Returns:
            The agent's response
        """
        pass
    
    def add_to_history(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.conversation_history.append({
            "role": role,
            "content": content
        })

    def _create_chat_completion(self, operation: str, model: str, messages: list, **kwargs):
        """
        Create a chat completion with comprehensive OpenTelemetry tracking.
        
        Automatically captures:
        - Agent name and model information
        - Request parameters (token budgets, temperature, etc.)
        - Token usage (input, output, total)
        - Latency and performance metrics
        - Prompts/responses (if sensitive data capture enabled)
        """
        tracer = get_tracer()
        start_time = time.time()

        # Always try to create completion - telemetry failure shouldn't block requests
        response = None

        try:
            # If tracer is available, wrap call in a telemetry span
            if tracer:
                with tracer.start_as_current_span(f"chat_completion_{operation}", kind=SpanKind.CLIENT) as span:
                    # GenAI semantic convention attributes
                    span.set_attribute("gen_ai.system", "azure_openai")
                    span.set_attribute("gen_ai.model", model or "")
                    span.set_attribute("gen_ai.operation.name", "chat")
                    span.set_attribute("gen_ai.request.model", model or "")

                    # Agent context
                    span.set_attribute("agent.name", self.name)
                    span.set_attribute("gen_ai.agent.name", self.name)
                    span.set_attribute("gen_ai.agent.id", self.name)

                    # Request parameters
                    max_tokens = kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
                    if max_tokens is not None:
                        span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))

                    temperature = kwargs.get("temperature")
                    if temperature is not None:
                        span.set_attribute("gen_ai.request.temperature", float(temperature))

                    top_p = kwargs.get("top_p")
                    if top_p is not None:
                        span.set_attribute("gen_ai.request.top_p", float(top_p))

                    # Application context
                    for key, value in self._trace_context.items():
                        if value is not None:
                            span.set_attribute(f"app.{key}", str(value))

                    # Prompt content (if configured)
                    if should_capture_sensitive_data():
                        try:
                            span.set_attribute("gen_ai.prompt", json.dumps(messages, ensure_ascii=True)[:2000])
                        except Exception:
                            pass

                    # Support optional multi-pass refinement loop via `refinements` kwarg.
                    refinements = int(kwargs.pop("refinements", 1)) if kwargs.get("refinements", None) is not None else 1
                    refinement_instruction = kwargs.pop("refinement_instruction", None)

                    def _single_call(msgs, call_kwargs):
                        return self.client.chat.completions.create(
                            model=model,
                            messages=msgs,
                            **call_kwargs
                        )

                    # First call
                    response = _single_call(messages, kwargs)

                    # If refinements requested, run iterative refinement passes.
                    for r in range(1, refinements):
                        try:
                            prev_content = ""
                            try:
                                prev_content = response.choices[0].message.content if response.choices else ""
                            except Exception:
                                prev_content = str(response)

                            # Build refinement messages: include original messages, assistant's previous reply, and a user instruction to refine.
                            refinement_msgs = []
                            # preserve system/user structure from original messages
                            for m in messages:
                                refinement_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})

                            # Append the assistant's previous content
                            refinement_msgs.append({"role": "assistant", "content": prev_content})

                            # Add a refinement instruction to the user role
                            if refinement_instruction:
                                instr = refinement_instruction
                            else:
                                instr = "Refine and improve the previous assistant response for accuracy, completeness, and clarity. Keep the same output format unless asked otherwise."

                            refinement_msgs.append({"role": "user", "content": instr})

                            # Call model again for the refinement pass
                            response = _single_call(refinement_msgs, kwargs)
                        except Exception:
                            # If a refinement pass fails, continue with the last successful response
                            break

                    # Record latency
                    duration_ms = int((time.time() - start_time) * 1000)
                    span.set_attribute("gen_ai.latency_ms", duration_ms)

                    # Extract and record token usage
                    usage = getattr(response, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", None)
                        output_tokens = getattr(usage, "completion_tokens", None)
                        total_tokens = getattr(usage, "total_tokens", None)
                        
                        if input_tokens is not None:
                            span.set_attribute("gen_ai.usage.prompt_tokens", int(input_tokens))
                        if output_tokens is not None:
                            span.set_attribute("gen_ai.usage.completion_tokens", int(output_tokens))
                        if total_tokens is not None:
                            span.set_attribute("gen_ai.usage.total_tokens", int(total_tokens))
                        
                        # Log metric data
                        telemetry.log_model_call(
                            model=model,
                            input_tokens=input_tokens or 0,
                            output_tokens=output_tokens or 0,
                            duration_ms=duration_ms,
                            success=True
                        )
                    
                    # Response ID (if available)
                    response_id = getattr(response, "id", None)
                    if response_id:
                        span.set_attribute("gen_ai.response.id", str(response_id))
                    
                    # Response content (if configured)
                    if should_capture_sensitive_data():
                        try:
                            content = response.choices[0].message.content if response.choices else ""
                            span.set_attribute("gen_ai.response", str(content)[:2000])
                        except Exception:
                            pass
            else:
                # Telemetry disabled - just make the call
                # Support refinements even when telemetry disabled
                refinements = int(kwargs.pop("refinements", 1)) if kwargs.get("refinements", None) is not None else 1
                refinement_instruction = kwargs.pop("refinement_instruction", None)

                def _single_call(msgs, call_kwargs):
                    return self.client.chat.completions.create(
                        model=model,
                        messages=msgs,
                        **call_kwargs
                    )

                response = _single_call(messages, kwargs)
                for r in range(1, refinements):
                    try:
                        prev_content = ""
                        try:
                            prev_content = response.choices[0].message.content if response.choices else ""
                        except Exception:
                            prev_content = str(response)

                        refinement_msgs = []
                        for m in messages:
                            refinement_msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
                        refinement_msgs.append({"role": "assistant", "content": prev_content})
                        if refinement_instruction:
                            instr = refinement_instruction
                        else:
                            instr = "Refine and improve the previous assistant response for accuracy, completeness, and clarity. Keep the same output format unless asked otherwise."
                        refinement_msgs.append({"role": "user", "content": instr})

                        response = _single_call(refinement_msgs, kwargs)
                    except Exception:
                        break
            
            return response
        
        except Exception as e:
            endpoint = getattr(self.client, "azure_endpoint", None) or getattr(self.client, "base_url", None)
            endpoint_host = None
            if isinstance(endpoint, str) and endpoint:
                try:
                    endpoint_host = urlparse(endpoint).netloc or endpoint
                except Exception:
                    endpoint_host = endpoint

            api_version = getattr(self.client, "api_version", None)
            telemetry.track_event(
                "model_call_error",
                properties={
                    "agent_name": self.name,
                    "model": model or "",
                    "operation": operation,
                    "api_version": str(api_version) if api_version else "",
                    "endpoint_host": endpoint_host or "",
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )
            logger.warning(
                "Model call failed",
                extra={
                    "agent_name": self.name,
                    "model": model,
                    "operation": operation,
                    "api_version": api_version,
                    "endpoint_host": endpoint_host,
                    "error": str(e),
                }
            )
            # Log error to telemetry
            if tracer:
                try:
                    telemetry.log_model_call(
                        model=model,
                        input_tokens=0,
                        output_tokens=0,
                        duration_ms=int((time.time() - start_time) * 1000),
                        success=False
                    )
                except Exception:
                    pass
            raise

    def set_trace_context(
        self,
        application_id: Optional[Any] = None,
        student_id: Optional[Any] = None,
        applicant_name: Optional[str] = None
    ) -> None:
        self._trace_context = {
            "app.application_id": application_id,
            "app.student_id": student_id,
            "app.applicant_name": applicant_name
        }

    def clear_trace_context(self) -> None:
        self._trace_context = {}
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
