# Django 6.0 Template Partials Migration

**Date**: 2026-02-21
**Status**: ✅ Complete

## Summary

Successfully migrated simulation tool templates from traditional `{% include %}` statements to Django 6.0's native `{% partialdef %}` and `{% partial %}` framework.

## Changes Made

### 1. Created Consolidated Template (`simulation/tools.html`)

**Location**: `SimWorks/simulation/templates/simulation/tools.html`

Consolidated 7 separate template files into one file with named partials:

- `{% partialdef tool_wrapper %}` - Main container for tool cards
- `{% partialdef tool_panel %}` - Tool header and actions
- `{% partialdef tool_generic %}` - Generic key-value display
- `{% partialdef tool_patient_history %}` - Patient medical history timeline
- `{% partialdef tool_patient_results %}` - Lab and imaging results
- `{% partialdef tool_simulation_feedback %}` - AI feedback display
- `{% partialdef tool_fallback %}` - Default empty state

**Benefits**:
- Single source of truth for all tool templates
- Clear section boundaries with explicit naming
- Better organization and maintainability
- Aligned with Django 6.0 best practices

### 2. Updated View Layer (`simulation/views.py`)

**Changed**: `refresh_tool()` function (lines 27-48)

**Before**:
```python
custom_partial = f"simulation/partials/tools/_{tool_name}.html"
try:
    get_template(custom_partial)
    template = custom_partial
except TemplateDoesNotExist:
    template = "simulation/partials/tools/_generic.html"
return render(request, template, {"tool": tool, "simulation": simulation})
```

**After**:
```python
partial_name = f"tool_{tool_name}"
try:
    # Django 6.0 partial syntax: template.html#partial_name
    template = get_template(f"simulation/tools.html#{partial_name}")
except TemplateDoesNotExist:
    # Fallback to generic partial
    template = get_template("simulation/tools.html#tool_generic")

context = {"tool": tool, "simulation": simulation}
return render(request, template.template, context)
```

**Key Changes**:
- Direct partial loading via `template.html#partial_name` syntax
- Cleaner fallback logic
- Native Django 6.0 template partial API

### 3. Updated Sidebar Wrapper (`chatlab/partials/sidebar_wrapper.html`)

**Changed**: Tool rendering loop

**Before**:
```django
{% for tool in tools %}
    {% include 'simulation/partials/tools/_wrapper.html' with tool=tool %}
{% endfor %}
```

**After**:
```django
{% load core_tags %}
{% for tool in tools %}
    {% include "simcore/tools.html#tool_wrapper" %}
{% endfor %}
```

**Key Changes**:
- Cross-file partial reference using `{% include "template.html#partial_name" %}` syntax
- Context automatically inherited (Django 6.0 partials inherit parent context)
- No separate file includes needed

**Important Notes**:

1. **Cross-file partials**: Use `{% include "template.html#partial_name" %}` to reference partials from other template files. The `{% partial %}` tag only works for partials defined in the same template.

2. **Context inheritance**: Partials automatically inherit the current template context. To override context, use `{% with %}` blocks:
   ```django
   {% with custom_var="value" %}
       {% include "template.html#partial_name" %}
   {% endwith %}
   ```

3. **Programmatic loading**: In views, use `get_template("template.html#partial_name")` to load specific partials directly.

### 4. Fixed Context Variable Handling (`chatlab/views.py`)

**Issue**: `feedback_continuation` was only added to context when `True`, causing potential `KeyError` in templates.

**Fix**: Always set `feedback_continuation` in context (lines 132-133):

```python
feedback_continuation = val in ("true", "1", "yes", "on")
context["feedback_continuation"] = feedback_continuation
```

### 5. Removed Deprecated Files

**Deleted** (7 files):
- `SimWorks/simulation/templates/simulation/partials/tools/_wrapper.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_panel.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_generic.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_patient_history.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_patient_results.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_simulation_feedback.html`
- `SimWorks/simulation/templates/simulation/partials/tools/_fallback.html`

### 6. Added Tests

**Created**: `tests/simulation/test_tool_partials.py` (9 tests)

Tests cover:
- ✅ All partials can be loaded
- ✅ Non-existent partials raise proper errors
- ✅ Partials can be rendered with context
- ✅ Django 6.0 partial API works correctly

**Test Results**: All 9 tests pass ✅

## Architecture Benefits

### Before (Traditional Includes)
```
sidebar_wrapper.html
  ├─ include _wrapper.html
       ├─ include _panel.html
       └─ include (_generic.html | _patient_history.html | _fallback.html)
```

**Issues**:
- Multiple file reads per render
- Scattered template logic
- Naming convention with underscores
- Template resolution logic in templates

### After (Django 6.0 Partials)
```
sidebar_wrapper.html
  └─ partial tools.html#tool_wrapper
       ├─ partial tools.html#tool_panel
       └─ partial tools.html#(tool_generic | tool_patient_history | tool_fallback)
```

**Benefits**:
- Single file load, multiple partial invocations
- Centralized template definitions
- Clear semantic naming
- HTMX-native pattern
- Better performance (cached partials)

## HTMX Integration

Django 6.0 partials were specifically designed for HTMX-style partial updates:

```python
# Direct partial loading for HTMX responses
template = get_template("simulation/tools.html#tool_patient_history")
return template.render(context)
```

This aligns with SimWorks' existing HTMX architecture for:
- Tool panel refreshes
- WebSocket event-driven updates
- Server-rendered HTML fragments

## Compatibility

- ✅ **Django 6.0+**: Native partial support
- ✅ **Backward Compatible**: No breaking changes to tool API
- ✅ **HTMX**: Direct partial loading for fragment updates
- ✅ **Tests**: All existing tests pass

## Future Enhancements

1. **Dynamic Partial Resolution**: Could add registry-based partial lookup for extensibility
2. **Partial Caching**: Django 6.0 partials support template-level caching
3. **Composition**: Could nest partials for more complex tool UIs
4. **Testing**: Could add integration tests with real Simulation objects

## Django 6.0 Partial Tag Usage Guide

### When to Use `{% partial %}` vs `{% include %}`

**Use `{% partial partial_name %}` (no quotes) when:**
- Rendering a partial defined in the **same template file**
- Example:
  ```django
  {% partialdef button %}
      <button>Click me</button>
  {% endpartialdef %}

  {% partial button %}  {# ✅ Works - same file, no quotes #}
  ```

**Use `{% include "template.html#partial_name" %}` when:**
- Rendering a partial defined in a **different template file**
- Example:
  ```django
  {# components.html #}
  {% partialdef button %}
      <button>Click me</button>
  {% endpartialdef %}

  {# page.html #}
  {% include "components.html#button" %}  {# ✅ Works - cross-file #}
  ```

### Context Inheritance

Both `{% partial %}` and `{% include "template.html#partial_name" %}` automatically inherit the current template context. No explicit parameter passing is needed.

```django
{# Context: {'user': 'Alice', 'count': 5} #}

{% partial user_info %}      {# Has access to user and count #}
{% include "tools.html#widget" %}  {# Also has access to user and count #}
```

## References

- Django 6.0 Release Notes: https://docs.djangoproject.com/en/6.0/releases/6.0/
- Template Partials Documentation: https://docs.djangoproject.com/en/6.0/ref/templates/builtins/#partial
- Original Package (now in Django core): https://github.com/carltongibson/django-template-partials
