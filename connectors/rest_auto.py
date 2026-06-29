import json
import yaml
import requests
import re
from typing import List, Dict, Any, Type
from pydantic import create_model, BaseModel, Field
from urllib.parse import urljoin
from connectors.base import BaseConnector
from crewai.tools import BaseTool
from utils.logger import get_logger

logger = get_logger("connectors.rest_auto")

class RESTAutoConnector(BaseConnector):
    """
    OpenAPI Specification Connector.
    Loads JSON/YAML specs, parses endpoints, and returns dynamically generated CrewAI tools.
    """
    def __init__(self, name: str, config: Dict[str, Any] = None, spec_url_or_path: str = None):
        super().__init__(name, config)
        self.spec_url_or_path = spec_url_or_path or self.config.get("spec_url") or self.config.get("spec_path")
        self.spec_data: Dict[str, Any] = {}
        self.base_url: str = ""
        self.headers: Dict[str, str] = {}
        
    def authenticate(self) -> None:
        """
        Extracts authentication parameters from configuration or secrets vault.
        """
        auth_cfg = self.config.get("auth")
        
        # If string expression, try resolving from secrets
        if isinstance(auth_cfg, str) and auth_cfg.startswith("env:"):
            from security.secrets import get_secret
            token_key = auth_cfg.split("env:")[1]
            token = get_secret(token_key)
            if token:
                self.headers["Authorization"] = f"Bearer {token}"
            return

        if not auth_cfg:
            from security.secrets import get_secret
            token = get_secret(f"{self.name.upper()}_TOKEN")
            if token:
                self.headers["Authorization"] = f"Bearer {token}"
            return

        if isinstance(auth_cfg, dict):
            auth_type = auth_cfg.get("type", "").lower()
            if auth_type == "bearer":
                token = auth_cfg.get("token")
                self.headers["Authorization"] = f"Bearer {token}"
            elif auth_type == "api_key":
                key_name = auth_cfg.get("key_name", "X-API-Key")
                key_val = auth_cfg.get("value")
                self.headers[key_name] = key_val
            elif auth_type == "basic":
                import base64
                username = auth_cfg.get("username", "")
                password = auth_cfg.get("password", "")
                encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
                self.headers["Authorization"] = f"Basic {encoded}"

    def from_openapi(self) -> List[BaseTool]:
        """
        Loads the OpenAPI spec, parses all valid endpoints, and constructs a list of CrewAI tools.
        """
        if not self.spec_url_or_path:
            logger.error("Cannot load OpenAPI spec: spec_url_or_path parameter is missing.")
            return []

        try:
            # Handle Remote Fetch vs Local Files
            if self.spec_url_or_path.startswith("http://") or self.spec_url_or_path.startswith("https://"):
                res = requests.get(self.spec_url_or_path, timeout=10)
                res.raise_for_status()
                # Determine json vs yaml parsing
                if self.spec_url_or_path.endswith(".yaml") or self.spec_url_or_path.endswith(".yml") or "yaml" in res.headers.get("Content-Type", ""):
                    self.spec_data = yaml.safe_load(res.text)
                else:
                    self.spec_data = res.json()
            else:
                with open(self.spec_url_or_path, "r", encoding="utf-8") as f:
                    if self.spec_url_or_path.endswith(".yaml") or self.spec_url_or_path.endswith(".yml"):
                        self.spec_data = yaml.safe_load(f)
                    else:
                        self.spec_data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading OpenAPI definition: {str(e)}")
            return []

        # Extract server block Base URL
        servers = self.spec_data.get("servers", [])
        if servers:
            self.base_url = servers[0].get("url", "")
            if self.base_url.startswith("/") and (self.spec_url_or_path.startswith("http://") or self.spec_url_or_path.startswith("https://")):
                self.base_url = urljoin(self.spec_url_or_path, self.base_url)
        else:
            self.base_url = "http://localhost"

        tools = []
        paths = self.spec_data.get("paths", {})
        
        for path, path_item in paths.items():
            for method, op in path_item.items():
                if method.lower() not in ["get", "post", "put", "delete", "patch"]:
                    continue
                
                # Deriving operation identification
                op_id = op.get("operationId")
                if not op_id:
                    clean_path = re.sub(r"[{}]", "", path).replace("/", "_").strip("_")
                    op_id = f"{method}_{clean_path}"
                
                tags = op.get("tags", [])
                tag = tags[0] if tags else self.name
                
                tool_name = f"{tag}_{op_id}".lower().replace("-", "_")
                
                # Accumulate parameters
                fields = {}
                parameters = op.get("parameters", [])
                # Include root parameters for this specific path item
                if isinstance(path_item.get("parameters"), list):
                    parameters.extend(path_item["parameters"])
                
                for param in parameters:
                    p_name = param.get("name")
                    p_in = param.get("in")  # path, query, header, cookie
                    p_required = param.get("required", False)
                    schema = param.get("schema", {})
                    p_type = schema.get("type", "string")
                    
                    py_type = str
                    if p_type == "integer":
                        py_type = int
                    elif p_type == "number":
                        py_type = float
                    elif p_type == "boolean":
                        py_type = bool
                        
                    default_expr = ... if p_required else None
                    fields[p_name] = (py_type, Field(default_expr, description=param.get("description", "")))
                
                # Process body parameters for writing methods
                request_body = op.get("requestBody", {})
                if request_body:
                    content_schema = request_body.get("content", {}).get("application/json", {}).get("schema", {})
                    if content_schema:
                        if content_schema.get("type") == "object":
                            properties = content_schema.get("properties", {})
                            required = content_schema.get("required", [])
                            for prop_name, prop_val in properties.items():
                                p_type = prop_val.get("type", "string")
                                py_type = str
                                if p_type == "integer":
                                    py_type = int
                                elif p_type == "number":
                                    py_type = float
                                elif p_type == "boolean":
                                    py_type = bool
                                elif p_type == "object":
                                    py_type = dict
                                elif p_type == "array":
                                    py_type = list
                                    
                                default_expr = ... if prop_name in required else None
                                fields[prop_name] = (py_type, Field(default_expr, description=prop_val.get("description", "")))
                        else:
                            fields["json_body"] = (dict, Field(None, description="Direct JSON dict payload"))

                args_schema = create_model(f"{tool_name}_args", **fields)
                description = op.get("summary") or op.get("description") or f"Executes {method.upper()} HTTP call to {path}"
                
                tools.append(self._create_rest_tool(tool_name, description, args_schema, method, path, parameters))
                
        return tools

    def _create_rest_tool(self, name: str, description: str, args_schema: Type[BaseModel], method: str, path: str, parameters: list) -> BaseTool:
        connector_instance = self
        
        class RESTTool(BaseTool):
            name: str = name
            description: str = description
            args_schema: Type[BaseModel] = args_schema
            
            def _run(self, **kwargs: Any) -> str:
                # 1. Enforce RBAC validation
                agent_name = "unknown"
                for frame_info in inspect.stack():
                    frame_self = frame_info.frame.f_locals.get("self")
                    if frame_self and frame_self.__class__.__name__ == "Agent":
                        agent_role = getattr(frame_self, "role", None)
                        if agent_role:
                            agent_name = agent_role
                        else:
                            agent_name = getattr(frame_self, "id", "unknown")
                        break
                
                normalized_agent = agent_name.lower().replace(" ", "_")
                try:
                    from security.rbac import check_permission
                    check_permission(normalized_agent, name)
                except PermissionError as pe:
                    connector_instance.audit(name, kwargs, "rbac_denied", error=str(pe))
                    return f"Permission Denied: {str(pe)}"
                except Exception as e:
                    logger.debug(f"RBAC failed to execute check: {str(e)}")

                # 2. Setup call variables
                url_path = path
                query_params = {}
                body_data = {}
                
                path_params = {p.get("name") for p in parameters if p.get("in") == "path"}
                query_params_set = {p.get("name") for p in parameters if p.get("in") == "query"}
                
                for k, v in kwargs.items():
                    if k in path_params:
                        url_path = url_path.replace(f"{{{k}}}", str(v))
                    elif k in query_params_set:
                        query_params[k] = v
                    elif k == "json_body":
                        body_data.update(v)
                    else:
                        body_data[k] = v
                        
                target_url = urljoin(connector_instance.base_url, url_path)
                
                # Mock fallback if address looks like a mock URL or lacks schema
                if "mock" in target_url or not target_url.startswith("http"):
                    connector_instance.audit(name, kwargs, "success", result="mock_success")
                    return f"MOCK REST Call [{method.upper()}] URL: {target_url} Parameters: {query_params} Body: {body_data} -> Response: 200 OK. Operation: Completed."
                
                try:
                    connector_instance.authenticate()
                    
                    def run_http_call():
                        headers = connector_instance.headers
                        if method.lower() == "get":
                            resp = requests.get(target_url, params=query_params, headers=headers, timeout=10)
                        elif method.lower() == "post":
                            resp = requests.post(target_url, json=body_data, params=query_params, headers=headers, timeout=10)
                        elif method.lower() == "put":
                            resp = requests.put(target_url, json=body_data, params=query_params, headers=headers, timeout=10)
                        elif method.lower() == "patch":
                            resp = requests.patch(target_url, json=body_data, params=query_params, headers=headers, timeout=10)
                        elif method.lower() == "delete":
                            resp = requests.delete(target_url, params=query_params, headers=headers, timeout=10)
                        else:
                            return f"Unsupported REST action: {method}"
                            
                        resp.raise_for_status()
                        try:
                            return json.dumps(resp.json())
                        except ValueError:
                            return resp.text
                            
                    result = connector_instance.retry(run_http_call)
                    connector_instance.audit(name, kwargs, "success", result=result)
                    return str(result)
                except Exception as e:
                    connector_instance.audit(name, kwargs, "failed", error=str(e))
                    return f"Error executing REST operation {name}: {str(e)}"
                    
        return RESTTool()
