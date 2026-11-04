"""task_items.priority server_default P2 -> P5 — the half a code edit cannot reach

Revision ID: 9a1c4f27bd30
Revises: 8d404f635e84

The default priority from here on is P5.

Why a migration and not just the model edit
-------------------------------------------
`postgres_models.py` carries two defaults on this column, and they fire in different places.

Example:
    default        = "P5"   # SQLAlchemy: applies when the ORM builds the `INSERT`
    server_default = "P5"   # Postgres: applies when the `INSERT` omits the column

Editing the model moves the first one for the running process. It moves the second one
for a database that has not been created yet. It does not touch a column that exists.
A code-only change leaves the live table handing out `'P2'::character varying` to any
writer that omits the column. That means raw SQL, a psql session or a future service.

Alembic would not catch this on its own. `src/migrations/env.py` sets no
`compare_server_default`, which is off by default, so autogenerate ignores
server-default drift. This file is hand-written for that reason.

What this does and does not do
------------------------------
It changes the column default only. Existing rows are left exactly as they are. A default
governs what a future `INSERT` gets when it stays silent. It has never governed rows
already written, and rewriting them would re-prioritise the whole board.

After this lands the table holds P0-P3 rows from the old regime beside new P5 ones. That
is the intended state, not drift. Whether the firewall applies retroactively is an open
question for Rick to rule, not for a migration to assume.

No width change is needed. The column is `String( 2 )`, and every member of the widened
`VALID_PRIORITIES`, P0 through P5, is two characters. The application-level enum refuses
`P6`. The column has no `CHECK` constraint, so the database accepts any two characters.

The downgrade restores `'P2'`, verified against the column definition at `8d404f635e84`.
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
