import os
import json
from datetime import datetime
from typing import Any, Dict, List
from monitoring.tracer import StepEvent
from utils.logger import get_logger

logger = get_logger("monitoring.audit")

def get_audit_file_path() -> str:
    """
    Returns the path to the central audit log file.
    Creates directories if not present. Falls back to workspace dir on permission error.
    """
    try:
        home = os.path.expanduser("~")
        audit_dir = os.path.join(home, ".crewctl")
        os.makedirs(audit_dir, exist_ok=True)
        return os.path.join(audit_dir, "audit.jsonl")
    except Exception as e:
        logger.debug(f"User home directory not writeable: {str(e)}. Using local workspace fallback.")
        audit_dir = os.path.join(os.getcwd(), ".crewctl")
        os.makedirs(audit_dir, exist_ok=True)
        return os.path.join(audit_dir, "audit.jsonl")

def log_audit_record(record: Dict[str, Any]) -> None:
    """
    Writes a dict structure directly as a single line JSON format into the audit trail.
    """
    filepath = get_audit_file_path()
    if "timestamp" not in record:
        record["timestamp"] = datetime.now().isoformat()
        
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error(f"Audit writer failed: {str(e)}")

def log_step_event(event: StepEvent) -> None:
    """
    Translates a StepEvent object to a dict record and stores it.
    """
    from dataclasses import asdict
    record = asdict(event)
    record["event_type"] = "step_event"
    if isinstance(record["timestamp"], datetime):
        record["timestamp"] = record["timestamp"].isoformat()
    log_audit_record(record)

def get_events_by_run(run_id: str) -> List[Dict[str, Any]]:
    """
    Reads the audit logs and filters records by a specific run ID.
    """
    filepath = get_audit_file_path()
    events = []
    if not os.path.exists(filepath):
        return []
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("run_id") == run_id:
                    events.append(record)
    except Exception as e:
        logger.error(f"Failed to scan audit files: {str(e)}")
        
    return events

def get_events_by_agent(agent_name: str) -> List[Dict[str, Any]]:
    """
    Reads the audit logs and filters records by agent name.
    """
    filepath = get_audit_file_path()
    events = []
    if not os.path.exists(filepath):
        return []
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("agent_name") == agent_name or record.get("agent_name", "").lower().replace(" ", "_") == agent_name.lower().replace(" ", "_"):
                    events.append(record)
    except Exception as e:
        logger.error(f"Failed to scan audit files: {str(e)}")
        
    return events
