import inspect
import time
from typing import Any, Callable, Dict, List, Type
from pydantic import create_model, BaseModel
from crewai.tools import BaseTool
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.base")

class BaseConnector:
    """
    Base class for all enterprise connectors.
    Handles auth, retries, audit logging, and conversion of domain methods to CrewAI tools.
    """
    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        
    def authenticate(self) -> None:
        """
        Performs authentication or configuration setup.
        Overridden by subclasses to fetch secrets from the config/secrets backend.
        """
        pass
        
    def execute(self, action: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Wraps call execution with retry logic.
        """
        return self.retry(action, *args, **kwargs)
        
    def retry(self, fn: Callable[..., Any], *args: Any, max_retries: int = 3, **kwargs: Any) -> Any:
        """
        Executes a function with exponential backoff on failure.
        """
        delay = 1.0
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Connector {self.name} failed attempt {attempt + 1}/{max_retries}. Error: {str(e)}"
                )
                if attempt == max_retries - 1:
                    raise e
                time.sleep(delay)
                delay *= 2.0
                
    def audit(self, action: str, params: Dict[str, Any], status: str, result: Any = None, error: str = None) -> None:
        """
        Appends the connector execution trace to the central audit log.
        """
        try:
            from monitoring.audit import log_audit_record
            log_audit_record({
                "event_type": "connector_call",
                "connector_name": self.name,
                "action": action,
                "params": params,
                "status": status,
                "result": str(result) if result is not None else None,
                "error": error
            })
        except Exception as e:
            logger.debug(f"Audit log write skipped during connector execution: {str(e)}")

    def as_crewai_tools(self) -> List[BaseTool]:
        """
        Generates CrewAI tools dynamically by reflecting on all public methods of the subclass.
        """
        tools = []
        base_methods = set(dir(BaseConnector))
        
        for attr_name in dir(self):
            # Exclude private methods and methods inherited directly from BaseConnector
            if attr_name.startswith('_') or attr_name in base_methods:
                continue
                
            member = getattr(self, attr_name)
            if not inspect.ismethod(member):
                continue
                
            tools.append(self._create_tool_from_method(attr_name, member))
            
        return tools

    def _create_tool_from_method(self, method_name: str, method: Callable[..., Any]) -> BaseTool:
        """
        Creates a CrewAI BaseTool subclass dynamically with Pydantic arguments schema.
        """
        sig = inspect.signature(method)
        fields = {}
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            
            # Infer parameter type or default to Any
            param_type = param.annotation if param.annotation != inspect.Parameter.empty else Any
            
            # Infer parameter default value or default to Ellipsis (...) signifying required
            default_val = param.default if param.default != inspect.Parameter.empty else ...
            
            fields[param_name] = (param_type, default_val)
            
        # Dynamically build Pydantic model for validation
        args_schema = create_model(f"{self.name}_{method_name}_args", **fields)
        tool_name = f"{self.name}.{method_name}"
        docstring = method.__doc__ or f"Execute {self.name}.{method_name} connector function."
        
        connector_instance = self
        
        class DynamicConnectorTool(BaseTool):
            name: str = tool_name
            description: str = docstring
            args_schema: Type[BaseModel] = args_schema
            
            def _run(self, **kwargs: Any) -> str:
                # 1. Determine agent calling this tool by scanning the stack
                agent_name = "unknown"
                for frame_info in inspect.stack():
                    frame_self = frame_info.frame.f_locals.get("self")
                    if frame_self and frame_self.__class__.__name__ == "Agent":
                        # Attempt to get the role or id to match rbac role naming conventions
                        agent_role = getattr(frame_self, "role", None)
                        if agent_role:
                            agent_name = agent_role
                        else:
                            agent_name = getattr(frame_self, "id", "unknown")
                        break
                
                # Format to normalized name (e.g. "IT Support Specialist" -> "it_support_agent" or match direct role)
                normalized_agent = agent_name.lower().replace(" ", "_")
                # Append '_agent' if not already present
                if not normalized_agent.endswith("_agent") and normalized_agent != "unknown":
                    # Check both versions in RBAC: role as-is, and role with _agent
                    pass
                
                # 2. Enforce RBAC validation
                try:
                    from security.rbac import check_permission
                    check_permission(normalized_agent, tool_name)
                except PermissionError as pe:
                    connector_instance.audit(method_name, kwargs, "rbac_denied", error=str(pe))
                    return f"Permission Denied: {str(pe)}"
                except Exception as e:
                    # If RBAC config check fails, proceed but log warning
                    logger.warning(f"RBAC check raised unexpected error: {str(e)}")
                
                # 3. Authenticate and execute domain logic
                try:
                    connector_instance.authenticate()
                    result = connector_instance.execute(method, **kwargs)
                    connector_instance.audit(method_name, kwargs, "success", result=result)
                    return str(result)
                except Exception as e:
                    connector_instance.audit(method_name, kwargs, "failed", error=str(e))
                    return f"Error executing {tool_name}: {str(e)}"
                    
        return DynamicConnectorTool()
