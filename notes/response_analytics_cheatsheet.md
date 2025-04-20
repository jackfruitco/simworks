# 🧠 Response Analytics Cheat Sheet

This document outlines all the available filters, grouping, and aggregation methods for analyzing OpenAI `Response` data using the `ResponseQuerySet` and `ResponseAnalytics` classes.

---

## 📊 QuerySet Filters

These are used directly from the `Response` model manager:

```python
from simai.models import Response
```

| Method             | Description                             |
|--------------------|-----------------------------------------|
| `.this_month()`    | Responses created in the current month  |
| `.this_year()`     | Responses created in the current year   |
| `.today()`         | Responses created today                 |

**Example**:
```python
Response.objects.this_month()
```

---

## 📈 Analytics Entry Point

From any filtered or base queryset:

```python
Response.objects.analytics()
```

Returns a `ResponseAnalytics` instance, enabling further chaining.

---

## 🧮 Chainable Analytics Methods

### 📅 Date Filters
```python
.from_date(dt)
.to_date(dt)
.range(start, end)
```

- Accepts strings, datetime, or date objects.

---

### 🔢 Grouping Methods
```python
.by_month()
.by_day()
.by_user()
.by_simulation()
```

- All can be combined. Example:
```python
Response.objects.analytics().by_user().by_month().range("2025-01-01", "2025-04-01")
```

---

### 📊 Aggregation Methods

| Method        | Description                                              |
|---------------|----------------------------------------------------------|
| `.tally()`    | Returns grouped totals of input, output, reasoning, total |
| `.summary()`  | Flat dict of total usage across entire queryset          |
| `.as_list()`  | Returns `.tally()` results as a list of dicts            |
| `.as_csv()`   | Returns `.tally()` results as a CSV string               |

---

## ⚡ Prebuilt Shortcuts

These exist on `ResponseQuerySet` for convenience:

| Method          | Equivalent To                                      |
|------------------|-----------------------------------------------------|
| `.monthly()`     | `.analytics().by_month().by_user().tally()`         |
| `.yearly()`      | `.analytics().by_month().by_user().tally()`         |
| `.all_time()`    | `.analytics().by_user().tally()`                    |

---

## ✅ Usage Examples

```python
# Get this month's usage by user
Response.objects.this_month().analytics().by_user().tally()

# Get a CSV export of daily token usage
csv = Response.objects.analytics().by_day().range("2025-01-01", "2025-04-01").as_csv()

# Summary of total usage this year
Response.objects.this_year().analytics().summary()
```

---

## 🧰 Advanced

- Add `.by_model()` or `.by_tool()` for model-level breakdowns
- Use `.as_csv()` to export data to admin reports or download APIs
- Combine with `.values()` or `Q(...)` filters for scoped analytics