"""Add is_protected column to users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8

Fixes a drift between the model and the migrations. ``User.is_protected``
(src/cosa/rest/postgres_models.py:84) is declared on the ORM model as
``Boolean, nullable=False, default=False, server_default="false"``, but no
migration ever added the column. So any migration-bootstrapped database (for
example the GCP cloud-test ``lupin_db_test``) lacked it, and user creation
failed with::

    column "is_protected" of relation "users" does not exist

The ``server_default='false'`` backfills any pre-existing rows. The `NOT NULL`
constraint is then satisfiable without a separate data step. It matches the
model's own ``server_default`` exactly, so there is nothing to drop afterward.

Idempotent: the column is added only when it is actually absent, and
dropped only when present. The baseline schema is created two different ways
across environments. One is the ``src/scripts/sql/schema.sql`` init-mount,
which historically did not include ``is_protected``, on a fresh Cloud-SQL DB.
The other is a long-lived dev DB that already grew the column out-of-band while
still stamped one revision behind this one (``c3d4e5f6a7b8``).

A blind ``op.add_column`` crashes the latter with ``DuplicateColumn``. This
migration runs automatically at app startup (auto-migrate, see
``cosa.rest.db.auto_migrate``), so that crash would abort boot. Guarding the DDL
with the inspector makes ``alembic upgrade head`` safe and idempotent on every
environment, without any hand-run SQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _users_has_is_protected() -> bool:
    """Return True iff the live ``users`` table already has ``is_protected``."""
    bind      = op.get_bind()
    inspector = inspect( bind )
    columns   = [ col[ "name" ] for col in inspector.get_columns( "users" ) ]
    return "is_protected" in columns


def upgrade() -> None:
    """Add users.is_protected (matches the ORM model) — only if absent."""
    if _users_has_is_protected():
        # Already present (e.g. schema bootstrapped by schema.sql or a prior
        # out-of-band add). Nothing to do — keep the migration idempotent.
        return

    op.add_column(
        'users',
        sa.Column(
            'is_protected',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text( 'false' ),
        ),
    )


def downgrade() -> None:
    """Drop users.is_protected — only if present."""
    if not _users_has_is_protected():
        return

    op.drop_column( 'users', 'is_protected' )
