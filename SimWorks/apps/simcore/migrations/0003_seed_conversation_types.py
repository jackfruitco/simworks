# Data migration: seed ConversationType rows and Stitch bot user,
# then backfill Conversation + Message.conversation for existing data.

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

STITCH_BOT_EMAIL = "stitch@simworks.local"


def seed_conversation_types(apps, schema_editor):
    ConversationType = apps.get_model("simcore", "ConversationType")
    for ct_data in CONVERSATION_TYPES:
        is_active = ct_data.pop("is_active", True)
        ConversationType.objects.get_or_create(
            slug=ct_data["slug"],
            defaults={**ct_data, "is_active": is_active},
        )


def create_stitch_bot_user(apps, schema_editor):
    """Create a dedicated bot User for Stitch AI messages."""
    User = apps.get_model("accounts", "User")
    UserRole = apps.get_model("accounts", "UserRole")

    stitch_role, _ = UserRole.objects.get_or_create(title="Bot")

    User.objects.get_or_create(
        email=STITCH_BOT_EMAIL,
        defaults={
            "first_name": "Stitch",
            "last_name": "Bot",
            "is_active": False,  # Cannot log in
            "role": stitch_role,
        },
    )


def backfill_conversations(apps, schema_editor):
    """For every legacy Simulation, ensure a patient Conversation exists,
    then link any existing conversation-less messages to it."""
    Simulation = apps.get_model("simcore", "Simulation")
    Conversation = apps.get_model("simcore", "Conversation")
    ConversationType = apps.get_model("simcore", "ConversationType")
    Message = apps.get_model("chatlab", "Message")

    patient_type = ConversationType.objects.get(slug="simulated_patient")

    # Ensure every existing simulation has a default patient conversation,
    # even if it currently has zero messages.
    for sim in Simulation.objects.all().iterator():

        conv, _ = Conversation.objects.get_or_create(
            simulation_id=sim.id,
            conversation_type=patient_type,
            defaults={
                "display_name": sim.sim_patient_display_name or "Patient",
            },
        )

        # Bulk update messages for this simulation
        Message.objects.filter(
            simulation_id=sim.id,
            conversation__isnull=True,
        ).update(conversation=conv)


def reverse_seed(apps, schema_editor):
    ConversationType = apps.get_model("simcore", "ConversationType")
    slugs = [ct["slug"] for ct in CONVERSATION_TYPES]
    ConversationType.objects.filter(slug__in=slugs).delete()


def reverse_bot_user(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(email=STITCH_BOT_EMAIL).delete()


def reverse_backfill(apps, schema_editor):
    Message = apps.get_model("chatlab", "Message")
    Conversation = apps.get_model("simcore", "Conversation")
    Message.objects.all().update(conversation=None)
    Conversation.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("simcore", "0002_conversation_models"),
        ("chatlab", "0003_message_conversation"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_conversation_types, reverse_seed),
        migrations.RunPython(create_stitch_bot_user, reverse_bot_user),
        migrations.RunPython(backfill_conversations, reverse_backfill),
    ]
