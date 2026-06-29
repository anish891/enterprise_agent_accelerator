import os
import yaml
import fnmatch
from typing import Dict, List, Any
from utils.logger import get_logger

logger = get_logger("security.rbac")

def check_permission(agent_name: str, tool_name: str, rbac_yaml_path: str = "rbac.yaml") -> bool:
    """
    Validates if an agent has permission to execute a specific tool based on rules in rbac.yaml.
    Supports wildcards like 'jira.*', 'outlook.send_email', or '*'.
    If the policy file doesn't exist, allows all by default to avoid blocking developer usage.
    """
    if not os.path.exists(rbac_yaml_path):
        _log_to_audit_log(agent_name, tool_name, permitted=True, reason="rbac.yaml not found. Allowed by default.")
        return True

    try:
        with open(rbac_yaml_path, "r", encoding="utf-8") as f:
            rbac_data = yaml.safe_load(f) or {}
    except Exception as e:
        msg = f"Failed to parse rbac.yaml: {str(e)}"
        logger.error(msg)
        _log_to_audit_log(agent_name, tool_name, permitted=False, reason=msg)
        raise PermissionError(f"RBAC loading error: {msg}")

    roles = rbac_data.get("roles", {})
    if agent_name not in roles:
        msg = f"Agent '{agent_name}' has no role configuration defined in rbac.yaml"
        logger.warning(msg)
        _log_to_audit_log(agent_name, tool_name, permitted=False, reason=msg)
        raise PermissionError(f"RBAC Denied: {msg}")

    allowed_patterns = roles[agent_name].get("allowed_tools", [])
    
    # Check if tool_name matches any pattern
    for pattern in allowed_patterns:
        if fnmatch.fnmatch(tool_name, pattern):
            _log_to_audit_log(agent_name, tool_name, permitted=True, reason=f"Allowed by pattern '{pattern}'")
            return True

    msg = f"Agent '{agent_name}' is not authorized to call tool '{tool_name}' under current RBAC policy"
    logger.warning(msg)
    _log_to_audit_log(agent_name, tool_name, permitted=False, reason=msg)
    raise PermissionError(f"RBAC Denied: {msg}")

def _log_to_audit_log(agent_name: str, tool_name: str, permitted: bool, reason: str) -> None:
    """
    Helper to append RBAC events to the centralized audit log file if available.
    """
    try:
        from monitoring.audit import log_audit_record
        log_audit_record({
            "event_type": "rbac_check",
            "agent_name": agent_name,
            "tool_name": tool_name,
            "permitted": permitted,
            "reason": reason
        })
    except Exception as e:
        logger.debug(f"Audit log write skipped or failed during RBAC check: {str(e)}")
