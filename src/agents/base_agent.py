"""Base agent class for Azure AI Foundry agents."""

from abc import ABC, abstractmethod
from typing import Any, Optional


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
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
