"""
Professional logging configuration for the NextGen AI Evaluation System.

Implements industry-standard logging with:
- Structured logging with JSON output for parsing
- Security-sensitive field masking
- Performance metrics tracking
- Audit trail logging
- Multiple output handlers
"""

import logging
import json
import sys
from pathlib import Path
from typing import Dict, Any
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
import traceback


class SensitiveDataFilter(logging.Filter):
    """Filter that masks sensitive information in logs."""
    
    SENSITIVE_KEYS = {
        'password', 'token', 'key', 'secret', 'credential',
        'api_key', 'connection_string', 'auth', 'bearer'
    }
    
    SENSITIVE_PATTERNS = [
        r'(?<=password[=:]\s)[^,\s}]+',
        r'(?<=token[=:]\s)[^,\s}]+',
        r'(?<=key[=:]\s)[^,\s}]+',
    ]
    
    def filter(self, record):
        """Mask sensitive data in log records."""
        # Mask in the formatted message
        if hasattr(record, 'msg'):
            if isinstance(record.msg, dict):
                record.msg = self._mask_dict(record.msg)
            elif isinstance(record.msg, str):
                record.msg = self._mask_string(record.msg)
        
        # Mask in args
        if hasattr(record, 'args'):
            if isinstance(record.args, dict):
                record.args = self._mask_dict(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    self._mask_value(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        
        return True
    
    def _mask_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive values in a dictionary."""
        masked = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in self.SENSITIVE_KEYS):
                masked[key] = '***MASKED***'
            elif isinstance(value, dict):
                masked[key] = self._mask_dict(value)
            elif isinstance(value, str):
                masked[key] = self._mask_string(value)
            else:
                masked[key] = value
        return masked
    
    def _mask_string(self, value: str) -> str:
        """Mask sensitive patterns in a string."""
        for pattern in self.SENSITIVE_PATTERNS:
            import re
            value = re.sub(pattern, '***MASKED***', value, flags=re.IGNORECASE)
        return value
    
    def _mask_value(self, value: str) -> str:
        """Mask a single value if it looks like sensitive data."""
        if len(value) > 20 and any(char.isdigit() for char in value):
            # Likely an API key or token
            return '***MASKED***'
        return value


class StructuredFormatter(logging.Formatter):
    """Formatter that outputs structured logs."""
    
    def format(self, record):
        """Format log record as structured JSON."""
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exc()
            }
        
        # Add extra fields if present
        if hasattr(record, 'extra'):
            log_data['extra'] = record.extra
        
        return json.dumps(log_data)


class SimpleFormatter(logging.Formatter):
    """Formatter for human-readable logs."""
    
    FORMAT_MAP = {
        logging.DEBUG: '🔍 %(asctime)s [%(name)s] %(message)s',
        logging.INFO: '✓ %(asctime)s [%(name)s] %(message)s',
        logging.WARNING: '⚠️  %(asctime)s [%(name)s] %(message)s',
        logging.ERROR: '✗ %(asctime)s [%(name)s] %(message)s',
        logging.CRITICAL: '🚨 %(asctime)s [%(name)s] %(message)s'
    }
    
    def format(self, record):
        """Format log record for human consumption."""
        format_str = self.FORMAT_MAP.get(record.levelno, '%(asctime)s [%(name)s] %(message)s')
        formatter = logging.Formatter(format_str, datefmt='%Y-%m-%d %H:%M:%S')
        return formatter.format(record)


class AuditLogger:
    """Specialized logger for audit trail events."""
    
    def __init__(self, log_file: str = 'audit.log'):
        """Initialize audit logger."""
        self.logger = logging.getLogger('audit')
        self.logger.setLevel(logging.INFO)
        
        # Create rotating file handler for audit logs
        handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=10
        )
        
        formatter = StructuredFormatter()
        handler.setFormatter(formatter)
        handler.addFilter(SensitiveDataFilter())
        
        self.logger.addHandler(handler)
    
    def log_agent_execution(self, agent_name: str, application_id: int, 
                           status: str, duration_ms: float, result: Any = None):
        """Log agent execution event."""
        self.logger.info(
            "agent_execution",
            extra={
                'event_type': 'agent_execution',
                'agent': agent_name,
                'application_id': application_id,
                'status': status,
                'duration_ms': duration_ms,
                'result_type': type(result).__name__ if result else None
            }
        )
    
    def log_data_access(self, user_id: str, application_id: int, 
                       data_type: str, action: str):
        """Log data access event."""
        self.logger.info(
            "data_access",
            extra={
                'event_type': 'data_access',
                'user_id': user_id,
                'application_id': application_id,
                'data_type': data_type,
                'action': action,
                'timestamp': datetime.utcnow().isoformat()
            }
        )
    
    def log_security_event(self, event_type: str, severity: str, 
                          details: Dict[str, Any]):
        """Log security event."""
        self.logger.warning(
            f"security_event: {event_type}",
            extra={
                'event_type': event_type,
                'severity': severity,
                'details': details,
                'timestamp': datetime.utcnow().isoformat()
            }
        )


def configure_logging(
    app_name: str = 'nextgen',
    log_level: str = 'INFO',
    log_file: str = None,
    structured: bool = False
) -> logging.Logger:
    """
    Configure application logging with security best practices.
    
    Args:
        app_name: Name of the application
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file (if None, logs to console only)
        structured: If True, uses JSON structured logging
        
    Returns:
        Configured logger instance
    """
    
    # Create logger
    logger = logging.getLogger(app_name)
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create sensitive data filter
    sensitive_filter = SensitiveDataFilter()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.addFilter(sensitive_filter)
    
    if structured:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(SimpleFormatter())
    
    logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.addFilter(sensitive_filter)
        
        if structured:
            file_handler.setFormatter(StructuredFormatter())
        else:
            file_handler.setFormatter(SimpleFormatter())
        
        logger.addHandler(file_handler)
    
    return logger


# Application logger instance
app_logger = configure_logging(
    app_name='nextgen',
    log_level='INFO',
    log_file='logs/application.log',
    structured=False
)

# Audit logger instance
audit_logger = AuditLogger('logs/audit.log')
