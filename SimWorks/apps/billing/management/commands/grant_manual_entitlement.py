# apps/accounts/billing/management/commands/grant_manual_entitlement.py

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Account
from apps.accounts.services import get_personal_account_for_user
from apps.billing.catalog import ProductCode, all_product_codes
from apps.billing.services.entitlements import grant_manual_product_entitlement


class Command(BaseCommand):
    help = "Grant a manual product entitlement to a user."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            required=True,
            help="Email address of the user to grant access to.",
        )
        parser.add_argument(
            "--product",
            default=ProductCode.MEDSIM_ONE.value,
            choices=all_product_codes(),
            help="Internal product code to grant. Defaults to medsim_one.",
        )
        parser.add_argument(
            "--account-id",
            type=int,
            help="Optional account ID. Defaults to the user's personal account.",
        )
        parser.add_argument(
            "--source-ref",
            default="manual-entitlement",
            help="Entitlement source_ref to record.",
        )

    def handle(self, *args, **options):
        email = options["email"].strip()
        product_code = options["product"]
        account_id = options.get("account_id")
        source_ref = options["source_ref"].strip()

        user_model = get_user_model()

        try:
            user = user_model.objects.get(email=email)
        except user_model.DoesNotExist as exc:
            raise CommandError(f'No user found with email "{email}".') from exc

        if account_id is not None:
            try:
                account = Account.objects.get(pk=account_id)
            except Account.DoesNotExist as exc:
                raise CommandError(f"No account found with ID {account_id}.") from exc
        else:
            account = get_personal_account_for_user(user)

        entitlement = grant_manual_product_entitlement(
            user=user,
            account=account,
            product_code=product_code,
            source_ref=source_ref,
        )

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
