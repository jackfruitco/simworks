"""Django-specific fixups for OrchestrAI applications."""

from __future__ import annotations

import logging
from typing import Any

from orchestrai.fixups.base import Fixup, FixupStage
from orchestrai.identity.domains import PERSIST_DOMAIN

from orchestrai_django.registry.persistence import PersistenceHandlerRegistry

logger = logging.getLogger(__name__)


class PersistenceRegistryFixup:
    """Install the Django persistence handler registry onto the component store."""

    def apply(self, stage: FixupStage, app: Any, **context: Any) -> None:
        if stage is not FixupStage.CONFIGURE_POST:
            return None

        store = getattr(app, "component_store", None)
        if store is None:
            return None

        try:
            registry = PersistenceHandlerRegistry()
            if hasattr(store, "set_registry"):
                store.set_registry(PERSIST_DOMAIN, registry, replace=True)
            else:
                logger.debug(
                    "Component store does not support set_registry; "
                    "skipping persistence registry injection"
                )
        except Exception:
            logger.debug("Failed to install persistence registry", exc_info=True)


__all__ = ["PersistenceRegistryFixup"]
