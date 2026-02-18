"""Base agent class for Azure AI Foundry agents."""

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.telemetry import telemetry
from src.observability import get_tracer, should_capture_sensitive_data
from opentelemetry.trace import SpanKind


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
            if tracer:
                # Create telemetry span for LLM call
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
                    
                    # Make the API call
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        **kwargs
                    )
                    
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
                response = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    **kwargs
                )
            
            return response
        
        except Exception as e:
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
