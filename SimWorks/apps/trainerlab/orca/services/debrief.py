# trainerlab/orca/services/debrief.py

from __future__ import annotations

from asgiref.sync import sync_to_async

from apps.trainerlab.models import TrainerSession
from apps.trainerlab.services import apply_debrief_output
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

from ..instructions import (
    TrainerDebriefContextInstruction,
    TrainerDebriefContractInstruction,
    TrainerDebriefRoleInstruction,
)


@orca.service
class GenerateTrainerRunDebrief(
    TrainerDebriefRoleInstruction,
    TrainerDebriefContractInstruction,
    TrainerDebriefContextInstruction,
    DjangoBaseService,
):
    required_context_keys = ("simulation_id", "session_id")
    use_native_output = True

    from ..schemas import TrainerRunDebriefOutput as _Schema

    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        session = await TrainerSession.objects.select_related("summary").aget(
            pk=self.context["session_id"]
        )
        summary = getattr(session, "summary", None)
        summary_json = dict(getattr(summary, "summary_json", {}) or {})
        self.context.setdefault(
            "final_state", summary_json.get("final_state", session.runtime_state_json)
        )
        self.context.setdefault("timeline_highlights", summary_json.get("timeline_highlights", []))
        self.context.setdefault("notes", summary_json.get("notes", []))
        self.context.setdefault("command_log", summary_json.get("command_log", []))

    async def on_success_ctx(self, *, context, result) -> None:
        output = result.output
        payload = output.model_dump(mode="json") if hasattr(output, "model_dump") else output
        await sync_to_async(apply_debrief_output, thread_sensitive=True)(
            session_id=context["session_id"],
            output_payload=payload,
            correlation_id=context.get("correlation_id"),
        )
