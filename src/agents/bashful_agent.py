"""Bashful agent - a simple example agent using Azure AI Foundry."""

from typing import Optional, Any
from azure.ai.inference.models import SystemMessage, UserMessage
from .base_agent import BaseAgent
from .telemetry_helpers import agent_run


class BashfulAgent(BaseAgent):
    """A simple agent (Bashful) that uses Azure AI Foundry for chat completions."""
    
    def __init__(
        self, 
        name: str, 
        client: Any,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        Initialize the simple agent.
        
        Args:
            name: The name of the agent
            client: AI client instance (AzureOpenAI or similar)
            system_prompt: Optional system prompt for the agent
            model: Optional model name to use
        """
        super().__init__(name, client)
        self.system_prompt = system_prompt or "You are a helpful AI assistant."
        self.model = model or config.foundry_model_name or config.deployment_name
    
    async def process(self, message: str) -> str:
        """
        Process a message and return a response.
        
        Args:
            message: The input message to process
            
        Returns:
            The agent's response
        """
        with agent_run("Bashful", "process") as span:
            # Add user message to history
            self.add_to_history("user", message)
            
            # Build messages for the API
            messages = [{"role": "system", "content": self.system_prompt}]
            
            for msg in self.conversation_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
            
            try:
                # Make the API call to Azure OpenAI
                response = self._create_chat_completion(
                    operation="bashful.process",
                    model=self.model,
                    messages=messages,
                    max_completion_tokens=800
                )
                
                # Extract the response content
                assistant_message = response.choices[0].message.content
                
                # Add assistant response to history
                self.add_to_history("assistant", assistant_message)
                
                return assistant_message
                
            except Exception as e:
                error_message = f"Error processing message: {str(e)}"
                print(f"[{self.name}] {error_message}")
                return error_message
