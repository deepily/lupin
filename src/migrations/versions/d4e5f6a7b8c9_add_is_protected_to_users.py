"""Add is_protected column to users

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-15 22:30:00.000000

Fixes a model<->migration DRIFT: ``User.is_protected`` (src/cosa/rest/postgres_models.py:84)
was declared on the ORM model — ``Boolean, nullable=False, default=False,
server_default="false"`` — but NO migration ever added the column. So any
migration-bootstrapped database (e.g. the GCP cloud-test ``lupin_db_test``)
lacked it, and user creation failed with::

    column "is_protected" of relation "users" does not exist

The ``server_default='false'`` backfills any pre-existing rows so the NOT NULL
constraint is satisfiable without a separate data step; it matches the model's
own ``server_default`` exactly (so there is nothing to drop afterward).

Discovered 2026-06-15 during GCP cloud-test bring-up (user seeding). See
src/rnd/v0.1.8/2026.05.30-gcp-deployment/2026.06.15-new-deployer-runbook-gcp-cloud-test.md
(GOTCHA #5).

IDEMPOTENT BY DESIGN: the column is added only when it is actually absent, and
dropped only when present. This matters because the baseline schema is created
two different ways across environments — the ``src/scripts/sql/schema.sql``
init-mount (which historically did NOT include ``is_protected``) on a fresh
Cloud-SQL DB, versus a long-lived dev DB that already grew the column out-of-band
while still stamped one revision behind this one (``c3d4e5f6a7b8``). A blind
``op.add_column`` crashes the latter with ``DuplicateColumn`` — which, once this
migration runs automatically at app startup (auto-migrate, see
``cosa.rest.db.auto_migrate``), would abort boot. Inspector-guarding the DDL
makes ``alembic upgrade head`` safe and idempotent on EVERY environment without
any hand-run SQL.
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
