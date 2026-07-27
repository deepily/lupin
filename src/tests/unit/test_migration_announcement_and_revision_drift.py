"""
Row `0aae1a28` — (a) announce an APPLIED migration, (c) alarm on schema BEHIND head.

THE HAZARD
----------
`:7999` runs uvicorn with StatReload over a bind-mounted repo, so **saving** a
watched host file restarts the server, and startup runs `alembic upgrade head`.
Not committing. Not bouncing. Saving. A schema change reaches the fleet's task
store with no gate and — until this row — no announcement: `command.upgrade` is
silent whether it moves the database or no-ops. María spent an afternoon asking
for a deploy window for a change that had already shipped hours earlier.

⚠️ Mr Radio's ruling, and the reason (b) is absent here: the third candidate
remedy — excluding `src/migrations/` from the reload watch — is **INERT and must
not be built**. `reload_excludes` does nothing without `watchfiles`, which is not
in the image, so uvicorn falls back to StatReload and ignores excludes. Documented
verbatim at `main.py:1189-1197` from bug `5b654a15`. It is moot regardless: the
`reload_dirs` whitelist already omits `migrations`.

WHAT (c) ACTUALLY FIXES — and it is not what the row's title suggests
---------------------------------------------------------------------
`check_schema_drift` read the alembic revisions **only after** finding a missing
column:

    drift = find_missing_columns( ... )
    if not drift: return None          # <- revisions never read
    db_revision, head_revision = read_revisions( engine )

So the revision comparison was **dead code unless a column was already gone** —
the revisions were decoration on an alarm something else had already raised.
A migration that changes only an index, a constraint, or a column TYPE moves the
revision **without changing the column set**, so column-diffing is structurally
blind to it and the early return reported it clean.

That is the same distinction as preflight C7-vs-C8 (`4aa2b9d5` / `3eb6dc41`), one
layer in: presence-of-columns is the SYMPTOM, revision-vs-head is the CAUSE, and
neither subsumes the other.

⚠️ WHAT A GREEN HERE DOES NOT MEAN
- It does not mean the announcement was *seen*. This is an announcement, not a
  gate, and Mr Radio ruled it as such — a log line is not claimed to be a guard.
- It does not cover the `print` statement in `main.py`'s lifespan itself. What is
  covered is the load-bearing half: the `applied` flag that gates it. Stated
  rather than left for a reader to assume from a coverage number.

Venue: :7999 unit tier. No network, no Postgres, no persistent state.
"""

import pytest

from cosa.rest.db import auto_migrate, schema_drift
from cosa.rest.db.schema_drift import (
    KIND_MISSING_COLUMN,
    KIND_REVISION_BEHIND,
    check_schema_drift,
    format_drift_alarm,
)


# ── (c) the revision comparison is now an INDEPENDENT check ──────────────────

def _stub_engine_path( monkeypatch, missing_columns, revisions ):
    """
    Drive check_schema_drift's two inputs without a database.

    Ensures:
        - find_missing_columns returns `missing_columns`
        - read_revisions returns `revisions`
        - the engine is a stub whose dispose() is harmless
    """
    class _StubEngine:
        def dispose( self ): pass

    monkeypatch.setattr( schema_drift, "create_engine",        lambda url: _StubEngine() )
    monkeypatch.setattr( schema_drift, "find_missing_columns", lambda *a, **k: list( missing_columns ) )
    monkeypatch.setattr( schema_drift, "read_revisions",       lambda engine: revisions )
    monkeypatch.setattr( "cosa.rest.db.auto_migrate.resolve_database_url", lambda url=None: "sqlite://" )


def test_a_database_BEHIND_head_alarms_even_with_every_column_present( monkeypatch ):
    """
    THE REGRESSION LOCK. Before this row the early return made this exact case —
    complete column set, revision behind — report clean.
    """
    _stub_engine_path( monkeypatch, missing_columns=[], revisions=( "aaa111", "bbb222" ) )

    report = check_schema_drift()

    assert report is not None, "a DB behind head with a complete column set reported CLEAN"
    kinds = [ row[ "kind" ] for row in report[ "drift" ] ]
    assert KIND_REVISION_BEHIND in kinds
    assert report[ "db_revision" ]   == "aaa111"
    assert report[ "head_revision" ] == "bbb222"


