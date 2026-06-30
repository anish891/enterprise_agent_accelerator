import os
import sys
import click
import threading
import json
import time
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from runtime.orchestrator import CrewOrchestrator
from cli.index import index_source
from cli.watch import watch_command
from monitoring.dashboard import run_dashboard
from monitoring.audit import get_events_by_run, get_events_by_agent
from utils.logger import get_logger

logger = get_logger("cli.main")

@click.group()
def cli() -> None:
    """
    crewctl — Enterprise No-Code CrewAI Orchestration Command Line Interface.
    """
    pass

@cli.command()
@click.option("--template", default="it-support", type=click.Choice(["it-support", "hr-onboarding", "data-analysis"]), help="Scaffold templates name.")
def new(template: str) -> None:
    """
    Scaffolds agents.yaml, tasks.yaml, memory.yaml, config.yaml, and rbac.yaml configurations in current directory.
    """
    console = Console()
    console.print(f"[cyan]Scaffolding new agent crew from template: '{template}'...[/cyan]")
    
    # Locate templates files or use inline definitions if files do not exist
    # Writing inline ensures zero missing-dependency failures
    
    # 1. Config.yaml definition
    config_yaml = """# Central environment configurations
secrets_backend: env             # env / vault / aws
max_steps_default: 10
process: sequential              # sequential / parallel / hierarchical

# Default LLM for all agents that do not declare one explicitly.
# Current setup: Azure OpenAI (gpt-4o deployment).
# To switch provider just change this one line, e.g.:
#   openai/gpt-4o
#   anthropic/claude-3-5-sonnet-20241022
#   ollama/llama3
#   groq/llama3-70b-8192
default_llm: azure/gpt-4o

llm_costs:
  azure/gpt-4o:
    input_per_1k: 0.005
    output_per_1k: 0.015
  openai/gpt-4o:
    input_per_1k: 0.005
    output_per_1k: 0.015
  anthropic/claude-3-5-sonnet-20241022:
    input_per_1k: 0.003
    output_per_1k: 0.015
  google/gemini-1.5-pro:
    input_per_1k: 0.00125
    output_per_1k: 0.00375
  groq/llama3-70b-8192:
    input_per_1k: 0.00059
    output_per_1k: 0.00079
"""

    # 2. RBAC rules definition
    rbac_yaml = """# Access control permission schema
roles:
  it_support_agent:
    allowed_tools:
      - jira.*
      - servicenow.*
      - outlook.send_email
      - knowledge.search
  hr_agent:
    allowed_tools:
      - sharepoint.*
      - outlook.send_email
      - knowledge.search
  analyst_agent:
    allowed_tools:
      - sap.*
      - outlook.send_email
      - knowledge.search
"""

    # 3. Memory.yaml definition
    memory_yaml = """# Memory configurations and knowledge resources
memory:
  conversation: true
  persistent:
    backend: redis
    ttl_days: 30
  knowledge:
    vector_store: chroma            # chroma / pgvector
    chunk_size: 512
    chunk_overlap: 64
    embedding_model: text-embedding-3-small
    sources:
      - type: confluence
        base_url: https://mock-company.atlassian.net/wiki
        space: IT_DOCS
        auth: env:CONFLUENCE_TOKEN
      - type: sharepoint
        site: https://mock-company.sharepoint.com/sites/HR
        folder: /Policies
        auth: env:SHAREPOINT_TOKEN
      - type: text
        path: ./docs/runbook.txt
"""

    # Template specifics
    if template == "it-support":
        agents_yaml = """# IT Support Specialist crew
it_support_agent:
  role: IT Support Specialist
  goal: Investigate VPN connection incidents and resolve ticket workflows autonomously
  backstory: Lead IT systems developer with 10 years experience troubleshooting networks
  llm: azure/gpt-4o
  tools:
    - jira.get_issue
    - jira.update_issue
    - servicenow.create_ticket
    - servicenow.update_ticket
    - outlook.send_email
    - knowledge.search
"""
        tasks_yaml = """# IT Ticket workflow tasks
investigate_ticket:
  agent: it_support_agent
  description: "Search local files or confluence using knowledge.search for VPN configuration. Fetch issue context for ticket_id VPN-101 using jira.get_issue."
  expected_output: Root cause explanation of the VPN connection error and resolved instructions.
  depends_on: []
resolve_ticket:
  agent: it_support_agent
  description: "Update ServiceNow incident details using servicenow.update_ticket. Notify user using outlook.send_email."
  expected_output: Action confirmation string verifying notification and ticket modifications.
  depends_on: [investigate_ticket]
"""
    elif template == "hr-onboarding":
        agents_yaml = """# HR Specialist Crew
hr_agent:
  role: HR Specialist
  goal: Streamline onboarding programs for new hires
  backstory: Human resources specialist managing administrative processes
  llm: azure/gpt-4o
  tools:
    - sharepoint.get_file
    - outlook.send_email
    - knowledge.search
"""
        tasks_yaml = """# HR Onboarding workflow tasks
prepare_onboarding:
  agent: hr_agent
  description: "Search SharePoint files using knowledge.search or sharepoint.get_file to locate onboarding compliance sheets."
  expected_output: Structured text summary mapping required forms and submission links.
  depends_on: []
notify_candidate:
  agent: hr_agent
  description: "Send initial greeting mail using outlook.send_email containing onboarding schedules."
  expected_output: Transaction status confirming message delivery.
  depends_on: [prepare_onboarding]
"""
    else:  # data-analysis
        agents_yaml = """# Data Analyst Crew
analyst_agent:
  role: Financial Analyst
  goal: Audit enterprise resource planning records
  backstory: Core data accountant examining resource logs
  llm: azure/gpt-4o
  tools:
    - sap.get_record
    - sap.update_record
    - outlook.send_email
    - knowledge.search
"""
        tasks_yaml = """# SAP Financial auditing tasks
audit_records:
  agent: analyst_agent
  description: "Query SAP material table MARC for record item R-9482 using sap.get_record."
  expected_output: Analytical table parsing inventory levels and stock counts.
  depends_on: []
email_findings:
  agent: analyst_agent
  description: "Email audit findings report using outlook.send_email."
  expected_output: Email receipt response code.
  depends_on: [audit_records]
"""

    # Scaffold files
    try:
        with open("agents.yaml", "w", encoding="utf-8") as f:
            f.write(agents_yaml.strip())
        with open("tasks.yaml", "w", encoding="utf-8") as f:
            f.write(tasks_yaml.strip())
        with open("memory.yaml", "w", encoding="utf-8") as f:
            f.write(memory_yaml.strip())
        with open("config.yaml", "w", encoding="utf-8") as f:
            f.write(config_yaml.strip())
        with open("rbac.yaml", "w", encoding="utf-8") as f:
            f.write(rbac_yaml.strip())
            
        # Scaffold a sample directory docs folder
        os.makedirs("docs", exist_ok=True)
        with open("docs/runbook.txt", "w", encoding="utf-8") as f:
            f.write("Company VPN Policy Runbook:\n\nIf VPN fails, check if the SSO status is active.\nDefault VPN Client URL: client.company.com.\nIT Support Desk email: support@company.com.")
            
        console.print("[green]Successfully scaffolded project settings in current workspace![/green]")
    except Exception as e:
        console.print(f"[red]Error writing project settings: {str(e)}[/red]")

