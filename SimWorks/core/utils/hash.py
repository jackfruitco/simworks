# core/utils/hash.py
import hashlib
import logging

logger = logging.getLogger(__name__)


def compute_fingerprint(*args: str) -> str:
    """
    Compute a SHA256 hash from any number of string arguments.

    Args:
        *args (str): Any number of strings to combine and hash.

    Returns:
        str: The SHA256 hex digest of the combined string.
    """
    combined = "".join(arg.strip() for arg in args if isinstance(arg, str))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
