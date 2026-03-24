import getpass
import os
import secrets

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, UserRole
from apps.billing.catalog import ProductCode, all_product_codes
from apps.billing.services.entitlements import grant_manual_product_entitlement

DEFAULT_EMAIL = "demo@medsim.local"
DEFAULT_PASSWORD = os.getenv("DEMO_USER_PASSWORD", "")
DEFAULT_ROLE_NAME = "System"


class Command(BaseCommand):
    help = (
        "Create or update a demo user, ensure login is enabled, and grant a "
        "manual product entitlement."
    )

    def _write_generated_password_notice(self, password: str) -> None:
        self.stderr.write(
            self.style.WARNING(
                "Generated random password for demo user. "
                "Store it now; it will not be shown again: "
                f"{password}"
            )
        )

    def _resolve_password(self, options) -> str:
        password = (options.get("password") or "").strip()
        if password:
            return password

        env_password = DEFAULT_PASSWORD.strip()
        if env_password:
            self.stdout.write(self.style.WARNING("Using password from DEMO_USER_PASSWORD."))
            return env_password

        interactive = options.get("interactive", True)
        allow_random_password = options.get("allow_random_password", False)
        if not interactive:
            if allow_random_password:
                password = secrets.token_urlsafe(18)
                self._write_generated_password_notice(password)
                return password
            raise CommandError(
                "No password provided via --password or DEMO_USER_PASSWORD. "
                "Under --no-input, pass --allow-random-password to generate one."
            )

        provide_password = (
            input(
                "No password provided via --password or DEMO_USER_PASSWORD. "
                "Do you want to enter one now? [y/N]: "
            )
            .strip()
            .lower()
        )
        if provide_password in {"y", "yes"}:
            while True:
                entered_password = getpass.getpass("Password: ")
                confirm_password = getpass.getpass("Confirm password: ")
                if not entered_password:
                    self.stdout.write(self.style.ERROR("Password cannot be empty."))
                    continue
                if entered_password != confirm_password:
                    self.stdout.write(self.style.ERROR("Passwords do not match."))
                    continue
                return entered_password

        continue_without_manual_password = (
            input("Generate a random password instead? [Y/n]: ").strip().lower()
        )
        if continue_without_manual_password in {"", "y", "yes"}:
            password = secrets.token_urlsafe(18)
            self._write_generated_password_notice(password)
            return password

        raise CommandError(
            "Password setup aborted. Pass --password, set DEMO_USER_PASSWORD, "
            "or choose random password generation interactively."
        )

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            default=DEFAULT_EMAIL,
            help=f"Email address for the demo user. Defaults to {DEFAULT_EMAIL}.",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=("Password for the demo user. Falls back to DEMO_USER_PASSWORD when set."),
        )
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_false",
            dest="interactive",
            default=True,
            help=(
                "Do not prompt for input. Requires --password, DEMO_USER_PASSWORD, "
                "or --allow-random-password."
            ),
        )
        parser.add_argument(
            "--allow-random-password",
            action="store_true",
            default=False,
            help=(
                "Allow random password generation when no password is provided. "
                "Required with --no-input."
            ),
        )
        parser.add_argument(
            "--product",
            default=ProductCode.MEDSIM_ONE.value,
            choices=all_product_codes(),
            help="Internal product code to grant. Defaults to medsim_one.",
        )
        parser.add_argument(
            "--role",
            default=DEFAULT_ROLE_NAME,
            help=f'UserRole name to assign. Defaults to "{DEFAULT_ROLE_NAME}".',
        )
        parser.add_argument(
            "--first-name",
            default="Demo",
            help='First name for the user. Defaults to "Demo".',
        )
        parser.add_argument(
            "--last-name",
            default="User",
            help='Last name for the user. Defaults to "User".',
        )
        parser.add_argument(
            "--staff",
            action="store_true",
            default=True,
            help="Mark the user as staff. Enabled by default.",
        )
        parser.add_argument(
            "--no-staff",
            action="store_false",
            dest="staff",
            help="Do not mark the user as staff.",
        )
        parser.add_argument(
            "--superuser",
            action="store_true",
            default=False,
            help="Also mark the user as a superuser. Off by default.",
        )
        parser.add_argument(
            "--source-ref",
            default="manual-entitlement",
            help='Entitlement source_ref to record. Defaults to "manual-entitlement".',
        )

    def handle(self, *args, **options):
        from apps.accounts.services import get_personal_account_for_user

        email = options["email"].strip().lower()
        password = self._resolve_password(options)
        product_code = options["product"]
        role_name = options["role"].strip()
        first_name = options["first_name"].strip()
        last_name = options["last_name"].strip()
        is_staff = options["staff"]
        is_superuser = options["superuser"]
        source_ref = options["source_ref"].strip()

        try:
            role = UserRole.objects.get(name=role_name)
        except UserRole.DoesNotExist as exc:
            raise CommandError(
                f'No UserRole found with name "{role_name}". Create it first.'
            ) from exc

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
                "role": role,
            },
        )

        updated_fields: list[str] = []

        if not created:
            if user.first_name != first_name:
                user.first_name = first_name
                updated_fields.append("first_name")
            if user.last_name != last_name:
                user.last_name = last_name
                updated_fields.append("last_name")
            if user.role_id != role.id:
                user.role = role
                updated_fields.append("role")
            if user.is_active is not True:
                user.is_active = True
                updated_fields.append("is_active")
            if user.is_staff != is_staff:
                user.is_staff = is_staff
                updated_fields.append("is_staff")
            if user.is_superuser != is_superuser:
                user.is_superuser = is_superuser
                updated_fields.append("is_superuser")

        user.set_password(password)
        updated_fields.append("password")

        # save() instead of update_fields if role/password hashing/custom model save
        # logic makes partial updates brittle.
        user.save()

        EmailAddress.objects.update_or_create(
            user=user,
            email=user.email,
            defaults={
                "verified": True,
                "primary": True,
            },
        )
        EmailAddress.objects.filter(user=user).exclude(email=user.email).update(primary=False)

        account = get_personal_account_for_user(user)
        entitlement = grant_manual_product_entitlement(
            user=user,
            account=account,
            product_code=product_code,
            source_ref=source_ref,
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created demo user: {email}"))
        else:
            self.stdout.write(self.style.WARNING(f"Updated existing user: {email}"))

        self.stdout.write(
            self.style.SUCCESS(
                "Granted manual entitlement: "
                f"user={user.email} "
                f"account_id={account.id} "
                f"product={entitlement.product_code} "
                f"scope={entitlement.scope_type} "
                f"portable={entitlement.portable_across_accounts} "
                f"source_ref={entitlement.source_ref}"
            )
        )
