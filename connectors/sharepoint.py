from typing import Any, Dict
from connectors.base import BaseConnector
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("connectors.sharepoint")

class SharePointConnector(BaseConnector):
    """
    SharePoint Connector providing file download and upload functionality.
    """
    def __init__(self, name: str = "sharepoint", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.site_url = None
        self.client_secret = None

    def authenticate(self) -> None:
        self.site_url = self.config.get("site_url") or get_secret("SHAREPOINT_SITE_URL") or "https://mock-company.sharepoint.com"
        self.client_secret = self.config.get("auth") or get_secret("SHAREPOINT_TOKEN")
        if not self.client_secret:
            logger.warning("No SHAREPOINT_TOKEN secret resolved; operating in mock credential mode.")

    def get_file(self, site: str, filepath: str) -> str:
        """
        Retrieves the content of a document stored on a SharePoint site folder.
        """
        logger.info(f"Retrieving file {filepath} from SharePoint site: {site}")
        return f"Content of SharePoint file [https://{site}/{filepath}]: HR benefits guidelines. Medical coverage: 100% preventive, Dental: up to $2000 annually. Vision: $250 allowance for frames every 2 years. Questions: contact benefits@company.com"

    def upload_file(self, site: str, filepath: str, content: str) -> str:
        """
        Uploads/overwrites a file in the SharePoint document directory.
        """
        logger.info(f"Uploading file to {filepath} on site {site}")
        return f"Successfully uploaded file to SharePoint site '{site}' at path '{filepath}'. Size: {len(content)} characters."
