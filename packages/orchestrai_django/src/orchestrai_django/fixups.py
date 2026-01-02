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
            existing_registry = None

            try:
                if hasattr(store, "items"):
                    existing_registry = store.items().get(PERSIST_DOMAIN)
            except Exception:
                logger.debug(
                    "Failed to inspect component store registries; proceeding with"
                    " installation",
                    exc_info=True,
                )

            if isinstance(existing_registry, PersistenceHandlerRegistry):
                logger.info(
                    "Component store already has a PersistenceHandlerRegistry;"
                    " reusing existing instance",
                )
                return None

            if hasattr(store, "set_registry"):
                if existing_registry is None:
                    store.set_registry(PERSIST_DOMAIN, registry)
                    logger.info(
                        "Installed PersistenceHandlerRegistry on empty component"
                        " store",
                    )
                    return None

                existing_count = (
                    existing_registry.count()
                    if hasattr(existing_registry, "count")
                    else 0
                )

                if existing_count:
                    migrated = 0
                    components = (
                        existing_registry.items()
                        if hasattr(existing_registry, "items")
                        else ()
                    )

                    for component in components:
                        try:
                            registry.register(component)
                            migrated += 1
                        except Exception:
                            logger.warning(
                                "Skipping migration of persistence component %s",
                                component,
                                exc_info=True,
                            )

                    if migrated == existing_count:
                        try:
                            if hasattr(existing_registry, "clear"):
                                existing_registry.clear()

                            store.set_registry(
                                PERSIST_DOMAIN, registry, replace=True
                            )
                            logger.info(
                                "Migrated %s existing persistence registrations into"
                                " PersistenceHandlerRegistry",
                                migrated,
                            )
                        except Exception:
                            logger.warning(
                                "Failed to install migrated persistence registry;"
                                " retaining existing registry",
                                exc_info=True,
                            )
                    else:
                        logger.info(
                            "Component store already has %s persistence"
                            " registrations; keeping existing registry",
                            existing_count,
                        )
                else:
                    store.set_registry(
                        PERSIST_DOMAIN, registry, replace=True
                    )
                    logger.info(
                        "Installed PersistenceHandlerRegistry, replacing empty"
                        " existing registry",
                    )
                return None
            else:
                logger.debug(
                    "Component store does not support set_registry; "
                    "skipping persistence registry injection"
                )
        except Exception:
            logger.debug("Failed to install persistence registry", exc_info=True)


__all__ = ["PersistenceRegistryFixup"]
