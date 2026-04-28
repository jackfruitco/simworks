from __future__ import annotations

import hashlib
from pathlib import Path

from django.db import migrations
from django.utils import timezone


SEED_FILES = (
    ("chatlab", "rubrics/initial_feedback_v1.yaml"),
    ("chatlab", "rubrics/continuation_feedback_v1.yaml"),
)


def _load_seed(path: Path):
    import yaml

    raw_bytes = path.read_bytes()
    parsed = yaml.safe_load(raw_bytes)
    canonical = yaml.safe_dump(parsed, sort_keys=True, default_flow_style=False).encode("utf-8")
    return parsed, hashlib.sha256(canonical).hexdigest()


def seed_chatlab_rubrics(apps, schema_editor):
    AssessmentCriterion = apps.get_model("assessments", "AssessmentCriterion")
    AssessmentRubric = apps.get_model("assessments", "AssessmentRubric")

    apps_dir = Path(__file__).resolve().parents[2]
    now = timezone.now()

    for app_label, relative_path in SEED_FILES:
        path = apps_dir / app_label / relative_path
        parsed, checksum = _load_seed(path)

        rubric, created = AssessmentRubric.objects.get_or_create(
            slug=parsed["slug"],
            version=int(parsed["version"]),
            lab_type=parsed["lab_type"],
            assessment_type=parsed["assessment_type"],
            scope="global",
            account=None,
            defaults={
                "name": parsed["name"],
                "description": parsed.get("description", "") or "",
                "status": "draft",
                "seed_source_app": app_label,
                "seed_source_path": f"{app_label}/{relative_path}",
                "seed_checksum": checksum,
            },
        )
        if not created:
            continue

        for raw in parsed.get("criteria") or []:
            AssessmentCriterion.objects.create(
                rubric=rubric,
                slug=raw["slug"],
                label=raw["label"],
                description=raw.get("description", "") or "",
                category=raw.get("category", "") or "",
                value_type=raw["value_type"],
                min_value=raw.get("min_value"),
                max_value=raw.get("max_value"),
                allowed_values=raw.get("allowed_values") or [],
                weight=raw.get("weight", 1),
                sort_order=int(raw.get("sort_order", 0)),
                required=bool(raw.get("required", True)),
                include_in_user_summary=bool(raw.get("include_in_user_summary", True)),
            )

        if parsed["status"] == "published":
            rubric.status = "published"
            rubric.published_at = now
            rubric.save(update_fields=["status", "published_at", "updated_at"])


def unseed_chatlab_rubrics(apps, schema_editor):
    AssessmentRubric = apps.get_model("assessments", "AssessmentRubric")

    for app_label, relative_path in SEED_FILES:
        AssessmentRubric.objects.filter(
            seed_source_app=app_label,
            seed_source_path=f"{app_label}/{relative_path}",
            assessments__isnull=True,
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assessments", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(seed_chatlab_rubrics, unseed_chatlab_rubrics),
    ]
