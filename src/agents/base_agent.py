"""Base agent class for Azure AI Foundry agents."""

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.telemetry import get_tracer, should_capture_prompts


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
        """Create a chat completion with telemetry attached."""
        tracer = get_tracer()
        if not tracer:
            return self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )

        start_time = time.time()
        with tracer.start_as_current_span(operation) as span:
            span.set_attribute("agent.name", self.name)
            span.set_attribute("ai.agent.name", self.name)
            span.set_attribute("gen_ai.agent.name", self.name)
            span.set_attribute("ai.span.kind", "agent")
            span.set_attribute("gen_ai.span.kind", "agent")
            span.set_attribute("gen_ai.model", model or "")
            span.set_attribute("gen_ai.request.model", model or "")
            span.set_attribute("gen_ai.system", "azure_openai")
            span.set_attribute("gen_ai.operation.name", operation)
            max_tokens = kwargs.get("max_completion_tokens") or kwargs.get("max_tokens")
            if max_tokens is not None:
                span.set_attribute("gen_ai.request.max_tokens", int(max_tokens))
            temperature = kwargs.get("temperature")
            if temperature is not None:
                span.set_attribute("gen_ai.request.temperature", float(temperature))

                for key, value in self._trace_context.items():
                    if value is not None:
                        span.set_attribute(key, value)

            if should_capture_prompts():
                span.set_attribute("gen_ai.prompt", json.dumps(messages, ensure_ascii=True))

            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )

            span.set_attribute("gen_ai.latency_ms", int((time.time() - start_time) * 1000))

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

            return response

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