def test_a_database_AT_head_with_every_column_present_stays_silent( monkeypatch ):
    """The other arm. Without it, a detector that always fires would pass above."""
    _stub_engine_path( monkeypatch, missing_columns=[], revisions=( "same999", "same999" ) )
    assert check_schema_drift() is None


def test_the_two_arms_DISAGREE( monkeypatch ):
    """
    THE CONTROL. The two tests above are individually satisfiable by a constant —
    "always alarm" passes the first, "never alarm" passes the second. Only their
    DISAGREEMENT proves the revision comparison is what is being measured.
    """
    _stub_engine_path( monkeypatch, missing_columns=[], revisions=( "aaa111", "bbb222" ) )
    behind = check_schema_drift()
    _stub_engine_path( monkeypatch, missing_columns=[], revisions=( "aaa111", "aaa111" ) )
    at_head = check_schema_drift()

    assert ( behind is None ) != ( at_head is None ), (
        "both arms returned the same verdict — the revision comparison is inert"
    )


@pytest.mark.parametrize( "revisions", [ ( None, "bbb222" ), ( "aaa111", None ), ( None, None ) ] )
def test_an_UNREADABLE_revision_never_manufactures_an_alarm( monkeypatch, revisions ):
    """
    A detector must not fire on its own blindness. `read_revisions` degrades to
    None rather than raising, and None != "bbb222" is True in Python — so without
    the explicit both-readable guard this would alarm every time the revision
    could not be read.
    """
    _stub_engine_path( monkeypatch, missing_columns=[], revisions=revisions )
    assert check_schema_drift() is None


def test_a_missing_column_still_alarms_and_now_carries_the_revision_finding_too( monkeypatch ):
    """Both findings coexist; neither displaces the other."""
    col = { "kind": KIND_MISSING_COLUMN, "table": "t", "column": "c", "model": "M" }
    _stub_engine_path( monkeypatch, missing_columns=[ col ], revisions=( "aaa111", "bbb222" ) )

    report = check_schema_drift()
    kinds  = [ row[ "kind" ] for row in report[ "drift" ] ]
    assert KIND_MISSING_COLUMN  in kinds
    assert KIND_REVISION_BEHIND in kinds


# ── the alarm TEXT must not overstate ────────────────────────────────────────

def test_a_revision_only_finding_does_NOT_claim_a_live_500():
    """
    A missing column IS a live 500; a revision gap alone is not. An alarm that
    overstates gets discounted the next time it fires correctly.
    """
    text = format_drift_alarm(
        [ { "kind": KIND_REVISION_BEHIND, "table": None, "column": None, "model": None } ],
        "aaa111", "bbb222",
    )
    assert "BEHIND THE TREE'S MIGRATION HEAD" in text
    assert "CRITICAL: ORM/DATABASE SCHEMA DRIFT" not in text
    assert "UndefinedColumn" not in text
    assert "NOT a live 500" in text
    assert "REVISION BEHIND  db=aaa111 tree=bbb222" in text
    assert "ANYWAY" in text, "fail-open must stay legible"


def test_a_column_finding_keeps_its_original_diagnosis_and_remedy():
    """The pre-existing contract must not have been traded away for the new one."""
    text = format_drift_alarm(
        [ { "kind": KIND_MISSING_COLUMN, "table": "t", "column": "c", "model": "M" } ],
        "aaa111", "bbb222",
    )
    assert "CRITICAL: ORM/DATABASE SCHEMA DRIFT" in text
    assert "UndefinedColumn" in text
    assert "allowlist" in text
    assert "REVISION BEHIND" not in text


