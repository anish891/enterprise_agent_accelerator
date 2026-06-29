import os
import json
import hashlib
from typing import List, Dict, Any, Optional
from utils.config import load_settings
from memory.vector_store import ChromaStore, PGVectorStore, Chunk, SearchResult
from memory.loaders.file_loader import load_file
from memory.loaders.confluence_loader import load_confluence_space
from memory.loaders.sharepoint_loader import load_sharepoint_folder
from crewai.tools import BaseTool
from utils.logger import get_logger

logger = get_logger("memory.knowledge")

class KnowledgeMemory:
    """
    Knowledge Memory component.
    Coordinates local and remote document loaders, performs incremental SHA256 checksum checks,
    manages vector db upserts/deletions, and exposes the CrewAI search tool interface.
    """
    def __init__(self, crew_id: str, config_dir: str = "."):
        self.crew_id = crew_id
        self.config_dir = config_dir
        self.settings = load_settings(config_dir)
        
        # Resolve backend vector store
        vs_backend = self.settings.memory.knowledge.vector_store.lower()
        if vs_backend == "pgvector":
            self.store = PGVectorStore(crew_id=crew_id)
        else:
            self.store = ChromaStore(crew_id=crew_id)
            
        self.status_file = os.path.join(config_dir, ".index_status.json")
        self.index_status = self._load_status()

    def _load_status(self) -> Dict[str, str]:
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.debug(f"Failed to read index status file: {str(e)}")
        return {}

    def _save_status(self) -> None:
        try:
            # Ensure folder structure exists
            os.makedirs(os.path.dirname(os.path.abspath(self.status_file)), exist_ok=True)
            with open(self.status_file, "w", encoding="utf-8") as f:
                json.dump(self.index_status, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not persist index status manifest: {str(e)}")

    def ingest_all(self, force: bool = False) -> Dict[str, Any]:
        """
        Iterates over all configured sources and ingests new or modified data.
        Returns a dict tracking indexed, skipped, and failed paths.
        """
        sources = self.settings.memory.knowledge.sources
        chunk_size = self.settings.memory.knowledge.chunk_size
        chunk_overlap = self.settings.memory.knowledge.chunk_overlap
        
        results = {"indexed": [], "skipped": [], "failed": []}
        
        for source in sources:
            source_type = source.get("type", "").lower()
            try:
                if source_type in ["pdf", "text"]:
                    filepath = source.get("path")
                    if not filepath:
                        continue
                        
                    abs_path = os.path.abspath(filepath)
                    if not os.path.exists(abs_path):
                        logger.error(f"File source not found: {filepath}")
                        results["failed"].append(filepath)
                        continue
                        
                    # 1. Compute SHA256 of file
                    with open(abs_path, "rb") as f:
                        file_hash = hashlib.sha256(f.read()).hexdigest()
                        
                    # 2. Check incremental status
                    if not force and self.index_status.get(abs_path) == file_hash:
                        logger.info(f"Incremental Ingestion: source '{filepath}' is unchanged. Skipping.")
                        results["skipped"].append(filepath)
                        continue
                        
                    # 3. Read and store
                    chunks = load_file(abs_path, chunk_size, chunk_overlap)
                    if chunks:
                        self.store.delete(abs_path)
                        self.store.upsert(chunks)
                        self.index_status[abs_path] = file_hash
                        results["indexed"].append(filepath)
                        
                elif source_type == "confluence":
                    space_key = source.get("space")
                    base_url = source.get("base_url")
                    if not space_key or not base_url:
                        continue
                        
                    auth_val = source.get("auth")
                    source_key = f"confluence:{base_url}:{space_key}"
                    
                    chunks = load_confluence_space(space_key, base_url, auth_val, chunk_size, chunk_overlap)
                    if chunks:
                        # Compute aggregate content hash of text
                        comb_text = "".join(c.text for c in chunks)
                        content_hash = hashlib.sha256(comb_text.encode("utf-8")).hexdigest()
                        
                        if not force and self.index_status.get(source_key) == content_hash:
                            logger.info(f"Incremental Ingestion: confluence space '{space_key}' is unchanged. Skipping.")
                            results["skipped"].append(source_key)
                            continue
                            
                        # Override chunk URLs to point to workspace namespace for deletion
                        self.store.delete(source_key)
                        for c in chunks:
                            c.source_url = source_key
                        self.store.upsert(chunks)
                        
                        self.index_status[source_key] = content_hash
                        results["indexed"].append(source_key)
                        
                elif source_type == "sharepoint":
                    site = source.get("site")
                    folder_path = source.get("folder", "/")
                    if not site:
                        continue
                        
                    auth_val = source.get("auth")
                    source_key = f"sharepoint:{site}:{folder_path}"
                    
                    chunks = load_sharepoint_folder(site, folder_path, auth_val, chunk_size, chunk_overlap)
                    if chunks:
                        comb_text = "".join(c.text for c in chunks)
                        content_hash = hashlib.sha256(comb_text.encode("utf-8")).hexdigest()
                        
                        if not force and self.index_status.get(source_key) == content_hash:
                            logger.info(f"Incremental Ingestion: sharepoint folder '{folder_path}' is unchanged. Skipping.")
                            results["skipped"].append(source_key)
                            continue
                            
                        self.store.delete(source_key)
                        for c in chunks:
                            c.source_url = source_key
                        self.store.upsert(chunks)
                        
                        self.index_status[source_key] = content_hash
                        results["indexed"].append(source_key)
            except Exception as e:
                logger.error(f"Failed to ingest source {source_type}: {str(e)}")
                results["failed"].append(f"{source_type}:{str(e)}")
                
        self._save_status()
        return results

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Queries the vector store and yields search hits as dictionaries.
        """
        search_res = self.store.search(query, k=top_k)
        hits = []
        for r in search_res:
            hits.append({
                "text": r.chunk.text,
                "source_url": r.chunk.source_url,
                "title": r.chunk.title,
                "score": r.score
            })
        return hits

    def as_crewai_tool(self) -> BaseTool:
        """
        Creates a CrewAI search tool wrapping this instance's retrieve routine.
        """
        instance = self
        from pydantic import BaseModel, Field
        
        class RAGSearchSchema(BaseModel):
            query: str = Field(..., description="Query phrase for finding details in knowledge files.")
            
        class RAGSearchTool(BaseTool):
            name: str = "knowledge.search"
            description: str = (
                "Search corporate policies, procedures, onboarding documents, "
                "or configuration wikis stored in Confluence, SharePoint, and PDFs."
            )
            args_schema: Any = RAGSearchSchema
            
            def _run(self, query: str) -> str:
                logger.info(f"RAG Search invoked for query: '{query}'")
                hits = instance.retrieve(query, top_k=5)
                if not hits:
                    return "Search query did not return any matches in corporate knowledge logs."
                    
                response = f"RAG Query Hits for '{query}':\n\n"
                for idx, hit in enumerate(hits):
                    response += f"[{idx + 1}] Title: {hit['title']} | Source: {hit['source_url']}\n"
                    response += f"Content: {hit['text']}\n"
                    response += f"Similarity Match: {hit['score']:.2%}\n\n"
                return response
                
        return RAGSearchTool()
