import os
import yaml
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

@dataclass
class LLMCost:
    input_per_1k: float
    output_per_1k: float

@dataclass
class PersistentMemorySettings:
    backend: str = "redis"
    ttl_days: int = 30

@dataclass
class KnowledgeMemorySettings:
    vector_store: str = "chroma"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str = "text-embedding-3-small"
    sources: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class MemorySettings:
    conversation: bool = True
    persistent: PersistentMemorySettings = field(default_factory=PersistentMemorySettings)
    knowledge: KnowledgeMemorySettings = field(default_factory=KnowledgeMemorySettings)

@dataclass
class Settings:
    llm_costs: Dict[str, LLMCost] = field(default_factory=dict)
    secrets_backend: str = "env"
    max_steps_default: int = 10
    process: str = "sequential"
    # Default LLM used when an agent does not declare one explicitly.
    # Examples:
    #   azure/gpt-4o          → Azure OpenAI (recommended if you have an Azure key)
    #   openai/gpt-4o         → OpenAI direct
    #   anthropic/claude-3-5-sonnet-20241022
    #   ollama/llama3
    default_llm: str = "azure/gpt-4o"
    memory: MemorySettings = field(default_factory=MemorySettings)

def load_settings(config_dir: str = ".") -> Settings:
    """
    Loads and merges config.yaml and memory.yaml from the specified directory.
    If the files do not exist, returns defaults.
    """
    config_path = os.path.join(config_dir, "config.yaml")
    memory_path = os.path.join(config_dir, "memory.yaml")
    
    settings = Settings()
    
    # Set default standard rates if none provided
    settings.llm_costs = {
        "anthropic/claude-sonnet-4-6": LLMCost(input_per_1k=0.003, output_per_1k=0.015),
        "openai/gpt-4o": LLMCost(input_per_1k=0.005, output_per_1k=0.015),
        "google/gemini-1.5-pro": LLMCost(input_per_1k=0.00125, output_per_1k=0.00375),
    }

    # Load config.yaml
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
            if "secrets_backend" in cfg:
                settings.secrets_backend = cfg["secrets_backend"]
            if "max_steps_default" in cfg:
                settings.max_steps_default = int(cfg["max_steps_default"])
            if "process" in cfg:
                settings.process = cfg["process"]
            if "default_llm" in cfg:
                settings.default_llm = cfg["default_llm"]
            if "llm_costs" in cfg:
                # Merge or overwrite costs
                for k, v in cfg["llm_costs"].items():
                    settings.llm_costs[k] = LLMCost(
                        input_per_1k=float(v.get("input_per_1k", 0.0)),
                        output_per_1k=float(v.get("output_per_1k", 0.0))
                    )
                    
    # Load memory.yaml
    if os.path.exists(memory_path):
        with open(memory_path, "r", encoding="utf-8") as f:
            mem = yaml.safe_load(f) or {}
            mem_section = mem.get("memory", {})
            settings.memory.conversation = mem_section.get("conversation", True)
            
            persistent_cfg = mem_section.get("persistent", {})
            settings.memory.persistent.backend = persistent_cfg.get("backend", "redis")
            settings.memory.persistent.ttl_days = int(persistent_cfg.get("ttl_days", 30))
            
            knowledge_cfg = mem_section.get("knowledge", {})
            settings.memory.knowledge.vector_store = knowledge_cfg.get("vector_store", "chroma")
            settings.memory.knowledge.chunk_size = int(knowledge_cfg.get("chunk_size", 512))
            settings.memory.knowledge.chunk_overlap = int(knowledge_cfg.get("chunk_overlap", 64))
            settings.memory.knowledge.embedding_model = knowledge_cfg.get("embedding_model", "text-embedding-3-small")
            settings.memory.knowledge.sources = knowledge_cfg.get("sources", [])
            
    return settings
