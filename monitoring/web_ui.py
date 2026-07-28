import os
import json
import threading
import http.server
import socketserver
from typing import Any, Dict, List
from monitoring.audit import get_audit_file_path, get_events_by_run, list_all_runs
from runtime.orchestrator import CrewOrchestrator

active_run_id = None
active_run_status = "idle"

class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress standard request logging to keep console clean
        pass

    def do_GET(self):
        global active_run_id, active_run_status
        
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
            
        elif self.path == "/api/runs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            runs = self.get_runs_list()
            self.wfile.write(json.dumps(runs).encode("utf-8"))
            
        elif self.path.startswith("/api/runs/"):
            run_id = self.path.split("/")[-1]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            events = get_events_by_run(run_id)
            self.wfile.write(json.dumps(events).encode("utf-8"))
            
        elif self.path == "/api/active_run":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            self.wfile.write(json.dumps({
                "run_id": active_run_id,
                "status": active_run_status
            }).encode("utf-8"))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        global active_run_id, active_run_status
        
        if self.path == "/api/run":
            if active_run_status == "running":
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "A crew run is already in progress."}).encode("utf-8"))
                return
                
            # Start a new run
            orchestrator = CrewOrchestrator(config_dir=".")
            active_run_id = orchestrator.run_id
            active_run_status = "running"
            
            def run_thread_fn():
                global active_run_status
                try:
                    orchestrator.run_crew()
                except Exception as e:
                    print(f"Error during background crew execution: {e}")
                finally:
                    active_run_status = "idle"
            
            t = threading.Thread(target=run_thread_fn)
            t.start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "message": "Crew run started.",
                "run_id": active_run_id,
                "status": active_run_status
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def get_runs_list(self) -> List[Dict[str, Any]]:
        runs_map = {}
        
        # 1. Fetch from SQLite DB
        sqlite_runs = list_all_runs(limit=100)
        for r in sqlite_runs:
            run_id = r.get("run_id")
            if run_id:
                events = get_events_by_run(run_id)
                steps_count = sum(1 for e in events if e.get("status") in ["thinking", "tool_call", "done"])
                runs_map[run_id] = {
                    "run_id": run_id,
                    "timestamp": r.get("start_time"),
                    "crew_name": r.get("crew_name", "Agent Crew"),
                    "status": r.get("status", "completed"),
                    "steps_count": steps_count,
                    "tokens_count": r.get("total_tokens", 0),
                    "cost_usd": r.get("total_cost_usd", 0.0),
                    "final_output": r.get("final_output")
                }
            
        # 2. Merge JSONL persistent audit history
        filepath = get_audit_file_path()
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        record = json.loads(line)
                        run_id = record.get("run_id")
                        if not run_id:
                            continue
                            
                        if run_id not in runs_map:
                            runs_map[run_id] = {
                                "run_id": run_id,
                                "timestamp": record.get("timestamp"),
                                "crew_name": record.get("crew_name") or "Agent Crew",
                                "status": "running",
                                "steps_count": 0,
                                "tokens_count": 0,
                                "cost_usd": 0.0,
                                "final_output": None
                            }
                        
                        run = runs_map[run_id]
                        task = record.get("task")
                        
                        if task == "Orchestration Finished":
                            run["status"] = record.get("status") or "completed"
                            run["final_output"] = record.get("tool_output")
                        
                        if record.get("cost_usd"):
                            run["cost_usd"] += record.get("cost_usd", 0.0)
                        if record.get("tokens_in") or record.get("tokens_out"):
                            run["tokens_count"] += (record.get("tokens_in", 0) + record.get("tokens_out", 0))
                        
                        if record.get("status") in ["thinking", "tool_call", "done"]:
                            run["steps_count"] += 1
                            
                        if record.get("timestamp") and (not run["timestamp"] or record.get("timestamp") < run["timestamp"]):
                            run["timestamp"] = record.get("timestamp")
            except Exception as e:
                print(f"Error reading audit file: {e}")
                
        runs_list = list(runs_map.values())
        runs_list.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        return runs_list

