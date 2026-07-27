"""
Cost and token tracking utility module.
Provides pricing tables for popular LLM providers and dynamic cost calculations.
"""

from typing import Dict, Any, Tuple, Optional
from utils.logger import get_logger

logger = get_logger("utils.cost")

# Default pricing rates in USD per 1,000 tokens (input_per_1k, output_per_1k)
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    # OpenAI & Azure OpenAI
    "gpt-4o": (0.0025, 0.0100),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    
    # Anthropic
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3-opus": (0.015, 0.075),
    
    # Google Gemini
    "gemini-1.5-pro": (0.00125, 0.00375),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini-2.0-flash": (0.0001, 0.0004),
    
    # Groq & Open Source
    "llama3-70b-8192": (0.00059, 0.00079),
    "llama3-8b-8192": (0.00005, 0.0001),
    "mixtral-8x7b-32768": (0.00027, 0.00027),
    
    # Default fallback rate if model is unknown
    "default": (0.002, 0.006)
}

def get_model_rates(model_name: Optional[str]) -> Tuple[float, float]:
    """
    Returns (input_cost_per_1k, output_cost_per_1k) for a given model string.
    Normalizes provider prefixes like 'azure/gpt-4o' or 'openai/gpt-4o'.
    """
    if not model_name:
        return MODEL_PRICING["default"]
        
    # Strip provider prefix if present (e.g. azure/gpt-4o -> gpt-4o)
    clean_name = model_name.split("/")[-1].lower().strip()
    
    # Exact match
    if clean_name in MODEL_PRICING:
        return MODEL_PRICING[clean_name]
        
    # Substring match
    for key, rates in MODEL_PRICING.items():
        if key in clean_name:
            return rates
            
    return MODEL_PRICING["default"]

def calculate_step_cost(tokens_in: int, tokens_out: int, model_name: Optional[str] = None) -> float:
    """
    Calculates USD cost for prompt and completion tokens.
    """
    rate_in, rate_out = get_model_rates(model_name)
    cost_in = (tokens_in / 1000.0) * rate_in
    cost_out = (tokens_out / 1000.0) * rate_out
    return round(cost_in + cost_out, 6)
