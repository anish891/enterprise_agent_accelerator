import os
import hashlib
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("memory.vector_store")

@dataclass
class Chunk:
    id: str           # SHA256 of text content
    text: str
    source_type: str  # confluence | sharepoint | pdf | text
    source_url: str
    title: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SearchResult:
    chunk: Chunk
    score: float

def get_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    """
    Fetches the 1536-dimension float vector using OpenAI client if API key is present.
    Otherwise, generates a completely deterministic unit vector by hashing the text
    to support seamless developer offline execution and testing.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            resp = client.embeddings.create(input=[text], model=model)
            return resp.data[0].embedding
        except Exception as e:
            logger.debug(f"OpenAI embedding generation failed, using hash fallback: {str(e)}")
            
    # Deterministic mock embedding fallback
    dim = 1536
    hash_obj = hashlib.sha256(text.encode("utf-8"))
    seed = int(hash_obj.hexdigest(), 16) % (2**32)
    
    # Simple linear congruential generator-like deterministic vector
    import numpy as np
    rng = np.random.default_rng(seed)
    vector = rng.normal(0.0, 1.0, dim).tolist()
    
    # Normalize to unit length
    norm = sum(x * x for x in vector) ** 0.5
    if norm > 0:
        vector = [x / norm for x in vector]
    return vector

class ChromaStore:
    """
    Local ChromaDB persistent store wrapper. Falls back to a localized
    in-memory database if chromadb client library is not installed.
    """
    def __init__(self, crew_id: str, persist_dir: str = ".chroma_db"):
        self.crew_id = crew_id
        self.persist_dir = persist_dir
        self.collection = None
        self.in_memory_db: List[Dict[str, Any]] = []
        
        try:
            import chromadb
            client = chromadb.PersistentClient(path=self.persist_dir)
            self.collection = client.get_or_create_collection(name=f"crew_{crew_id}")
            logger.debug(f"Initialized ChromaDB persistent store collection: crew_{crew_id}")
        except Exception as e:
            logger.debug(f"ChromaDB library not available, falling back to local in-memory store: {str(e)}")

    def upsert(self, chunks: List[Chunk]) -> None:
        if self.collection is not None:
            ids = [c.id for c in chunks]
            documents = [c.text for c in chunks]
            embeddings = [get_embedding(c.text) for c in chunks]
            metadatas = []
            for c in chunks:
                meta = {
                    "source_type": c.source_type,
                    "source_url": c.source_url,
                    "title": c.title,
                }
                for k, v in c.metadata.items():
                    if isinstance(v, (str, int, float, bool)):
                        meta[k] = v
                metadatas.append(meta)
                
            self.collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas
            )
        else:
            # Local in-memory upsert with deduplication
            existing_ids = {item["chunk"].id for item in self.in_memory_db}
            for c in chunks:
                if c.id in existing_ids:
                    self.in_memory_db = [x for x in self.in_memory_db if x["chunk"].id != c.id]
                self.in_memory_db.append({
                    "chunk": c,
                    "embedding": get_embedding(c.text)
                })

    def search(self, query: str, k: int = 5) -> List[SearchResult]:
        query_vector = get_embedding(query)
        if self.collection is not None:
            try:
                res = self.collection.query(
                    query_embeddings=[query_vector],
                    n_results=k
                )
                results = []
                if res and res["ids"] and len(res["ids"][0]) > 0:
                    for i in range(len(res["ids"][0])):
                        cid = res["ids"][0][i]
                        text = res["documents"][0][i]
                        meta = res["metadatas"][0][i]
                        dist = res["distances"][0][i] if "distances" in res and res["distances"] else 0.5
                        score = max(0.0, min(1.0, 1.0 - dist))
                        
                        chunk = Chunk(
                            id=cid,
                            text=text,
                            source_type=meta.pop("source_type", "text"),
                            source_url=meta.pop("source_url", ""),
                            title=meta.pop("title", ""),
                            metadata=meta
                        )
                        results.append(SearchResult(chunk=chunk, score=score))
                return results
            except Exception as e:
                logger.error(f"ChromaDB search query failed: {str(e)}")
                return []
        else:
            # Cosine similarity brute-force over in-memory list
            results = []
            for item in self.in_memory_db:
                c = item["chunk"]
                vec = item["embedding"]
                dot_product = sum(q * v for q, v in zip(query_vector, vec))
                results.append(SearchResult(chunk=c, score=dot_product))
            results.sort(key=lambda x: x.score, reverse=True)
            return results[:k]

    def delete(self, source_id: str) -> None:
        """
        Deletes all chunks associated with a specific source path/URL.
        """
        if self.collection is not None:
            try:
                self.collection.delete(where={"source_url": source_id})
            except Exception as e:
                logger.error(f"ChromaDB delete failed: {str(e)}")
        else:
            self.in_memory_db = [x for x in self.in_memory_db if x["chunk"].source_url != source_id]

class PGVectorStore:
    """
    PostgreSQL with pgvector extension store.
    Namespaced per crew_id and falls back to ChromaStore if PostgreSQL connection fails.
    """
    def __init__(self, crew_id: str, connection_string: str = None):
        self.crew_id = crew_id
        self.conn_str = connection_string or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/crewctl")
        self.enabled = False
        self.conn = None
        self.cursor = None
        self.fallback_store = None
        
        try:
            import psycopg2
            self.conn = psycopg2.connect(self.conn_str)
            self.conn.autocommit = True
            self.cursor = self.conn.cursor()
            
            # Setup database schemas and vector dimension (1536 matches OpenAI text-embedding-3-small)
            self.cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS crew_chunks (
                    id VARCHAR(64) PRIMARY KEY,
                    crew_id VARCHAR(100),
                    text TEXT,
                    source_type VARCHAR(50),
                    source_url TEXT,
                    title TEXT,
                    metadata JSONB,
                    embedding vector(1536)
                );
            """)
            self.enabled = True
            logger.debug(f"Connected to PGVector database. Table crew_chunks prepared.")
        except Exception as e:
            logger.debug(f"PGVector setup skipped, falling back to ChromaStore: {str(e)}")
            self.fallback_store = ChromaStore(crew_id=crew_id)

    def upsert(self, chunks: List[Chunk]) -> None:
        if not self.enabled:
            self.fallback_store.upsert(chunks)
            return
            
        import json
        for c in chunks:
            emb = get_embedding(c.text)
            meta_json = json.dumps(c.metadata)
            try:
                self.cursor.execute("""
                    INSERT INTO crew_chunks (id, crew_id, text, source_type, source_url, title, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        text = EXCLUDED.text,
                        source_type = EXCLUDED.source_type,
                        source_url = EXCLUDED.source_url,
                        title = EXCLUDED.title,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding;
                """, (c.id, self.crew_id, c.text, c.source_type, c.source_url, c.title, meta_json, emb))
            except Exception as e:
                logger.error(f"PGVector upsert failed for chunk {c.id}: {str(e)}")

    def search(self, query: str, k: int = 5) -> List[SearchResult]:
        if not self.enabled:
            return self.fallback_store.search(query, k)
            
        emb = get_embedding(query)
        try:
            # <=> is cosine distance operator in pgvector
            self.cursor.execute("""
                SELECT id, text, source_type, source_url, title, metadata, (1.0 - (embedding <=> %s::vector)) as similarity
                FROM crew_chunks
                WHERE crew_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """, (emb, self.crew_id, emb, k))
            
            results = []
            for row in self.cursor.fetchall():
                cid, text, s_type, s_url, title, meta_val, score = row
                chunk = Chunk(
                    id=cid,
                    text=text,
                    source_type=s_type,
                    source_url=s_url,
                    title=title,
                    metadata=meta_val if isinstance(meta_val, dict) else {}
                )
                results.append(SearchResult(chunk=chunk, score=float(score)))
            return results
        except Exception as e:
            logger.error(f"PGVector search query failed: {str(e)}")
            return []

    def delete(self, source_id: str) -> None:
        if not self.enabled:
            self.fallback_store.delete(source_id)
            return
            
        try:
            self.cursor.execute("""
                DELETE FROM crew_chunks
                WHERE crew_id = %s AND source_url = %s;
            """, (self.crew_id, source_id))
        except Exception as e:
            logger.error(f"PGVector delete failed for source {source_id}: {str(e)}")