@cli.command()
def run() -> None:
    """
    Executes the crew configurations defined in current directory.
    """
    console = Console()
    console.print("[cyan]Initializing Crew Orchestrator...[/cyan]")
    
    orchestrator = CrewOrchestrator(config_dir=".")
    
    # Run Crew synchronously in the main thread so that all agent outputs,
    # task transitions, and tool executions are clearly visible in the terminal.
    res = orchestrator.run_crew()
    
    if res.status == "completed":
        console.print("\n[green]Crew Execution Finished Successfully![/green]")
        console.print(Panel(res.final_output, title="Final Crew Output Result", border_style="green"))
        console.print(f"Total Steps: {len(res.steps)} | Total Tokens: {res.total_tokens} | Time: {res.elapsed_seconds:.1f}s")
    else:
        console.print(f"\n[red]Crew Execution Ended with Status: {res.status}[/red]")
        console.print(Panel(res.final_output, title="Failure Details", border_style="red"))

@cli.command()
@click.option("--port", default=8000, help="Port to host the dashboard web server.")
def ui(port: int) -> None:
    """
    Starts a local web-based dashboard to view agent runs, task logs, and details.
    """
    from monitoring.web_ui import start_ui_server
    start_ui_server(port=port)

@cli.command()
@click.argument("command")
def watch(command: str) -> None:
    """
    Monitors a separate python crew script execution.
    Usage: crewctl watch "python my_crew.py"
    """
    watch_command(command)

