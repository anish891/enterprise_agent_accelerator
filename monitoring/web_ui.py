import os
import json
import threading
import http.server
import socketserver
from typing import Any, Dict, List
from monitoring.audit import get_audit_file_path, get_events_by_run
from runtime.orchestrator import CrewOrchestrator

active_run_id = None
active_run_status = "idle"

class DashboardHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress standard request logging to keep the console clean
        pass

    def do_GET(self):
        global active_run_id, active_run_status
        
        # Handle CORS
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
        filepath = get_audit_file_path()
        if not os.path.exists(filepath):
            return []
            
        runs_map = {}
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
                    
                    event_type = record.get("event_type")
                    task = record.get("task")
                    
                    if task == "Orchestration Finished":
                        run["status"] = record.get("status") or "completed"
                        run["final_output"] = record.get("tool_output")
                    
                    if record.get("cost_usd"):
                        run["cost_usd"] += record.get("cost_usd", 0.0)
                    if record.get("tokens_in") or record.get("tokens_out"):
                        run["tokens_count"] += (record.get("tokens_in", 0) + record.get("tokens_out", 0))
                    
                    if record.get("status") in ["thinking", "tool_call"]:
                        run["steps_count"] += 1
                        
                    # Keep the earliest timestamp
                    if record.get("timestamp") and record.get("timestamp") < run["timestamp"]:
                        run["timestamp"] = record.get("timestamp")
        except Exception as e:
            print(f"Error reading audit file: {e}")
            
        runs_list = list(runs_map.values())
        # Sort by timestamp descending
        runs_list.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        return runs_list

