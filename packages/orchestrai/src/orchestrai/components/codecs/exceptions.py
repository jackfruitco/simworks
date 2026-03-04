"""Codec compatibility exceptions."""


class CodecNotFoundError(LookupError):
    """Raised when no codec can be resolved."""


class CodecDecodeError(ValueError):
    """Raised when codec decode fails."""
