from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AccountOut(BaseModel):
    uuid: str
    name: str
    slug: str
    account_type: str
    is_active: bool
    requires_join_approval: bool
    parent_account_uuid: str | None = None
    membership_role: str = ""
    membership_status: str = ""
    is_active_context: bool = False


class AccountSelectIn(BaseModel):
    account_uuid: str


class OrganizationCreateIn(BaseModel):
    name: str
    slug: str = ""
    requires_join_approval: bool = False
    parent_account_uuid: str | None = None


class MembershipInviteIn(BaseModel):
    email: str
    role: str


class MembershipOut(BaseModel):
    uuid: str
    account_uuid: str
    user_id: int | None = None
    invite_email: str = ""
    role: str
    status: str
    joined_at: datetime | None = None
    ended_at: datetime | None = None


class ProductAccessOut(BaseModel):
    enabled: bool = False
    features: list[str] = Field(default_factory=list)
    limits: dict[str, int | None] = Field(default_factory=dict)


class AccessSnapshotOut(BaseModel):
    account_uuid: str
    account_name: str
    account_type: str
    membership_role: str = ""
    products: dict[str, ProductAccessOut] = Field(default_factory=dict)
