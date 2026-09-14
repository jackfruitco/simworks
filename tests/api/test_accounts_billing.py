from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, override_settings
from django.utils import timezone
import pytest

from api.v1.auth import create_access_token
from apps.accounts.models import AccountMembership, UserRole
from apps.accounts.services import create_organization_account, get_personal_account_for_user
from apps.billing.catalog import ProductCode
from apps.billing.models import (
    BillingAccount,
    Entitlement,
    ProviderType,
    Subscription,
    WebhookEvent,
)
from apps.billing.providers.stripe import process_stripe_webhook
from apps.billing.services.entitlements import has_product_access


@pytest.fixture
def user_role(db):
    return UserRole.objects.create(title="Accounts Foundation Role")


@pytest.fixture
def auth_client_factory():
    def factory(user):
        client = Client()
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {create_access_token(user)}"
        return client

    return factory


def _stripe_signature(payload_bytes: bytes, secret: str = "test-stripe-webhook-secret") -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload_bytes.decode('utf-8')}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


@pytest.fixture
def owner_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        email="owner@example.com",
        password="pass12345",
        role=user_role,
    )


@pytest.fixture
def member_user(django_user_model, user_role):
    return django_user_model.objects.create_user(
        email="member@example.com",
        password="pass12345",
        role=user_role,
    )


