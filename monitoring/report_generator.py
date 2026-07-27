"""
Report Generator module.
Generates comprehensive execution summary reports in Markdown and JSON formats
for any historical or active agent crew run.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from monitoring.audit import get_events_by_run, list_all_runs
from utils.logger import get_logger

logger = get_logger("monitoring.report_generator")

def generate_markdown_report(run_id: str) -> str:
    """
    Generates a formatted Markdown report for a specific run ID.
    """
    events = get_events_by_run(run_id)
    runs = list_all_runs(limit=100)
    run_meta = next((r for r in runs if r["run_id"] == run_id), None)
    
    crew_name = run_meta.get("crew_name", "Agent Crew") if run_meta else "Agent Crew"
    status = run_meta.get("status", "completed") if run_meta else "completed"
    start_time = run_meta.get("start_time", "N/A") if run_meta else "N/A"
    total_cost = run_meta.get("total_cost_usd", 0.0) if run_meta else sum(e.get("cost_usd", 0.0) for e in events)
    total_tokens = run_meta.get("total_tokens", 0) if run_meta else sum(e.get("tokens_in", 0) + e.get("tokens_out", 0) for e in events)
    elapsed_sec = run_meta.get("elapsed_seconds", 0.0) if run_meta else 0.0
    final_output = run_meta.get("final_output", "") if run_meta else ""
    
    # Calculate step breakdown per agent
    agent_stats: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        agent = ev.get("agent_name", "Unknown")
        if agent not in agent_stats:
            agent_stats[agent] = {"steps": 0, "tools_called": [], "tokens": 0, "cost": 0.0}
        agent_stats[agent]["steps"] += 1
        tool = ev.get("tool_called")
        if tool and tool != "None":
            agent_stats[agent]["tools_called"].append(tool)
        t_in = ev.get("tokens_in", 0)
        t_out = ev.get("tokens_out", 0)
        agent_stats[agent]["tokens"] += (t_in + t_out)
        agent_stats[agent]["cost"] += ev.get("cost_usd", 0.0)

    lines = [
        f"# CrewAI Execution Report — {crew_name}",
        f"**Run ID:** `{run_id}` | **Status:** `{status.upper()}` | **Timestamp:** `{start_time}`\n",
        "---",
        "## Summary Metrics",
        f"- **Duration:** {elapsed_sec:.2f} seconds",
        f"- **Total Steps Executed:** {len(events)}",
        f"- **Total Tokens Consumed:** {total_tokens:,} tokens",
        f"- **Total Estimated Cost:** ${total_cost:.6f} USD\n",
        "---",
        "## Agent Breakdown",
        "| Agent Role | Steps | Tools Used | Total Tokens | Estimated Cost (USD) |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]

    for agent, stats in agent_stats.items():
        tools_str = ", ".join(set(stats["tools_called"])) if stats["tools_called"] else "None"
        lines.append(f"| `{agent}` | {stats['steps']} | `{tools_str}` | {stats['tokens']:,} | ${stats['cost']:.6f} |")

    lines.extend([
        "\n---",
        "## Detailed Step Events",
    ])

    for idx, ev in enumerate(events, 1):
        lines.extend([
            f"### Step {idx}: {ev.get('agent_name', 'Agent')} (`{ev.get('status', 'done')}`)",
            f"- **Task:** {ev.get('task', '')}",
            f"- **Tool Called:** `{ev.get('tool_called', 'None')}`",
            f"- **Tokens (In/Out):** {ev.get('tokens_in', 0)} / {ev.get('tokens_out', 0)}",
            f"- **Cost:** ${ev.get('cost_usd', 0.0):.6f}",
            "```json",
            json.dumps(ev.get("tool_input", {}), indent=2),
            "```",
            "**Tool Outcome:**",
            f"> {str(ev.get('tool_output', ''))[:500]}\n"
        ])

    if final_output:
        lines.extend([
            "---",
            "## Final Crew Result",
            "```text",
            final_output,
            "```"
        ])

    return "\n".join(lines)

def save_report_to_disk(run_id: str, output_dir: Optional[str] = None) -> str:
    """
    Saves markdown report to .crewctl/reports/ directory and returns file path.
    """
    if not output_dir:
        home = os.path.expanduser("~")
        output_dir = os.path.join(home, ".crewctl", "reports")
        os.makedirs(output_dir, exist_ok=True)
        
    filepath = os.path.join(output_dir, f"report_{run_id}.md")
    report_content = generate_markdown_report(run_id)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_content)
        
    return filepath
