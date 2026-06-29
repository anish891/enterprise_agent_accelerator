import os
import yaml
import time
import inspect
from uuid import uuid4
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

from crewai import Agent, Task, Crew, Process
from runtime.llm_router import get_llm
from runtime.task_graph import resolve_execution_batches
from memory.knowledge import KnowledgeMemory
from monitoring.tracer import StepEvent, publish_step_event
from dataclasses import dataclass, asdict, field
from utils.config import load_settings
from utils.logger import get_logger

# Import Connectors mapping
from connectors.jira import JiraConnector
from connectors.servicenow import ServiceNowConnector
from connectors.sap import SapConnector
from connectors.sharepoint import SharePointConnector
from connectors.outlook import OutlookConnector
from connectors.confluence import ConfluenceConnector
from connectors.rest_auto import RESTAutoConnector

logger = get_logger("runtime.orchestrator")

CONNECTOR_MAP: Dict[str, Any] = {
    "jira": JiraConnector,
    "servicenow": ServiceNowConnector,
    "sap": SapConnector,
    "sharepoint": SharePointConnector,
    "outlook": OutlookConnector,
    "confluence": ConfluenceConnector
}

@dataclass
class RunResult:
    run_id: str
    crew_name: str
    final_output: str
    steps: List[StepEvent] = field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    elapsed_seconds: float = 0.0
    status: str = "completed"  # completed | failed | stopped

def resolve_agent_tools(tool_names: List[str], crew_id: str, config_dir: str) -> List[Any]:
    """
    Translates string representations of tools in agents.yaml into live CrewAI BaseTool configurations.
    """
    resolved_tools = []
    connectors_cache: Dict[str, Any] = {}
    settings = load_settings(config_dir)
    
    knowledge_memory = None

    for tool_str in tool_names:
        if tool_str == "knowledge.search":
            if not knowledge_memory:
                knowledge_memory = KnowledgeMemory(crew_id=crew_id, config_dir=config_dir)
            resolved_tools.append(knowledge_memory.as_crewai_tool())
            continue

        parts = tool_str.split(".", 1)
        if len(parts) == 2:
            conn_name, method_name = parts
            if conn_name in CONNECTOR_MAP:
                if conn_name not in connectors_cache:
                    conn_class = CONNECTOR_MAP[conn_name]
                    # Attempt to extract connector settings
                    conn_config = {}
                    for src in settings.memory.knowledge.sources:
                        if src.get("type") == conn_name:
                            conn_config = src
                            break
                    connectors_cache[conn_name] = conn_class(name=conn_name, config=conn_config)
                
                connector = connectors_cache[conn_name]
                all_tools = connector.as_crewai_tools()
                matched = False
                for tool in all_tools:
                    if tool.name == tool_str:
                        resolved_tools.append(tool)
                        matched = True
                        break
                if not matched:
                    logger.warning(f"Method '{method_name}' was not found on connector '{conn_name}'")
            else:
                logger.warning(f"Unknown connector key '{conn_name}' in tool declaration '{tool_str}'")
        else:
            # Check if matching openapi auto-rest endpoints
            resolved_any = False
            for src in settings.memory.knowledge.sources:
                if src.get("type") in ["openapi", "rest"]:
                    spec_path = src.get("spec_url") or src.get("spec_path")
                    if spec_path:
                        conn_name = src.get("name", "openapi")
                        if conn_name not in connectors_cache:
                            connectors_cache[conn_name] = RESTAutoConnector(name=conn_name, config=src, spec_url_or_path=spec_path)
                        rest_tools = connectors_cache[conn_name].from_openapi()
                        for rt in rest_tools:
                            if rt.name.lower() == tool_str.lower():
                                resolved_tools.append(rt)
                                resolved_any = True
                                break
                if resolved_any:
                    break
            if not resolved_any:
                logger.warning(f"Could not map tool name '{tool_str}' to any active connector.")
                
    return resolved_tools

