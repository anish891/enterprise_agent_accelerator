from typing import Any, Dict, Optional
from crewai import LLM
from security.secrets import get_secret
from utils.logger import get_logger

logger = get_logger("runtime.llm_router")

# ---------------------------------------------------------------------------
# Provider routing table
# ---------------------------------------------------------------------------
# Supported model string formats:
#   azure/gpt-4o               → Azure OpenAI (uses AZURE_OPENAI_* env vars)
#   openai/gpt-4o              → OpenAI direct
#   anthropic/claude-3-5-sonnet→ Anthropic
#   google/gemini-1.5-pro      → Google Gemini
#   gemini/gemini-1.5-pro      → Google Gemini (alias)
#   ollama/llama3              → Local Ollama
#   groq/llama3-70b-8192       → Groq
#   mistral/mistral-large      → Mistral AI
#   cohere/command-r-plus      → Cohere
#   huggingface/<model>        → HuggingFace Inference API
#   bedrock/anthropic.claude…  → AWS Bedrock
#   <anything-else>            → treated as OpenAI-compatible; falls back to
#                                Azure if AZURE_OPENAI_API_KEY is set,
#                                otherwise OpenAI key.
# ---------------------------------------------------------------------------

def _build_azure_llm(model_string: str) -> LLM:
    """
    Builds a CrewAI LLM configured for Azure OpenAI.

    Required env vars:
        AZURE_OPENAI_API_KEY      – your Azure resource key
        AZURE_OPENAI_ENDPOINT     – e.g. https://ai-native-dev-llm.cognitiveservices.azure.com
        AZURE_OPENAI_DEPLOYMENT   – deployment name (e.g. gpt-4o); defaults to
                                    the model part after the first '/'
        AZURE_OPENAI_API_VERSION  – defaults to 2024-08-01-preview

    In agents.yaml use:  llm: azure/gpt-4o
    The part after '/' is used as the deployment name unless
    AZURE_OPENAI_DEPLOYMENT overrides it.
    """
    api_key = get_secret("AZURE_OPENAI_API_KEY")
    endpoint = get_secret("AZURE_OPENAI_ENDPOINT") or "https://ai-native-dev-llm.cognitiveservices.azure.com"
    api_version = get_secret("AZURE_OPENAI_API_VERSION") or "2024-08-01-preview"

    # Derive deployment name: prefer explicit env var, fall back to model slug
    parts = model_string.split("/", 1)
    model_slug = parts[1] if len(parts) > 1 else "gpt-4o"
    deployment = get_secret("AZURE_OPENAI_DEPLOYMENT") or model_slug

    # Ensure endpoint has no trailing slash
    endpoint = endpoint.rstrip("/")

    logger.info(
        f"Azure OpenAI → endpoint={endpoint}  deployment={deployment}  api_version={api_version}"
    )

    # CrewAI/LiteLLM expects the model string as "azure/<deployment-name>"
    return LLM(
        model=f"azure/{deployment}",
        api_key=api_key,
        base_url=endpoint,
        api_version=api_version,
    )


