"""audit log append-only trigger

Revision ID: 029294c1a5fa
Revises: c47c54e6ad1b
Create Date: 2026-11-03 23:09:18.160406

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "029294c1a5fa"
down_revision: str | None = "c47c54e6ad1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_append_only()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only: % not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only();")
