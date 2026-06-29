import logging
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict

class JsonFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as single-line JSON.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_record: Dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "filename": record.filename,
            "lineno": record.lineno,
        }
        
        # Include exception traceback if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            
        # Merge extra properties passed in extra={} dictionary
        if hasattr(record, "extra_fields"):
            log_record.update(getattr(record, "extra_fields"))
            
        return json.dumps(log_record)

def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Returns a configured JSON logger with handlers for stdout.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers if already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        
    return logger
