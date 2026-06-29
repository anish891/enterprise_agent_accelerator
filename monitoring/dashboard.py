import os
import sys
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.text import Text
from rich.align import Align
from utils.logger import get_logger

logger = get_logger("monitoring.dashboard")

# Global monitoring status dictionaries
agent_states: Dict[str, Dict[str, Any]] = {}
crew_meta: Dict[str, Any] = {
    "crew_name": "No-Code AI Orchestration",
    "run_id": "Initializing",
    "start_time": datetime.now(),
    "status": "running",
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "total_cost": 0.0,
}

def make_layout() -> Layout:
    """
    Splits the dashboard frame into a top title block, center agent execution grid,
    and a bottom cumulative statistics footer.
    """
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body", minimum_size=10),
        Layout(name="footer", size=3)
    )
    return layout

def update_header(layout: Layout) -> None:
    elapsed = datetime.now() - crew_meta["start_time"]
    elapsed_str = str(elapsed).split(".")[0]
    
    header_text = Text()
    header_text.append("CREWCTL LIVE RUNBOARD", style="bold magenta")
    header_text.append("  |  ", style="bright_black")
    header_text.append(f"Crew: {crew_meta['crew_name']}", style="cyan")
    header_text.append("  |  ", style="bright_black")
    header_text.append(f"Run ID: {crew_meta['run_id']}", style="yellow")
    header_text.append("  |  ", style="bright_black")
    header_text.append(f"Time Elapsed: {elapsed_str}", style="green")
    
    layout["header"].update(
        Panel(Align.center(header_text), title="Enterprise Agent Orchestrator", border_style="blue")
    )

def update_footer(layout: Layout) -> None:
    footer_text = Text()
    footer_text.append("Orchestration Status: ", style="bold")
    
    status_str = crew_meta["status"].upper()
    if status_str in ["RUNNING", "THINKING"]:
        footer_text.append(status_str, style="bold blink green")
    elif status_str in ["COMPLETED", "SUCCESS", "DONE"]:
        footer_text.append(status_str, style="bold green")
    elif status_str in ["FAILED", "ERROR"]:
        footer_text.append(status_str, style="bold red")
    else:
        footer_text.append(status_str, style="bold yellow")
        
    footer_text.append("  |  ", style="bright_black")
    tot_tokens = crew_meta["total_tokens_in"] + crew_meta["total_tokens_out"]
    footer_text.append(f"Cumulative Tokens: {tot_tokens} (In: {crew_meta['total_tokens_in']} / Out: {crew_meta['total_tokens_out']})", style="cyan")
    footer_text.append("  |  ", style="bright_black")
    footer_text.append(f"Run Cost: ${crew_meta['total_cost']:.5f} USD", style="bold yellow")
    
    layout["footer"].update(
        Panel(Align.center(footer_text), border_style="blue")
    )

def update_body(layout: Layout) -> None:
    table = Table(expand=True, show_lines=True)
    table.add_column("Agent / Role", style="cyan", width=22)
    table.add_column("Active Action / Task", style="white")
    table.add_column("State", style="yellow", width=12)
    table.add_column("Called Tool / Arguments", style="green")
    table.add_column("Tokens (In/Out)", style="cyan", width=15)
    table.add_column("Cost (USD)", style="bold yellow", width=12)
    
    # Populate row per unique active agent
    for agent_raw, state in agent_states.items():
        agent_display = agent_raw.replace("_", " ").title()
        
        status_val = state.get("status", "thinking").upper()
        status_text = Text(status_val)
        if status_val in ["THINKING", "RUNNING"]:
            status_text.stylize("bold magenta")
        elif status_val in ["TOOL_CALL", "EXECUTING"]:
            status_text.stylize("bold blink green")
        elif status_val in ["DONE", "COMPLETED"]:
            status_text.stylize("bold green")
        elif status_val == "ERROR":
            status_text.stylize("bold red")

        tool_called = state.get("tool_called") or "None"
        tool_text = Text()
        if tool_called != "None":
            tool_text.append(tool_called, style="bold green")
            tool_args = state.get("tool_input")
            if tool_args:
                tool_text.append(f"\nArgs: {json.dumps(tool_args)}", style="dim white")
        else:
            tool_text.append("None", style="dim")
            
        task_desc = state.get("task", "Waiting for trigger...")
        if len(task_desc) > 65:
            task_desc = task_desc[:62] + "..."
            
        t_in = state.get("tokens_in", 0)
        t_out = state.get("tokens_out", 0)
        t_cost = state.get("cost_usd", 0.0)
        
        table.add_row(
            agent_display,
            task_desc,
            status_text,
            tool_text,
            f"{t_in} / {t_out}",
            f"${t_cost:.5f}"
        )
        
    layout["body"].update(Panel(table, title="Agent Execution Grid", border_style="blue"))

