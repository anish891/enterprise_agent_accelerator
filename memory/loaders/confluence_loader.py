import requests
import hashlib
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from memory.vector_store import Chunk
from utils.logger import get_logger
from security.secrets import get_secret

logger = get_logger("memory.loaders.confluence_loader")

def load_confluence_space(
    space_key: str,
    base_url: str,
    auth_token: Optional[str] = None,
    chunk_size: int = 512,
    chunk_overlap: int = 64
) -> List[Chunk]:
    """
    Connects to Confluence API, downloads pages recursively from a space key,
    strips HTML markup, and splits text into searchable chunks.
    """
    logger.info(f"Indexing Confluence space '{space_key}' from {base_url}")
    token = auth_token or get_secret("CONFLUENCE_TOKEN")

    # Mock mode fallback for local execution without active credentials
    if not token or "mock" in base_url.lower():
        logger.warning("CONFLUENCE_TOKEN is empty or mock URL detected. Running Confluence indexer in mock mode.")
        mock_pages = [
            {
                "id": "1001",
                "title": f"[{space_key}] Welcome to Confluence IT Docs",
                "html": "<p>This is the IT Documentation landing wiki space. We maintain policies here for VPN, hardware provisioning, and software setups.</p>",
                "url": f"{base_url}/spaces/{space_key}/pages/1001"
            },
            {
                "id": "1002",
                "title": f"[{space_key}] VPN Connection Guidelines",
                "html": "<h3>Connecting to Cisco VPN</h3><p>Ensure you have registered your corporate phone for MFA. Connect to the client using <code>vpn.company.net</code>. If you get error 403, verify if your account group includes VPN-Access-Active.</p>",
                "url": f"{base_url}/spaces/{space_key}/pages/1002"
            }
        ]
        return _process_pages(mock_pages, space_key, chunk_size, chunk_overlap)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json"
    }
    pages = []
    
    try:
        url = urljoin(base_url, "/wiki/api/v2/pages")
        params = {"spaceKey": space_key, "limit": 20}
        
        while url:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            
            for r in results:
                page_id = r.get("id")
                page_title = r.get("title")
                page_url = urljoin(base_url, f"/wiki/spaces/{space_key}/pages/{page_id}")
                
                # Fetch page body format (storage)
                body_url = urljoin(base_url, f"/wiki/api/v2/pages/{page_id}")
                body_resp = requests.get(body_url, params={"body-format": "storage"}, headers=headers, timeout=10)
                body_resp.raise_for_status()
                body_data = body_resp.json()
                html_body = body_data.get("body", {}).get("storage", {}).get("value", "")
                
                pages.append({
                    "id": page_id,
                    "title": page_title,
                    "html": html_body,
                    "url": page_url
                })
            
            # Handle Pagination next link
            next_link = data.get("_links", {}).get("next")
            if next_link:
                url = urljoin(base_url, next_link)
                params = {}  # Parameters are pre-encoded in Confluence's relative next links
            else:
                url = None
    except Exception as e:
        logger.error(f"Error fetching Confluence space '{space_key}': {str(e)}")
        # Safe fallback: return empty to avoid failing the entire ingestion sequence
        return []

    return _process_pages(pages, space_key, chunk_size, chunk_overlap)

def _process_pages(pages: List[Dict[str, str]], space_key: str, chunk_size: int, chunk_overlap: int) -> List[Chunk]:
    chunks = []
    for p in pages:
        html = p.get("html", "")
        # Remove HTML tag markers
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        
        from memory.loaders.file_loader import _slice_text
        sliced_blocks = _slice_text(text, chunk_size, chunk_overlap)
        
        for idx, block in enumerate(sliced_blocks):
            chunk_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()
            meta = {
                "page_id": p["id"],
                "space": space_key,
                "chunk_index": idx
            }
            chunks.append(Chunk(
                id=chunk_hash,
                text=block,
                source_type="confluence",
                source_url=p["url"],
                title=p["title"],
                metadata=meta
            ))
            
    return chunks
