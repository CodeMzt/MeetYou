"""endpoint workspace memberships

Revision ID: 20260505_000015
Revises: 20260430_000014
Create Date: 2026-05-05
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260505_000015"
down_revision = "20260430_000014"
branch_labels = None
depends_on = None


UUID = postgresql.UUID(as_uuid=True)


def _json_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def upgrade() -> None:
    op.create_table(
        "endpoint_workspace_memberships",
        sa.Column("id", UUID, nullable=False),
        sa.Column("membership_id", sa.String(length=255), nullable=False),
        sa.Column("endpoint_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("membership_role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="core"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["endpoint_id"], ["endpoints.id"], name="fk_ewm_endpoint"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_ewm_workspace"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", name="uq_ewm_membership_id"),
        sa.UniqueConstraint("endpoint_id", "workspace_id", name="uq_ewm_endpoint_workspace"),
    )
    op.create_table(
        "endpoint_address_workspace_memberships",
        sa.Column("id", UUID, nullable=False),
        sa.Column("membership_id", sa.String(length=255), nullable=False),
        sa.Column("address_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("membership_role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="core"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["address_id"], ["endpoint_addresses.id"], name="fk_eawm_address"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_eawm_workspace"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", name="uq_eawm_membership_id"),
        sa.UniqueConstraint("address_id", "workspace_id", name="uq_eawm_address_workspace"),
    )

    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    workspace_rows = conn.execute(sa.text("SELECT id, workspace_id FROM workspaces WHERE status <> 'archived'")).mappings().all()
    workspace_by_key = {row["workspace_id"]: row["id"] for row in workspace_rows}
    personal_workspace_id = workspace_by_key.get("personal")
    endpoint_workspace_ids: dict[uuid.UUID, list[uuid.UUID]] = {}

    endpoint_rows = conn.execute(
        sa.text("SELECT id, endpoint_id, provider_type, workspace_scope FROM endpoints ORDER BY endpoint_id")
    ).mappings().all()
    for endpoint in endpoint_rows:
        scope = [workspace_by_key[item] for item in _json_list(endpoint["workspace_scope"]) if item in workspace_by_key]
        if not scope and str(endpoint["provider_type"] or "").lower() != "core" and personal_workspace_id is not None:
            scope = [personal_workspace_id]
        endpoint_workspace_ids[endpoint["id"]] = scope
        for index, workspace_id in enumerate(scope):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO endpoint_workspace_memberships (
                        id, membership_id, endpoint_id, workspace_id, membership_role, is_primary, enabled, source, metadata, created_at, updated_at
                    )
                    VALUES (
                        :id, :membership_id, :endpoint_id, :workspace_id, 'member', :is_primary, true, 'migration',
                        :metadata, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "membership_id": f"ewm.{uuid.uuid4().hex}",
                    "endpoint_id": endpoint["id"],
                    "workspace_id": workspace_id,
                    "is_primary": index == 0,
                    "metadata": {"migrated_from_workspace_scope": _json_list(endpoint["workspace_scope"])},
                    "created_at": now,
                    "updated_at": now,
                },
            )

    address_rows = conn.execute(
        sa.text("SELECT id, address_id, endpoint_id, workspace_scope FROM endpoint_addresses ORDER BY address_id")
    ).mappings().all()
    for address in address_rows:
        scope = [workspace_by_key[item] for item in _json_list(address["workspace_scope"]) if item in workspace_by_key]
        if not scope:
            scope = list(endpoint_workspace_ids.get(address["endpoint_id"], []))
        for index, workspace_id in enumerate(scope):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO endpoint_address_workspace_memberships (
                        id, membership_id, address_id, workspace_id, membership_role, is_primary, enabled, source, metadata, created_at, updated_at
                    )
                    VALUES (
                        :id, :membership_id, :address_id, :workspace_id, 'member', :is_primary, true, 'migration',
                        :metadata, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "membership_id": f"eawm.{uuid.uuid4().hex}",
                    "address_id": address["id"],
                    "workspace_id": workspace_id,
                    "is_primary": index == 0,
                    "metadata": {"migrated_from_workspace_scope": _json_list(address["workspace_scope"])},
                    "created_at": now,
                    "updated_at": now,
                },
            )


def downgrade() -> None:
    op.drop_table("endpoint_address_workspace_memberships")
    op.drop_table("endpoint_workspace_memberships")