def process_event_dict(event: Dict[str, Any]) -> None:
    # Read overall run id and title
    r_id = event.get("run_id", "Unknown")
    crew_meta["run_id"] = r_id
    if event.get("crew_name"):
        crew_meta["crew_name"] = event["crew_name"]
        
    agent = event.get("agent_name", "Orchestrator")
    
    # Hook general workflow events
    if event.get("event_type") == "run_lifecycle" or agent == "Orchestrator":
        status_val = event.get("status", "running")
        crew_meta["status"] = status_val
        if "total_tokens_in" in event:
            crew_meta["total_tokens_in"] = event["total_tokens_in"]
        if "total_tokens_out" in event:
            crew_meta["total_tokens_out"] = event["total_tokens_out"]
        if "total_cost_usd" in event:
            crew_meta["total_cost"] = event["total_cost_usd"]
        return

    # Track specific agent execution blocks
    if agent not in agent_states:
        agent_states[agent] = {
            "status": "thinking",
            "tool_called": "None",
            "tool_input": {},
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
            "task": "Active..."
        }
        
    state = agent_states[agent]
    if "status" in event:
        state["status"] = event["status"]
    if event.get("task"):
        state["task"] = event["task"]
    if "tool_called" in event:
        state["tool_called"] = event["tool_called"]
    if "tool_input" in event:
        state["tool_input"] = event["tool_input"]

    # Increment parameters
    in_t = event.get("tokens_in", 0)
    out_t = event.get("tokens_out", 0)
    cost = event.get("cost_usd", 0.0)
    
    state["tokens_in"] += in_t
    state["tokens_out"] += out_t
    state["cost_usd"] += cost
    
    # Only increment global if we're not receiving summaries
    if event.get("event_type") != "run_lifecycle":
        crew_meta["total_tokens_in"] += in_t
        crew_meta["total_tokens_out"] += out_t
        crew_meta["total_cost"] += cost

def run_dashboard(run_id: Optional[str] = None) -> None:
    """
    Displays the live board in screen buffer mode.
    Subscribes to Redis channels and falls back to polling file logs on failure.
    """
    layout = make_layout()
    crew_meta["start_time"] = datetime.now()
    if run_id:
        crew_meta["run_id"] = run_id

    # Try establishing connection to Redis Event Broker
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    pubsub = None
    try:
        import redis
        r = redis.from_url(redis_url)
        pubsub = r.pubsub()
        if run_id:
            pubsub.subscribe(f"crewctl:events:{run_id}")
        else:
            pubsub.psubscribe("crewctl:events:*")
        logger.debug("Subscribed to Redis event stream.")
    except Exception as e:
        logger.debug(f"Redis connection failed. Dashboard operating in file poll mode: {str(e)}")

    last_position = 0

    with Live(layout, screen=True, refresh_per_second=2):
        while True:
            # 1. Update views
            update_header(layout)
            update_body(layout)
            update_footer(layout)

            # Exit dashboard cleanly if run reached terminal state
            if crew_meta["status"].lower() in ["completed", "failed", "success", "stopped"]:
                time.sleep(1.5)
                break

            processed_any = False

            # 2. Redis fetch
            if pubsub is not None:
                try:
                    message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
                    if message:
                        event_data = json.loads(message["data"])
                        process_event_dict(event_data)
                        processed_any = True
                except Exception:
                    pass

            # 3. Fallback: Local thread buffer (if inside same execution framework)
            if not processed_any:
                try:
                    from monitoring.tracer import _local_event_bus
                    if _local_event_bus:
                        while _local_event_bus:
                            msg = _local_event_bus.pop(0)
                            process_event_dict(json.loads(msg))
                        processed_any = True
                except Exception:
                    pass

            # 4. Fallback: Audit file log polling
            if not processed_any:
                try:
                    from monitoring.audit import get_audit_file_path
                    audit_path = get_audit_file_path()
                    if os.path.exists(audit_path):
                        with open(audit_path, "r", encoding="utf-8") as f:
                            f.seek(last_position)
                            lines = f.readlines()
                            last_position = f.tell()
                            
                            for line in lines:
                                if not line.strip():
                                    continue
                                record = json.loads(line)
                                if run_id and record.get("run_id") != run_id:
                                    continue
                                process_event_dict(record)
                except Exception:
                    pass

            time.sleep(0.2)
