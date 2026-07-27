import os
import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional
from monitoring.tracer import StepEvent
from utils.logger import get_logger

logger = get_logger("monitoring.audit")

def get_audit_dir() -> str:
    """
    Returns the path to the central .crewctl storage directory.
    """
    try:
        home = os.path.expanduser("~")
        audit_dir = os.path.join(home, ".crewctl")
        os.makedirs(audit_dir, exist_ok=True)
        return audit_dir
    except Exception as e:
        logger.debug(f"User home directory not writeable: {str(e)}. Using local workspace fallback.")
        audit_dir = os.path.join(os.getcwd(), ".crewctl")
        os.makedirs(audit_dir, exist_ok=True)
        return audit_dir

def get_audit_file_path() -> str:
    """
    Returns the path to the central audit JSONL file.
    """
    return os.path.join(get_audit_dir(), "audit.jsonl")

def get_db_path() -> str:
    """
    Returns the path to the persistent SQLite database file.
    """
    return os.path.join(get_audit_dir(), "history.db")

def init_db() -> None:
    """
    Initializes SQLite tables and indexes with WAL journal mode.
    """
    db_path = get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            crew_name TEXT NOT NULL,
            status TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            total_tokens INTEGER DEFAULT 0,
            total_cost_usd REAL DEFAULT 0.0,
            elapsed_seconds REAL DEFAULT 0.0,
            final_output TEXT
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS step_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            task TEXT NOT NULL,
            tool_called TEXT,
            tool_input TEXT,
            tool_output TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            latency_ms INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
        )
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_steps_run_id ON step_events(run_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_steps_agent_name ON step_events(agent_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_start_time ON runs(start_time DESC);")
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to initialize SQLite audit database: {str(e)}")

# Initialize DB on module load
init_db()

def log_audit_record(record: Dict[str, Any]) -> None:
    """
    Writes a record to JSONL and persists run/step data to SQLite.
    """
    # 1. Append to audit.jsonl
    filepath = get_audit_file_path()
    if "timestamp" not in record:
        record["timestamp"] = datetime.now().isoformat()
        
    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        logger.error(f"Audit JSONL writer failed: {str(e)}")

    # 2. Persist to SQLite
    run_id = record.get("run_id")
    if not run_id:
        return

    try:
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        task_name = record.get("task", "")
        agent_name = record.get("agent_name", "")
        
        # Check if this is an Orchestration start/finish event
        if agent_name == "Orchestrator" and task_name == "Orchestration Initializing":
            crew_name = record.get("crew_name") or "Agent Crew"
            cursor.execute("""
                INSERT INTO runs (run_id, crew_name, status, start_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET status=excluded.status
            """, (run_id, crew_name, "running", record.get("timestamp")))
            
        elif agent_name == "Orchestrator" and task_name == "Orchestration Finished":
            cursor.execute("""
                UPDATE runs
                SET status = ?, end_time = ?, total_cost_usd = ?, elapsed_seconds = ?, final_output = ?
                WHERE run_id = ?
            """, (
                record.get("status", "completed"),
                record.get("timestamp"),
                record.get("cost_usd", 0.0),
                record.get("latency_ms", 0) / 1000.0,
                record.get("tool_output", ""),
                run_id
            ))
        else:
            # Ensure run record exists
            cursor.execute("SELECT run_id FROM runs WHERE run_id = ?", (run_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO runs (run_id, crew_name, status, start_time)
                    VALUES (?, ?, ?, ?)
                """, (run_id, "Agent Crew", "running", record.get("timestamp")))

            tool_inp = json.dumps(record.get("tool_input", {}))
            cursor.execute("""
                INSERT INTO step_events 
                (run_id, timestamp, agent_name, task, tool_called, tool_input, tool_output, tokens_in, tokens_out, cost_usd, latency_ms, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                record.get("timestamp", datetime.now().isoformat()),
                agent_name,
                task_name,
                record.get("tool_called", "None"),
                tool_inp,
                str(record.get("tool_output", "")),
                record.get("tokens_in", 0),
                record.get("tokens_out", 0),
                record.get("cost_usd", 0.0),
                record.get("latency_ms", 0),
                record.get("status", "done")
            ))
            
            # Update cumulative totals in runs table
            tokens_total = (record.get("tokens_in", 0) + record.get("tokens_out", 0))
            cursor.execute("""
                UPDATE runs
                SET total_tokens = total_tokens + ?,
                    total_cost_usd = total_cost_usd + ?
                WHERE run_id = ?
            """, (tokens_total, record.get("cost_usd", 0.0), run_id))

        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to record audit step in SQLite database: {str(e)}")

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
    Reads records for a specific run ID from SQLite (falling back to JSONL).
    """
    db_path = get_db_path()
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM step_events WHERE run_id = ? ORDER BY id ASC", (run_id,))
            rows = cursor.fetchall()
            conn.close()
            if rows:
                result = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["tool_input"] = json.loads(item.get("tool_input") or "{}")
                    except Exception:
                        pass
                    result.append(item)
                return result
        except Exception as e:
            logger.debug(f"SQLite query failed: {str(e)}. Falling back to JSONL.")

    # Fallback to JSONL
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
    Reads records for an agent name from SQLite (falling back to JSONL).
    """
    db_path = get_db_path()
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM step_events WHERE LOWER(agent_name) LIKE ? ORDER BY id ASC", (f"%{agent_name.lower()}%",))
            rows = cursor.fetchall()
            conn.close()
            if rows:
                result = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["tool_input"] = json.loads(item.get("tool_input") or "{}")
                    except Exception:
                        pass
                    result.append(item)
                return result
        except Exception as e:
            logger.debug(f"SQLite query failed: {str(e)}. Falling back to JSONL.")

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
                agent_raw = record.get("agent_name", "").lower().replace(" ", "_")
                if agent_name.lower().replace(" ", "_") in agent_raw:
                    events.append(record)
    except Exception as e:
        logger.error(f"Failed to scan audit files: {str(e)}")
        
    return events

def list_all_runs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Returns a list of all historical runs with totals.
    """
    db_path = get_db_path()
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs ORDER BY start_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug(f"SQLite list runs failed: {str(e)}")
            
    return []
