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

@register_section
@dataclass
class PatientResultsSection(PromptSection):
    name: str = "patient_results"
    weight: int = 10
    instruction: str = (
        "### Role and Objective\n"
        f"For this response only, assume the role of simulation facilitator.\n"
        f"The user is requesting clinical results (e.g. labs, radiology). For each order, provide "
        f"the standardized name using standardized terminology and order sentences. Include standard "
        f"reference ranges, values, units, and normal/abnormal flags. Reference LabCorp Test Menu.\n"
    )

    def render_message(self, **ctx) -> Optional[str]:
        orders_: list[str] | str = ctx.get('submitted_orders')

        if not orders_:
            raise ValueError(
                f"PromptSection {self.name} requires `submitted_orders` in context, but none were found."
            )

        if not isinstance(orders_, list):
            orders_ = [orders_]

        if not all(isinstance(item, str) for item in orders_):
            raise ValueError("lab_order must be a string or a list of strings.")

        lines: list[str] = []
        for order in orders_:
            lines.append(order)

        return (
            f"#### Orders\n"
            f"{'\n- '.join(lines)}"
        )