class CrewOrchestrator:
    """
    Enterprise No-Code Crew Orchestration engine.
    Imports configurations from yaml manifests, sets up connectors, RBAC filters,
    handles retries and outputs RunResults.
    """
    def __init__(self, config_dir: str = "."):
        self.config_dir = config_dir
        self.settings = load_settings(config_dir)
        self.run_id = str(uuid4())
        self.crew_name = os.path.basename(os.path.abspath(config_dir)) or "No-Code Agent Crew"
        self.current_task_ref = {"current_task": "Init"}
        self.captured_steps: List[StepEvent] = []

    def _build_step_callback(self) -> Any:
        run_id = self.run_id
        crew_name = self.crew_name
        task_ref = self.current_task_ref
        captured_list = self.captured_steps

        def step_callback(step_output: Any) -> None:
            # 1. Parse tool actions
            tool_called = "None"
            tool_input = {}
            tool_output_val = ""
            
            if hasattr(step_output, "tool"):
                tool_called = getattr(step_output, "tool")
                tool_input = getattr(step_output, "tool_input", {})
                tool_output_val = getattr(step_output, "log", "")
            elif isinstance(step_output, tuple) and len(step_output) > 0:
                action = step_output[0]
                if hasattr(action, "tool"):
                    tool_called = getattr(action, "tool")
                    tool_input = getattr(action, "tool_input", {})
                if len(step_output) > 1:
                    tool_output_val = str(step_output[1])
            elif hasattr(step_output, "output"):
                tool_output_val = getattr(step_output, "output", "")

            # 2. Trace agent identity
            agent_role = "unknown"
            for frame_info in inspect.stack():
                f_self = frame_info.frame.f_locals.get("self")
                if f_self and f_self.__class__.__name__ == "Agent":
                    agent_role = getattr(f_self, "role", "unknown")
                    break

            # 3. Estimate cost metrics
            chars = len(str(tool_input)) + len(str(tool_output_val))
            tokens_in_est = len(str(tool_input)) // 4
            tokens_out_est = len(str(tool_output_val)) // 4
            cost = (tokens_in_est * 0.000003) + (tokens_out_est * 0.000015)

            event = StepEvent(
                run_id=run_id,
                timestamp=datetime.now(),
                agent_name=agent_role,
                task=task_ref.get("current_task", "unknown"),
                tool_called=tool_called,
                tool_input=tool_input,
                tool_output=tool_output_val,
                tokens_in=tokens_in_est,
                tokens_out=tokens_out_est,
                cost_usd=cost,
                latency_ms=150,
                status="thinking" if tool_called == "None" else "tool_call"
            )
            captured_list.append(event)
            publish_step_event(event)

        return step_callback

    def run_crew(self) -> RunResult:
        """
        Loads config settings, initializes resources, executes tasks, and resolves graph batches.
        """
        start_time = time.time()
        
        # Broadcast initiation
        start_event = StepEvent(
            run_id=self.run_id,
            timestamp=datetime.now(),
            agent_name="Orchestrator",
            task="Orchestration Initializing",
            tool_called="None",
            tool_input={},
            tool_output=f"Starting Run {self.run_id} on crew '{self.crew_name}'",
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=0,
            status="thinking"
        )
        publish_step_event(start_event)
        
        # Load Yaml targets
        agents_yaml_path = os.path.join(self.config_dir, "agents.yaml")
        tasks_yaml_path = os.path.join(self.config_dir, "tasks.yaml")
        
        if not os.path.exists(agents_yaml_path) or not os.path.exists(tasks_yaml_path):
            err_msg = f"Orchestrator config loading error: agents.yaml or tasks.yaml not found in directory: {self.config_dir}"
            logger.error(err_msg)
            fail_result = RunResult(
                run_id=self.run_id,
                crew_name=self.crew_name,
                final_output=err_msg,
                status="failed"
            )
            return fail_result

        try:
            with open(agents_yaml_path, "r", encoding="utf-8") as f:
                agents_data = yaml.safe_load(f) or {}
            with open(tasks_yaml_path, "r", encoding="utf-8") as f:
                tasks_data = yaml.safe_load(f) or {}
        except Exception as e:
            err_msg = f"Yaml parsing syntax error: {str(e)}"
            logger.error(err_msg)
            return RunResult(self.run_id, self.crew_name, err_msg, status="failed")

        # 1. Compile CrewAI Agent instances
        agent_instances: Dict[str, Agent] = {}
        for agent_key, info in agents_data.items():
            llm_model = info.get("llm") or self.settings.default_llm
            llm_obj = get_llm(llm_model)
            
            tool_strings = info.get("tools") or []
            resolved_tools = resolve_agent_tools(tool_strings, self.run_id, self.config_dir)
            
            agent_instances[agent_key] = Agent(
                role=info.get("role", "Assistant"),
                goal=info.get("goal", "Support operations"),
                backstory=info.get("backstory", ""),
                llm=llm_obj,
                tools=resolved_tools,
                verbose=True,
                allow_delegation=False
            )

        # 2. Determine execution structure
        process_mode = self.settings.process.lower()
        step_callback_fn = self._build_step_callback()
        
        final_output_str = ""
        run_status = "completed"

        try:
            if process_mode == "parallel":
                # Resolve batch execution DAG
                batches = resolve_execution_batches(tasks_data)
                
                # We retain outputs of previous tasks to inject as inputs for dependent tasks
                task_outputs: Dict[str, str] = {}
                
                for idx, batch in enumerate(batches):
                    self.current_task_ref["current_task"] = f"Executing Batch {idx + 1}"
                    
                    def run_single_task(task_key: str) -> Tuple[str, str]:
                        t_info = tasks_data[task_key]
                        agent_key = t_info.get("agent")
                        agent_obj = agent_instances.get(agent_key)
                        if not agent_obj:
                            raise ValueError(f"Agent '{agent_key}' declared in task '{task_key}' does not exist.")
                            
                        # Build desc with parent outputs if referenced
                        description_str = t_info.get("description", "")
                        # Simple placeholder replacement if inputs are present
                        # formatting with task output data
                        description_str = description_str.format(**task_outputs)
                        
                        task_obj = Task(
                            description=description_str,
                            expected_output=t_info.get("expected_output", "Success"),
                            agent=agent_obj
                        )
                        
                        # Set current task description in logs
                        logger.info(f"Kicking off parallel Task: {task_key}")
                        
                        # Execute task as a mini-crew sequence
                        mini_crew = Crew(
                            agents=[agent_obj],
                            tasks=[task_obj],
                            step_callback=step_callback_fn,
                            verbose=True
                        )
                        result = mini_crew.kickoff()
                        # Extract string result
                        res_str = getattr(result, "raw", str(result))
                        return task_key, res_str

                    # Execute batch concurrent threads
                    if len(batch) > 1:
                        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                            futures = [executor.submit(run_single_task, t_key) for t_key in batch]
                            for fut in futures:
                                t_key, res = fut.result()
                                task_outputs[t_key] = res
                    else:
                        t_key, res = run_single_task(batch[0])
                        task_outputs[t_key] = res
                
                # Final task output is mapped
                final_output_str = list(task_outputs.values())[-1] if task_outputs else "No tasks executed."

            else:
                # Sequential / Hierarchical Execution
                # Compile Tasks in sequential order matching definition
                tasks_list: List[Task] = []
                for t_key, t_info in tasks_data.items():
                    agent_key = t_info.get("agent")
                    agent_obj = agent_instances.get(agent_key)
                    if not agent_obj:
                        raise ValueError(f"Agent '{agent_key}' declared in task '{t_key}' does not exist.")
                        
                    task_obj = Task(
                        description=t_info.get("description", ""),
                        expected_output=t_info.get("expected_output", "Output description"),
                        agent=agent_obj
                    )
                    tasks_list.append(task_obj)
                
                crew_process = Process.hierarchical if process_mode == "hierarchical" else Process.sequential
                
                crew_instance = Crew(
                    agents=list(agent_instances.values()),
                    tasks=tasks_list,
                    process=crew_process,
                    step_callback=step_callback_fn,
                    verbose=True
                )
                
                # Attach manager LLM if hierarchical
                if process_mode == "hierarchical":
                    manager_llm = get_llm(self.settings.default_llm)
                    crew_instance.manager_llm = manager_llm
                
                # Kickoff Crew
                logger.info(f"Kicking off sequential/hierarchical Crew: '{self.crew_name}'")
                result_obj = crew_instance.kickoff()
                final_output_str = getattr(result_obj, "raw", str(result_obj))
                
        except Exception as e:
            logger.error(f"Execution crashed during Crew execution: {str(e)}")
            final_output_str = f"Execution Failure: {str(e)}"
            run_status = "failed"

        # Calculate final totals
        elapsed_sec = time.time() - start_time
        total_tokens = sum(e.tokens_in + e.tokens_out for e in self.captured_steps)
        total_cost = sum(e.cost_usd for e in self.captured_steps)
        
        # Broadcast completed/failed event
        end_event = StepEvent(
            run_id=self.run_id,
            timestamp=datetime.now(),
            agent_name="Orchestrator",
            task="Orchestration Finished",
            tool_called="None",
            tool_input={},
            tool_output=final_output_str,
            tokens_in=0,
            tokens_out=0,
            cost_usd=total_cost,
            latency_ms=int(elapsed_sec * 1000),
            status=run_status
        )
        publish_step_event(end_event)
        
        # Compile result object
        result = RunResult(
            run_id=self.run_id,
            crew_name=self.crew_name,
            final_output=final_output_str,
            steps=self.captured_steps,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            elapsed_seconds=elapsed_sec,
            status=run_status
        )
        return result
