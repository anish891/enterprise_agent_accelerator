import os
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from utils.logger import get_logger

logger = get_logger("monitoring.tracer")

@dataclass
class StepEvent:
    run_id: str
    timestamp: datetime
    agent_name: str
    task: str
    tool_called: str
    tool_input: Dict[str, Any]
    tool_output: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    status: str   # thinking | tool_call | done | error

# Local queue fallback for dashboard if Redis is not running or available
_local_event_bus: List[str] = []

def publish_step_event(event: StepEvent) -> None:
    """
    Publishes step events to the central audit file, and broadcasts
    to Redis Pub/Sub for the CLI Rich dashboard.
    """
    # 1. Write to central audit log
    try:
        from monitoring.audit import log_step_event
        log_step_event(event)
    except Exception as e:
        logger.debug(f"Tracer failed to append step to audit log: {str(e)}")

    # 2. Serialize event to JSON
    event_dict = asdict(event)
    if isinstance(event_dict["timestamp"], datetime):
        event_dict["timestamp"] = event_dict["timestamp"].isoformat()
    event_json = json.dumps(event_dict)

    # 3. Publish to Redis
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis
        r = redis.from_url(redis_url)
        r.publish(f"crewctl:events:{event.run_id}", event_json)
    except Exception as e:
        # Store locally so that the local monitor can access it if running in the same process
        _local_event_bus.append(event_json)
        if len(_local_event_bus) > 500:
            _local_event_bus.pop(0)
        logger.debug(f"Redis publish skipped, event buffered locally: {str(e)}")
