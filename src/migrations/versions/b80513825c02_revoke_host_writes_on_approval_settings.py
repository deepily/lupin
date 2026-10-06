"""Revoke the host role's write rights on approval_settings

Revision ID: b80513825c02
Revises: a80513825b01
Create Date: 2026-10-02

`init-db-roles.sql` grants `lupin_host` `INSERT`/`UPDATE`/`DELETE` on every app
table through `ALTER DEFAULT PRIVILEGES FOR ROLE lupin_app`. A table that is
dropped and re-created by `lupin_app` therefore comes back writable to
`lupin_host`, and the script's own `REVOKE` only ran once, before. This
revision repeats the `REVOKE` on the migration path, so it holds whenever the
table is created or re-created by a migration run.

The revision is idempotent and safe without the roles. It does nothing when the
`lupin_host` role or the `approval_settings` table does not exist (every
database that has not been provisioned).

It never fails the boot. Every server boot runs migrations, so a role that
cannot revoke (not the table's owner) must not stop the server. Postgres either
answers success without revoking or raises insufficient_privilege. The revoke
swallows the second, and a check afterwards logs one warning through alembic's
logger when `lupin_host` can still write.
"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = 'b80513825c02'
down_revision: Union[str, Sequence[str], None] = 'a80513825b01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger( "alembic.runtime.migration" )

_REVOKE_SQL = """
DO $$
BEGIN
    IF EXISTS ( SELECT FROM pg_roles WHERE rolname = 'lupin_host' )
       AND to_regclass( 'public.approval_settings' ) IS NOT NULL THEN
        BEGIN
            REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.approval_settings FROM lupin_host;
        EXCEPTION WHEN insufficient_privilege THEN
            NULL;   -- not the owner: the check below reports it
        END;
    END IF;
END
$$;
"""

_STILL_WRITABLE_SQL = """
SELECT EXISTS ( SELECT FROM pg_roles WHERE rolname = 'lupin_host' )
   AND to_regclass( 'public.approval_settings' ) IS NOT NULL
   AND ( has_table_privilege( 'lupin_host', 'public.approval_settings', 'INSERT' )
      OR has_table_privilege( 'lupin_host', 'public.approval_settings', 'UPDATE' )
      OR has_table_privilege( 'lupin_host', 'public.approval_settings', 'DELETE' ) )
"""

_CURRENT_USER_SQL = "SELECT current_user"

WARNING_TEXT = (
    "b80513825c02: role lupin_host still has INSERT, UPDATE or DELETE on approval_settings "
    "(this migration ran as %s and could not revoke it). Remedy: as the table owner or a superuser, "
    "re-run src/scripts/sql/init-db-roles.sql, or REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON "
    "approval_settings FROM lupin_host."
)


def upgrade() -> None:
    """
    Take the write rights on approval_settings away from lupin_host.

    Ensures:
        - a no-op when the role or the table is absent
        - lupin_host keeps `SELECT`
        - never raises for want of privilege; logs one `WARNING` (alembic.runtime.migration)
          when lupin_host can still `INSERT`, `UPDATE` or `DELETE` afterwards
    """
    op.execute( _REVOKE_SQL )
    connection = op.get_bind()
    if connection.execute( text( _STILL_WRITABLE_SQL ) ).scalar():
        logger.warning( WARNING_TEXT, connection.execute( text( _CURRENT_USER_SQL ) ).scalar() )


def downgrade() -> None:
    """
    Nothing to undo: a revoked right is not restored, because the earlier state was the hole.
    """
    pass
