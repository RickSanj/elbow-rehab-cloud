import os
from src.utils.logger import get_logger

logger = get_logger()

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.error(f"Missing required env var: {name}")
        raise RuntimeError(f"Missing required env var: {name}")
    return value
