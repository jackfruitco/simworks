from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.contrib.auth import get_user_model
import inspect

from django.contrib.auth.models import AnonymousUser

from accounts.models import CustomUser
from ...promptkit import PromptSection, register_section

logger = logging.getLogger(__name__)

User = get_user_model()


@dataclass
class BaseSection(PromptSection):
    category = "core"


@register_section
@dataclass
class UserRoleSection(BaseSection):
    name: str = "user_role"
    weight: int = 50

    async def render_instruction(self, **ctx) -> Optional[str]:
        """Add developer instructions for the given user's role, if provided.

        This attempts to fetch the user's role from the context
        and falls back to the user's pk or username.

        Args:
            self: The section instance
            **ctx: The context dictionary

        Returns:
            A string with the user's role and sources, if available.

        """
        role = ctx.get("role")

        if not role:
            logger.debug(
                f"PromptSection {self.label}:: No role found in PromptEngine context. "
                f"Attempting to fetch the user's role."
            )
            user = ctx.get("user")
            if not user:
                logger.warning(
                    f"PromptSection {self.label}:: No user found in PromptEngine context - skipping."
                )
                return None

            from django.contrib.auth.models import AnonymousUser

            try:
                if isinstance(user, AnonymousUser) or not getattr(user, "is_authenticated", False):
                    logger.warning(
                        f"PromptSection {self.label}:: User in context is Anonymous or unauthenticated - skipping."
                    )
                    return None

                # If already a CustomUser and role is available, reuse; else refetch with select_related
                if isinstance(user, CustomUser) and getattr(user, "role_id", None) is not None and hasattr(user,
                                                                                                           "role"):
                    cu = user
                else:
                    # Prefer PK if present, fall back to username
                    lookup = {}
                    if getattr(user, "pk", None):
                        lookup["pk"] = user.pk
                    elif getattr(user, "username", None):
                        lookup["username"] = user.username
                    else:
                        logger.warning("PromptSection %s:: User in context missing pk/username - skipping.", self.label)
                        return None

                    cu = await CustomUser.objects.select_related("role").aget(**lookup)

            except CustomUser.DoesNotExist:
                uname = getattr(user, "username", "<unknown>")
                logger.warning("PromptSection %s:: User %s does not exist - skipping.", self.label, uname)
                return None

            role = getattr(cu, "role", None)
            if not role:
                logger.info("PromptSection %s:: User %s has no role - skipping.", self.label, cu.pk)
                return None

        logger.debug(f"PromptSection {self.label}:: User role found: {repr(role)}")

        # Normalize resource_list → string (handle callables, awaitables, iterables)
        resources = getattr(role, "resource_list", None)
        try:
            if callable(resources):
                resources = resources()
            if inspect.isawaitable(resources):
                resources = await resources
        except Exception:
            logger.exception(
                f"PromptSection {self.label}:: Failed to resolve role.resource_list; skipping resources."
            )
            resources = None

        if resources is None:
            tail = ""
        elif isinstance(resources, str):
            tail = f"\n{resources}"
        else:
            # Try to coerce common container types (lists, tuples, sets, querysets) to lines
            try:
                # QuerySet-safe stringification
                try:
                    from django.db.models.query import QuerySet  # type: ignore
                    if isinstance(resources, QuerySet):
                        resources = list(resources)
                except Exception:
                    pass

                # Map items to string lines
                tail = "\n" + "\n".join(map(str, resources))
            except Exception:
                tail = f"\n{str(resources)}"

        if tail and tail != "":
            tail = f"Additionally, consider the following sources:\n{tail}"

        return (
            f"### User Role Context\n"
            f"The user takes the role of a {role}. Factor this context into all scenario drafting and SMS responses. "
            f"{tail}"
        )


@register_section
@dataclass
class UserHistorySection(BaseSection):
    name: str = "user_history"
    weight: int = 100

    async def render_instruction(self, **ctx) -> Optional[str]:
        """Add developer instructions for the given user's history, if provided.

        """
        user_: CustomUser | int = ctx.get("user")

        if isinstance(user_, AnonymousUser) or not getattr(user_, "is_authenticated", False):
            logger.warning(
                f"PromptSection {self.label}:: User in context is Anonymous or unauthenticated - skipping."
            )
            return None

        elif not isinstance(user_, CustomUser):
            try:
                user = await CustomUser.objects.aget(pk=user_)
            except CustomUser.DoesNotExist:
                logger.warning(
                    f"PromptSection {self.label}:: User in context is Anonymous or unauthenticated - skipping."
                )
                return None

        logger.debug(f"PromptSection {self.label}:: User resolved: {repr(user_)}")

        hx: list = await user_.aget_scenario_log(within_days=180)

        if isinstance(hx, list) and len(hx) == 0:
            logger.info(
                "PromptSection %s:: User history is empty - skipping.", self.label
            )
            return None

        allowed_keys = {"diagnosis", "chief_complaint"}
        lines: list[str] = []
        for item in hx:
            if not isinstance(item, dict):
                item = dict(item)

            for k in list(item.keys()):
                if k not in allowed_keys:
                    item.pop(k, None)

            diag = item.get("diagnosis") or None
            cc = item.get("chief_complaint") or None

            if diag is not None or cc is not None:
                lines.append(f"{diag}: {cc}")

        list_ = "\n- ".join(lines)

        return (
            "### User History\n"
            f"The user has recently completed the following scenarios:\n{list_}"
        )


@register_section
@dataclass
class PatientNameSection(BaseSection):
    name: str = "patient_name"
    weight: int = 0

    async def render_instruction(self, **ctx) -> Optional[str]:

        full_name = ctx.get("sim_patient_full_name")

        simulation = ctx.get("simulation")
        if simulation and not full_name:
            from simcore.models import Simulation
            try:
                sim = await Simulation.aresolve(simulation)
                full_name = sim.sim_patient_full_name
            except Simulation.DoesNotExist:
                logger.warning(
                    f"PromptSection {self.label}:: Simulation {simulation} not found - skipping section."
                )
                return None

        if not full_name:
            logger.warning(
                f"PromptSection {self.label}:: Missing patient name (no simulation or sim_patient_full_name) - skipping."
            )
            return None

        return (
            "### Role and Objective\n"
            f"Portray {full_name}, a standardized patient, for realistic SMS/text-based medical simulation scenarios."
        )
