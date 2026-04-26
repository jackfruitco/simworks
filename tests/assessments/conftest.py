"""Fixtures for the assessments test suite.

Reuses the lightweight account/user/role pattern established elsewhere in
the test suite (e.g. ``tests/chatlab/test_message_flow.py``).
"""

from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture
def user_role(db):
    from apps.accounts.models import UserRole

    return UserRole.objects.create(title="Test Role Assessments")


@pytest.fixture
def user(db, user_role):
    from apps.accounts.models import User

    return User.objects.create_user(
        email="assessments@example.com",
        password="testpass123",
        role=user_role,
    )


@pytest.fixture
def account(db, user):
    """Reuse the personal account auto-created by the user signal."""
    from apps.accounts.models import Account

    return Account.objects.get(owner_user=user, account_type=Account.AccountType.PERSONAL)


@pytest.fixture
def account_b(db):
    from apps.accounts.models import Account, User, UserRole

    role = UserRole.objects.create(title="Test Role Assessments B")
    other_user = User.objects.create_user(
        email="assessments-b@example.com",
        password="testpass123",
        role=role,
    )
    return Account.objects.get(owner_user=other_user, account_type=Account.AccountType.PERSONAL)


@pytest.fixture
def simulation(db, user, account):
    from apps.simcore.models import Simulation

    return Simulation.objects.create(
        user=user,
        account=account,
        diagnosis="Test Diagnosis",
        chief_complaint="Test Complaint",
        sim_patient_full_name="Test Patient",
    )


@pytest.fixture
def draft_rubric(db):
    """A DRAFT global rubric with three criteria covering bool / int / enum.

    Matches the chatlab initial-feedback shape so tests that need a real
    rubric can use this without invoking the management command.
    """
    from apps.assessments.models import AssessmentCriterion, AssessmentRubric

    rubric = AssessmentRubric.objects.create(
        slug="chatlab_initial_feedback",
        name="ChatLab Initial Feedback",
        description="Test fixture rubric.",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="initial_feedback",
        version=1,
        status=AssessmentRubric.Status.DRAFT,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="correct_diagnosis",
        label="Correct Diagnosis",
        category="clinical_reasoning",
        value_type=AssessmentCriterion.ValueType.BOOL,
        weight=Decimal("1.000"),
        sort_order=10,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="patient_experience",
        label="Patient Experience",
        category="communication",
        value_type=AssessmentCriterion.ValueType.INT,
        min_value=Decimal("0"),
        max_value=Decimal("5"),
        weight=Decimal("1.000"),
        sort_order=30,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="acuity",
        label="Acuity",
        category="triage",
        value_type=AssessmentCriterion.ValueType.ENUM,
        allowed_values=["low", "medium", "high"],
        weight=Decimal("1.000"),
        sort_order=40,
    )
    return rubric


@pytest.fixture
def published_rubric(db, draft_rubric):
    """The draft_rubric promoted to PUBLISHED."""
    draft_rubric.status = draft_rubric.Status.PUBLISHED
    draft_rubric.save()
    return draft_rubric
