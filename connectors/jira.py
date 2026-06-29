from typing import Any, Dict
from connectors.base import BaseConnector
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.jira")

class JiraConnector(BaseConnector):
    """
    Jira Connector providing issue search, creation, and update functionality.
    """
    def __init__(self, name: str = "jira", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.token = None
        self.url = None

    def authenticate(self) -> None:
        # Retrieve secrets through secrets manager
        self.url = self.config.get("url") or get_secret("JIRA_URL") or "https://mock-company.atlassian.net"
        self.token = self.config.get("auth") or get_secret("JIRA_TOKEN")
        if not self.token:
            logger.warning("No JIRA_TOKEN secret resolved; operating in mock credential mode.")

    def get_issue(self, ticket_id: str) -> str:
        """
        Retrieves detailed information about a specific Jira issue ticket.
        """
        logger.info(f"Retrieving Jira issue {ticket_id} from {self.url}")
        # Simulated responses for robust demo execution
        if "101" in ticket_id:
            return f"Jira Issue [{ticket_id}]: 'VPN Access Failure'. Status: Open. Reporter: john.doe@company.com. Description: Cannot connect to Cisco VPN since updates yesterday. Error code 403."
        return f"Jira Issue [{ticket_id}]: 'HR Portal Link Broken'. Status: In Progress. Reporter: jane.smith@company.com. Description: The corporate HR benefits portal link yields a 404 page."

    def create_issue(self, summary: str, description: str, project_key: str = "IT") -> str:
        """
        Creates a new Jira issue under the specified project.
        """
        logger.info(f"Creating Jira issue in project {project_key}: '{summary}'")
        ticket_id = f"{project_key}-2042"
        return f"Successfully created Jira issue {ticket_id}. Summary: '{summary}'. Status: Open."

    def update_issue(self, ticket_id: str, comment: str, status: str = None) -> str:
        """
        Updates an existing Jira issue with a comment and optional status change.
        """
        logger.info(f"Updating Jira issue {ticket_id} (status={status})")
        status_msg = f" and status updated to '{status}'" if status else ""
        return f"Successfully added comment '{comment}'{status_msg} to Jira issue {ticket_id}."