@pytest.mark.django_db
def test_user_gets_personal_account_and_active_account(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    owner_user.refresh_from_db()

    membership = AccountMembership.objects.get(account=personal_account, user=owner_user)

    assert personal_account.owner_user_id == owner_user.id
    assert owner_user.active_account_id == personal_account.id
    assert membership.status == AccountMembership.Status.ACTIVE
    assert membership.role == AccountMembership.Role.ORG_ADMIN


@pytest.mark.django_db
def test_accounts_api_lists_selects_and_returns_access_snapshot(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    list_response = client.get("/api/v1/accounts/")
    assert list_response.status_code == 200
    accounts = list_response.json()
    assert len(accounts) == 1
    assert accounts[0]["account_type"] == "personal"
    assert accounts[0]["is_active_context"] is True

    create_response = client.post(
        "/api/v1/accounts/organizations/",
        data={"name": "Field Team", "requires_join_approval": True},
        content_type="application/json",
    )
    assert create_response.status_code == 201
    org_account = create_response.json()
    assert org_account["account_type"] == "organization"
    assert org_account["requires_join_approval"] is True

    select_response = client.post(
        "/api/v1/accounts/select/",
        data={"account_uuid": org_account["uuid"]},
        content_type="application/json",
    )
    assert select_response.status_code == 200
    assert select_response.json()["is_active_context"] is True

    access_response = client.get(
        "/api/v1/accounts/me/access/",
        HTTP_X_ACCOUNT_UUID=org_account["uuid"],
    )
    assert access_response.status_code == 200
    access = access_response.json()
    assert access["account_uuid"] == org_account["uuid"]
    assert access["account_type"] == "organization"
    assert access["products"] == {}


@pytest.mark.django_db
def test_accounts_access_snapshot_rejects_malformed_account_uuid(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    response = client.get(
        "/api/v1/accounts/me/access/",
        HTTP_X_ACCOUNT_UUID="not-a-uuid",
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Account access denied"


@pytest.mark.django_db
def test_membership_invite_and_approve_flow(owner_user, member_user, auth_client_factory):
    client = auth_client_factory(owner_user)
    org_account = create_organization_account(name="Org Alpha", owner_user=owner_user)

    invite_response = client.post(
        "/api/v1/accounts/memberships/invite/",
        data={"email": member_user.email, "role": "general_user"},
        content_type="application/json",
        HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
    )
    assert invite_response.status_code == 201
    membership = invite_response.json()
    assert membership["status"] == "pending"
    assert membership["invite_email"] == member_user.email

    approve_response = client.post(
        f"/api/v1/accounts/memberships/{membership['uuid']}/approve/",
        HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["status"] == "active"
    assert approved["user_id"] == member_user.id

    list_response = client.get(
        "/api/v1/accounts/memberships/",
        HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
    )
    assert list_response.status_code == 200
    listed = list_response.json()
    assert {item["status"] for item in listed} == {"active"}
    assert {item["user_id"] for item in listed} == {owner_user.id, member_user.id}


@pytest.mark.django_db
def test_account_scoped_simulation_listing_respects_org_roles(
    owner_user,
    member_user,
    auth_client_factory,
):
    from apps.simcore.models import Simulation

    org_account = create_organization_account(name="Org Bravo", owner_user=owner_user)
    AccountMembership.objects.create(
        account=org_account,
        user=member_user,
        invite_email=member_user.email,
        role=AccountMembership.Role.GENERAL_USER,
        status=AccountMembership.Status.ACTIVE,
    )

    # Grant ChatLab access so the entitlement gate does not block the request.
    for user in (owner_user, member_user):
        personal = get_personal_account_for_user(user)
        Entitlement.objects.create(
            account=personal,
            source_type=Entitlement.SourceType.MANUAL,
            source_ref="manual:chatlab-go",
            scope_type=Entitlement.ScopeType.USER,
            subject_user=user,
            product_code=ProductCode.CHATLAB_GO.value,
            status=Entitlement.Status.ACTIVE,
            portable_across_accounts=True,
        )

    admin_sim = Simulation.objects.create(
        user=owner_user, account=org_account, sim_patient_full_name="Admin"
    )
    member_sim = Simulation.objects.create(
        user=member_user, account=org_account, sim_patient_full_name="Member"
    )
    from apps.chatlab.models import ChatSession

    ChatSession.objects.create(simulation=admin_sim)
    ChatSession.objects.create(simulation=member_sim)

    admin_client = auth_client_factory(owner_user)
    member_client = auth_client_factory(member_user)

    admin_response = admin_client.get(
        "/api/v1/simulations/",
        HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
    )
    assert admin_response.status_code == 200
    admin_ids = {item["id"] for item in admin_response.json()["items"]}
    assert admin_ids == {admin_sim.id, member_sim.id}

    member_response = member_client.get(
        "/api/v1/simulations/",
        HTTP_X_ACCOUNT_UUID=str(org_account.uuid),
    )
    assert member_response.status_code == 200
    member_ids = {item["id"] for item in member_response.json()["items"]}
    assert member_ids == {member_sim.id}


@pytest.mark.django_db
def test_portable_personal_entitlements_union_with_org_access(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    org_account = create_organization_account(name="Org Entitlements", owner_user=owner_user)

    Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:chatlab",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=owner_user,
        product_code=ProductCode.CHATLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )
    Entitlement.objects.create(
        account=org_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:trainerlab",
        scope_type=Entitlement.ScopeType.ACCOUNT,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
    )

    assert has_product_access(owner_user, org_account, ProductCode.CHATLAB_GO.value) is True
    assert has_product_access(owner_user, org_account, ProductCode.TRAINERLAB_GO.value) is True


@pytest.mark.django_db
def test_apple_sync_endpoint_is_idempotent(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    payload = {
        "transaction_id": "txn-123",
        "original_transaction_id": "orig-123",
        "product_id": "com.jackfruitco.medsim.individual.plus.monthly",
        "status": "active",
    }
    first = client.post(
        "/api/v1/billing/apple/sync/",
        data=payload,
        content_type="application/json",
    )
    first_entitlement_count = Entitlement.objects.filter(
        source_type=Entitlement.SourceType.SUBSCRIPTION
    ).count()
    second = client.post(
        "/api/v1/billing/apple/sync/",
        data=payload,
        content_type="application/json",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert Subscription.objects.filter(provider_type="apple").count() == 1
    subscription = Subscription.objects.get(provider_type="apple")
    assert subscription.plan_code == "com.jackfruitco.medsim.individual.plus.monthly"
    second_entitlement_count = Entitlement.objects.filter(
        source_type=Entitlement.SourceType.SUBSCRIPTION
    ).count()
    assert first_entitlement_count > 0
    assert second_entitlement_count == first_entitlement_count
    assert Entitlement.objects.filter(
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        product_code=ProductCode.CHATLAB_PLUS.value,
    ).exists()


@pytest.mark.django_db
def test_access_snapshot_endpoint_ignores_malformed_entitlements(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:good",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=owner_user,
        product_code=ProductCode.CHATLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )
    malformed = Entitlement.objects.create(
        account=personal_account,
        source_type=Entitlement.SourceType.MANUAL,
        source_ref="manual:bad",
        scope_type=Entitlement.ScopeType.USER,
        subject_user=owner_user,
        product_code=ProductCode.TRAINERLAB_GO.value,
        status=Entitlement.Status.ACTIVE,
        portable_across_accounts=True,
    )
    Entitlement.objects.filter(pk=malformed.pk).update(product_code="stripe:legacy-price-id")

    client = auth_client_factory(owner_user)
    response = client.get("/api/v1/accounts/me/access/")

    assert response.status_code == 200
    assert response.json()["products"] == {
        ProductCode.CHATLAB_GO.value: {"enabled": True, "features": {}, "limits": {}}
    }


@pytest.mark.django_db
def test_stripe_webhook_rejects_invalid_signature():
    client = Client()
    response = client.post(
        "/api/v1/billing/stripe/webhook/",
        data='{"id": "evt_test", "object": "event", "type": "customer.subscription.created"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=123,v1=bad",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_stripe_checkout_disabled_returns_404(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    response = client.post(
        "/api/v1/billing/stripe/checkout-session/",
        data={
            "product_code": ProductCode.MEDSIM_ONE.value,
            "billing_interval": "monthly",
            "success_url": "https://medsim.example/billing/success/",
            "cancel_url": "https://medsim.example/billing/",
        },
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"},
)
def test_stripe_checkout_rejects_invalid_product(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    response = client.post(
        "/api/v1/billing/stripe/checkout-session/",
        data={
            "product_code": "enterprise",
            "billing_interval": "monthly",
            "success_url": "https://medsim.example/billing/success/",
            "cancel_url": "https://medsim.example/billing/",
        },
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"},
    BILLING_STRIPE_PROMO_COUPON_MAP={"medsim_one:monthly": "coupon_medsim_one"},
    BILLING_STRIPE_PROMO_COUPON_ID="coupon_global",
    BILLING_STRIPE_TRIAL_DAYS=14,
)
def test_stripe_checkout_creates_session_for_personal_account(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    with (
        patch(
            "apps.billing.providers.stripe.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        ) as customer_create,
        patch(
            "apps.billing.providers.stripe.stripe.checkout.Session.create",
            return_value=SimpleNamespace(
                id="cs_test",
                url="https://checkout.stripe.com/c/cs_test",
            ),
        ) as session_create,
    ):
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": ProductCode.MEDSIM_ONE.value,
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 200
    assert response.json() == {
        "checkout_url": "https://checkout.stripe.com/c/cs_test",
        "session_id": "cs_test",
    }
    customer_create.assert_called_once()
    session_create.assert_called_once()
    call_kwargs = session_create.call_args.kwargs
    assert call_kwargs["mode"] == "subscription"
    assert call_kwargs["line_items"] == [{"price": "price_test", "quantity": 1}]
    assert call_kwargs["subscription_data"]["trial_period_days"] == 14
    assert call_kwargs["discounts"] == [{"coupon": "coupon_medsim_one"}]
    assert call_kwargs["metadata"]["account_uuid"]
    assert call_kwargs["metadata"]["user_id"] == str(owner_user.id)
    assert call_kwargs["metadata"]["product_code"] == ProductCode.MEDSIM_ONE.value
    assert BillingAccount.objects.get(
        provider_type=ProviderType.STRIPE,
        provider_customer_id="cus_test",
    ).account == get_personal_account_for_user(owner_user)


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"chatlab_go:monthly": "price_chatlab_go_test"},
    BILLING_STRIPE_PROMO_COUPON_MAP={"chatlab_go:monthly": "coupon_chatlab_go"},
    BILLING_STRIPE_PROMO_COUPON_ID="coupon_global",
)
def test_stripe_checkout_uses_chatlab_go_coupon_and_canonical_metadata(
    owner_user, auth_client_factory
):
    client = auth_client_factory(owner_user)

    with (
        patch(
            "apps.billing.providers.stripe.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        ),
        patch(
            "apps.billing.providers.stripe.stripe.checkout.Session.create",
            return_value=SimpleNamespace(
                id="cs_test",
                url="https://checkout.stripe.com/c/cs_test",
            ),
        ) as session_create,
    ):
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": "chatlab",
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 200
    call_kwargs = session_create.call_args.kwargs
    assert call_kwargs["discounts"] == [{"coupon": "coupon_chatlab_go"}]
    assert call_kwargs["metadata"]["product_code"] == ProductCode.CHATLAB_GO.value
    assert (
        call_kwargs["subscription_data"]["metadata"]["product_code"] == ProductCode.CHATLAB_GO.value
    )


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"trainerlab_go:monthly": "price_trainerlab_go_test"},
    BILLING_STRIPE_PROMO_COUPON_MAP={"medsim_one:monthly": "coupon_medsim_one"},
    BILLING_STRIPE_PROMO_COUPON_ID="",
)
def test_stripe_checkout_missing_coupon_map_entry_does_not_block_checkout(
    owner_user, auth_client_factory
):
    client = auth_client_factory(owner_user)

    with (
        patch(
            "apps.billing.providers.stripe.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        ),
        patch(
            "apps.billing.providers.stripe.stripe.checkout.Session.create",
            return_value=SimpleNamespace(
                id="cs_test",
                url="https://checkout.stripe.com/c/cs_test",
            ),
        ) as session_create,
    ):
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": ProductCode.TRAINERLAB_GO.value,
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 200
    call_kwargs = session_create.call_args.kwargs
    assert call_kwargs["line_items"] == [
        {"price": "price_trainerlab_go_test", "quantity": 1}
    ]
    assert "discounts" not in call_kwargs


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"trainerlab_go:monthly": "price_trainerlab_go_test"},
    BILLING_STRIPE_PROMO_COUPON_MAP={},
    BILLING_STRIPE_PROMO_COUPON_ID="coupon_global",
)
def test_stripe_checkout_global_coupon_fallback_still_works(
    owner_user, auth_client_factory
):
    client = auth_client_factory(owner_user)

    with (
        patch(
            "apps.billing.providers.stripe.stripe.Customer.create",
            return_value=SimpleNamespace(id="cus_test"),
        ),
        patch(
            "apps.billing.providers.stripe.stripe.checkout.Session.create",
            return_value=SimpleNamespace(
                id="cs_test",
                url="https://checkout.stripe.com/c/cs_test",
            ),
        ) as session_create,
    ):
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": ProductCode.TRAINERLAB_GO.value,
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 200
    call_kwargs = session_create.call_args.kwargs
    assert call_kwargs["line_items"] == [
        {"price": "price_trainerlab_go_test", "quantity": 1}
    ]
    assert call_kwargs["discounts"] == [{"coupon": "coupon_global"}]


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"},
)
def test_stripe_checkout_blocks_duplicate_active_subscription(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    Subscription.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_subscription_id="sub_existing",
        plan_code="price_test",
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timedelta(days=10),
    )
    client = auth_client_factory(owner_user)

    with patch("apps.billing.providers.stripe.stripe.checkout.Session.create") as session_create:
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": ProductCode.MEDSIM_ONE.value,
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 409
    session_create.assert_not_called()


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PORTAL_ENABLED=True)
def test_stripe_customer_portal_requires_existing_customer(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    response = client.post(
        "/api/v1/billing/stripe/customer-portal-session/",
        data={"return_url": "https://medsim.example/billing/"},
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_stripe_customer_portal_disabled_returns_404(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    BillingAccount.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_customer_id="cus_test",
        billing_email=owner_user.email,
    )
    client = auth_client_factory(owner_user)

    response = client.post(
        "/api/v1/billing/stripe/customer-portal-session/",
        data={"return_url": "https://medsim.example/billing/"},
        content_type="application/json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PORTAL_ENABLED=True)
def test_stripe_customer_portal_creates_session(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    BillingAccount.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_customer_id="cus_test",
        billing_email=owner_user.email,
    )
    client = auth_client_factory(owner_user)

    with patch(
        "apps.billing.providers.stripe.stripe.billing_portal.Session.create",
        return_value=SimpleNamespace(id="bps_test", url="https://billing.stripe.com/p/session"),
    ) as portal_create:
        response = client.post(
            "/api/v1/billing/stripe/customer-portal-session/",
            data={"return_url": "https://medsim.example/billing/"},
            content_type="application/json",
        )

    assert response.status_code == 200
    assert response.json() == {
        "portal_url": "https://billing.stripe.com/p/session",
        "session_id": "bps_test",
    }
    portal_create.assert_called_once_with(
        customer="cus_test", return_url="https://medsim.example/billing/"
    )


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_PORTAL_ENABLED=True,
    BILLING_STRIPE_RETURN_BASE_URL="https://medsim.example",
)
def test_stripe_customer_portal_rejects_foreign_return_url(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    BillingAccount.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_customer_id="cus_test",
        billing_email=owner_user.email,
    )
    client = auth_client_factory(owner_user)

    with patch("apps.billing.providers.stripe.stripe.billing_portal.Session.create") as create:
        response = client.post(
            "/api/v1/billing/stripe/customer-portal-session/",
            data={"return_url": "https://evil.example/billing/"},
            content_type="application/json",
        )

    assert response.status_code == 400
    create.assert_not_called()


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PORTAL_ENABLED=True,
)
def test_billing_page_renders_personal_checkout_buttons(owner_user):
    client = Client()
    client.force_login(owner_user)

    response = client.get("/billing/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "data-checkout-form" in content
    assert ProductCode.CHATLAB_GO.value in content
    assert ProductCode.TRAINERLAB_GO.value in content
    assert ProductCode.MEDSIM_ONE.value in content
    assert "/api/v1/billing/stripe/checkout-session/" in content


@pytest.mark.django_db
@override_settings(
    BILLING_STRIPE_CHECKOUT_ENABLED=True,
    BILLING_STRIPE_PRICE_PLAN_MAP={},
)
def test_stripe_checkout_missing_price_mapping_returns_400(owner_user, auth_client_factory):
    client = auth_client_factory(owner_user)

    with patch("apps.billing.providers.stripe.stripe.checkout.Session.create") as create:
        response = client.post(
            "/api/v1/billing/stripe/checkout-session/",
            data={
                "product_code": ProductCode.MEDSIM_ONE.value,
                "billing_interval": "monthly",
                "success_url": "https://medsim.example/billing/success/",
                "cancel_url": "https://medsim.example/billing/",
            },
            content_type="application/json",
        )

    assert response.status_code == 400
    assert "Missing Stripe price mapping" in response.json()["detail"]
    create.assert_not_called()


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_stripe_subscription_webhook_syncs_entitlement_idempotently(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    payload = {
        "id": "evt_sub_created",
        "object": "event",
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_test",
                "customer": "cus_test",
                "status": "active",
                "metadata": {"account_uuid": str(personal_account.uuid)},
                "items": {"data": [{"price": {"id": "price_test"}}]},
                "start_date": 1_700_000_000,
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_800_000_000,
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    first_event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )
    entitlement_count = Entitlement.objects.filter(
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        product_code=ProductCode.MEDSIM_ONE.value,
    ).count()
    second_event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    assert first_event.status == WebhookEvent.Status.PROCESSED
    assert second_event.status == WebhookEvent.Status.PROCESSED
    assert Subscription.objects.filter(provider_subscription_id="sub_test").exists()
    entitlement = Entitlement.objects.get(
        source_type=Entitlement.SourceType.SUBSCRIPTION,
        product_code=ProductCode.MEDSIM_ONE.value,
    )
    assert entitlement.scope_type == Entitlement.ScopeType.USER
    assert entitlement.subject_user_id == owner_user.id
    assert entitlement.portable_across_accounts is True
    assert entitlement_count == 1
    assert (
        Entitlement.objects.filter(
            source_type=Entitlement.SourceType.SUBSCRIPTION,
            product_code=ProductCode.MEDSIM_ONE.value,
        ).count()
        == entitlement_count
    )


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_checkout_session_completed_links_customer_and_processes_event(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    payload = {
        "id": "evt_checkout_completed",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test",
                "customer": "cus_test",
                "subscription": "sub_test",
                "customer_email": owner_user.email,
                "client_reference_id": str(personal_account.uuid),
                "metadata": {
                    "account_uuid": str(personal_account.uuid),
                    "product_code": ProductCode.MEDSIM_ONE.value,
                },
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    with patch(
        "apps.billing.providers.stripe.stripe.Subscription.retrieve",
        return_value={
            "id": "sub_test",
            "customer": "cus_test",
            "status": "trialing",
            "metadata": {"account_uuid": str(personal_account.uuid)},
            "items": {"data": [{"price": {"id": "price_test"}}]},
            "start_date": 1_700_000_000,
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_800_000_000,
        },
    ):
        event = process_stripe_webhook(
            payload_bytes=payload_bytes,
            signature_header=_stripe_signature(payload_bytes),
        )

    assert event.status == WebhookEvent.Status.PROCESSED
    assert (
        BillingAccount.objects.get(
            provider_type=ProviderType.STRIPE,
            provider_customer_id="cus_test",
        ).account
        == personal_account
    )
    assert Subscription.objects.filter(provider_subscription_id="sub_test").exists()


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_access_snapshot_includes_web_purchased_entitlement(owner_user, auth_client_factory):
    personal_account = get_personal_account_for_user(owner_user)
    payload = {
        "id": "evt_access_snapshot",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_snapshot",
                "customer": "cus_snapshot",
                "status": "active",
                "metadata": {"account_uuid": str(personal_account.uuid)},
                "items": {"data": [{"price": {"id": "price_test"}}]},
                "start_date": 1_700_000_000,
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_800_000_000,
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    response = auth_client_factory(owner_user).get("/api/v1/accounts/me/access/")

    assert response.status_code == 200
    assert response.json()["products"][ProductCode.MEDSIM_ONE.value]["enabled"] is True


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_invoice_payment_failed_reconciles_entitlement_status(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    Subscription.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_subscription_id="sub_failed",
        plan_code="price_test",
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() - timedelta(days=1),
    )
    subscription = Subscription.objects.get(provider_subscription_id="sub_failed")
    from apps.billing.services.subscriptions import reconcile_subscription_entitlements

    reconcile_subscription_entitlements(subscription)
    assert Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}").status == "expired"

    Entitlement.objects.filter(source_ref=f"subscription:{subscription.pk}").update(
        status=Entitlement.Status.ACTIVE,
        ends_at=None,
    )
    payload = {
        "id": "evt_invoice_failed",
        "object": "event",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": "in_failed", "subscription": "sub_failed"}},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    subscription.refresh_from_db()
    entitlement = Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}")
    assert event.status == WebhookEvent.Status.PROCESSED
    assert subscription.status == Subscription.Status.PAST_DUE
    assert entitlement.status == Entitlement.Status.EXPIRED


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_invoice_payment_failed_with_future_period_keeps_access(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    subscription = Subscription.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_subscription_id="sub_failed_future",
        plan_code="price_test",
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timedelta(days=10),
    )
    from apps.billing.services.subscriptions import reconcile_subscription_entitlements

    reconcile_subscription_entitlements(subscription)
    payload = {
        "id": "evt_invoice_failed_future",
        "object": "event",
        "type": "invoice.payment_failed",
        "data": {"object": {"id": "in_failed_future", "subscription": "sub_failed_future"}},
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    subscription.refresh_from_db()
    entitlement = Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}")
    assert event.status == WebhookEvent.Status.PROCESSED
    assert subscription.status == Subscription.Status.PAST_DUE
    assert entitlement.status == Entitlement.Status.ACTIVE


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_customer_subscription_deleted_expires_access(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    subscription = Subscription.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_subscription_id="sub_deleted",
        plan_code="price_test",
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timedelta(days=10),
    )
    from apps.billing.services.subscriptions import reconcile_subscription_entitlements

    reconcile_subscription_entitlements(subscription)
    payload = {
        "id": "evt_sub_deleted",
        "object": "event",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_deleted",
                "customer": "cus_deleted",
                "status": "canceled",
                "metadata": {"account_uuid": str(personal_account.uuid)},
                "items": {"data": [{"price": {"id": "price_test"}}]},
                "start_date": 1_700_000_000,
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_800_000_000,
                "ended_at": 1_700_500_000,
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    subscription.refresh_from_db()
    entitlement = Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}")
    assert event.status == WebhookEvent.Status.PROCESSED
    assert subscription.status == Subscription.Status.EXPIRED
    assert entitlement.status == Entitlement.Status.EXPIRED


@pytest.mark.django_db
@override_settings(BILLING_STRIPE_PRICE_PLAN_MAP={"medsim_one:monthly": "price_test"})
def test_unknown_stripe_price_for_existing_subscription_fails_closed(owner_user):
    personal_account = get_personal_account_for_user(owner_user)
    subscription = Subscription.objects.create(
        account=personal_account,
        provider_type=ProviderType.STRIPE,
        provider_subscription_id="sub_unknown_price",
        plan_code="price_test",
        status=Subscription.Status.ACTIVE,
        current_period_end=timezone.now() + timedelta(days=20),
    )
    from apps.billing.services.subscriptions import reconcile_subscription_entitlements

    reconcile_subscription_entitlements(subscription)
    assert Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}").status == "active"

    payload = {
        "id": "evt_unknown_price",
        "object": "event",
        "type": "customer.subscription.updated",
        "data": {
            "object": {
                "id": "sub_unknown_price",
                "customer": "cus_unknown_price",
                "status": "active",
                "metadata": {"account_uuid": str(personal_account.uuid)},
                "items": {"data": [{"price": {"id": "price_unknown"}}]},
                "start_date": 1_700_000_000,
                "current_period_start": 1_700_000_000,
                "current_period_end": 1_800_000_000,
            }
        },
    }
    payload_bytes = json.dumps(payload).encode("utf-8")

    event = process_stripe_webhook(
        payload_bytes=payload_bytes,
        signature_header=_stripe_signature(payload_bytes),
    )

    subscription.refresh_from_db()
    entitlement = Entitlement.objects.get(source_ref=f"subscription:{subscription.pk}")
    assert event.status == WebhookEvent.Status.FAILED
    assert event.processing_error == "Unknown Stripe price id"
    assert subscription.status == Subscription.Status.EXPIRED
    assert entitlement.status == Entitlement.Status.EXPIRED