def get_llm(model_string: str) -> LLM:
    """
    Instantiates and returns a CrewAI-compatible LLM object.

    Resolution order for unknown providers:
      1. If AZURE_OPENAI_API_KEY is set  → treat as Azure OpenAI
      2. If OPENAI_API_KEY is set        → treat as OpenAI
      3. Return a clearly-labelled mock so the rest of the system stays alive.
    """
    logger.info(f"Routing LLM for model string: '{model_string}'")

    parts = model_string.split("/", 1)
    provider = parts[0].lower() if len(parts) > 1 else "openai"

    # ── Azure OpenAI ────────────────────────────────────────────────────────
    if provider == "azure":
        try:
            return _build_azure_llm(model_string)
        except Exception as e:
            logger.error(f"Azure LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── OpenAI ──────────────────────────────────────────────────────────────
    if provider == "openai":
        api_key = get_secret("OPENAI_API_KEY")
        # If no OpenAI key but Azure key exists, transparently re-route
        if not api_key and get_secret("AZURE_OPENAI_API_KEY"):
            logger.info(
                "No OPENAI_API_KEY found; transparently routing to Azure OpenAI."
            )
            # Rewrite e.g. "openai/gpt-4o" → "azure/gpt-4o"
            azure_model = f"azure/{parts[1]}" if len(parts) > 1 else "azure/gpt-4o"
            try:
                return _build_azure_llm(azure_model)
            except Exception as e:
                logger.error(f"Azure fallback also failed: {e}")
                return _fallback_llm(model_string)
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"OpenAI LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Anthropic ────────────────────────────────────────────────────────────
    if provider == "anthropic":
        api_key = get_secret("ANTHROPIC_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"Anthropic LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Google / Gemini ──────────────────────────────────────────────────────
    if provider in ("google", "gemini"):
        api_key = get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"Google/Gemini LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Ollama (local) ───────────────────────────────────────────────────────
    if provider == "ollama":
        base_url = get_secret("OLLAMA_BASE_URL") or "http://localhost:11434"
        try:
            return LLM(model=model_string, api_key="ollama", base_url=base_url)
        except Exception as e:
            logger.error(f"Ollama LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Groq ─────────────────────────────────────────────────────────────────
    if provider == "groq":
        api_key = get_secret("GROQ_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"Groq LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Mistral ──────────────────────────────────────────────────────────────
    if provider == "mistral":
        api_key = get_secret("MISTRAL_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"Mistral LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Cohere ───────────────────────────────────────────────────────────────
    if provider == "cohere":
        api_key = get_secret("COHERE_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"Cohere LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── HuggingFace Inference API ────────────────────────────────────────────
    if provider == "huggingface":
        api_key = get_secret("HUGGINGFACE_API_KEY")
        try:
            return LLM(model=model_string, api_key=api_key)
        except Exception as e:
            logger.error(f"HuggingFace LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── AWS Bedrock ──────────────────────────────────────────────────────────
    if provider == "bedrock":
        aws_region = get_secret("AWS_DEFAULT_REGION") or "us-east-1"
        try:
            return LLM(model=model_string, aws_region_name=aws_region)
        except Exception as e:
            logger.error(f"Bedrock LLM init failed: {e}")
            return _fallback_llm(model_string)

    # ── Unknown provider – smart fallback ────────────────────────────────────
    logger.warning(
        f"Unknown provider '{provider}' in model string '{model_string}'. "
        "Attempting smart fallback."
    )
    return _fallback_llm(model_string)


def _fallback_llm(original_model: str) -> LLM:
    """
    Smart fallback resolution:
      1. Azure OpenAI (if AZURE_OPENAI_API_KEY is present)
      2. OpenAI       (if OPENAI_API_KEY is present)
      3. Stub object  (keeps the system alive without crashing)
    """
    azure_key = get_secret("AZURE_OPENAI_API_KEY")
    openai_key = get_secret("OPENAI_API_KEY")

    if azure_key:
        logger.warning(
            f"Falling back from '{original_model}' → Azure OpenAI (gpt-4o deployment)."
        )
        try:
            return _build_azure_llm("azure/gpt-4o")
        except Exception as e:
            logger.error(f"Azure fallback also failed: {e}")

    if openai_key:
        logger.warning(
            f"Falling back from '{original_model}' → OpenAI gpt-4o."
        )
        try:
            return LLM(model="openai/gpt-4o", api_key=openai_key)
        except Exception as e:
            logger.error(f"OpenAI fallback also failed: {e}")

    # Last resort – return a stub so imports/initialisation don't crash.
    # Actual calls will fail gracefully with a clear error message.
    logger.error(
        "No API keys found for any provider. "
        "Set AZURE_OPENAI_API_KEY or OPENAI_API_KEY to enable LLM calls."
    )
    # Return a minimal LLM stub using a placeholder key so CrewAI doesn't
    # throw at construction time; it will fail at inference with a clear message.
    return LLM(model="openai/gpt-4o", api_key="NO_KEY_CONFIGURED")
