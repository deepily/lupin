"""i3_kind_aware_blocked_chase

Revision ID: 53835fd51f1a
Revises: d0caad3ee21e
Create Date: 2026-07-20 16:49:14.549311

I3 kind-aware chase requirement (eab1d7da, plan
src/rnd/v0.1.9/2026.07.20-i3-kind-aware-chase-migration-plan.md).

Replaces the GLOBAL blocked-requires-chase CHECK with a KIND-AWARE one, in place
and under the SAME constraint name:

    OLD: status != 'blocked' OR next_chase_ts IS NOT NULL
    NEW: status != 'blocked' OR next_chase_ts IS NOT NULL
                             OR NOT (blocked_by @> '[{"kind": "persona"}]'::jsonb)

A chase time is required only when a PERSONA blocks (a peer is chaseable, so a
chase is honest); a user/item-only block needs none — you cannot schedule Rick,
and an item resolves on its own edge. That is what makes the honest state
"blocked on Rick, no schedulable chase" EXPRESSIBLE instead of dying quietly in
`queued` prose the arbiter counts as active work.

⚠️ NO BACKFILL NEEDED — and this is proved, not assumed. The new predicate is a
SUPERSET of the old (it permits everything the old did, plus null-chase
non-persona blocks). Every existing blocked row already carries a chase (the old
CHECK is why), so every existing row satisfies the new CHECK. Zero violators ⇒ a
plain DROP+ADD is safe on live data with no NOT VALID carve-out. AC5 is a test
that PROVES zero violators against the real table.

`@>` (jsonb containment) is IMMUTABLE, so it is legal inside a CHECK constraint.

The NEW predicate literal here MUST match postgres_models.TaskItem's
CheckConstraint VERBATIM — a parity test asserts the two strings agree, because a
model/migration divergence is a CHECK that silently means two different things on
a fresh-from-metadata DB vs a migrated one (the file's own :1446 comment names
this hazard for the park CHECKs).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '53835fd51f1a'
down_revision: Union[str, Sequence[str], None] = 'd0caad3ee21e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME      = "task_items"
CONSTRAINT_NAME = "ck_task_items_blocked_requires_chase_ts"

# The kind-aware predicate (upgrade target). Kept in ONE place so upgrade() and
# the parity test read the same string. MUST match postgres_models verbatim.
KIND_AWARE_PREDICATE = (
    "status != 'blocked' OR next_chase_ts IS NOT NULL "
    "OR NOT (blocked_by @> '[{\"kind\": \"persona\"}]'::jsonb)"
)

# The original GLOBAL predicate (downgrade target) — a real reversal, not a stub.
GLOBAL_PREDICATE = "status != 'blocked' OR next_chase_ts IS NOT NULL"


def _table_exists( inspector ) -> bool:
    return TABLE_NAME in inspector.get_table_names()


def _constraint_names( inspector ) -> set:
    return { c[ "name" ] for c in inspector.get_check_constraints( TABLE_NAME ) }


def _swap_predicate( new_condition ) -> None:
    """
    Drop the blocked-chase CHECK (by name, if present) and recreate it with
    `new_condition`. Idempotent + inspector-guarded, mirroring the park migration:

        - no-op when task_items is absent (a fresh DB built straight from
          metadata already carries the model's constraint; nothing to migrate)
        - the DROP is guarded by name, so a partial / re-run state converges
        - the CREATE always runs after the DROP, so the constraint ends holding
          exactly `new_condition` regardless of which predicate it held before
    """
    inspector = inspect( op.get_bind() )
    if not _table_exists( inspector ):
        return
    if CONSTRAINT_NAME in _constraint_names( inspector ):
        op.drop_constraint( CONSTRAINT_NAME, TABLE_NAME, type_="check" )
    op.create_check_constraint( CONSTRAINT_NAME, TABLE_NAME, new_condition )


def upgrade() -> None:
    """Replace the global blocked-chase CHECK with the kind-aware predicate."""
    _swap_predicate( KIND_AWARE_PREDICATE )


def downgrade() -> None:
    """Restore the original global blocked-chase CHECK (a real reversal)."""
    _swap_predicate( GLOBAL_PREDICATE )
