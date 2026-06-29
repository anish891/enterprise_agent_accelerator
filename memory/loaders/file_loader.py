import os
import hashlib
from typing import List, Tuple, Dict, Any
from memory.vector_store import Chunk
from utils.logger import get_logger

logger = get_logger("memory.loaders.file_loader")

def load_file(filepath: str, chunk_size: int = 512, chunk_overlap: int = 64) -> List[Chunk]:
    """
    Reads a local text or PDF file, partitions it into overlapping chunks, and returns Chunk instances.
    """
    if not os.path.exists(filepath):
        logger.error(f"Loader failed: file does not exist at {filepath}")
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    pages: List[Tuple[int, str]] = []
    
    if ext == ".pdf":
        pages = _read_pdf_pages(filepath)
    else:
        # Load as UTF-8 plain text (e.g. txt, md, log, yaml)
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                pages.append((1, content))
        except Exception as e:
            logger.error(f"Failed to read plaintext file {filepath}: {str(e)}")
            raise ValueError(f"Unable to read file {filepath}: {str(e)}")

    chunks: List[Chunk] = []
    for page_num, text in pages:
        if not text.strip():
            continue
            
        page_chunks = _slice_text(text, chunk_size, chunk_overlap)
        for idx, ch_text in enumerate(page_chunks):
            # Unique ID based on SHA256 of text block
            chunk_hash = hashlib.sha256(ch_text.encode("utf-8")).hexdigest()
            meta = {
                "page": page_num,
                "chunk_index": idx,
                "file_size_bytes": os.path.getsize(filepath)
            }
            chunks.append(Chunk(
                id=chunk_hash,
                text=ch_text,
                source_type="pdf" if ext == ".pdf" else "text",
                source_url=os.path.abspath(filepath),
                title=os.path.basename(filepath),
                metadata=meta
            ))
            
    logger.debug(f"Successfully loaded {len(chunks)} chunks from {filepath}")
    return chunks

def _read_pdf_pages(filepath: str) -> List[Tuple[int, str]]:
    """
    Loads text page-by-page from a PDF, falling back across different libraries.
    """
    pages: List[Tuple[int, str]] = []
    
    # Try pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append((i + 1, text))
        return pages
    except ImportError:
        pass
        
    # Try pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                pages.append((i + 1, text))
        return pages
    except ImportError:
        pass

    # Simple plain text fallback for testing if no PDF libraries are installed
    logger.warning(f"No PDF parsing libraries available. Reading raw bytes for {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            pages.append((1, f"[PDF Raw Fallback Content]\n{content[:5000]}"))
    except Exception as e:
        logger.error(f"PDF raw fallback read failed: {str(e)}")
        pages.append((1, "[Unreadable PDF file]"))
        
    return pages

def _slice_text(text: str, size: int, overlap: int) -> List[str]:
    """
    Slices text string into overlapping blocks.
    Size and overlap represent character counts.
    """
    chunks = []
    start = 0
    if size <= overlap:
        # Guard against infinite loop
        overlap = size // 2
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start += size - overlap
        if start >= len(text):
            break
    return chunks
