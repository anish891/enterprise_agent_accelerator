import os
import requests
import hashlib
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from memory.vector_store import Chunk
from utils.logger import get_logger
from security.secrets import get_secret

logger = get_logger("memory.loaders.sharepoint_loader")

def load_sharepoint_folder(
    site: str,
    folder_path: str,
    auth_token: Optional[str] = None,
    chunk_size: int = 512,
    chunk_overlap: int = 64
) -> List[Chunk]:
    """
    Scans a folder in SharePoint recursively using Microsoft Graph API,
    downloads document payloads, and yields formatted Chunk structures.
    """
    logger.info(f"Indexing SharePoint site '{site}' folder '{folder_path}'")
    token = auth_token or get_secret("SHAREPOINT_TOKEN")

    # Mock mode fallback for local execution without active credentials
    if not token or "mock" in site.lower():
        logger.warning("SHAREPOINT_TOKEN is empty or mock site URL detected. Running SharePoint indexer in mock mode.")
        mock_docs = [
            {
                "id": "sp101",
                "title": "HR Benefit Details.docx",
                "text": "HR Benefits Program details. Dental Plan: covers up to $1500 per member. Vision Plan: covers up to $300 for frames. Submit claims via SharePoint HR benefits hub.",
                "url": f"{site}/Policies/HR_Benefit_Details.docx"
            },
            {
                "id": "sp102",
                "title": "Onboarding Guide.md",
                "text": "# HR Onboarding Policy\nNew hires must review security protocols within the first 48 hours. Submit signed agreements to hr-benefits@company.com.",
                "url": f"{site}/Policies/Onboarding_Guide.md"
            }
        ]
        return _process_docs(mock_docs, chunk_size, chunk_overlap)

    headers = {
        "Authorization": f"Bearer {token}"
    }
    chunks: List[Chunk] = []

    try:
        # 1. Resolve host and site ID path
        clean_site = site.replace("https://", "").replace("http://", "")
        parts = clean_site.split("/", 1)
        hostname = parts[0]
        site_path = f"/sites/{parts[1]}" if len(parts) > 1 else ""

        site_url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
        site_resp = requests.get(site_url, headers=headers, timeout=10)
        site_resp.raise_for_status()
        site_id = site_resp.json().get("id")

        # 2. Get Site Drive
        drive_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
        drive_resp = requests.get(drive_url, headers=headers, timeout=10)
        drive_resp.raise_for_status()
        drive_id = drive_resp.json().get("id")

        # 3. Resolve folder endpoint ID
        clean_folder = folder_path.strip("/")
        folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{clean_folder}"
        folder_resp = requests.get(folder_url, headers=headers, timeout=10)
        folder_resp.raise_for_status()
        folder_id = folder_resp.json().get("id")

        # 4. Fetch child elements recursively
        items = _fetch_items_recursively(drive_id, folder_id, headers)

        # 5. Extract text from drive item outputs
        for item in items:
            name = item.get("name", "")
            ext = os.path.splitext(name)[1].lower()
            download_url = item.get("@microsoft.graph.downloadUrl")
            web_url = item.get("webUrl", "")

            if not download_url:
                continue

            file_resp = requests.get(download_url, timeout=15)
            file_resp.raise_for_status()
            text_body = ""

            if ext in [".txt", ".md"]:
                text_body = file_resp.text
            elif ext == ".pdf":
                os.makedirs("scratch", exist_ok=True)
                temp_pdf = f"scratch/temp_{item['id']}.pdf"
                with open(temp_pdf, "wb") as pf:
                    pf.write(file_resp.content)
                try:
                    from memory.loaders.file_loader import _read_pdf_pages
                    pages = _read_pdf_pages(temp_pdf)
                    text_body = "\n".join(p[1] for p in pages)
                finally:
                    if os.path.exists(temp_pdf):
                        os.remove(temp_pdf)
            elif ext == ".docx":
                os.makedirs("scratch", exist_ok=True)
                temp_docx = f"scratch/temp_{item['id']}.docx"
                with open(temp_docx, "wb") as df:
                    df.write(file_resp.content)
                try:
                    text_body = _read_docx_content(temp_docx)
                finally:
                    if os.path.exists(temp_docx):
                        os.remove(temp_docx)

            if text_body:
                from memory.loaders.file_loader import _slice_text
                sliced_blocks = _slice_text(text_body, chunk_size, chunk_overlap)
                for idx, block in enumerate(sliced_blocks):
                    chunk_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()
                    meta = {
                        "item_id": item["id"],
                        "chunk_index": idx
                    }
                    chunks.append(Chunk(
                        id=chunk_hash,
                        text=block,
                        source_type="sharepoint",
                        source_url=web_url,
                        title=name,
                        metadata=meta
                    ))
    except Exception as e:
        logger.error(f"Error loading SharePoint drive records: {str(e)}")
        # Safe fallback
        return []

    return chunks

def _fetch_items_recursively(drive_id: str, folder_id: str, headers: dict) -> list:
    items = []
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{folder_id}/children"
    while url:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for child in data.get("value", []):
            if "folder" in child:
                items.extend(_fetch_items_recursively(drive_id, child["id"], headers))
            elif "file" in child:
                items.append(child)
        url = data.get("@odata.nextLink")
    return items

def _read_docx_content(filepath: str) -> str:
    try:
        import docx
        doc = docx.Document(filepath)
        return "\n".join(para.text for para in doc.paragraphs)
    except ImportError:
        logger.warning("python-docx not installed. Word parser skipped.")
        return ""
    except Exception as e:
        logger.error(f"Word docx parser error: {str(e)}")
        return ""

def _process_docs(docs: List[Dict[str, str]], chunk_size: int, chunk_overlap: int) -> List[Chunk]:
    chunks = []
    for d in docs:
        text = d.get("text", "")
        from memory.loaders.file_loader import _slice_text
        sliced_blocks = _slice_text(text, chunk_size, chunk_overlap)
        for idx, block in enumerate(sliced_blocks):
            chunk_hash = hashlib.sha256(block.encode("utf-8")).hexdigest()
            meta = {
                "doc_id": d["id"],
                "chunk_index": idx
            }
            chunks.append(Chunk(
                id=chunk_hash,
                text=block,
                source_type="sharepoint",
                source_url=d["url"],
                title=d["title"],
                metadata=meta
            ))
    return chunks
