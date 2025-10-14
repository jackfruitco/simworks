# simcore_ai_django/prompts/render_section.py
"""
Renderer for prompt sections that prefers core PromptRegistry hints when available.
This module attempts to use the core PromptRegistry to influence template resolution
if it is present, allowing project-level prompt definitions to participate in Django
template selection.
"""
from __future__ import annotations
from typing import Any, Mapping, Optional
from asgiref.sync import sync_to_async
from django.template.loader import select_template
from django.utils import timezone

# Optional integration with the core prompt engine
try:
    # Prefer a stable import path; adjust if your project uses a different module layout
    from simcore_ai.promptkit import PromptRegistry  # type: ignore
except Exception:  # pragma: no cover - registry optional
    PromptRegistry = None  # type: ignore

async def render_section(
    namespace: str,
    section_key: str,
    simulation: Any,
    *,
    ctx: Optional[Mapping[str, Any]] = None,
) -> str:
    """
    Render a prompt section with Django templates.

    Looks up templates in this order (examples for namespace='chatlab'):
      - "chatlab/ai/prompts/{section_key}.txt"
      - "chatlab/ai/prompts/{section_key}.md"
      - "ai/prompts/{namespace}/{section_key}.txt"
      - "ai/prompts/{section_key}.txt"

    If the core `PromptRegistry` is available, any template candidates it provides
    (e.g., via `template_candidates(namespace, section)` or prompt metadata like
    `template_paths`) will be *prepended* to this search list, so project-specific
    prompt definitions can influence Django template resolution without requiring
    Django-specific code.
    """
    # Allow the core PromptRegistry to influence template resolution, if present.
    registry_candidates = []
    if PromptRegistry is not None:
        try:
            # Try a dedicated helper if your PromptRegistry exposes one
            get_cands = getattr(PromptRegistry, "template_candidates", None)
            if callable(get_cands):
                extra = get_cands(namespace=namespace, section=section_key)  # type: ignore[call-arg]
                if isinstance(extra, (list, tuple)):
                    registry_candidates.extend([str(p) for p in extra])
            else:
                # Fallback: if a namespaced prompt exists, look for a conventional template path hint
                # Namespaced key pattern: "<namespace>:<section_key>"
                key = f"{namespace}:{section_key}"
                get_prompt = getattr(PromptRegistry, "get", None)
                prompt_obj = get_prompt(key) if callable(get_prompt) else None  # type: ignore[misc]
                # If the prompt object exposes `template_paths` or `templates`, add them
                for attr in ("template_paths", "templates"):
                    paths = getattr(prompt_obj, attr, None)
                    if isinstance(paths, (list, tuple)):
                        registry_candidates.extend([str(p) for p in paths])
        except Exception:
            # If the registry integration fails for any reason, fall back to static candidates
            registry_candidates = []

    candidates = (
        list(dict.fromkeys(registry_candidates)) +  # de-dupe while preserving order
        [
            f"{namespace}/ai/prompts/{section_key}.txt",
            f"{namespace}/ai/prompts/{section_key}.md",
            f"ai/prompts/{namespace}/{section_key}.txt",
            f"ai/prompts/{section_key}.txt",
        ]
    )

    template = await sync_to_async(select_template)(candidates)

    base_ctx = {
        "namespace": namespace,
        "section": section_key,
        "simulation": simulation,
        "now": timezone.now(),
    }
    if ctx:
        base_ctx.update(ctx)

    # render is sync; wrap it
    rendered = await sync_to_async(template.render)(base_ctx)
    return rendered.strip()