def start_ui_server(port: int = 8000):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), DashboardHTTPHandler) as httpd:
        print(f"\n==================================================")
        print(f"🚀 Enterprise Agent Web Dashboard is running at:")
        print(f"   👉 http://localhost:{port}")
        print(f"==================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping web dashboard server...")


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Enterprise Agent Execution Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root {
            --bg-base: #060812;
            --bg-surface: #0e1224;
            --bg-surface-glass: rgba(14, 18, 36, 0.75);
            --bg-card: rgba(22, 28, 54, 0.6);
            --border-color: rgba(255, 255, 255, 0.08);
            --border-highlight: rgba(139, 92, 246, 0.3);
            
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            
            --accent-primary: #8b5cf6;
            --accent-primary-hover: #7c3aed;
            --accent-cyan: #06b6d4;
            --accent-emerald: #10b981;
            
            --status-success: #10b981;
            --status-failed: #ef4444;
            --status-running: #f59e0b;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-base);
            color: var(--text-primary);
            height: 100vh;
            display: flex;
            overflow: hidden;
        }

        /* Sidebar */
        .sidebar {
            width: 340px;
            background-color: var(--bg-surface);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            height: 100%;
            flex-shrink: 0;
            z-index: 20;
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-icon {
            width: 36px;
            height: 36px;
            border-radius: 10px;
            background: linear-gradient(135deg, #8b5cf6, #06b6d4);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            box-shadow: 0 4px 12px rgba(139, 92, 246, 0.4);
        }

        .brand-title {
            font-size: 17px;
            font-weight: 800;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #ffffff, #94a3b8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .badge-live {
            font-size: 10px;
            font-weight: 700;
            color: var(--accent-emerald);
            background: rgba(16, 185, 129, 0.15);
            padding: 2px 8px;
            border-radius: 12px;
            border: 1px solid rgba(16, 185, 129, 0.3);
            text-transform: uppercase;
        }

        .runs-list {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .runs-list::-webkit-scrollbar {
            width: 6px;
        }

        .runs-list::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }

        .run-item {
            padding: 16px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.25s ease;
        }

        .run-item:hover {
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 255, 255, 0.15);
            transform: translateY(-2px);
        }

        .run-item.active {
            background: rgba(139, 92, 246, 0.12);
            border-color: var(--border-highlight);
            box-shadow: 0 4px 16px rgba(139, 92, 246, 0.15);
        }

        .run-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .run-name {
            font-size: 14px;
            font-weight: 700;
            color: var(--text-primary);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 180px;
        }

        .status-badge {
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
            padding: 3px 8px;
            border-radius: 20px;
            letter-spacing: 0.5px;
        }

        .status-completed {
            background: rgba(16, 185, 129, 0.15);
            color: var(--status-success);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .status-failed {
            background: rgba(239, 68, 68, 0.15);
            color: var(--status-failed);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .status-running {
            background: rgba(245, 158, 11, 0.15);
            color: var(--status-running);
            border: 1px solid rgba(245, 158, 11, 0.3);
            animation: pulse 1.5s infinite alternate;
        }

        @keyframes pulse {
            0% { opacity: 0.6; }
            100% { opacity: 1; }
        }

        .run-date {
            font-size: 11px;
            color: var(--text-muted);
            margin-bottom: 10px;
        }

        .run-meta {
            font-size: 11px;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
            border-top: 1px dashed var(--border-color);
            padding-top: 8px;
        }

        /* Main View */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
            background: radial-gradient(circle at 50% 0%, #151b38 0%, var(--bg-base) 70%);
        }

        .main-header {
            padding: 20px 40px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(12px);
            background-color: rgba(6, 8, 18, 0.6);
            z-index: 10;
        }

        .header-title h1 {
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.5px;
        }

        .header-title p {
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
            font-family: 'JetBrains Mono', monospace;
        }

        .btn-run {
            background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-hover));
            color: var(--text-primary);
            border: none;
            padding: 12px 24px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.25s ease;
            display: flex;
            align-items: center;
            gap: 10px;
            box-shadow: 0 4px 16px rgba(139, 92, 246, 0.35);
        }

        .btn-run:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5);
        }

        .btn-run:disabled {
            background: var(--text-muted);
            opacity: 0.6;
            cursor: not-allowed;
            box-shadow: none;
        }

        /* Container & Grid */
        .details-container {
            flex: 1;
            overflow-y: auto;
            padding: 32px 40px;
            display: flex;
            flex-direction: column;
            gap: 28px;
        }

        .details-container::-webkit-scrollbar {
            width: 8px;
        }

        .details-container::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }

        .welcome-screen {
            flex: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: var(--text-secondary);
            text-align: center;
            gap: 16px;
        }

        .welcome-icon {
            font-size: 56px;
            opacity: 0.4;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
        }

        .stat-card {
            background: var(--bg-surface-glass);
            border: 1px solid var(--border-color);
            padding: 20px;
            border-radius: 16px;
            backdrop-filter: blur(12px);
        }

        .stat-label {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }

        .stat-value {
            font-size: 22px;
            font-weight: 800;
        }

        /* Timeline & Steps */
        .feed-section {
            background: var(--bg-surface-glass);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 28px;
            backdrop-filter: blur(12px);
        }

        .section-title {
            font-size: 16px;
            font-weight: 800;
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            gap: 10px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 14px;
        }

        .timeline {
            position: relative;
            padding-left: 28px;
            border-left: 2px solid rgba(255, 255, 255, 0.08);
            display: flex;
            flex-direction: column;
            gap: 28px;
        }

        .timeline-item {
            position: relative;
        }

        .timeline-dot {
            position: absolute;
            left: -37px;
            top: 4px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background-color: var(--bg-base);
            border: 3px solid var(--text-muted);
            z-index: 2;
        }

        .timeline-dot.completed {
            border-color: var(--status-success);
            background-color: var(--status-success);
            box-shadow: 0 0 10px var(--status-success);
        }

        .timeline-dot.failed {
            border-color: var(--status-failed);
            background-color: var(--status-failed);
        }

        .timeline-dot.running {
            border-color: var(--status-running);
            background-color: var(--status-running);
            box-shadow: 0 0 12px var(--status-running);
        }

        .event-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            padding: 20px;
            transition: all 0.2s ease;
        }

        .event-card:hover {
            border-color: rgba(255, 255, 255, 0.15);
        }

        .event-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .event-agent {
            font-size: 14px;
            font-weight: 700;
            color: var(--accent-cyan);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .event-time {
            font-size: 11px;
            color: var(--text-muted);
            font-family: 'JetBrains Mono', monospace;
        }

        .event-task {
            font-size: 14px;
            font-weight: 600;
            line-height: 1.5;
            margin-bottom: 12px;
            color: var(--text-primary);
        }

        /* Tool Boxes */
        .tool-box {
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 14px;
            margin-top: 12px;
        }

        .tool-name {
            font-size: 11px;
            font-weight: 800;
            color: var(--status-running);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .code-block {
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
            color: #cbd5e1;
            background: rgba(0, 0, 0, 0.4);
            padding: 10px 14px;
            border-radius: 6px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .toggle-btn {
            font-size: 11px;
            font-weight: 700;
            color: var(--accent-primary);
            cursor: pointer;
            margin-top: 10px;
            display: inline-block;
            user-select: none;
            transition: color 0.2s;
        }

        .toggle-btn:hover {
            color: var(--accent-primary-hover);
        }

        .collapsible {
            display: none;
            margin-top: 8px;
        }

        .collapsible.show {
            display: block;
        }

        /* Output markdown card */
        .output-card {
            background: rgba(16, 185, 129, 0.04);
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 16px;
            padding: 24px;
            line-height: 1.6;
        }

        .output-card h1, .output-card h2, .output-card h3 {
            margin-top: 16px;
            margin-bottom: 8px;
            color: var(--text-primary);
        }

        .output-card p {
            margin-bottom: 12px;
            color: #e2e8f0;
        }

        .output-card ul, .output-card ol {
            margin-left: 20px;
            margin-bottom: 12px;
        }

        .output-card code {
            font-family: 'JetBrains Mono', monospace;
            background: rgba(0, 0, 0, 0.3);
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 13px;
        }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="brand">
                <div class="brand-icon">⚡</div>
                <div>
                    <div class="brand-title">crewctl UI</div>
                    <div class="badge-live">Persistent Memory</div>
                </div>
            </div>
        </div>
        <div class="runs-list" id="runsList"></div>
    </div>

    <!-- Main Section -->
    <div class="main-content">
        <div class="main-header">
            <div class="header-title">
                <h1 id="selectedRunTitle">Select an Execution</h1>
                <p id="selectedRunSubtitle">Choose an agent run to inspect complete steps or trigger a new execution</p>
            </div>
            <button class="btn-run" id="btnRun" onclick="triggerRun()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                Run Agent Crew
            </button>
        </div>

        <div class="details-container" id="detailsContainer">
            <div class="welcome-screen">
                <div class="welcome-icon">🤖</div>
                <h2>Enterprise Agent Dashboard</h2>
                <p>Select any recorded execution from persistent memory to inspect step-by-step agent thoughts, tool invocations, and responses.</p>
            </div>
        </div>
    </div>

    <script>
        let selectedRunId = null;
        let isPollingActive = false;
        let pollTimer = null;

        async function fetchRuns() {
            try {
                const res = await fetch('/api/runs');
                const runs = await res.json();
                renderRunsList(runs);
            } catch (err) {
                console.error("Error fetching runs:", err);
            }
        }

        async function checkActiveRun() {
            try {
                const res = await fetch('/api/active_run');
                const data = await res.json();
                const btn = document.getElementById('btnRun');
                if (data.status === "running") {
                    btn.disabled = true;
                    btn.innerHTML = `<span class="status-running">●</span> Running Agent Crew...`;
                    if (!isPollingActive) {
                        selectedRunId = data.run_id;
                        startPolling();
                    }
                } else {
                    btn.disabled = false;
                    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Run Agent Crew`;
                    if (isPollingActive && selectedRunId === data.run_id) {
                        stopPolling();
                    }
                }
            } catch (err) {
                console.error("Error checking active run:", err);
            }
        }

        function renderRunsList(runs) {
            const container = document.getElementById('runsList');
            container.innerHTML = '';
            
            if (runs.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding-top: 40px; font-size: 13px;">No agent executions stored yet.</div>';
                return;
            }

            runs.forEach(run => {
                const item = document.createElement('div');
                item.className = `run-item ${run.run_id === selectedRunId ? 'active' : ''}`;
                item.onclick = () => selectRun(run.run_id);

                const timeStr = run.timestamp ? new Date(run.timestamp).toLocaleString() : "Recent Run";
                const statusClass = `status-${run.status}`;

                item.innerHTML = `
                    <div class="run-header">
                        <span class="run-name">${run.crew_name}</span>
                        <span class="status-badge ${statusClass}">${run.status}</span>
                    </div>
                    <div class="run-date">${timeStr}</div>
                    <div class="run-meta">
                        <span>Steps: <strong>${run.steps_count}</strong></span>
                        <span>Tokens: <strong>${run.tokens_count}</strong></span>
                    </div>
                `;
                container.appendChild(item);
            });
        }

        async function selectRun(runId) {
            selectedRunId = runId;
            await fetchRuns();
            loadRunDetails(runId);
        }

        async function loadRunDetails(runId) {
            try {
                const res = await fetch(`/api/runs/${runId}`);
                const events = await res.json();
                renderRunDetails(runId, events);
            } catch (err) {
                console.error("Error loading run details:", err);
            }
        }

        function renderRunDetails(runId, events) {
            const container = document.getElementById('detailsContainer');
            if (events.length === 0) {
                container.innerHTML = '<div class="welcome-screen"><h2>No step events recorded for this run.</h2></div>';
                return;
            }

            const startEvent = events.find(e => e.task === "Orchestration Initializing") || events[0];
            const endEvent = events.find(e => e.task === "Orchestration Finished");
            
            const crewName = startEvent.crew_name || "Agent Crew";
            const status = endEvent ? (endEvent.status || "completed") : "running";
            
            document.getElementById('selectedRunTitle').innerText = crewName;
            document.getElementById('selectedRunSubtitle').innerText = `Run ID: ${runId}`;

            let steps = 0;
            let tokens = 0;
            let costUsd = 0.0;
            let finalOutput = "";
            
            events.forEach(e => {
                if (e.status in {thinking:1, tool_call:1, done:1} && e.task !== "Orchestration Initializing" && e.task !== "Orchestration Finished") {
                    steps++;
                }
                if (e.tokens_in) tokens += e.tokens_in;
                if (e.tokens_out) tokens += e.tokens_out;
                if (e.cost_usd) costUsd += e.cost_usd;
            });

            if (endEvent && endEvent.tool_output) {
                finalOutput = endEvent.tool_output;
            } else {
                const lastStep = events[events.length - 1];
                if (lastStep && lastStep.tool_output) finalOutput = lastStep.tool_output;
            }

            let statsHtml = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">Execution Status</div>
                        <div class="stat-value" style="color: ${status === 'completed' ? 'var(--status-success)' : status === 'failed' ? 'var(--status-failed)' : 'var(--status-running)'}">${status.toUpperCase()}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Agent Steps</div>
                        <div class="stat-value">${steps}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Tokens Consumed</div>
                        <div class="stat-value">${tokens}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Execution Cost</div>
                        <div class="stat-value" style="color: var(--accent-cyan);">$${costUsd.toFixed(4)}</div>
                    </div>
                </div>
            `;

            let timelineHtml = '<div class="timeline">';
            events.forEach((e, idx) => {
                if (e.task === "Orchestration Initializing" || e.task === "Orchestration Finished") return;

                let dotClass = e.status === "error" ? "failed" : e.status === "done" ? "completed" : "running";
                if (e.tool_called && e.tool_called !== "None") dotClass = "completed";

                let toolHtml = "";
                if (e.tool_called && e.tool_called !== "None") {
                    toolHtml = `
                        <div class="tool-box">
                            <div class="tool-name">🔧 Tool Invoked: ${e.tool_called}</div>
                            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">Arguments:</div>
                            <pre class="code-block">${JSON.stringify(e.tool_input, null, 2)}</pre>
                            
                            <div class="toggle-btn" onclick="toggleCollapsible('col-${idx}', this)">Show Tool Output ▼</div>
                            <div class="collapsible" id="col-${idx}">
                                <div style="font-size: 11px; color: var(--text-muted); margin-top: 8px; margin-bottom: 4px;">Returned Output:</div>
                                <pre class="code-block" style="color: #a78bfa;">${e.tool_output}</pre>
                            </div>
                        </div>
                    `;
                }

                let stepOutcomeHtml = "";
                if (e.status === "done" && (!e.tool_called || e.tool_called === "None") && e.tool_output) {
                    stepOutcomeHtml = `
                        <div class="tool-box" style="border-color: rgba(16, 185, 129, 0.2);">
                            <div class="tool-name" style="color: var(--status-success);">💡 Step Outcome / Reflection</div>
                            <div style="font-size: 13px; line-height: 1.5; color: #e2e8f0;">${e.tool_output}</div>
                        </div>
                    `;
                }

                const timeStr = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : "";

                timelineHtml += `
                    <div class="timeline-item">
                        <div class="timeline-dot ${dotClass}"></div>
                        <div class="event-card">
                            <div class="event-header">
                                <span class="event-agent">🤖 ${e.agent_name || "Agent"}</span>
                                <span class="event-time">${timeStr}</span>
                            </div>
                            <div class="event-task">${e.task}</div>
                            ${toolHtml}
                            ${stepOutcomeHtml}
                        </div>
                    </div>
                `;
            });
            timelineHtml += '</div>';

            let finalOutputSection = "";
            if (finalOutput) {
                const parsedMarkdown = marked.parse(finalOutput);
                finalOutputSection = `
                    <div class="feed-section">
                        <div class="section-title">🎯 Final Execution Result</div>
                        <div class="output-card">${parsedMarkdown}</div>
                    </div>
                `;
            }

            container.innerHTML = `
                ${statsHtml}
                <div class="feed-section">
                    <div class="section-title">📋 Step-by-Step Execution Feed</div>
                    ${timelineHtml}
                </div>
                ${finalOutputSection}
            `;
        }

        function toggleCollapsible(id, btn) {
            const content = document.getElementById(id);
            content.classList.toggle('show');
            if (content.classList.contains('show')) {
                btn.innerText = 'Hide Tool Output ▲';
            } else {
                btn.innerText = 'Show Tool Output ▼';
            }
        }

        async function triggerRun() {
            try {
                const res = await fetch('/api/run', { method: 'POST' });
                const data = await res.json();
                if (data.run_id) {
                    selectedRunId = data.run_id;
                    await fetchRuns();
                    await checkActiveRun();
                }
            } catch (err) {
                console.error("Error triggering run:", err);
            }
        }

        function startPolling() {
            if (isPollingActive) return;
            isPollingActive = true;
            pollTimer = setInterval(async () => {
                await checkActiveRun();
                await fetchRuns();
                if (selectedRunId) {
                    await loadRunDetails(selectedRunId);
                }
            }, 1000);
        }

        function stopPolling() {
            if (!isPollingActive) return;
            isPollingActive = false;
            clearInterval(pollTimer);
        }

        // Initialize
        fetchRuns();
        checkActiveRun();
        setInterval(checkActiveRun, 3000);
        setInterval(fetchRuns, 5000);
    </script>
</body>
</html>
"""
