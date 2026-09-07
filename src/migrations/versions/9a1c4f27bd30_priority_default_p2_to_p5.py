"""task_items.priority server_default P2 -> P5 — the half a code edit cannot reach

Revision ID: 9a1c4f27bd30
Revises: 8d404f635e84
Create Date: 2026-09-07

Row `0107c19e`. Authorized by Rick's broadcast e254ec7d, 2026-09-07: "The
default Priority from here on now will be P5."

WHY A MIGRATION AND NOT JUST THE MODEL EDIT
--------------------------------------------
`postgres_models.py` carries TWO defaults on this column and they fire in
different places:

    default        = "P5"   # SQLAlchemy — applies when the ORM builds the INSERT
    server_default = "P5"   # POSTGRES   — applies when the INSERT omits the column

Editing the model moves the first one for the running process and moves the
second one for a database that has not been created yet. It does NOT touch a
column that already exists. So a code-only change leaves the LIVE table still
handing out `'P2'::character varying` to any writer that omits the column —
raw SQL, a psql session, a future service, an `INSERT` built by anything that
is not this ORM.

⚠️ Alembic would not have caught this on its own: `src/migrations/env.py` sets
no `compare_server_default`, which is OFF by default, so autogenerate ignores
server-default drift entirely. This file is hand-written for that reason.

WHAT THIS DOES AND DELIBERATELY DOES NOT DO
--------------------------------------------
Changes the column default ONLY. **Existing rows are left exactly as they
are.** A default governs what a future INSERT gets when it stays silent; it
has never governed rows already written, and rewriting them would be a
re-prioritisation of the whole board wearing a migration's clothes.

⇒ So after this lands the table legitimately holds P0-P3 rows minted under the
old regime alongside new P5 ones. That is the intended state, not drift.
Whether the firewall applies retroactively is an OPEN question on row
`b8205986` and is Rick's to rule, not a migration's to assume.

⚠️ NO WIDTH CHANGE IS NEEDED and none is made: the column is `String( 2 )` and
every member of the widened `VALID_PRIORITIES` — P0 through P5 — is two
characters. The value space grew; the storage did not.

The application-level enum (`task_store_rules.VALID_PRIORITIES`) is what
actually refuses `P6`; this column is a plain `String( 2 )` with no CHECK
constraint, so the database will accept any two characters and always would
have. That is unchanged by this migration and is not a regression it
introduces.

DOWNGRADE restores `'P2'` — the value that was there, verified against the
column definition at revision `8d404f635e84`, not assumed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9a1c4f27bd30'
down_revision: Union[str, Sequence[str], None] = '8d404f635e84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "task_items",
        "priority",
        existing_type      = sa.String( 2 ),
        existing_nullable  = False,
        server_default     = "P5"
    )


def downgrade() -> None:
    op.alter_column(
        "task_items",
        "priority",
        existing_type      = sa.String( 2 ),
        existing_nullable  = False,
        server_default     = "P2"
    )
