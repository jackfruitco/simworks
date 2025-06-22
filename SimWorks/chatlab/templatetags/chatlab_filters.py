from django import template

register = template.Library()


@register.filter
def feedback(value: object) -> str:
    """
    Interpret feedback value and format it into an appropriate symbol or string.

    - Booleans: ✅ or ❌
    - Integers: Star rating (e.g. ⭐️⭐️⭐️☆☆)
    - Strings: Capitalized or mapped to special icons (e.g. 'partial' → 🟡)
    """
    # Try integer (e.g. star rating)
    try:
        int_value = int(value)
        return display_star_rating(int_value)
    except (ValueError, TypeError):
        pass

    # Try boolean-ish (e.g. ✅ ❌ 🟡)
    if isinstance(value, bool) or str(value).strip().lower() in ("true", "false", "yes", "no", "0", "1", "partial"):
        return display_success(value)

    # Fallback: title-case string
    return str(value).title()


@register.filter
def display_success(value: object) -> str:
    """
    Convert boolean-like values into symbols:
    - true/yes/1 → ✅
    - false/no/0 → ❌
    - partial → 🟡
    """
    if isinstance(value, bool):
        return "✅" if value else "❌"

    value_str = str(value).strip().lower()
    if value_str in ("true", "yes", "1"):
        return "✅"
    elif value_str in ("false", "no", "0"):
        return "❌"
    elif value_str == "partial":
        return "🟡"

    return str(value)


@register.filter
def display_star_rating(value: object, total: int = 5) -> str:
    """
    Convert numeric rating into a string of stars:

    Example:
        display_star_rating(3) -> '⭐️  ⭐️  ⭐️  ☆  ☆'
    """
    try:
        value_int = int(value)
    except (ValueError, TypeError):
        return "☆  " * total

    value_int = max(0, min(total, value_int))
    return "⭐️  " * value_int + "☆  " * (total - value_int)