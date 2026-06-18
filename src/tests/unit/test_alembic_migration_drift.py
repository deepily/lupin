"""
DB-free structural guards for migration e5f6a7b8c9d0 — the migration<->ORM
drift fix (4 tables + 5 notifications columns that the empty-DB
``alembic upgrade head`` path previously MISSED; see the migration docstring).

These assertions read straight from the migration script via Alembic's
``ScriptDirectory`` and a source-level inspection — they need NO Postgres, so
they run in the :7999 unit bucket / plain CI. The EMPIRICAL upgrade/downgrade
round-trip (which actually executes the DDL against a live Postgres) lives in
``src/tests/smoke/test_alembic_migration_drift_roundtrip.py`` and skips when no
database is reachable.

Sibling chain-integrity guards (single base/head, linear span, absorbed
revisions gone) live in ``test_alembic_baseline_chain.py``; this module focuses
on the e5f6a7b8c9d0 revision's own contract.
"""
import os

from alembic.script import ScriptDirectory

from cosa.rest.db.auto_migrate import build_alembic_config


_REVISION       = "e5f6a7b8c9d0"
_DOWN_REVISION  = "d4e5f6a7b8c9"   # rebased directly onto the prior head

# The four ORM tables this migration creates (had NO migration before it).
_DRIFT_TABLES = [ "proxy_decisions", "trust_states", "prediction_log", "server_lifecycle" ]

# The five notifications columns this migration adds (the OTHER five —
# direction/sender_persona/sender_icon/reply_to/thread_id — were already added
# by c3d4e5f6a7b8 and must NOT be re-added here).
_NOTIF_COLUMNS = [ "job_id", "progress_group_id", "abstract", "response_options", "is_hidden" ]


def _script_dir():
    """Build a ScriptDirectory over the project's migrations (no DB needed)."""
    config = build_alembic_config( database_url=None )
    return ScriptDirectory.from_config( config )


def _migration_source():
    """Return the raw source text of the e5f6a7b8c9d0 migration script."""
    rev = _script_dir().get_revision( _REVISION )
    with open( rev.path, "r", encoding="utf-8" ) as fh:
        return fh.read()


def test_revision_present_and_rebased_onto_prior_head():
    """e5f6a7b8c9d0 exists and chains directly onto d4e5f6a7b8c9."""
    rev = _script_dir().get_revision( _REVISION )
    assert rev is not None, f"migration {_REVISION!r} is missing from the chain"
    assert rev.down_revision == _DOWN_REVISION, (
        f"down_revision must be {_DOWN_REVISION!r} (prior head), got {rev.down_revision!r}"
    )


def test_chain_has_a_single_head():
    """The migration chain has exactly ONE head (no fork).

    Head IDENTITY moves as later migrations land — e5f6a7b8c9d0 was the head when
    this guard was written, but f6a7b8c9d0e1 (the task-project-alias migration)
    has since superseded it. So this guards the single-head INVARIANT (a forked
    chain breaks ``upgrade head``), NOT a frozen revision id that rots on every
    new migration.
    """
    heads = list( _script_dir().get_heads() )
    assert len( heads ) == 1, f"expected a single migration head (no fork), got {heads!r}"


def test_script_file_present():
    """The migration script physically exists under versions/."""
    rev = _script_dir().get_revision( _REVISION )
    assert rev.path.endswith(
        "e5f6a7b8c9d0_add_proxy_trust_prediction_serverlifecycle_tables_and_notif_columns.py"
    )
    assert os.path.isfile( rev.path )


def test_upgrade_creates_the_four_drift_tables():
    """upgrade() op.create_table()s each of the four previously-missing tables."""
    src = _migration_source()
    for table in _DRIFT_TABLES:
        assert f"op.create_table(\n        '{table}'" in src or f"'{table}'," in src, (
            f"upgrade() does not create table {table!r}"
        )


def test_upgrade_adds_the_five_notification_columns():
    """upgrade() op.add_column()s each of the five missing notifications columns."""
    src = _migration_source()
    for column in _NOTIF_COLUMNS:
        assert f"sa.Column( '{column}'" in src, (
            f"upgrade() does not add notifications column {column!r}"
        )


def test_does_not_readd_columns_already_added_by_c3d4e5f6a7b8():
    """The five DM/direction columns from c3d4e5f6a7b8 are NOT re-added here."""
    src = _migration_source()
    for already_added in [ "'direction'", "'sender_persona'", "'sender_icon'", "'reply_to'", "'thread_id'" ]:
        assert f"sa.Column( {already_added}" not in src, (
            f"column {already_added} was already added by c3d4e5f6a7b8 — must not be re-added"
        )


def test_downgrade_drops_the_four_tables_and_five_columns():
    """downgrade() reverses upgrade(): drops every table + column it created."""
    src = _migration_source()
    for table in _DRIFT_TABLES:
        assert f"op.drop_table( '{table}' )" in src, f"downgrade() does not drop table {table!r}"
    for column in _NOTIF_COLUMNS:
        assert f"op.drop_column( 'notifications', '{column}' )" in src, (
            f"downgrade() does not drop notifications column {column!r}"
        )
