import os
from typing import Any, Dict
from connectors.base import BaseConnector
from utils.logger import get_logger

logger = get_logger("connectors.local_file")

class LocalFileConnector(BaseConnector):
    """
    Local File Connector providing tools to read and write local files in the workspace.
    """
    def __init__(self, name: str = "local_file", config: Dict[str, Any] = None):
        super().__init__(name, config)

    def authenticate(self) -> None:
        # No authentication needed for local file access
        pass

    def read_file(self, filepath: str) -> str:
        """
        Reads the content of a local file in the workspace directory.
        """
        logger.info(f"Reading local file: {filepath}")
        try:
            if not os.path.exists(filepath):
                return f"Error: File '{filepath}' does not exist."
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file '{filepath}': {e}"

    def write_file(self, filepath: str, content: str) -> str:
        """
        Writes/overwrites content to a local file in the workspace directory.
        """
        logger.info(f"Writing content to local file: {filepath}")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully wrote {len(content)} characters to '{filepath}'."
        except Exception as e:
            return f"Error writing file '{filepath}': {e}"
