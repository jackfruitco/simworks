"""Tests for the ``sync_assessment_rubrics`` management command."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest

pytestmark = pytest.mark.django_db


CHATLAB_RUBRICS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "SimWorks" / "apps" / "chatlab" / "rubrics"
)


def _run(**kwargs):
    out = StringIO()
    call_command("sync_assessment_rubrics", stdout=out, **kwargs)
    return out.getvalue()


def test_command_creates_rubric_from_chatlab_yaml():
    from apps.assessments.models import AssessmentCriterion, AssessmentRubric

    output = _run(app="chatlab")

    assert "created chatlab_initial_feedback v1" in output
    rubric = AssessmentRubric.objects.get(slug="chatlab_initial_feedback")
    assert rubric.version == 1
    assert rubric.status == AssessmentRubric.Status.PUBLISHED
    assert rubric.lab_type == "chatlab"
    assert rubric.assessment_type == "initial_feedback"
    criteria = list(rubric.criteria.order_by("sort_order"))
    assert [c.slug for c in criteria] == [
        "correct_diagnosis",
        "correct_treatment_plan",
        "patient_experience",
    ]
    assert criteria[0].value_type == AssessmentCriterion.ValueType.BOOL
    assert criteria[1].value_type == AssessmentCriterion.ValueType.BOOL
    assert criteria[2].value_type == AssessmentCriterion.ValueType.INT
    assert criteria[2].min_value == 0
    assert criteria[2].max_value == 5


def test_published_at_set_when_status_published():
    from apps.assessments.models import AssessmentRubric

    _run(app="chatlab")
    rubric = AssessmentRubric.objects.get(slug="chatlab_initial_feedback")
    assert rubric.published_at is not None


def test_seed_metadata_recorded():
    from apps.assessments.models import AssessmentRubric

    _run(app="chatlab")
    rubric = AssessmentRubric.objects.get(slug="chatlab_initial_feedback")
    assert rubric.seed_source_app == "chatlab"
    assert rubric.seed_source_path.endswith("initial_feedback_v1.yaml")
    assert len(rubric.seed_checksum) == 64
    assert all(c in "0123456789abcdef" for c in rubric.seed_checksum)


def test_rerun_unchanged_is_noop():
    from apps.assessments.models import AssessmentRubric

    _run(app="chatlab")
    output = _run(app="chatlab")
    assert "unchanged chatlab_initial_feedback v1" in output
    assert AssessmentRubric.objects.filter(slug="chatlab_initial_feedback").count() == 1


def test_dry_run_makes_no_changes():
    from apps.assessments.models import AssessmentRubric

    output = _run(app="chatlab", dry_run=True)
    assert "(dry-run, rolled back)" in output
    assert not AssessmentRubric.objects.filter(slug="chatlab_initial_feedback").exists()


def test_app_filter_skips_other_apps():
    """--app flag limits discovery to that app's rubrics directory."""
    from apps.assessments.models import AssessmentRubric

    # Run with a non-existent app label → no rubrics should be created
    # even though chatlab/rubrics exists.
    _run(app="nonexistent")
    assert not AssessmentRubric.objects.exists()


def test_published_yaml_change_fails_loudly(tmp_path, monkeypatch):
    """Pre-create a published rubric with a different checksum, then run sync."""
    from apps.assessments.models import AssessmentRubric

    AssessmentRubric.objects.create(
        slug="chatlab_initial_feedback",
        name="ChatLab Initial Feedback",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="initial_feedback",
        version=1,
        status=AssessmentRubric.Status.PUBLISHED,
        seed_checksum="deadbeef" * 8,  # 64 chars, deliberately wrong
    )

    with pytest.raises(CommandError, match="differs from"):
        _run(app="chatlab")


def test_published_change_with_create_draft_flag_creates_new_version():
    from apps.assessments.models import AssessmentRubric

    AssessmentRubric.objects.create(
        slug="chatlab_initial_feedback",
        name="ChatLab Initial Feedback",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="initial_feedback",
        version=1,
        status=AssessmentRubric.Status.PUBLISHED,
        seed_checksum="deadbeef" * 8,
    )

    output = _run(app="chatlab", create_draft_on_change=True)
    assert "drafted chatlab_initial_feedback v2" in output

    rows = AssessmentRubric.objects.filter(slug="chatlab_initial_feedback").order_by("version")
    assert [(r.version, r.status) for r in rows] == [
        (1, AssessmentRubric.Status.PUBLISHED),
        (2, AssessmentRubric.Status.DRAFT),
    ]
    assert rows[1].based_on_id == rows[0].id


def test_draft_yaml_change_replaces_criteria(tmp_path):
    """Pre-create a DRAFT rubric with stale criteria; sync should overwrite."""
    from apps.assessments.models import AssessmentCriterion, AssessmentRubric

    draft = AssessmentRubric.objects.create(
        slug="chatlab_initial_feedback",
        name="Old Name",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="initial_feedback",
        version=1,
        status=AssessmentRubric.Status.DRAFT,
        seed_checksum="oldcheck" * 8,
    )
    AssessmentCriterion.objects.create(
        rubric=draft,
        slug="stale_criterion",
        label="Stale",
        value_type=AssessmentCriterion.ValueType.TEXT,
    )

    output = _run(app="chatlab")
    assert "updated draft chatlab_initial_feedback v1" in output

    draft.refresh_from_db()
    assert draft.name == "ChatLab Initial Feedback"
    assert sorted(c.slug for c in draft.criteria.all()) == [
        "correct_diagnosis",
        "correct_treatment_plan",
        "patient_experience",
    ]


def test_pyyaml_missing_raises_clear_error():
    """If PyYAML is unavailable, the command must error with install hint."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated missing pyyaml")
        return real_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        pytest.raises(CommandError, match="PyYAML is required"),
    ):
        _run(app="chatlab")


def test_account_scope_in_yaml_rejected(tmp_path, monkeypatch):
    """Verify the file-seed scope guard."""

    bad_yaml = tmp_path / "rubrics"
    bad_yaml.mkdir()
    (bad_yaml / "bad.yaml").write_text(
        "slug: bad\n"
        "name: Bad\n"
        "scope: account\n"
        "lab_type: chatlab\n"
        "assessment_type: initial_feedback\n"
        "version: 1\n"
        "status: draft\n"
        "criteria: []\n"
    )

    fake_app = type(
        "FakeApp",
        (),
        {
            "name": "apps.fakelab",
            "label": "fakelab",
            "path": str(tmp_path),
        },
    )()

    from django.apps import apps as django_apps

    real_get_app_configs = django_apps.get_app_configs

    def patched():
        return [*real_get_app_configs(), fake_app]

    monkeypatch.setattr(django_apps, "get_app_configs", patched)
    with pytest.raises(CommandError, match="scope='global'"):
        _run(app="fakelab")


def test_missing_required_field_raises(tmp_path, monkeypatch):
    bad_dir = tmp_path / "rubrics"
    bad_dir.mkdir()
    (bad_dir / "bad.yaml").write_text(
        "slug: bad\nname: Bad\nscope: global\n"
        # missing lab_type, assessment_type, version, status, criteria
    )
    fake_app = type(
        "FakeApp",
        (),
        {
            "name": "apps.fakelab",
            "label": "fakelab",
            "path": str(tmp_path),
        },
    )()

    from django.apps import apps as django_apps

    real_get_app_configs = django_apps.get_app_configs

    def patched():
        return [*real_get_app_configs(), fake_app]

    monkeypatch.setattr(django_apps, "get_app_configs", patched)
    with pytest.raises(CommandError, match="missing required keys"):
        _run(app="fakelab")
