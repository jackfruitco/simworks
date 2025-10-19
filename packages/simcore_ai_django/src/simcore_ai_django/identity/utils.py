# simcore_ai_django/identity/utils.py
import re
from typing import Iterable

DEFAULT_STRIP_TOKENS = {
    "Codec", "Service", "Prompt", "PromptSection", "Section", "Response",
}

def snake(s: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return re.sub(r"_+", "_", s2).strip("_").lower()

def strip_tokens(name: str, extra_tokens: Iterable[str] = ()) -> str:
    tokens = set(DEFAULT_STRIP_TOKENS) | set(extra_tokens)
    out = name
    for t in sorted(tokens, key=len, reverse=True):
        out = re.sub(fr"{t}$", "", out)
    return out or name  # guard against empty

def derive_name_from_class(cls_name: str, extra_tokens: Iterable[str] = ()) -> str:
    return snake(strip_tokens(cls_name, extra_tokens))