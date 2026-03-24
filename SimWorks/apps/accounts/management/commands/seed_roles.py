from django.core.management.base import BaseCommand

SYSTEM_USERS = [
    {
        "role_title": "Sim",
        "email": "stitch@simworks.local",
        "first_name": "Stitch",
        "last_name": "Sim",
    },
    {
        "role_title": "System",
        "email": "system@medsim.local",
        "first_name": "System",
        "last_name": "",
    },
]

LEARNER_ROLES = [
    "EMT (NREMT-B)",
    "Paramedic (NRP)",
    "Military Medic",
    "SOF Medic",
    "RN",
    "RN, BSN",
    "Physician",
]


class Command(BaseCommand):
    help = "Seed default UserRoles and inactive system users; idempotent (skips existing records)."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        from apps.accounts.models import UserRole

        User = get_user_model()

        # System roles + users (always created)
        for entry in SYSTEM_USERS:
            role, role_created = UserRole.objects.get_or_create(title=entry["role_title"])
            user, user_created = User.objects.get_or_create(
                email=entry["email"],
                defaults={
                    "first_name": entry["first_name"],
                    "last_name": entry.get("last_name", ""),
                    "is_active": False,
                    "role": role,
                },
            )
            if role_created:
                self.stdout.write(self.style.SUCCESS(f"  Created role: {role.title}"))
            if user_created:
                self.stdout.write(self.style.SUCCESS(f"  Created system user: {user.email}"))

        # Learner roles (no associated system user)
        for title in LEARNER_ROLES:
            role, created = UserRole.objects.get_or_create(title=title)
            if created:
                self.stdout.write(self.style.SUCCESS(f"  Created role: {role.title}"))
