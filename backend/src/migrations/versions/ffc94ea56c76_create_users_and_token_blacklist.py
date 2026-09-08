"""create users and token_blacklist

Revision ID: ffc94ea56c76
Revises:
Create Date: 2026-09-06 19:25:01.791955

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ffc94ea56c76"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("current_timestamp(0)"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_name", sa.String(length=30), nullable=False),
        sa.Column("last_name", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("oauth_provider", sa.String(length=20), nullable=True),
        sa.Column("oauth_sub", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=50), server_default="UTC", nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    # Hand-edited: SQLAlchemy's declarative syntax needs the dialect-specific
    # `postgresql_where` arg for a partial index — autogenerate doesn't produce
    # this correctly on its own. Lets the same (provider, sub) pair be reused
    # across rows where oauth_sub is NULL (i.e. every password-only user).
    op.create_index(
        "ix_users_oauth_identity",
        "users",
        ["oauth_provider", "oauth_sub"],
        unique=True,
        postgresql_where=sa.text("oauth_sub IS NOT NULL"),
    )

    op.create_table(
        "token_blacklist",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("current_timestamp(0)"), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("token_type", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_token_blacklist_jti"), "token_blacklist", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_token_blacklist_jti"), table_name="token_blacklist")
    op.drop_table("token_blacklist")

    op.drop_index("ix_users_oauth_identity", table_name="users", postgresql_where=sa.text("oauth_sub IS NOT NULL"))
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
