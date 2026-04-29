"""endpoint addresses and persistent scheduled delivery

Revision ID: 20260429_000013
Revises: 20260429_000012
Create Date: 2026-04-29
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260429_000013"
down_revision = "20260429_000012"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def _drop_constraint(table: str, constraint: str) -> None:
    op.execute(sa.text(f'ALTER TABLE IF EXISTS "{table}" DROP CONSTRAINT IF EXISTS "{constraint}"'))


def upgrade() -> None:
    op.create_table(
        "endpoint_addresses",
        sa.Column("id", UUID, nullable=False),
        sa.Column("address_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", UUID, nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("address_type", sa.String(length=64), nullable=False, server_default="direct"),
        sa.Column("external_ref", sa.String(length=512), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("workspace_scope", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], name="fk_endpoint_addresses_endpoint_id_endpoints"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("address_id", name="uq_endpoint_addresses_address_id"),
        sa.UniqueConstraint("endpoint_id", "address_type", "external_ref", name="uq_endpoint_addresses_endpoint_type_external_ref"),
    )
    op.create_table(
        "actor_delivery_preferences",
        sa.Column("id", UUID, nullable=False),
        sa.Column("preference_id", sa.String(length=255), nullable=False),
        sa.Column("actor_id", UUID, nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=False),
        sa.Column("address_id", UUID, nullable=False),
        sa.Column("alias", sa.String(length=128), nullable=False, server_default="me"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["actors.id"], name="fk_actor_delivery_preferences_actor_id_actors"),
        sa.ForeignKeyConstraint(["address_id"], ["endpoint_addresses.id"], name="fk_actor_delivery_preferences_address_id_endpoint_addresses"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preference_id", name="uq_actor_delivery_preferences_preference_id"),
        sa.UniqueConstraint("actor_id", "provider_type", "alias", name="uq_actor_delivery_preferences_actor_provider_alias"),
    )

    op.add_column("endpoint_outbox", sa.Column("target_address_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_endpoint_outbox_target_address_id_endpoint_addresses",
        "endpoint_outbox",
        "endpoint_addresses",
        ["target_address_id"],
        ["id"],
    )
    op.add_column("delivery_attempts", sa.Column("target_address_id", UUID, nullable=True))
    op.create_foreign_key(
        "fk_delivery_attempts_target_address_id_endpoint_addresses",
        "delivery_attempts",
        "endpoint_addresses",
        ["target_address_id"],
        ["id"],
    )

    op.add_column("scheduled_jobs", sa.Column("next_fire_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheduled_jobs", sa.Column("last_fire_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheduled_jobs", sa.Column("lease_owner", sa.String(length=128), nullable=False, server_default=""))
    op.add_column("scheduled_jobs", sa.Column("lease_until_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_jobs", "lease_until_at")
    op.drop_column("scheduled_jobs", "lease_owner")
    op.drop_column("scheduled_jobs", "last_fire_at")
    op.drop_column("scheduled_jobs", "next_fire_at")

    _drop_constraint("delivery_attempts", "fk_delivery_attempts_target_address_id_endpoint_addresses")
    op.drop_column("delivery_attempts", "target_address_id")
    _drop_constraint("endpoint_outbox", "fk_endpoint_outbox_target_address_id_endpoint_addresses")
    op.drop_column("endpoint_outbox", "target_address_id")

    op.drop_table("actor_delivery_preferences")
    op.drop_table("endpoint_addresses")