def test_a_mixed_finding_prints_BOTH_remedies():
    """Two diagnoses, two remedies — collapsing them would send half the readers wrong."""
    text = format_drift_alarm(
        [ { "kind": KIND_MISSING_COLUMN, "table": "t", "column": "c", "model": "M" },
          { "kind": KIND_REVISION_BEHIND, "table": None, "column": None, "model": None } ],
        "aaa111", "bbb222",
    )
    assert "allowlist" in text                       # the column remedy
    assert "did NOT take" in text                    # the revision remedy
    assert "2 drift finding(s)" in text


# ── (a) an applied migration is distinguishable from a no-op ─────────────────

def _stub_migrate( monkeypatch, before, after, has_version_table=True, has_app_tables=True ):
    """Drive run_migrations_to_head's revision reads without a database."""
    seen = iter( [ before, after ] )
    monkeypatch.setattr( auto_migrate, "resolve_database_url", lambda url=None: "sqlite://" )
    monkeypatch.setattr( auto_migrate, "build_alembic_config", lambda database_url=None: object() )
    monkeypatch.setattr( auto_migrate, "_inspect_db_state",    lambda url: ( has_version_table, has_app_tables ) )
    monkeypatch.setattr( auto_migrate, "_read_current_revision", lambda url: next( seen ) )
    monkeypatch.setattr( auto_migrate.command, "upgrade", lambda *a, **k: None )
    monkeypatch.setattr( auto_migrate.command, "stamp",   lambda *a, **k: None )


def test_a_migration_that_MOVES_the_revision_reports_applied( monkeypatch ):
    _stub_migrate( monkeypatch, before="aaa111", after="bbb222" )
    result = auto_migrate.run_migrations_to_head()
    assert result[ "applied" ] is True
    assert result[ "before" ] == "aaa111" and result[ "after" ] == "bbb222"
    assert result[ "bootstrapped" ] is False


def test_a_NO_OP_migrate_reports_applied_False( monkeypatch ):
    """
    The whole point. A line printed on every boot is a line nobody reads, so the
    announcement must fire ONLY when the database actually moved.
    """
    _stub_migrate( monkeypatch, before="aaa111", after="aaa111" )
    assert auto_migrate.run_migrations_to_head()[ "applied" ] is False


def test_an_unreadable_after_revision_does_not_claim_a_deploy( monkeypatch ):
    """None != 'aaa111' is True — without the explicit not-None guard, a failed
    revision read would announce a migration that never happened."""
    _stub_migrate( monkeypatch, before="aaa111", after=None )
    assert auto_migrate.run_migrations_to_head()[ "applied" ] is False


def test_a_BOOTSTRAP_is_not_reported_as_an_applied_migration( monkeypatch ):
    """
    A fresh DB is built from the models and stamped — nothing was upgraded.
    Reporting it as applied would make a first boot indistinguishable from a live
    schema change, which is the distinction this value exists to draw.
    """
    from unittest.mock import MagicMock

    class _StubConn:
        def execute( self, *a, **k ): return None

    class _StubEngine:
        def begin( self ):
            conn = _StubConn()
            class _Ctx:
                def __enter__( self ): return conn
                def __exit__( self, *a ): return False
            return _Ctx()
        def dispose( self ): pass

    # The bootstrap arm issues `CREATE EXTENSION vector` — pgvector DDL SQLite
    # cannot parse. Stubbing the engine keeps this a unit test of the RETURN
    # CONTRACT; the DDL itself is covered by the alembic bootstrap smoke suite.
    monkeypatch.setattr( auto_migrate, "create_engine", lambda url: _StubEngine() )
    monkeypatch.setattr( "cosa.rest.postgres_models.Base", MagicMock() )
    _stub_migrate( monkeypatch, before=None, after="bbb222",
                   has_version_table=False, has_app_tables=False )

    result = auto_migrate.run_migrations_to_head()
    assert result[ "bootstrapped" ] is True
    assert result[ "applied" ] is False


def test_read_current_revision_NEVER_raises( monkeypatch ):
    """
    Observability must not be able to fail a migration. A bad URL is the cheapest
    way to make the read blow up inside.
    """
    assert auto_migrate._read_current_revision( "not-a-url://nope" ) is None
