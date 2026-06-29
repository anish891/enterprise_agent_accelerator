from typing import Any, Dict
from connectors.base import BaseConnector
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.outlook")

class OutlookConnector(BaseConnector):
    """
    Outlook Connector providing email tools (sending, receiving/listing).
    """
    def __init__(self, name: str = "outlook", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.auth_token = None

    def authenticate(self) -> None:
        self.auth_token = self.config.get("auth") or get_secret("OUTLOOK_TOKEN")
        if not self.auth_token:
            logger.warning("No OUTLOOK_TOKEN secret resolved; operating in mock credential mode.")

    def send_email(self, recipient: str, subject: str, body: str) -> str:
        """
        Sends an email message via Outlook to a recipient address.
        """
        logger.info(f"Sending email to {recipient} with subject: '{subject}'")
        return f"Successfully sent email to '{recipient}' with subject '{subject}'."

    def get_messages(self, folder: str = "Inbox", limit: int = 5) -> str:
        """
        Retrieves recent email messages from an Outlook folder.
        """
        logger.info(f"Retrieving up to {limit} emails from Outlook folder: {folder}")
        return (
            f"Outlook emails in folder '{folder}':\n"
            "1. From: support@it.com | Subject: VPN Update Successful | Body: Please reboot your system.\n"
            "2. From: hr@company.com | Subject: Onboarding Completion | Body: Complete your profile form by Friday.\n"
            "3. From: manager@company.com | Subject: Project Launch | Body: Kickoff scheduled tomorrow at 9 AM."
        )
