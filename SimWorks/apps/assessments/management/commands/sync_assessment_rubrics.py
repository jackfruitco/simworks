"""Discover and sync rubric YAML seeds from project apps.

For each project app (anything whose ``AppConfig.name`` starts with
``apps.``) this command scans ``<app>/rubrics/*.yaml`` and synchronises
the rubrics + criteria into the database.

Branches per existing rubric (matched on
``slug + version + lab_type + assessment_type`` with
``scope=GLOBAL, account=None``):

- not present → create.
- exists & ``status=DRAFT``: identical checksum is a noop;
  different checksum replaces the criteria from YAML.
- exists & ``status=PUBLISHED``: identical checksum is a noop;
  different checksum raises a clear error unless
  ``--create-draft-on-change`` is set, in which case a new
  ``status=DRAFT`` rubric at ``version+1`` is created with
  ``based_on`` pointing at the previous row.
- exists & ``status=ARCHIVED``: treated like ``PUBLISHED`` (immutable).

YAML files are seed-only and always create global rubrics; the file
format does not support ``scope: account`` (account-scoped rubrics are
managed via DB/UI).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django.apps import apps as django_apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

REQUIRED_TOP_LEVEL_KEYS = {
    "slug",
    "name",
    "lab_type",
    "assessment_type",
    "version",
    "scope",
    "status",
    "criteria",
}


class Command(BaseCommand):
    help = "Sync assessment rubrics from per-app rubrics/*.yaml seed files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            help="Limit discovery to a single app label (e.g. 'chatlab').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report intended actions without writing to the DB.",
        )
        parser.add_argument(
            "--create-draft-on-change",
            action="store_true",
            help=(
                "When a published rubric YAML differs from its stored "
                "checksum, create a new draft at version+1 instead of "
                "raising an error."
            ),
        )

    def handle(self, *args, **opts):
        try:
            import yaml  # PyYAML
        except ImportError as exc:  # pragma: no cover - exercised in tests via patch
            raise CommandError(
                "PyYAML is required for sync_assessment_rubrics. "
                "Add 'pyyaml>=6.0' to pyproject.toml dependencies and run `uv sync`."
            ) from exc

        app_filter = opts.get("app")
        dry_run = opts["dry_run"]
        create_draft_on_change = opts["create_draft_on_change"]

        counts = {"created": 0, "updated": 0, "unchanged": 0, "drafted": 0}

        with transaction.atomic():
            for app_config in django_apps.get_app_configs():
                if not app_config.name.startswith("apps."):
                    continue
                if app_filter and app_config.label != app_filter:
                    continue

                rubric_dir = Path(app_config.path) / "rubrics"
                if not rubric_dir.is_dir():
                    continue

                for path in sorted(rubric_dir.glob("*.yaml")):
                    self._sync_one(
                        app_config,
                        path,
                        yaml,
                        counts,
                        create_draft_on_change=create_draft_on_change,
                    )
            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                "Done. created={created} updated={updated} unchanged={unchanged} "
                "drafted={drafted}{dry}".format(
                    dry=" (dry-run, rolled back)" if dry_run else "",
                    **counts,
                )
            )
        )

    # ------------------------------------------------------------------ helpers

    def _sync_one(
        self,
        app_config,
        path: Path,
        yaml,
        counts: dict[str, int],
        *,
        create_draft_on_change: bool,
    ) -> None:
        from apps.assessments.models import AssessmentRubric

        try:
            with path.open("rb") as fh:
                raw_bytes = fh.read()
            parsed = yaml.safe_load(raw_bytes)
        except yaml.YAMLError as exc:
            raise CommandError(f"Failed to parse {path}: {exc}") from exc

        if not isinstance(parsed, dict):
            raise CommandError(f"{path}: top-level must be a mapping, got {type(parsed).__name__}.")

        missing = REQUIRED_TOP_LEVEL_KEYS - parsed.keys()
        if missing:
            raise CommandError(f"{path}: missing required keys: {sorted(missing)}.")

        if parsed["scope"] != "global":
            raise CommandError(
                f"{path}: file-seeded rubrics must use scope='global'; "
                f"got scope={parsed['scope']!r}. Account-scoped rubrics are "
                "managed via DB/UI, not YAML."
            )

        # Compute checksum from a stable canonical dump so whitespace /
        # key-order changes don't trip the comparison.
        canonical = yaml.safe_dump(parsed, sort_keys=True, default_flow_style=False).encode("utf-8")
        checksum = hashlib.sha256(canonical).hexdigest()

        relative_path = self._relative_path(app_config, path)

        slug = parsed["slug"]
        version = int(parsed["version"])
        lab_type = parsed["lab_type"]
        assessment_type = parsed["assessment_type"]

        existing = (
            AssessmentRubric.objects.filter(
                slug=slug,
                version=version,
                lab_type=lab_type,
                assessment_type=assessment_type,
                scope=AssessmentRubric.Scope.GLOBAL,
                account__isnull=True,
            )
            .order_by("-published_at", "-id")
            .first()
        )

        if existing is None:
            self._create_rubric(
                parsed=parsed,
                checksum=checksum,
                app_label=app_config.label,
                relative_path=relative_path,
            )
            counts["created"] += 1
            self.stdout.write(self.style.SUCCESS(f"  + created {slug} v{version}"))
            return

        if existing.seed_checksum == checksum:
            counts["unchanged"] += 1
            self.stdout.write(f"  · unchanged {slug} v{version}")
            return

        if existing.status == AssessmentRubric.Status.DRAFT:
            self._replace_draft(
                rubric=existing,
                parsed=parsed,
                checksum=checksum,
                app_label=app_config.label,
                relative_path=relative_path,
            )
            counts["updated"] += 1
            self.stdout.write(self.style.WARNING(f"  ~ updated draft {slug} v{version}"))
            return

        # Existing is PUBLISHED or ARCHIVED with a differing YAML.
        if not create_draft_on_change:
            raise CommandError(
                f"Refusing to mutate {existing.status} rubric "
                f"{slug!r} v{version}; the YAML at {path} differs from "
                f"the stored seed_checksum. Re-run with "
                f"--create-draft-on-change to create a new draft version."
            )

        new_version = version + 1
        # Avoid colliding with an already-bumped draft: walk forward.
        while AssessmentRubric.objects.filter(
            slug=slug,
            version=new_version,
            lab_type=lab_type,
            assessment_type=assessment_type,
            scope=AssessmentRubric.Scope.GLOBAL,
            account__isnull=True,
        ).exists():
            new_version += 1

        # Override version + status when shipping the bumped draft.
        bumped = dict(parsed)
        bumped["version"] = new_version
        bumped["status"] = AssessmentRubric.Status.DRAFT.value
        # Recompute checksum on the bumped form so the new draft's
        # seed_checksum reflects what we actually stored.
        bumped_canonical = yaml.safe_dump(bumped, sort_keys=True, default_flow_style=False).encode(
            "utf-8"
        )
        bumped_checksum = hashlib.sha256(bumped_canonical).hexdigest()

        self._create_rubric(
            parsed=bumped,
            checksum=bumped_checksum,
            app_label=app_config.label,
            relative_path=relative_path,
            based_on=existing,
        )
        counts["drafted"] += 1
        self.stdout.write(
            self.style.WARNING(f"  ! drafted {slug} v{new_version} (based_on v{version})")
        )

    def _create_rubric(
        self,
        *,
        parsed: dict,
        checksum: str,
        app_label: str,
        relative_path: str,
        based_on=None,
    ):
        from apps.assessments.models import AssessmentRubric

        status = parsed["status"]
        rubric = AssessmentRubric(
            slug=parsed["slug"],
            name=parsed["name"],
            description=parsed.get("description", "") or "",
            scope=AssessmentRubric.Scope.GLOBAL,
            account=None,
            lab_type=parsed["lab_type"],
            assessment_type=parsed["assessment_type"],
            version=int(parsed["version"]),
            status=status,
            seed_source_app=app_label,
            seed_source_path=relative_path,
            seed_checksum=checksum,
            based_on=based_on,
        )
        # Skip the model's published_at auto-stamp until criteria exist; we
        # set status to DRAFT first, attach criteria, then publish if the
        # YAML asked for it. This avoids an immutability lockout on the
        # criterion creates.
        target_status = rubric.status
        rubric.status = AssessmentRubric.Status.DRAFT
        rubric.save()

        for raw_criterion in parsed.get("criteria") or []:
            self._create_criterion(rubric, raw_criterion)

        if target_status != AssessmentRubric.Status.DRAFT:
            rubric.status = target_status
            if rubric.status == AssessmentRubric.Status.PUBLISHED:
                rubric.published_at = timezone.now()
            rubric.save()

    def _create_criterion(self, rubric, raw: dict) -> None:
        from apps.assessments.models import AssessmentCriterion

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

    def _replace_draft(
        self,
        *,
        rubric,
        parsed: dict,
        checksum: str,
        app_label: str,
        relative_path: str,
    ) -> None:
        # Wipe existing criteria and rebuild from YAML.
        rubric.criteria.all().delete()
        for raw_criterion in parsed.get("criteria") or []:
            self._create_criterion(rubric, raw_criterion)

        rubric.name = parsed["name"]
        rubric.description = parsed.get("description", "") or ""
        rubric.seed_source_app = app_label
        rubric.seed_source_path = relative_path
        rubric.seed_checksum = checksum
        rubric.save()

    def _relative_path(self, app_config, path: Path) -> str:
        try:
            return str(path.relative_to(Path(app_config.path).parent))
        except ValueError:
            return path.name
