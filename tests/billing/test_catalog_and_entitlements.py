from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone
import pytest

from apps.accounts.models import AccountMembership, UserRole
from apps.accounts.services import create_organization_account, get_personal_account_for_user
from apps.billing.catalog import (
    ProductCode,
    all_product_codes,
    product_code_from_apple_product_id,
    product_code_from_stripe_plan_code,
    product_codes_for_lab,
    product_includes_lab,
)
from apps.billing.forms import EntitlementAdminForm
from apps.billing.models import Entitlement, SeatAllocation, SeatAssignment
from apps.billing.services.entitlements import (
    get_access_snapshot,
    grant_demo_product_access,
    has_product_access,
)


@pytest.fixture
def user_role(db):
    return UserRole.objects.create(title="Billing Test Role")


@pytest.fixture
def owner_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        email="billing-owner@example.com",
        password="pass12345",
        role=user_role,
    )


@pytest.fixture
def other_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        email="billing-other@example.com",
        password="pass12345",
        role=user_role,
    )


@pytest.mark.django_db
def test_provider_catalog_maps_to_internal_product_codes():
    assert (
        product_code_from_apple_product_id("com.jackfruitco.medsim.individual.plus.monthly")
        == ProductCode.CHATLAB_PLUS.value
    )
    assert (
        product_code_from_stripe_plan_code("price_trainerlab_plus_monthly")
        == ProductCode.TRAINERLAB_PLUS.value
    )


@pytest.mark.django_db
def test_catalog_exposes_lab_capabilities():
    assert product_includes_lab(ProductCode.TRAINERLAB_GO.value, "trainerlab") is True
    assert product_includes_lab(ProductCode.TRAINERLAB_PLUS.value, "trainerlab") is True
    assert product_includes_lab(ProductCode.MEDSIM_ONE.value, "trainerlab") is True
    assert product_includes_lab(ProductCode.MEDSIM_ONE_PLUS.value, "trainerlab") is True
    assert product_includes_lab(ProductCode.CHATLAB_GO.value, "trainerlab") is False
    assert product_codes_for_lab("trainerlab") == (
        ProductCode.TRAINERLAB_GO.value,
        ProductCode.TRAINERLAB_PLUS.value,
        ProductCode.MEDSIM_ONE.value,
        ProductCode.MEDSIM_ONE_PLUS.value,
    )


@pytest.mark.django_db
def test_valid_base_manual_entitlement_grants_access_and_snapshot(owner_user):
    personal_account = get_personal_account_for_user(owner_user)

    Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:chatlab-go",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=owner_user,
        product_code=ProductCode.CHATLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )

    assert has_product_access(owner_user, personal_account, ProductCode.CHATLAB_GO.value) is True
    assert get_access_snapshot(owner_user, personal_account)["products"] == {
        ProductCode.CHATLAB_GO.value: {"enabled": True, "features": [], "limits": {}}
    }


@pytest.mark.django_db
def test_invalid_product_code_is_rejected(owner_user):
    personal_account = get_personal_account_for_user(owner_user)

    with pytest.raises(ValidationError):
        Entitlement.objects.create(
            account=personal_account,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref="manual:invalid",
            scope_type=Entitlement.ScopeType.USER,
            subject_user=owner_user,
            product_code="trainerlab",
            status=Entitlement.Status.ACTIVE,
            portable_across_accounts=True,
        )


@pytest.mark.django_db
def test_feature_and_limit_grants_are_rejected(owner_user):
    personal_account = get_personal_account_for_user(owner_user)

    with pytest.raises(ValidationError):
        Entitlement.objects.create(
            account=personal_account,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref="manual:feature",
            scope_type=Entitlement.ScopeType.USER,
            subject_user=owner_user,
            product_code=ProductCode.CHATLAB_GO.value,
            feature_code="exports",
            status=Entitlement.Status.ACTIVE,
            portable_across_accounts=True,
        )

    with pytest.raises(ValidationError):
        Entitlement.objects.create(
            account=personal_account,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref="manual:limit",
            scope_type=Entitlement.ScopeType.USER,
            subject_user=owner_user,
            product_code=ProductCode.CHATLAB_GO.value,
            limit_code="monthly_runs",
            limit_value=10,
            status=Entitlement.Status.ACTIVE,
            portable_across_accounts=True,
        )


