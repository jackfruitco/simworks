"""TrainerLab-owned progression execution. No provider or orchestration dependencies.

Targets are AI proposals, not clinically validated predictions. The engine validates
their shape, advances them only on active simulation time, and never extrapolates.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import ProgressionPlan, ScenarioDecision, SessionStatus, TrainerSession


def install_plan(*, session, state, targets, duration, portrayal, source_call_id):
    from .orca.schemas.runtime import PatientPortrayal, RuntimeVitalUpdate
    from .services import VITAL_TYPE_MODEL_MAP, get_active_elapsed_seconds

    # Validate the entire proposal before superseding the previous plan.
    if not 15 <= duration <= 120:
        raise ValidationError("Trajectory duration must be between 15 and 120 active seconds.")
    portrayal = PatientPortrayal.model_validate(portrayal).model_dump(mode="json")
    targets = [RuntimeVitalUpdate.model_validate(item).model_dump(mode="json") for item in targets]
    if len({item["vital_type"] for item in targets}) != len(targets):
        raise ValidationError("A progression plan cannot contain duplicate vital types.")
    baseline = []
    for target in targets:
        current = (
            VITAL_TYPE_MODEL_MAP[target["vital_type"]]
            .objects.filter(simulation_id=session.simulation_id, is_active=True)
            .order_by("-timestamp", "-id")
            .first()
        )
        if current is None:
            raise ValidationError("Progression requires an established vital baseline.")
        baseline.append(
            {
                key: getattr(current, key, None)
                for key in ("min_value", "max_value", "min_value_diastolic", "max_value_diastolic")
            }
            | {"vital_type": target["vital_type"]}
        )
    previous = ProgressionPlan.objects.filter(session=session).order_by("-version").first()
    ProgressionPlan.objects.filter(session=session, status="active").update(status="superseded")
    elapsed = get_active_elapsed_seconds(session, state=state)
    plan = ProgressionPlan.objects.create(
        session=session,
        version=previous.version + 1 if previous else 1,
        input_revision=int(state.get("input_revision", 0)),
        starts_at=elapsed,
        ends_at=elapsed + duration,
        baseline=baseline,
        targets=targets,
        portrayal=portrayal,
        source_call_id=source_call_id,
    )
    state["progression"] = {
        "plan_id": plan.pk,
        "version": plan.version,
        "status": "active",
        "ends_at": plan.ends_at,
        "portrayal": portrayal,
    }
    return plan


def propose_branch(*, session, state, observation, source_call_id):
    from .orca.schemas.runtime import RuntimeProblemObservation
    from .services import _resolve_active_cause

    observation = RuntimeProblemObservation.model_validate(observation).model_dump(mode="json")
    if (
        observation["observation"] != "new_problem"
        or _resolve_active_cause(
            session=session, cause_kind=observation["cause_kind"], cause_id=observation["cause_id"]
        )
        is None
    ):
        raise ValidationError("A branch requires an active cause in this scenario.")
    # Identical proposals remain one decision across retries / repeated turns.
    for existing in ScenarioDecision.objects.filter(
        session=session, status__in=["pending", "rejected"]
    ):
        same_branch = all(
            existing.proposal.get(key) == observation.get(key)
            for key in ("cause_kind", "cause_id", "problem_kind", "parent_problem_id")
        )
        if same_branch and (
            existing.status == "pending"
            or existing.input_revision + 1 == int(state.get("input_revision", 0))
        ):
            return existing
    return ScenarioDecision.objects.create(
        session=session,
        input_revision=int(state.get("input_revision", 0)),
        proposal=observation,
        source_call_id=source_call_id,
    )


def project_decisions(session, state):
    state["scenario_decisions"] = [
        {
            "id": row.pk,
            "title": row.proposal.get("title", "Scenario branch"),
            "description": row.proposal.get("description", ""),
            "status": row.status,
        }
        for row in ScenarioDecision.objects.filter(session=session, status="pending").order_by("id")
    ]


def invalidate_progression(session, state):
    ProgressionPlan.objects.filter(session=session, status="active").update(status="invalidated")
    ScenarioDecision.objects.filter(session=session, status="pending").update(status="stale")
    state["progression"] = {
        **state.get("progression", {}),
        "status": "awaiting_plan",
        "portrayal": {"behavior": "", "speech": ""},
    }
    state["scenario_decisions"] = []


def _refresh_patient_projection(session, correlation_id=None):
    from .services import (
        _current_patient_status_payload,
        _persist_patient_status_state,
        recompute_active_recommendations,
    )

    recompute_active_recommendations(session=session, correlation_id=correlation_id)
    _persist_patient_status_state(
        session=session, base_status=_current_patient_status_payload(session)
    )


@transaction.atomic
def advance_progression(*, session_id, tick_nonce):
    from .services import (
        _apply_progression_catalogs,
        _apply_vital_change,
        _finalize_runtime_views,
        append_pending_runtime_reason,
        get_active_elapsed_seconds,
        get_runtime_state,
    )

    session = (
        TrainerSession.objects.select_for_update().select_related("simulation").get(pk=session_id)
    )
    if session.status != SessionStatus.RUNNING or session.tick_nonce != tick_nonce:
        return
    state = get_runtime_state(session)
    if session.scenario_spec_json.get("authorized_progression_rules"):
        previous_sequence = session.event_sequence
        _apply_progression_catalogs(session=session, correlation_id=None)
        if session.event_sequence != previous_sequence:
            # Evaluate scenario rules before planning, so a new clinical fact
            # cannot coexist with a trajectory computed from the old patient.
            append_pending_runtime_reason(session=session, reason_kind="scenario_rule_applied")
            session.refresh_from_db()
            _refresh_patient_projection(session)
            _finalize_runtime_views(session=session, state=get_runtime_state(session))
            return
    if state.get("runtime_processing"):
        return  # Preserve the generation's observed revision until it settles.
    plan = ProgressionPlan.objects.filter(session=session, status="active").first()
    if plan is None:
        return
    if plan.input_revision != int(state.get("input_revision", 0)):
        invalidate_progression(session, state)
    else:
        elapsed = get_active_elapsed_seconds(session, state=state)
        fraction = min(1.0, max(0.0, (elapsed - plan.starts_at) / (plan.ends_at - plan.starts_at)))
        for baseline, target in zip(plan.baseline, plan.targets, strict=True):
            change = {
                **target,
                "progression_plan_id": plan.pk,
                "progression_plan_version": plan.version,
            }
            for key in ("min_value", "max_value", "min_value_diastolic", "max_value_diastolic"):
                if baseline.get(key) is not None and target.get(key) is not None:
                    change[key] = round(baseline[key] + fraction * (target[key] - baseline[key]))
            _apply_vital_change(session=session, change=change, correlation_id=None)
        if elapsed >= plan.ends_at:
            plan.status = "expired"
            plan.save(update_fields=["status"])
            state["progression"] = {
                **state.get("progression", {}),
                "status": "expired",
                "portrayal": {"behavior": "", "speech": ""},
            }
    _finalize_runtime_views(session=session, state=state)


@transaction.atomic
def resolve_decision(*, session_id, decision_id, approved, user, correlation_id=None):
    from .services import (
        _apply_problem_observation,
        _finalize_runtime_views,
        append_pending_runtime_reason,
        emit_runtime_event,
        get_runtime_state,
    )

    session = (
        TrainerSession.objects.select_for_update().select_related("simulation").get(pk=session_id)
    )
    decision = ScenarioDecision.objects.filter(session=session, pk=decision_id).first()
    if decision is None:
        raise ValidationError("Scenario decision not found.")
    desired = "approved" if approved else "rejected"
    if decision.status == desired:
        return  # Lost-response replay is safe, even after completion.
    state = get_runtime_state(session)
    if session.status not in {SessionStatus.RUNNING, SessionStatus.PAUSED}:
        raise ValidationError("This scenario cannot accept a branch decision.")
    if decision.status != "pending" or decision.input_revision != int(
        state.get("input_revision", 0)
    ):
        raise ValidationError("The scenario changed. Refresh before deciding.")
    if approved:
        from .services import _resolve_active_cause

        if (
            _resolve_active_cause(
                session=session,
                cause_kind=decision.proposal["cause_kind"],
                cause_id=decision.proposal["cause_id"],
            )
            is None
        ):
            raise ValidationError("The branch cause is no longer active. Refresh the scenario.")
        _apply_problem_observation(
            session=session, observation=decision.proposal, correlation_id=correlation_id
        )
        _refresh_patient_projection(session, correlation_id)
    decision.status = desired
    decision.decided_by = user
    decision.decided_at = timezone.now()
    decision.save(update_fields=["status", "decided_by", "decided_at"])
    emit_runtime_event(
        session=session,
        event_type="simulation.plan.updated",
        payload={
            "decision_id": decision.pk,
            "decision_status": desired,
            "proposal": decision.proposal,
        },
        created_by=user,
        correlation_id=correlation_id,
    )
    append_pending_runtime_reason(
        session=session,
        reason_kind="branch_decided",
        payload={"decision_id": decision.pk, "approved": approved},
        correlation_id=correlation_id,
    )
    session.refresh_from_db()
    state = get_runtime_state(session)
    project_decisions(session, state)
    state["branch_history"] = [
        *list(state.get("branch_history") or []),
        {"decision_id": decision.pk, "status": desired, "proposal": decision.proposal},
    ][-10:]
    _finalize_runtime_views(session=session, state=state, correlation_id=correlation_id)
