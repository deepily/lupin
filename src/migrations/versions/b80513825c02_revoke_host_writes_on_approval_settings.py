"""Revoke the host role's write rights on approval_settings

Revision ID: b80513825c02
Revises: a80513825b01
Create Date: 2026-10-02

Row 80513825 (option B). `init-db-roles.sql` grants `lupin_host` INSERT/UPDATE/DELETE on
every app table through `ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app`. A table that is dropped
and re-created by `lupin_app` therefore comes back writable to `lupin_host`, and the script's own
REVOKE only ran once, before. This revision repeats the REVOKE on the migration path, so it holds
whenever the table is created or re-created by a migration run.

IDEMPOTENT and SAFE WITHOUT THE ROLES: it does nothing when the `lupin_host` role or the
`approval_settings` table does not exist (every database that has not been provisioned).
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b80513825c02'
down_revision: Union[str, Sequence[str], None] = 'a80513825b01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Take the write rights on approval_settings away from lupin_host.

    Ensures:
        - a no-op when the role or the table is absent
        - lupin_host keeps SELECT
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS ( SELECT FROM pg_roles WHERE rolname = 'lupin_host' )
               AND to_regclass( 'public.approval_settings' ) IS NOT NULL THEN
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.approval_settings FROM lupin_host;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """
    Nothing to undo: a revoked right is not restored, because the earlier state was the hole.
    """
    pass
