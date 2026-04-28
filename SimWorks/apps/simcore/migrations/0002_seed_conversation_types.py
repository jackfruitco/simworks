"""Seed ConversationType rows.

Re-emits the seed data that previously lived in
``simcore/0003_seed_conversation_types.py`` and was lost to
reset_migrations during the assessments refactor. Only the
ConversationType seed remains here — the Stitch user and the
conversation backfill from the original migration are now handled
by ``apps/accounts/management/commands/seed_roles.py`` (post-migrate)
and are not needed on a fresh DB.
"""

from django.db import migrations

CONVERSATION_TYPES = [
    {
        "slug": "simulated_patient",
        "display_name": "Simulated Patient",
        "description": "Primary patient conversation during a simulation.",
        "icon": "mdi:account",
        "ai_persona": "patient",
        "locks_with_simulation": True,
        "available_in": ["chatlab"],
        "sort_order": 0,
    },
    {
        "slug": "simulated_feedback",
        "display_name": "Simulation Feedback",
        "description": "Post-simulation debrief with the Stitch facilitator.",
        "icon": "mdi:robot",
        "ai_persona": "stitch",
        "locks_with_simulation": False,
        "available_in": ["chatlab"],
        "sort_order": 10,
    },
    {
        "slug": "simulated_progress_feedback",
        "display_name": "Progress Feedback",
        "description": "Cumulative progress review across multiple simulations.",
        "icon": "mdi:chart-line",
        "ai_persona": "stitch",
        "locks_with_simulation": False,
        "available_in": ["chatlab"],
        "sort_order": 20,
    },
    {
        "slug": "simulation_engine",
        "display_name": "Simulation Engine",
        "description": "Trainer conversation with the simulation engine.",
        "icon": "mdi:cog",
        "ai_persona": "stitch",
        "locks_with_simulation": True,
        "available_in": ["trainerlab"],
        "sort_order": 30,
    },
    {
        "slug": "simulated_coach",
        "display_name": "Simulated Coach",
        "description": "AI coaching persona for cumulative feedback over time.",
        "icon": "mdi:school",
        "ai_persona": "stitch",
        "locks_with_simulation": False,
        "available_in": [],
        "is_active": False,
        "sort_order": 40,
    },
]


def seed_conversation_types(apps, schema_editor):
    ConversationType = apps.get_model("simcore", "ConversationType")
    for data in CONVERSATION_TYPES:
        ct_data = dict(data)
        is_active = ct_data.pop("is_active", True)
        ConversationType.objects.get_or_create(
            slug=ct_data["slug"],
            defaults={**ct_data, "is_active": is_active},
        )


def reverse_seed(apps, schema_editor):
    ConversationType = apps.get_model("simcore", "ConversationType")
    slugs = [ct["slug"] for ct in CONVERSATION_TYPES]
    ConversationType.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("simcore", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_conversation_types, reverse_seed),
    ]