def start_ui_server(port: int = 8000):
    # Enable reuse address to avoid 'Address already in use' errors
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
    <title>Enterprise Agent Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #070913;
            --bg-surface: #0f1224;
            --bg-surface-glass: rgba(15, 18, 36, 0.6);
            --border-color: rgba(255, 255, 255, 0.06);
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-primary: #8b5cf6;
            --accent-primary-hover: #7c3aed;
            --accent-cyan: #06b6d4;
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

        /* Sidebar styling */
        .sidebar {
            width: 320px;
            background-color: var(--bg-surface);
            border-right: 1px solid var(--border-color);
            display: flex;
            flex-direction: flex-col;
            height: 100%;
            flex-shrink: 0;
        }

        .sidebar-header {
            padding: 24px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .sidebar-title {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #a78bfa, #06b6d4);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .runs-list {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }

        .run-item {
            padding: 16px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid transparent;
            margin-bottom: 12px;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .run-item:hover {
            background: rgba(255, 255, 255, 0.04);
            border-color: rgba(255, 255, 255, 0.05);
            transform: translateY(-1px);
        }

        .run-item.active {
            background: rgba(139, 92, 246, 0.1);
            border-color: rgba(139, 92, 246, 0.3);
        }

        .run-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }

        .run-name {
            font-size: 14px;
            font-weight: 600;
            max-width: 180px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .status-badge {
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
            padding: 4px 8px;
            border-radius: 20px;
            letter-spacing: 0.5px;
        }

        .status-completed {
            background: rgba(16, 185, 129, 0.15);
            color: var(--status-success);
        }

        .status-failed {
            background: rgba(239, 68, 68, 0.15);
            color: var(--status-failed);
        }

        .status-running {
            background: rgba(245, 158, 11, 0.15);
            color: var(--status-running);
            animation: pulse 1.5s infinite alternate;
        }

        @keyframes pulse {
            0% { opacity: 0.6; }
            100% { opacity: 1; }
        }

        .run-meta {
            font-size: 11px;
            color: var(--text-secondary);
            display: flex;
            justify-content: space-between;
            margin-top: 8px;
        }

        /* Main content area */
        .main-content {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
            background: radial-gradient(circle at 50% 0%, #131735 0%, var(--bg-base) 70%);
        }

        .main-header {
            padding: 24px 40px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            backdrop-filter: blur(8px);
            background-color: rgba(7, 9, 19, 0.4);
            z-index: 10;
        }

        .header-left h1 {
            font-size: 24px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }

        .header-left p {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }

        .btn-run {
            background-color: var(--accent-primary);
            color: var(--text-primary);
            border: none;
            padding: 12px 24px;
            border-radius: 10px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
        }

        .btn-run:hover:not(:disabled) {
            background-color: var(--accent-primary-hover);
            transform: translateY(-1px);
        }

        .btn-run:disabled {
            background-color: var(--text-muted);
            cursor: not-allowed;
            box-shadow: none;
            opacity: 0.6;
        }

        /* Details layout */
        .details-container {
            flex: 1;
            overflow-y: auto;
            padding: 40px;
            display: flex;
            flex-direction: column;
            gap: 32px;
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
            font-size: 64px;
            opacity: 0.3;
        }

        /* Stats Cards */
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
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .stat-value {
            font-size: 20px;
            font-weight: 700;
        }

        /* Timeline / Feed */
        .feed-section {
            background: var(--bg-surface-glass);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 32px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        .section-title {
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
        }

        .timeline {
            position: relative;
            padding-left: 24px;
            border-left: 2px solid rgba(255, 255, 255, 0.05);
            display: flex;
            flex-direction: column;
            gap: 32px;
        }

        .timeline-item {
            position: relative;
        }

        .timeline-dot {
            position: absolute;
            left: -33px;
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
        }

        .timeline-dot.failed {
            border-color: var(--status-failed);
            background-color: var(--status-failed);
        }

        .timeline-dot.running {
            border-color: var(--status-running);
            background-color: var(--status-running);
            box-shadow: 0 0 10px var(--status-running);
        }

        .event-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }

        .event-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 12px;
            font-size: 13px;
        }

        .event-agent {
            font-weight: 600;
            color: var(--accent-cyan);
        }

        .event-time {
            color: var(--text-muted);
        }

        .event-task {
            font-size: 15px;
            font-weight: 500;
            margin-bottom: 12px;
            line-height: 1.5;
        }

        /* Tool calls styling */
        .tool-call-box {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            padding: 12px;
            margin-top: 12px;
        }

        .tool-title {
            font-size: 12px;
            font-weight: 700;
            color: var(--status-running);
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .tool-code {
            font-family: monospace;
            font-size: 12px;
            white-space: pre-wrap;
            color: var(--text-primary);
        }

        /* Collapsible detail button */
        .collapsible-trigger {
            font-size: 12px;
            color: var(--accent-primary);
            cursor: pointer;
            margin-top: 8px;
            display: inline-block;
            user-select: none;
        }

        .collapsible-content {
            display: none;
            margin-top: 8px;
        }

        .collapsible-content.show {
            display: block;
        }

        .final-answer-box {
            background: rgba(16, 185, 129, 0.05);
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 12px;
            padding: 20px;
            margin-top: 16px;
        }

        .final-answer-title {
            color: var(--status-success);
            font-weight: 700;
            font-size: 14px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
    </style>
</head>
<body>
    <!-- Sidebar -->
    <div class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-title">crewctl Dashboard</div>
        </div>
        <div class="runs-list" id="runsList">
            <!-- Dynamic Runs List -->
        </div>
    </div>

    <!-- Main Content -->
    <div class="main-content">
        <div class="main-header">
            <div class="header-left">
                <h1 id="selectedRunTitle">Select an Execution</h1>
                <p id="selectedRunSubtitle">Choose a run from the sidebar or kick off a new execution</p>
            </div>
            <button class="btn-run" id="btnRun" onclick="triggerRun()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                Run Agent Crew
            </button>
        </div>

        <div class="details-container" id="detailsContainer">
            <div class="welcome-screen">
                <div class="welcome-icon">🚀</div>
                <h2>Enterprise Agent Orchestrator</h2>
                <p>Select a historical execution from the sidebar to view detailed agent logs, tool inputs, outputs, and metrics.</p>
            </div>
        </div>
    </div>

    <script>
        let selectedRunId = null;
        let isPollingActive = false;
        let pollTimer = null;

        // Fetch runs list on load
        async function fetchRuns() {
            try {
                const res = await fetch('/api/runs');
                const runs = await res.json();
                renderRunsList(runs);
            } catch (err) {
                console.error("Error fetching runs:", err);
            }
        }

        // Fetch active run status
        async function checkActiveRun() {
            try {
                const res = await fetch('/api/active_run');
                const data = await res.json();
                const btn = document.getElementById('btnRun');
                if (data.status === "running") {
                    btn.disabled = true;
                    btn.innerHTML = `<span class="status-running">●</span> Running...`;
                    if (!isPollingActive) {
                        selectedRunId = data.run_id;
                        startPolling();
                    }
                } else {
                    btn.disabled = false;
                    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Run Agent Crew`;
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
                container.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding-top: 40px;">No runs found.</div>';
                return;
            }

            runs.forEach(run => {
                const item = document.createElement('div');
                item.className = `run-item ${run.run_id === selectedRunId ? 'active' : ''}`;
                item.onclick = () => selectRun(run.run_id);

                const timeStr = new Date(run.timestamp).toLocaleString();
                const statusClass = `status-${run.status}`;

                item.innerHTML = `
                    <div class="run-header">
                        <span class="run-name">${run.crew_name}</span>
                        <span class="status-badge ${statusClass}">${run.status}</span>
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted);">${timeStr}</div>
                    <div class="run-meta">
                        <span>Steps: ${run.steps_count}</span>
                        <span>Tokens: ${run.tokens_count}</span>
                    </div>
                `;
                container.appendChild(item);
            });
        }

        async function selectRun(runId) {
            selectedRunId = runId;
            // Update active styling in sidebar
            document.querySelectorAll('.run-item').forEach(el => el.classList.remove('active'));
            
            // Re-fetch list to show current active selection
            await fetchRuns();
            
            // Load run details
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
                container.innerHTML = '<div class="welcome-screen"><h2>No events found for this run.</h2></div>';
                return;
            }

            // Find run metadata
            const startEvent = events.find(e => e.task === "Orchestration Initializing") || events[0];
            const endEvent = events.find(e => e.task === "Orchestration Finished");
            
            const crewName = startEvent.crew_name || "Agent Crew";
            const status = endEvent ? (endEvent.status || "completed") : "running";
            
            document.getElementById('selectedRunTitle').innerText = crewName;
            document.getElementById('selectedRunSubtitle').innerText = `Run ID: ${runId}`;

            // Calculate stats
            let steps = 0;
            let tokens = 0;
            let finalOutput = "";
            events.forEach(e => {
                if (e.status in {thinking:1, tool_call:1}) steps++;
                if (e.tokens_in) tokens += e.tokens_in;
                if (e.tokens_out) tokens += e.tokens_out;
            });

            if (endEvent) {
                finalOutput = endEvent.tool_output || "";
            }

            let statsHtml = `
                <div class="stats-grid">
                    <div class="stat-card">
                        <div class="stat-label">Status</div>
                        <div class="stat-value" style="color: ${status === 'completed' ? 'var(--status-success)' : status === 'failed' ? 'var(--status-failed)' : 'var(--status-running)'}">${status.toUpperCase()}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total Steps</div>
                        <div class="stat-value">${steps}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Total Tokens</div>
                        <div class="stat-value">${tokens}</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-label">Execution ID</div>
                        <div class="stat-value" style="font-size: 11px; word-break: break-all; font-family: monospace; color: var(--text-secondary);">${runId}</div>
                    </div>
                </div>
            `;

            let timelineHtml = '<div class="timeline">';
            events.forEach((e, idx) => {
                if (e.task === "Orchestration Initializing" || e.task === "Orchestration Finished") {
                    return; // Skip boundary events in main timeline
                }

                let dotClass = e.status === "error" ? "failed" : e.status === "done" ? "completed" : "running";
                if (e.tool_called && e.tool_called !== "None") {
                    dotClass = "completed";
                }

                let toolHtml = "";
                if (e.tool_called && e.tool_called !== "None") {
                    toolHtml = `
                        <div class="tool-call-box">
                            <div class="tool-title">🔧 Tool Invoked: ${e.tool_called}</div>
                            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 4px;">Arguments:</div>
                            <pre class="tool-code">${JSON.stringify(e.tool_input, null, 2)}</pre>
                            
                            <div class="collapsible-trigger" onclick="toggleCollapsible(${idx})">Show Tool Output ▼</div>
                            <div class="collapsible-content" id="col-${idx}">
                                <div style="font-size: 11px; color: var(--text-muted); margin-top: 8px; margin-bottom: 4px;">Output:</div>
                                <pre class="tool-code" style="background: rgba(0,0,0,0.4); padding: 8px; border-radius: 4px; color: var(--text-secondary);">${e.tool_output}</pre>
                            </div>
                        </div>
                    `;
                }

                let finalAnswerHtml = "";
                if (e.status === "done" || (idx === events.length - 2 && !endEvent)) {
                    finalAnswerHtml = `
                        <div class="final-answer-box">
                            <div class="final-answer-title">✅ Agent Final Outcome</div>
                            <div style="font-size: 14px; line-height: 1.6;">${e.tool_output}</div>
                        </div>
                    `;
                }

                const timeStr = new Date(e.timestamp).toLocaleTimeString();

                timelineHtml += `
                    <div class="timeline-item">
                        <div class="timeline-dot ${dotClass}"></div>
                        <div class="event-card">
                            <div class="event-header">
                                <span class="event-agent">🤖 ${e.agent_name}</span>
                                <span class="event-time">${timeStr}</span>
                            </div>
                            <div class="event-task">${e.task}</div>
                            ${toolHtml}
                            ${finalAnswerHtml}
                        </div>
                    </div>
                `;
            });
            timelineHtml += '</div>';

            let finalOutputSection = "";
            if (finalOutput) {
                finalOutputSection = `
                    <div class="feed-section">
                        <div class="section-title">🏆 Final Output Result</div>
                        <div style="white-space: pre-wrap; line-height: 1.6; font-size: 15px;">${finalOutput}</div>
                    </div>
                `;
            }

            container.innerHTML = `
                ${statsHtml}
                <div class="feed-section">
                    <div class="section-title">📋 Execution Timeline</div>
                    ${timelineHtml}
                </div>
                ${finalOutputSection}
            `;
        }

        function toggleCollapsible(idx) {
            const content = document.getElementById(`col-${idx}`);
            content.classList.toggle('show');
            const trigger = content.previousElementSibling;
            if (content.classList.contains('show')) {
                trigger.innerText = 'Hide Tool Output ▲';
            } else {
                trigger.innerText = 'Show Tool Output ▼';
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
