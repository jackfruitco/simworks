from __future__ import annotations

from django.test import Client
import pytest

from api.v1.auth import create_access_token
from apps.accounts.models import AccountMembership, UserRole
from apps.accounts.services import create_organization_account, get_personal_account_for_user
from apps.billing.catalog import ProductCode
from apps.billing.models import Entitlement, Subscription
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
        data='{"id": "evt_test", "type": "customer.subscription.created"}',
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=123,v1=bad",
    )

    assert response.status_code == 400