@pytest.mark.django_db
def test_personal_account_owner_gets_automatic_seat(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab-go",
        scope_type=Entitlement.ScopeType.ACCOUNT,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
    )
    SeatAllocation.objects.create(
        account=personal_account,
        product_code=ProductCode.TRAINERLAB_GO.value,
        seat_limit=1,
        effective_from=timezone.now(),
    )

    assert has_product_access(owner_user, personal_account, ProductCode.TRAINERLAB_GO.value) is True


@pytest.mark.django_db
def test_personal_account_non_owner_does_not_get_automatic_seat(owner_user, other_user):
    personal_account = get_personal_account_for_user(owner_user)
    AccountMembership.objects.create(
        account=personal_account,
        user=other_user,
        invite_email=other_user.email,
        role=AccountMembership.Role.GENERAL_USER,
        status=AccountMembership.Status.ACTIVE,
    )
    Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab-go",
        scope_type=Entitlement.ScopeType.ACCOUNT,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
    )
    SeatAllocation.objects.create(
        account=personal_account,
        product_code=ProductCode.TRAINERLAB_GO.value,
        seat_limit=1,
        effective_from=timezone.now(),
    )

    assert (
        has_product_access(other_user, personal_account, ProductCode.TRAINERLAB_GO.value) is False
    )


@pytest.mark.django_db
def test_team_account_still_requires_normal_seat_assignment(owner_user):
    org_account = create_organization_account(name="Seat Team", owner_user=owner_user)
    Entitlement.objects.create(
        account=org_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab-plus",
        scope_type=Entitlement.ScopeType.ACCOUNT,
        product_code=ProductCode.TRAINERLAB_PLUS.value,
        status=Entitlement.Status.ACTIVE,
    )
    SeatAllocation.objects.create(
        account=org_account,
        product_code=ProductCode.TRAINERLAB_PLUS.value,
        seat_limit=1,
        effective_from=timezone.now(),
    )

    assert has_product_access(owner_user, org_account, ProductCode.TRAINERLAB_PLUS.value) is False

    SeatAssignment.objects.create(
        account=org_account,
        user=owner_user,
        product_code=ProductCode.TRAINERLAB_PLUS.value,
        assigned_by=owner_user,
    )

    assert has_product_access(owner_user, org_account, ProductCode.TRAINERLAB_PLUS.value) is True


@pytest.mark.django_db
def test_grant_demo_product_access_creates_valid_base_entitlement(owner_user):
    personal_account = get_personal_account_for_user(owner_user)

    entitlement = grant_demo_product_access(
        owner_user,
        personal_account,
        ProductCode.CHATLAB_PLUS.value,
        source_ref="demo:chatlab-plus",
    )

    assert entitlement.product_code == ProductCode.CHATLAB_PLUS.value
    assert entitlement.feature_code == ""
    assert entitlement.limit_code == ""
    assert entitlement.limit_value is None
    assert entitlement.scope_type == Entitlement.ScopeType.USER
    assert entitlement.subject_user_id == owner_user.id
    assert entitlement.portable_across_accounts is True


@pytest.mark.django_db
def test_entitlement_admin_form_uses_catalog_choices_and_rejects_feature_limit_data(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    form = EntitlementAdminForm(
        data={
            "account": personal_account.pk,
            "source_type": Entitlement.SourceType.MANUAL,
            "source_ref": "manual:admin",
            "scope_type": Entitlement.ScopeType.USER,
            "subject_user": owner_user.pk,
            "product_code": ProductCode.MEDSIM_ONE.value,
            "feature_code": "",
            "limit_code": "",
            "limit_value": "",
            "status": Entitlement.Status.ACTIVE,
            "portable_across_accounts": "on",
            "starts_at": "",
            "ends_at": "",
            "metadata": "{}",
        }
    )

    assert {code for code, _label in form.fields["product_code"].choices} == set(
        all_product_codes()
    )
    assert form.is_valid() is True

    invalid_form = EntitlementAdminForm(
        data={
            "account": personal_account.pk,
            "source_type": Entitlement.SourceType.MANUAL,
            "source_ref": "manual:admin-feature",
            "scope_type": Entitlement.ScopeType.USER,
            "subject_user": owner_user.pk,
            "product_code": ProductCode.MEDSIM_ONE.value,
            "feature_code": "exports",
            "limit_code": "",
            "limit_value": "",
            "status": Entitlement.Status.ACTIVE,
            "portable_across_accounts": "on",
            "starts_at": "",
            "ends_at": "",
            "metadata": "{}",
        }
    )

    assert invalid_form.is_valid() is False
