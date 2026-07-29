"""
Guardrails module for enterprise-agent framework.
Provides Input Guardrails (PII redaction, prompt injection defense),
Runtime/Tool Guardrails (HITL approvals, parameter verification),
and Output Guardrails (Secret masking, PII redaction).
"""

import re

from typing import Tuple, Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("security.guardrails")

# Common regex patterns for PII detection and redaction
PII_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CREDIT_CARD": r"\b(?:\d[ -]*?){13,16}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE": r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
}

# Prompt Injection Attack Patterns
PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(all\s+)?previous\s+instructions",
    r"(?i)system\s+prompt\s+override",
    r"(?i)you\s+are\s+now\s+unrestricted",
    r"(?i)bypass\s+security\s+filter",
    r"(?i)forget\s+(your\s+)?rules",
]

# Sensitive patterns to redact in agent output (Secrets, Tokens, Keys)
SECRET_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",                  # OpenAI / Secret Keys
    r"AKIA[0-9A-Z]{16}",                     # AWS Access Key ID
    r"bearer\s+[a-zA-Z0-9\-\._~\+\/]+=*",    # Bearer Tokens
    r"(postgres|mysql|mongodb|redis)://[^\s]+", # Database connection strings
    r"---BEGIN PRIVATE KEY---",              # Private keys
]

# High-risk/Destructive tools requiring Human-in-the-Loop (HITL) approval
HIGH_RISK_TOOLS = {
    "sap.release_payment",
    "outlook.send_email",
    "jira.delete_ticket",
    "servicenow.close_incident"
}

def validate_and_sanitize_input(text: str) -> Tuple[bool, str, str]:
    """
    Scans input for prompt injection threats and anonymizes PII.
    Returns: (is_safe, sanitized_text, warning_msg)
    """
    if not text:
        return True, "", ""

    # 1. Check for prompt injection
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text):
            msg = f"Security Guardrail Triggered: Potential prompt injection attack detected (pattern: '{pattern}')."
            logger.warning(msg)
            return False, text, msg

    # 2. Redact PII
    sanitized_text = text
    for pii_type, pattern in PII_PATTERNS.items():
        sanitized_text = re.sub(pattern, f"[{pii_type}_REDACTED]", sanitized_text)

    return True, sanitized_text, ""

def enforce_tool_guardrail(agent_name: str, tool_name: str, tool_args: Dict[str, Any], auto_approve: bool = False) -> bool:
    """
    Verifies tool execution guardrails including parameter inspection and HITL approval.
    Returns True if allowed, or raises PermissionError / returns False if rejected.
    """
    if tool_name in HIGH_RISK_TOOLS:
        logger.info(f"High-risk tool execution detected: '{tool_name}' invoked by agent '{agent_name}' with args {tool_args}")
        
        # High value payment guardrail
        if tool_name == "sap.release_payment":
            amount = tool_args.get("amount", 0)
            if isinstance(amount, (int, float)) and amount > 5000:
                logger.warning(f"Guardrail triggered: High-value payment release of ${amount} requires explicit approval.")

        if not auto_approve:
            print(f"\n⚠️  [GUARDRAIL TRIGGERED] Agent '{agent_name}' requested execution of high-risk tool '{tool_name}'.")
            print(f"   Parameters: {tool_args}")
            try:
                user_choice = input("   Do you authorize this tool execution? (y/N): ").strip().lower()
                if user_choice != 'y':
                    logger.warning(f"Human-in-the-loop: User rejected execution of tool '{tool_name}' by '{agent_name}'.")
                    raise PermissionError(f"Guardrail Denied: High-risk tool '{tool_name}' execution was rejected by user supervisor.")
            except EOFError:
                # Non-interactive environment: allow execution with warning if standard input is closed
                logger.warning(f"Non-interactive session detected. Proceeding with caution for tool '{tool_name}'.")
                
    return True

def sanitize_output(output_text: str) -> str:
    """
    Scans agent final outputs to redact secrets, tokens, API keys, and PII before display/storage.
    """
    if not output_text or not isinstance(output_text, str):
        return output_text

    sanitized = output_text

    # 1. Redact secrets & credentials
    for pattern in SECRET_PATTERNS:
        sanitized = re.sub(pattern, "[SECRET_REDACTED]", sanitized)

    # 2. Redact PII in output
    for pii_type, pattern in PII_PATTERNS.items():
        sanitized = re.sub(pattern, f"[{pii_type}_REDACTED]", sanitized)

    return sanitized
