# orchestrai/utils/dict_utils.py

from typing import Any

def clean_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-cleaned kwargs dict.

    Drops only keys whose values are None. This deliberately keeps falsy values
    like 0/False/"" (which may be meaningful).
    """
    return {k: v for k, v in raw.items() if v is not None}