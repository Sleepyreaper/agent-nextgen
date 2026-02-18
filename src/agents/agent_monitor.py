"""
Real-time agent execution monitoring and debugging.

Provides visibility into:
- Current agent execution status
- Timing information for each agent
- Error tracking
- Queue depth and processing state
"""

import time
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import json


class AgentStatus(Enum):
    """Agent execution status."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentExecution:
    """Track a single agent execution."""
    agent_name: str
    status: str = AgentStatus.QUEUED.value
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    error_message: Optional[str] = None
    input_size: Optional[int] = None
    output_size: Optional[int] = None
    model_used: Optional[str] = None
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, filtering None values."""
        return {k: v for k, v in asdict(self).items() if v is not None}


class AgentMonitor:
    """
    Real-time agent execution monitor.
    
    Thread-safe tracking of all agent executions with timing and error information.
    """
    
    def __init__(self, max_history: int = 100):
        """
        Initialize monitor.
        
        Args:
            max_history: Maximum number of execution records to keep
        """
        self.max_history = max_history
        self.executions: List[AgentExecution] = []
        self.current_executions: Dict[str, AgentExecution] = {}
        self.lock = threading.RLock()
        self.total_agent_calls = 0
        self.total_errors = 0
    
    def start_execution(self, agent_name: str, model: Optional[str] = None, 
                       input_size: Optional[int] = None) -> AgentExecution:
        """
        Record agent execution start.
        
        Args:
            agent_name: Name of the agent starting
            model: Model being used (e.g., gpt-4, o4miniagent)
            input_size: Size of input in bytes
            
        Returns:
            AgentExecution object for this execution
        """
        with self.lock:
            execution = AgentExecution(
                agent_name=agent_name,
                status=AgentStatus.RUNNING.value,
                start_time=time.time(),
                model_used=model,
                input_size=input_size
            )
            self.current_executions[agent_name] = execution
            self.total_agent_calls += 1
            return execution
    
    def end_execution(self, agent_name: str, status: AgentStatus = AgentStatus.COMPLETED,
                     error_message: Optional[str] = None, output_size: Optional[int] = None):
        """
        Record agent execution end.
        
        Args:
            agent_name: Name of the agent
            status: Final status (COMPLETED, FAILED, SKIPPED)
            error_message: Error message if FAILED
            output_size: Size of output in bytes
        """
        with self.lock:
            execution = self.current_executions.pop(agent_name, None)
            if execution is None:
                # Create a new execution record if not found
                execution = AgentExecution(agent_name=agent_name)
            
            execution.end_time = time.time()
            execution.status = status.value
            execution.error_message = error_message
            execution.output_size = output_size
            
            if execution.start_time:
                execution.duration_ms = (execution.end_time - execution.start_time) * 1000
            
            if status == AgentStatus.FAILED:
                self.total_errors += 1
            
            self.executions.append(execution)
            
            # Keep only max_history records
            if len(self.executions) > self.max_history:
                self.executions = self.executions[-self.max_history:]
    
    def get_status(self) -> Dict[str, Any]:
        """Get current system status."""
        with self.lock:
            current = list(self.current_executions.values())
            recent = self.executions[-10:] if self.executions else []
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "total_calls": self.total_agent_calls,
                "total_errors": self.total_errors,
                "currently_running": {
                    agent_name: exec.to_dict()
                    for agent_name, exec in self.current_executions.items()
                },
                "running_count": len(self.current_executions),
                "recent_executions": [exec.to_dict() for exec in recent],
                "average_duration_ms": self._calculate_avg_duration(recent)
            }
    
    def get_agent_history(self, agent_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get execution history for a specific agent."""
        with self.lock:
            history = [
                exec.to_dict() 
                for exec in self.executions 
                if exec.agent_name == agent_name
            ]
            return history[-limit:]
    
    def get_all_history(self) -> List[Dict[str, Any]]:
        """Get all execution history."""
        with self.lock:
            return [exec.to_dict() for exec in self.executions]
    
    def _calculate_avg_duration(self, executions: List[AgentExecution]) -> float:
        """Calculate average duration for executions."""
        completed = [exec for exec in executions 
                    if exec.status == AgentStatus.COMPLETED.value]
        if not completed:
            return 0.0
        return sum(exec.duration_ms for exec in completed) / len(completed)
    
    def clear_history(self):
        """Clear execution history (keep current executions)."""
        with self.lock:
            self.executions.clear()


# Global monitor instance
_monitor = None


def get_agent_monitor() -> AgentMonitor:
    """Get or create the global agent monitor."""
    global _monitor
    if _monitor is None:
        _monitor = AgentMonitor()
    return _monitor


def start_agent_monitoring(agent_name: str, model: Optional[str] = None) -> AgentExecution:
    """
    Convenience function to start monitoring an agent.
    
    Usage:
        execution = start_agent_monitoring(agent_name, model)
        try:
            # do work
            end_agent_monitoring(agent_name)
        except Exception as e:
            end_agent_monitoring(agent_name, error=str(e))
    """
    monitor = get_agent_monitor()
    return monitor.start_execution(agent_name, model=model)


def end_agent_monitoring(agent_name: str, status: AgentStatus = AgentStatus.COMPLETED,
                        error: Optional[str] = None):
    """
    Convenience function to end monitoring an agent.
    """
    monitor = get_agent_monitor()
    monitor.end_execution(agent_name, status=status, error_message=error)
