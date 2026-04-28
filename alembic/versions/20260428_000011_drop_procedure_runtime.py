"""drop procedure runtime remnants

Revision ID: 20260428_000011
Revises: 20260426_000010
Create Date: 2026-04-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_000011"
down_revision = "20260426_000010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text('ALTER TABLE IF EXISTS "threads" DROP CONSTRAINT IF EXISTS "fk_threads_pinned_procedure_id_procedures"'))
    op.execute(sa.text('ALTER TABLE IF EXISTS "threads" DROP COLUMN IF EXISTS "pinned_procedure_id"'))
    op.execute(sa.text('DROP TABLE IF EXISTS "procedures"'))


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS "procedures" (
                id UUID PRIMARY KEY,
                procedure_id VARCHAR(128) NOT NULL,
                principal_id UUID NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                prompt_overlay TEXT NOT NULL,
                default_execution_target VARCHAR(64) NOT NULL,
                risk_profile VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL,
                applicable_modes JSON NOT NULL,
                recommended_capabilities JSON NOT NULL,
                recommended_source_profiles JSON NOT NULL,
                metadata JSON NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                CONSTRAINT uq_procedures_procedure_id UNIQUE (procedure_id),
                CONSTRAINT fk_procedures_principal_id_principals FOREIGN KEY (principal_id) REFERENCES principals(id)
            )
            """
        )
    )
    op.execute(sa.text('ALTER TABLE IF EXISTS "threads" ADD COLUMN IF NOT EXISTS "pinned_procedure_id" VARCHAR(128)'))
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'fk_threads_pinned_procedure_id_procedures'
                ) THEN
                    ALTER TABLE "threads"
                    ADD CONSTRAINT "fk_threads_pinned_procedure_id_procedures"
                    FOREIGN KEY ("pinned_procedure_id") REFERENCES "procedures" ("procedure_id");
                END IF;
            END $$;
            """
        )
    )