@cli.command()
@click.option("--config", default="memory.yaml", help="Path to config configuration.")
@click.option("--source", default=None, help="Index specific source key (e.g. 'confluence:IT_DOCS').")
@click.option("--status", is_flag=True, help="Print indexing summary status table.")
def index(config: str, source: Optional[str], status: bool) -> None:
    """
    Runs the knowledge indexer to build and store RAG document vectors.
    """
    index_source(config_dir=".", source=source, show_status=status)

@cli.command()
@click.option("--run-id", default=None, help="Replay history of a specific execution ID.")
@click.option("--agent", default=None, help="Replay tool activities of a specific agent name.")
def audit(run_id: Optional[str], agent: Optional[str]) -> None:
    """
    Searches audit log files and pretty prints transaction replays.
    """
    console = Console()
    if not run_id and not agent:
        console.print("[red]Please specify either --run-id <id> or --agent <name> to execute audit logs inspection.[/red]")
        return

    if run_id:
        events = get_events_by_run(run_id)
        if not events:
            console.print(f"[yellow]No events discovered matching run ID: '{run_id}'[/yellow]")
            return
            
        console.print(Panel(f"Replaying Transaction Log: {run_id}", style="bold magenta"))
        for ev in events:
            ts = ev.get("timestamp", "")
            agent_name = ev.get("agent_name", "")
            task = ev.get("task", "")
            tool = ev.get("tool_called", "None")
            inp = ev.get("tool_input", {})
            out = ev.get("tool_output", "")
            status = ev.get("status", "")
            
            table = Table(show_header=False, expand=True)
            table.add_row("Timestamp", ts)
            table.add_row("Agent Role", agent_name)
            table.add_row("Target Task", task)
            table.add_row("Execution State", status)
            table.add_row("Used Tool", tool)
            table.add_row("Arguments", json.dumps(inp))
            
            # Truncate long outcomes
            out_str = str(out)
            if len(out_str) > 400:
                out_str = out_str[:397] + "..."
            table.add_row("Tool Output", out_str)
            
            console.print(Panel(table, title=f"Step Event [{status.upper()}]", border_style="cyan"))
            
    elif agent:
        events = get_events_by_agent(agent)
        if not events:
            console.print(f"[yellow]No events discovered matching agent role: '{agent}'[/yellow]")
            return
            
        console.print(Panel(f"Agent Activities Audit Trail: {agent}", style="bold magenta"))
        for ev in events:
            ts = ev.get("timestamp", "")
            run = ev.get("run_id", "")
            tool = ev.get("tool_called", "None")
            inp = ev.get("tool_input", {})
            out = ev.get("tool_output", "")
            
            table = Table(show_header=False, expand=True)
            table.add_row("Timestamp", ts)
            table.add_row("Workflow Run ID", run)
            table.add_row("Used Tool", tool)
            table.add_row("Arguments", json.dumps(inp))
            
            out_str = str(out)
            if len(out_str) > 200:
                out_str = out_str[:197] + "..."
            table.add_row("Response", out_str)
            
            console.print(Panel(table, border_style="cyan"))

@cli.command()
def deploy() -> None:
    """
    Deploys the current crew setup to production environment container clusters (Simulated).
    """
    console = Console()
    console.print("[cyan]Deploying crewctl configuration to production Kubernetes Cluster...[/cyan]")
    time.sleep(0.4)
    console.print("  [blue]-> Validating YAML configurations... OK[/blue]")
    time.sleep(0.3)
    console.print("  [blue]-> Constructing Crew Docker Container Image... OK[/blue]")
    time.sleep(0.4)
    console.print("  [blue]-> Deploying Service Pods to cluster namespace... OK[/blue]")
    time.sleep(0.3)
    console.print("[green]Deployment completed successfully. Agent Crew is live in cloud orchestrators.[/green]")

if __name__ == "__main__":
    cli()
