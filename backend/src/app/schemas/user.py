import uuid as uuid_pkg
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..core.schemas import PersistentDeletion, TimestampSchema, UUIDSchema

OnboardingStatus = Literal["not_started", "pending", "ready", "completed"]


class UserBase(BaseModel):
    first_name: Annotated[str, Field(min_length=1, max_length=30, examples=["Ada"])]
    last_name: Annotated[str | None, Field(min_length=1, max_length=30, default=None, examples=["Lovelace"])]
    email: Annotated[EmailStr, Field(examples=["ada@example.com"])]


class User(TimestampSchema, UserBase, UUIDSchema, PersistentDeletion):
    """Full internal shape — never returned directly from a route."""

    hashed_password: str | None = None
    oauth_provider: str | None = None
    oauth_sub: str | None = None
    timezone: str = "UTC"
    is_superuser: bool = False

    # Onboarding state — documentation parity only; not load-bearing for `crud_users`,
    # which is typed against the SQLAlchemy model directly.
    onboarding_status: OnboardingStatus = "not_started"
    onboarding_suggested_goals: list[dict[str, Any]] | None = None
    onboarding_completed_at: datetime | None = None


class UserRead(BaseModel):
    """Public shape — never exposes `hashed_password` or `oauth_sub`."""

    id: uuid_pkg.UUID

    first_name: Annotated[str, Field(min_length=1, max_length=30, examples=["Ada"])]
    last_name: Annotated[str | None, Field(min_length=1, max_length=30, default=None, examples=["Lovelace"])]
    email: Annotated[EmailStr, Field(examples=["ada@example.com"])]
    timezone: str
    is_superuser: bool


class UserCreate(UserBase):
    model_config = ConfigDict(extra="forbid")

    password: Annotated[str, Field(min_length=8, examples=["Str1ngst!"])]
    timezone: Annotated[str, Field(default="UTC", examples=["Africa/Lagos"])]


class UserCreateInternal(UserBase):
    hashed_password: str | None = None
    oauth_provider: str | None = None
    oauth_sub: str | None = None
    timezone: str = "UTC"


class UserUpdate(BaseModel):
    """Defined for FastCRUD's generic signature — not routed this slice."""

    model_config = ConfigDict(extra="forbid")

    first_name: Annotated[str | None, Field(min_length=1, max_length=30, default=None)]
    last_name: Annotated[str | None, Field(min_length=1, max_length=30, default=None)]
    email: Annotated[EmailStr | None, Field(default=None)]
    timezone: Annotated[str | None, Field(default=None)]


class UserUpdateInternal(UserUpdate):
    updated_at: datetime


class UserDelete(BaseModel):
    """Stub — not routed this slice (nothing deletes a user in Phase 1)."""

    model_config = ConfigDict(extra="forbid")

    is_deleted: bool
    deleted_at: datetime


class OnboardingStatusRead(BaseModel):
    """Public response shape for `GET /onboarding/status` and `POST /onboarding/run`."""

    onboarding_status: OnboardingStatus
    onboarding_suggested_goals: list[dict[str, Any]] | None = None
    onboarding_completed_at: datetime | None = None
