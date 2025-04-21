# 📘 Formatter Usage Guide

The `Formatter` class in `core/utils/formatters.py` allows you to convert data like Django `QuerySet`, lists of dictionaries, or single dictionary records into various human-readable formats.

---

## 🔧 Initialization

```python
from core.utils.formatters import Formatter

data = Simulation.objects.values("id", "diagnosis", "chief_complaint")
formatter = Formatter(data)
```

---

## 🎯 Supported Formats

| Format           | Description                                                        |
|------------------|--------------------------------------------------------------------|
| `"json"`         | Standard JSON with optional pretty-printing                        |
| `"csv"`          | CSV string with headers `id`, `start_timestamp`, etc.              |
| `"markdown"`     | Markdown table useful for documentation                            |
| `"log_pairs"`    | List of `("chief_complaint", "diagnosis")` pairs                   |
| `"openai_prompt"`| AI-friendly prompt format for OpenAI usage                         |

```python
formatter.supported_formats()
# ➜ ['json', 'log_pairs', 'openai_prompt', 'csv', 'markdown']
```

---

## 🖨 Rendering Output

```python
formatter.render("json")        # JSON string
formatter.render("csv")         # CSV format
formatter.render("markdown")    # Markdown table
formatter.render("log_pairs")   # Tuple string
formatter.render("openai_prompt")  # OpenAI formatted string
```

Pretty-print for easier debug:

```python
formatter.pretty_print()
```

---

## 🧠 Smart Serialization

The formatter handles serialization of:

- `datetime` → ISO 8601 string
- `decimal.Decimal` → string
- `uuid.UUID` → string

---

## 🧱 Advanced Usage: Register Your Own Format

```python
from core.utils.formatters import register_formatter

@register_formatter("custom_format")
def my_formatter(self):
    return "Custom formatted output"
```

Use it via:

```python
formatter.render("custom_format")
```

---

## ✅ Example: Prompt Format for OpenAI

```python
log = user.get_scenario_log()
formatter = Formatter(log)
formatter.render("openai_prompt")
```

This returns a message like:

```
This user has recently completed scenarios with the following 'chief complaint: diagnosis' pairs. Avoid repeating them excessively.

[("dizziness", "hypotension"), ("cough", "bronchitis")]
```

---

_Last updated: 2025-04-21 16:17 UTC_