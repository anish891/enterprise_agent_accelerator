import subprocess
import threading
import sys
import time
from typing import Dict, Any
from monitoring.dashboard import run_dashboard
from utils.logger import get_logger

logger = get_logger("cli.watch")

def watch_command(command: str) -> None:
    """
    Executes a shell command (running a crew script) in a background thread
    and renders the Rich-based Live Dashboard in the foreground terminal buffer.
    Handles SIGINT gracefully by terminating the running process.
    """
    logger.info(f"Starting watched subprocess: '{command}'")
    
    execution_result: Dict[str, Any] = {}
    
    def execute_subprocess() -> None:
        try:
            # Execute command using standard shell environments
            proc = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            execution_result["proc"] = proc
            stdout, stderr = proc.communicate()
            execution_result["stdout"] = stdout
            execution_result["stderr"] = stderr
            execution_result["returncode"] = proc.returncode
        except Exception as e:
            execution_result["error"] = str(e)
            logger.error(f"Failed to start watched command: {str(e)}")

    # Spin up background process
    bg_thread = threading.Thread(target=execute_subprocess)
    bg_thread.daemon = True
    bg_thread.start()

    # Let the process initialize and emit initial startup logs
    time.sleep(0.6)

    try:
        # Run live dashboard block in foreground
        run_dashboard()
    except KeyboardInterrupt:
        # If interrupted by user, kill process
        if "proc" in execution_result:
            proc_obj = execution_result["proc"]
            logger.info("Watch command terminated by user. Stopping subprocess...")
            proc_obj.terminate()
        sys.exit(0)

    bg_thread.join(timeout=3)
    
    ret_code = execution_result.get("returncode", 0)
    if ret_code != 0:
        sys.stderr.write(f"\n[Watch Error] Command '{command}' exited with return code {ret_code}\n")
        err_msg = execution_result.get("stderr")
        if err_msg:
            sys.stderr.write(f"Details:\n{err_msg}\n")
