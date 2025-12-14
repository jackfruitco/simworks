# orchestrai_django/templatetags/prompt_tags.py
"""
TODO: needs lots of updating
Template tag for rendering registered prompts via the core PromptRegistry.

Usage examples:
---------------
    {% load prompt_tags %}

    {# Directly render to output #}
    {% prompt "chatlab:system" %}

    {# Capture into a variable for further formatting #}
    {% prompt "chatlab:system" as system_prompt %}
    <pre>{{ system_prompt }}</pre>

This tag looks up the given prompt key in the core orchestrai PromptRegistry.
If the prompt defines templates or text, it renders them. If Django's
`render_section()` utility is available, template-based prompts will render
through that helper for full context support.
"""

from typing import Optional
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

# Optional integration hooks
from orchestrai.registry import prompt_sections

try:
    # Prefer the Django renderer if available
    from orchestrai_django.components.promptkit.render_section import render_section  # type: ignore
except Exception:
    render_section = None  # type: ignore


@register.simple_tag(name="prompt")
def render_prompt_tag(
    key: str,
    simulation: Optional[object] = None,
    namespace: Optional[str] = None,
) -> str:
    """
    Render a registered prompt by key.

    - If `PromptRegistry` is available, tries to fetch `PromptRegistry.get(key)`.
    - If the prompt defines `.text`, returns that.
    - If the prompt defines `.template_paths` or `.templates`, attempts
      to render via Django's `render_section` helper (if available).
    - If nothing found, returns an empty string.

    Parameters
    ----------
    key:
        Prompt key, e.g. "chatlab:system"
    simulation:
        Optional Simulation or context object for rendering templates.
    namespace:
        Optional override for template namespace (defaults to prefix of `key`).

    Returns
    -------
    str
        Rendered prompt text (HTML-safe)
    """
    if not key:
        return ""

    # Split namespaced key
    ns, _, section = key.partition(":")
    namespace = namespace or ns or "default"

    text = None

    if prompt_sections is not None:
        try:
            prompt_obj = prompt_sections.get(key)
            if prompt_obj is not None:
                # Priority: explicit text first
                if getattr(prompt_obj, "text", None):
                    text = str(prompt_obj.text)
                # Template paths next
                elif render_section and (
                    getattr(prompt_obj, "template_paths", None)
                    or getattr(prompt_obj, "templates", None)
                ):
                    # Render asynchronously if needed
                    import asyncio

                    async def _async_render():
                        return await render_section(namespace, section, simulation)

                    try:
                        text = asyncio.run(_async_render())
                    except RuntimeError:
                        # Already in event loop; use asyncio.run_coroutine_threadsafe
                        loop = asyncio.get_event_loop()
                        text = loop.run_until_complete(_async_render())
        except Exception:
            text = None

    return mark_safe(text or "")