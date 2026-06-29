import os
from typing import Dict, Optional
from utils.logger import get_logger

logger = get_logger("security.secrets")

# Thread-safe in-memory cache for fetched secrets
_secrets_cache: Dict[str, str] = {}

def get_secret(key: str, backend: str = "env") -> Optional[str]:
    """
    Retrieves a secret.
    Always checks environment variables first.
    If not found in environment, checks the configured backend.
    """
    # Check cache first
    if key in _secrets_cache:
        return _secrets_cache[key]

    # Check environment variable
    val = os.getenv(key)
    if val is not None:
        _secrets_cache[key] = val
        return val

    # Lookup secret backend if env lookup failed
    backend_lower = backend.lower()
    if backend_lower == "vault":
        val = _fetch_from_vault(key)
    elif backend_lower == "aws_secrets_manager" or backend_lower == "aws":
        val = _fetch_from_aws(key)

    if val is not None:
        _secrets_cache[key] = val
        return val

    return None

def invalidate_secret(key: str) -> None:
    """
    Removes key from local memory cache. Used when 401 responses occur,
    triggering a rotation/re-fetch.
    """
    if key in _secrets_cache:
        logger.info(f"Invalidating secret cache for key: {key}")
        del _secrets_cache[key]

def _fetch_from_vault(key: str) -> Optional[str]:
    """
    Fetches key from HashiCorp Vault. Gracefully falls back if hvac is not installed.
    """
    try:
        import hvac
        vault_url = os.getenv("VAULT_ADDR", "http://127.0.0.1:8200")
        vault_token = os.getenv("VAULT_TOKEN")
        if not vault_token:
            logger.warning("VAULT_TOKEN environment variable not set; vault fetch skipped.")
            return None
        
        client = hvac.Client(url=vault_url, token=vault_token)
        path = os.getenv("VAULT_SECRET_PATH", "secret/data/crewctl")
        
        response = client.secrets.kv.v2.read_secret_version(path=path)
        data = response.get("data", {}).get("data", {})
        return data.get(key)
    except ImportError:
        logger.debug("hvac client library not installed; Vault integration skipped.")
        return None
    except Exception as e:
        logger.error(f"Error resolving secret '{key}' from Vault: {str(e)}")
        return None

def _fetch_from_aws(key: str) -> Optional[str]:
    """
    Fetches key from AWS Secrets Manager. Gracefully falls back if boto3 is not installed.
    """
    try:
        import boto3
        import json
        from botocore.exceptions import ClientError
        
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region)
        secret_name = os.getenv("AWS_SECRET_NAME", "crewctl")
        
        response = client.get_secret_value(SecretId=secret_name)
        if "SecretString" in response:
            data = json.loads(response["SecretString"])
            return data.get(key)
    except ImportError:
        logger.debug("boto3/botocore client libraries not installed; AWS SM integration skipped.")
        return None
    except Exception as e:
        logger.error(f"Error resolving secret '{key}' from AWS Secrets Manager: {str(e)}")
        return None
