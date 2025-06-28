# core/utils/formatters/builtins/log_pairs_formatter.py
from core.utils.formatters.registry import register_formatter


@register_formatter("log_pairs")
def as_log_pairs(formatter):
    """
    Render data as a simplified log-style tuple list, like:
    [("headache", "migraine"), ("fever", "flu")]
    """
    pairs = []
    for entry in formatter.as_serializable():
        cc = entry.get("chief_complaint")
        dx = entry.get("diagnosis")
        if cc and dx:
            pairs.append(f'("{cc}", "{dx}")')
    return "[" + ", ".join(pairs) + "]"
