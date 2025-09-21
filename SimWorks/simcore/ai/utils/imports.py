# simcore/ai/utils/imports.py

import logging

from importlib import import_module

from django import conf
from django.apps import apps


logger = logging.getLogger(__name__)


def resolve_initial_section(lab: str):
    """
    Return the InitialSection class from `<app>.promptkit` based on `lab`.
    Accepts 'chatlab', 'ChatLab', etc. Raises ValueError/ImportError on failure.
    """
    if not lab:
        raise ValueError("cannot resolve initial Prompt Section: lab is required")

    logger.debug(f"...... resolving initial Prompt Section for {lab}")

    lab_norm = str(lab).strip().lower()

    # Resolve to an installed app (handles package path vs label)
    try:
        app_config = apps.get_app_config(lab_norm)
    except LookupError as e:
        # Optional: simple alias map if your labels differ from app configs
        ALIASES = {"chatlab": "chatlab", "trainerlab": "trainerlab"}
        target = ALIASES.get(lab_norm)
        if not target:
            raise ValueError(f"Unknown lab '{lab}'") from e
        app_config = apps.get_app_config(target)

    # Built‑in search order (least to most specific inside the app)
    DEFAULT_PATHS: list[str] = [
        f"{app_config.name}.ai.prompts",                       # e.g. app/ai/prompts.py
        f"{app_config.name}.ai.prompts.sections",              # e.g. app/ai/prompts/sections.py
        f"{app_config.name}.ai.prompts.sections.initial",      # e.g. app/ai/prompts/sections/initial.py
    ]

    # Optional comma‑separated override(s) — tried *before* defaults
    custom_path = getattr(conf.settings, "AI_CUSTOM_PROMPT_PATH", None)
    CUSTOM_PATHS: list[str] = []
    if custom_path:
        CUSTOM_PATHS = [p.strip() for p in custom_path.split(",") if p.strip()]

    # Compose search order: custom first, then defaults; de‑dupe while preserving order
    raw_paths = [*CUSTOM_PATHS, *DEFAULT_PATHS]
    module_paths: list[str] = []
    seen: set[str] = set()
    for p in raw_paths:
        if p not in seen:
            seen.add(p)
            module_paths.append(p)

    mod = None
    path: str | None = None

    # Try each candidate until one imports cleanly
    for path in module_paths:
        try:
            mod = import_module(path)
            break
        except ModuleNotFoundError:
            continue

    if mod is None:
        raise ImportError(
            f"No module following expected path for {app_config.name} "
            f"Initial Prompt (tried {', '.join(module_paths)})")

    try:
        return getattr(mod, "InitialSection")
    except AttributeError as e:
        raise ImportError(f"'InitialSection' not exported by {path}") from e