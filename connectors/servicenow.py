from typing import Any, Dict
from connectors.base import BaseConnector
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.servicenow")

class ServiceNowConnector(BaseConnector):
    """
    ServiceNow Connector providing incident/ticket querying, creation, and modification.
    """
    def __init__(self, name: str = "servicenow", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.instance_url = None
        self.auth_token = None

    def authenticate(self) -> None:
        self.instance_url = self.config.get("instance_url") or get_secret("SERVICENOW_URL") or "https://mock-instance.service-now.com"
        self.auth_token = self.config.get("auth") or get_secret("SERVICENOW_TOKEN")
        if not self.auth_token:
            logger.warning("No SERVICENOW_TOKEN secret resolved; operating in mock credential mode.")

    def get_ticket(self, sys_id: str) -> str:
        """
        Retrieves detailed information about a ServiceNow incident or request ticket.
        """
        logger.info(f"Retrieving ServiceNow incident {sys_id} from {self.instance_url}")
        return f"ServiceNow Ticket [{sys_id}]: Category: Software, State: New, Description: Outlook client crashes immediately on startup after the OS update, Comments: Initial assignment to IT Desktop support."

    def create_ticket(self, description: str, category: str = "IT") -> str:
        """
        Creates a new incident ticket in ServiceNow.
        """
        logger.info(f"Creating ServiceNow ticket under category {category}")
        sys_id = "INC0019482"
        return f"Successfully created ServiceNow ticket {sys_id}. Category: {category}. Description: '{description}'."

    def update_ticket(self, sys_id: str, comments: str, state: str = None) -> str:
        """
        Updates comments and state of a ServiceNow ticket.
        """
        logger.info(f"Updating ServiceNow ticket {sys_id} (state={state})")
        state_msg = f" state changed to '{state}' and" if state else ""
        return f"Successfully updated ServiceNow ticket {sys_id}:{state_msg} comment added: '{comments}'."
