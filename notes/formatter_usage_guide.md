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
# Render to string
formatter.render("json")
formatter.render("csv")
formatter.render("markdown")
formatter.render("log_pairs")
formatter.render("openai_prompt")

# Use keyword arguments (e.g., indent for JSON)
formatter.render("json", indent=2)

# Use file-style extensions
formatter.render(".md")
formatter.render(".json", indent=2)

# Output directly to file
formatter.render("markdown", output="file", filepath="/tmp/log.md")
formatter.render("json", output="file", filepath="log.json", indent=4)

# Pretty-print to console or file
formatter.pretty_print(indent=2)  # stdout
formatter.pretty_print(indent=2, output="output.json")  # to file
```

---

## 📂 File Extension Support

The `Formatter.render()` method also supports format calls using common file extensions:

| Extension | Interpreted Format |
|-----------|--------------------|
| `.json`   | `json`             |
| `.csv`    | `csv`              |
| `.md`     | `markdown`         |
| `.txt`    | `openai_prompt`    |

These can also be used in .render() and pretty_print() for file export and formatting convenience.

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
formatter.render(".md")  # Markdown version of the log
```

This returns a message like:

```
This user has recently completed scenarios with the following 'chief complaint: diagnosis' pairs. Avoid repeating them excessively.

[("dizziness", "hypotension"), ("cough", "bronchitis")]
```

---

_Last updated: 2025-04-21 16:17 UTC_