import os
import time
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from memory.knowledge import KnowledgeMemory
from utils.config import load_settings
from utils.logger import get_logger

logger = get_logger("cli.index")

def index_source(config_dir: str = ".", source: Optional[str] = None, show_status: bool = False) -> None:
    """
    Triggers indexing pipelines based on command parameters.
    Supports status printouts, single-source filters, and displays interactive progress bars.
    """
    console = Console()
    
    # We namespace index tasks as 'global_rag'
    knowledge = KnowledgeMemory(crew_id="global_rag", config_dir=config_dir)

    if show_status:
        # Show indexing status manifest
        status_data = knowledge.index_status
        table = Table(title="RAG Indexing Status Monitor")
        table.add_column("Indexed Resource Namespace / Path", style="cyan")
        table.add_column("Last SHA256 Signature Hash", style="yellow")

        if not status_data:
            console.print("[yellow]Index registry is empty. Run 'crewctl index' to trigger ingestion.[/yellow]")
            return

        for path_key, sha in status_data.items():
            table.add_row(path_key, sha)
        console.print(table)
        return

    # Ingest sources
    settings = load_settings(config_dir)
    sources = settings.memory.knowledge.sources

    if not sources:
        console.print("[yellow]No knowledge sources found configured in memory.yaml.[/yellow]")
        return

    # Filter source if provided
    if source:
        filtered_sources = []
        for s in sources:
            stype = s.get("type", "").lower()
            sval = str(s.get("space") or s.get("path") or s.get("site", ""))
            match_key = f"{stype}:{sval}"
            # Support matching type (e.g. 'confluence') or exact key (e.g. 'confluence:IT_DOCS')
            if source.lower() in [stype, match_key.lower()]:
                filtered_sources.append(s)
        if not filtered_sources:
            console.print(f"[red]No configured source matches search filter: '{source}'[/red]")
            return
        sources = filtered_sources

    console.print(f"[cyan]Ingesting {len(sources)} RAG Knowledge Sources...[/cyan]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        for s in sources:
            stype = s.get("type", "unknown")
            sval = s.get("space") or s.get("path") or s.get("site") or "resource"
            task_id = progress.add_task(f"Ingesting {stype} ({sval})", total=100)
            
            try:
                # Animate progress while executing ingestion pipeline
                for step in range(1, 5):
                    time.sleep(0.05)
                    progress.update(task_id, completed=step * 20)
                
                # Perform the ingestion
                single_source_knowledge = KnowledgeMemory(crew_id="global_rag", config_dir=config_dir)
                single_source_knowledge.settings.memory.knowledge.sources = [s]
                # Force re-index if single source is called, otherwise standard incremental checks
                res = single_source_knowledge.ingest_all(force=(source is not None))
                
                progress.update(task_id, completed=100, description=f"[green]Successfully Ingested: {stype} ({sval})[/green]")
            except Exception as e:
                progress.update(task_id, completed=100, description=f"[red]Failed to Index: {stype} ({sval}). Error: {str(e)}[/red]")
                logger.error(f"Cli indexing failure for source {stype}: {str(e)}")

    console.print("[green]Ingestion operation finalized.[/green]")
