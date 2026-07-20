"""
Unit tests for the Half 3b startup drift alarm (cosa.rest.db.schema_drift).

SCOPE NOTE — what these tests are and are NOT:
    The detector's oracle was proven RED against a REAL PostgreSQL database
    carrying the REAL historical drift (task_items.park_reason_captured_at, the
    column whose absence produced 12 live 500s on 2026-07-19). That proof is not
    reproducible in the unit tier, because postgres_models uses JSONB/UUID/INET
    types SQLite cannot render. Control receipts live in the SEAT 3 report.

    These tests are the hermetic regression lock and the coverage gate. They run
    real SQLAlchemy reflection against a real (SQLite) database — the instrument
    is never mocked. What IS substituted is the SUBJECT of the comparison: a
    small synthetic declarative base standing in for postgres_models.Base. That
    substitution changes what is being compared, not how, so a degradation in the
    comparison itself still shows up here.

Venue: :7999 unit tier. No network, no Postgres, no persistent state.
"""

import sys

import pytest
from sqlalchemy import create_engine, Integer, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from cosa.rest.db import schema_drift
from cosa.rest.db.schema_drift import (
    KIND_MISSING_COLUMN,
    KIND_MISSING_TABLE,
    check_schema_drift,
    emit_startup_drift_alarm,
    find_missing_columns,
    format_drift_alarm,
    model_names_by_table,
    read_revisions,
)


class SampleBase( DeclarativeBase ):
    """Stand-in for postgres_models.Base — SQLite-renderable types only."""
    pass


class Widget( SampleBase ):
    __tablename__ = "widgets"

    id:         Mapped[int] = mapped_column( Integer, primary_key=True )
    name:       Mapped[str] = mapped_column( String( 32 ) )
    late_added: Mapped[str] = mapped_column( String( 32 ), nullable=True )


class Gadget( SampleBase ):
    __tablename__ = "gadgets"

    id: Mapped[int] = mapped_column( Integer, primary_key=True )


@pytest.fixture
def sqlite_url( tmp_path ):
    """A real on-disk SQLite database, reflected by the real inspector."""
    return f"sqlite:///{tmp_path / 'drift.db'}"


def _build_full( url ):
    engine = create_engine( url )
    try:
        SampleBase.metadata.create_all( engine )
    finally:
        engine.dispose()


def _drift_for( url ):
    engine = create_engine( url )
    try:
        return find_missing_columns( engine, SampleBase.metadata, model_names_by_table( SampleBase ) )
    finally:
        engine.dispose()


class TestModelNamesByTable:

    def test_maps_every_mapped_table_to_its_class( self ):
        names = model_names_by_table( SampleBase )
        assert names == { "widgets": "Widget", "gadgets": "Gadget" }

    def test_skips_mapper_with_no_local_table( self ):
        """A mapper whose local_table is unresolvable is skipped, not raised on."""
        class FakeMapper:
            local_table = None
            class_       = Widget

        class FakeRegistry:
            mappers = [ FakeMapper() ]

        class FakeBase:
            registry = FakeRegistry()

        assert model_names_by_table( FakeBase ) == {}


class TestFindMissingColumns:

    def test_clean_database_reports_nothing( self, sqlite_url ):
        _build_full( sqlite_url )
        assert _drift_for( sqlite_url ) == []

    def test_missing_column_is_reported_with_model_and_kind( self, sqlite_url ):
        """The 500-causing class: ORM maps it, the DB does not have it."""
        _build_full( sqlite_url )
        engine = create_engine( sqlite_url )
        try:
            with engine.begin() as conn:
                conn.execute( text( "ALTER TABLE widgets DROP COLUMN late_added" ) )
        finally:
            engine.dispose()

        drift = _drift_for( sqlite_url )
        assert drift == [ {
            "table"  : "widgets",
            "column" : "late_added",
            "model"  : "Widget",
            "kind"   : KIND_MISSING_COLUMN
        } ]

    def test_missing_table_yields_one_row_not_per_column( self, sqlite_url ):
        """A missing table is ONE actionable finding, not N column findings."""
        _build_full( sqlite_url )
        engine = create_engine( sqlite_url )
        try:
            with engine.begin() as conn:
                conn.execute( text( "DROP TABLE widgets" ) )
        finally:
            engine.dispose()

        drift = _drift_for( sqlite_url )
        assert drift == [ {
            "table"  : "widgets",
            "column" : None,
            "model"  : "Widget",
            "kind"   : KIND_MISSING_TABLE
        } ]

    def test_empty_database_reports_every_mapped_table( self, sqlite_url ):
        """Harness-connected control: if this ever came back clean, the
        instrument would be disconnected rather than the schema perfect."""
        drift = _drift_for( sqlite_url )
        assert { row[ "table" ] for row in drift } == { "widgets", "gadgets" }
        assert all( row[ "kind" ] == KIND_MISSING_TABLE for row in drift )

    def test_detector_is_table_scoped_not_a_global_name_search( self, sqlite_url ):
        """The degradation control: the same column NAME present on another
        table must NOT suppress the finding on the table that lacks it. A global
        name-set oracle would go quiet here; a table-scoped one does not."""
        _build_full( sqlite_url )
        engine = create_engine( sqlite_url )
        try:
            with engine.begin() as conn:
                conn.execute( text( "ALTER TABLE widgets DROP COLUMN late_added" ) )
                conn.execute( text( "ALTER TABLE gadgets ADD COLUMN late_added VARCHAR(32)" ) )
        finally:
            engine.dispose()

        drift = _drift_for( sqlite_url )
        assert drift == [ {
            "table"  : "widgets",
            "column" : "late_added",
            "model"  : "Widget",
            "kind"   : KIND_MISSING_COLUMN
        } ]

    def test_model_names_defaults_to_unknown_marker( self, sqlite_url ):
        """Called without a name map, findings still render — model is '?'."""
        engine = create_engine( sqlite_url )
        try:
            drift = find_missing_columns( engine, SampleBase.metadata )
        finally:
            engine.dispose()
        assert drift and all( row[ "model" ] == "?" for row in drift )

    def test_findings_are_sorted_for_stable_alarm_text( self, sqlite_url ):
        drift = _drift_for( sqlite_url )
        assert [ row[ "table" ] for row in drift ] == sorted( row[ "table" ] for row in drift )


class TestReadRevisions:

    def test_returns_none_pair_when_unreadable( self, sqlite_url ):
        """A SQLite DB with no alembic_version yields (None, ...) rather than
        raising — revisions are advisory context, never a gate."""
        engine = create_engine( sqlite_url )
        try:
            db_revision, _head = read_revisions( engine )
        finally:
            engine.dispose()
        assert db_revision is None

    def test_reads_stamped_revision_when_present( self, sqlite_url ):
        engine = create_engine( sqlite_url )
        try:
            with engine.begin() as conn:
                conn.execute( text( "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)" ) )
                conn.execute( text( "INSERT INTO alembic_version VALUES ('d47487369407')" ) )
            db_revision, _head = read_revisions( engine )
        finally:
            engine.dispose()
        assert db_revision == "d47487369407"

    def test_head_lookup_failure_degrades_to_none( self, sqlite_url, monkeypatch ):
        def boom( *args, **kwargs ):
            raise RuntimeError( "no migrations dir" )

        monkeypatch.setattr( "cosa.rest.db.auto_migrate.build_alembic_config", boom )
        engine = create_engine( sqlite_url )
        try:
            _db, head = read_revisions( engine )
        finally:
            engine.dispose()
        assert head is None

    def test_connection_failure_degrades_to_none( self ):
        engine = create_engine( "sqlite:////nonexistent-dir/nope.db" )
        db_revision, _head = read_revisions( engine )
        assert db_revision is None


class TestFormatDriftAlarm:

    def test_names_model_table_column_and_revisions( self ):
        text_out = format_drift_alarm(
            [ { "table": "task_items", "column": "park_reason_captured_at",
                "model": "TaskItem", "kind": KIND_MISSING_COLUMN } ],
            "d47487369407", "d47487369407"
        )
        # Mr. Radio's constraint: an alarm reading only "drift detected"
        # reproduces the diagnosis cost it exists to remove.
        assert "task_items" in text_out
        assert "park_reason_captured_at" in text_out
        assert "TaskItem" in text_out
        assert "d47487369407" in text_out
        assert "CRITICAL" in text_out

    def test_renders_missing_table_branch( self ):
        text_out = format_drift_alarm(
            [ { "table": "widgets", "column": None, "model": "Widget",
                "kind": KIND_MISSING_TABLE } ],
            None, None
        )
        assert "TABLE MISSING" in text_out
        assert "widgets" in text_out

    def test_unknown_revisions_render_as_unknown( self ):
        text_out = format_drift_alarm(
            [ { "table": "t", "column": "c", "model": "M", "kind": KIND_MISSING_COLUMN } ],
            None, None
        )
        assert "unknown" in text_out

    def test_states_that_the_server_serves_anyway( self ):
        """Fail-open must be legible in the alarm itself — a reader must not
        conclude the box refused to boot."""
        text_out = format_drift_alarm(
            [ { "table": "t", "column": "c", "model": "M", "kind": KIND_MISSING_COLUMN } ],
            None, None
        )
        assert "ANYWAY" in text_out
        assert "allowlist" in text_out


class TestCheckSchemaDrift:

    def test_returns_none_when_schema_satisfies_models( self, sqlite_url, monkeypatch ):
        _build_full( sqlite_url )
        monkeypatch.setattr( "cosa.rest.db.auto_migrate.resolve_database_url", lambda url=None: sqlite_url )
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )
        assert check_schema_drift() is None

    def test_returns_report_with_revisions_when_drifted( self, sqlite_url, monkeypatch ):
        monkeypatch.setattr( "cosa.rest.db.auto_migrate.resolve_database_url", lambda url=None: sqlite_url )
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )

        report = check_schema_drift()
        assert report is not None
        assert len( report[ "drift" ] ) == 2
        assert "db_revision" in report and "head_revision" in report

    def test_explicit_url_argument_is_honoured( self, sqlite_url, monkeypatch ):
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )
        report = check_schema_drift( database_url=sqlite_url )
        assert report is not None


class TestEmitStartupDriftAlarm:
    """The boot-path contract: never raises, never blocks, always fail-open."""

    def test_writes_critical_alarm_to_stderr_on_drift( self, sqlite_url, monkeypatch, capsys ):
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )
        report = emit_startup_drift_alarm( database_url=sqlite_url )

        assert report is not None
        captured = capsys.readouterr()
        assert "CRITICAL" in captured.err
        assert "widgets" in captured.err

    def test_returns_none_and_is_silent_when_clean( self, sqlite_url, monkeypatch, capsys ):
        _build_full( sqlite_url )
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )

        assert emit_startup_drift_alarm( database_url=sqlite_url ) is None
        assert capsys.readouterr().err == ""

    def test_debug_prints_clean_one_liner( self, sqlite_url, monkeypatch, capsys ):
        _build_full( sqlite_url )
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )

        emit_startup_drift_alarm( database_url=sqlite_url, debug=True )
        assert "No ORM/database drift detected" in capsys.readouterr().out

    def test_detector_failure_is_swallowed_and_reported( self, monkeypatch, capsys ):
        """A bug in the detector must NOT be able to abort a boot that would
        otherwise have succeeded. This is the fail-open contract itself."""
        def boom( *args, **kwargs ):
            raise RuntimeError( "detector exploded" )

        monkeypatch.setattr( schema_drift, "check_schema_drift", boom )

        assert emit_startup_drift_alarm() is None          # returned, did not raise
        captured = capsys.readouterr()
        assert "continuing boot (fail-open)" in captured.err
        assert "detector exploded" in captured.err

    def test_makes_no_network_call( self, sqlite_url, monkeypatch ):
        """The alarm's transport must never be the server that is still booting.
        Any socket use in the pre-yield path is a defect, so forbid it outright."""
        import socket

        def forbidden( *args, **kwargs ):
            raise AssertionError( "schema drift alarm attempted network I/O" )

        monkeypatch.setattr( socket.socket, "connect", forbidden )
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )

        emit_startup_drift_alarm( database_url=sqlite_url )   # must not raise

    def test_is_not_a_coroutine( self ):
        """Nothing in the pre-yield critical path may be awaited."""
        import inspect as _inspect
        assert not _inspect.iscoroutinefunction( emit_startup_drift_alarm )


# ─────────────────────────────────────────────────────────────────────────────
# The notification leg — the SECOND channel.
#
# Ratified by Rick 2026-07-19: one INI key, EMPTY DEFAULT. The empty-default
# path gets the most attention here because it is the configuration every
# unconfigured deployment actually runs.
# ─────────────────────────────────────────────────────────────────────────────


class FakeUser:
    def __init__( self, user_id="u-123" ):
        self.id = user_id


class RecordingQueue:
    """Stands in for NotificationFifoQueue, recording what it was handed."""

    def __init__( self ):
        self.pushed = []

    def push_notification( self, **kwargs ):
        self.pushed.append( kwargs )


REPORT = {
    "drift": [ {
        "table"  : "task_items",
        "column" : "park_reason_captured_at",
        "model"  : "TaskItem",
        "kind"   : KIND_MISSING_COLUMN
    } ],
    "db_revision"   : "d47487369407",
    "head_revision" : "d47487369407"
}


def _patch_user_lookup( monkeypatch, user ):
    """Patch the DB seam only — the resolution logic under test is untouched."""
    class FakeSession:
        def close( self ): pass

    class FakeRepo:
        def __init__( self, db ): pass
        def get_by_email( self, email ): return user

    monkeypatch.setattr( "cosa.rest.db.database.get_db", lambda: iter( [ FakeSession() ] ) )
    monkeypatch.setattr( "cosa.rest.db.repositories.user_repository.UserRepository", FakeRepo )


class TestBuildDriftNotification:

    def test_spoken_line_gives_the_count_not_the_inventory( self ):
        message, abstract = schema_drift.build_drift_notification( REPORT )
        assert "1 finding" in message
        assert "serving anyway" in message.lower()
        # The per-column detail belongs in the card, never in the spoken line.
        assert "park_reason_captured_at" not in message
        assert "park_reason_captured_at" in abstract

    def test_pluralises_correctly( self ):
        two = dict( REPORT, drift=REPORT[ "drift" ] * 2 )
        assert "2 findings" in schema_drift.build_drift_notification( two )[ 0 ]


class TestPushDriftNotification:

    def test_enqueues_for_a_resolvable_recipient( self, monkeypatch ):
        _patch_user_lookup( monkeypatch, FakeUser() )
        queue = RecordingQueue()

        assert schema_drift.push_drift_notification( REPORT, "rick@example.com", queue ) is True
        assert len( queue.pushed ) == 1
        assert queue.pushed[ 0 ][ "user_id" ]  == "u-123"
        assert queue.pushed[ 0 ][ "priority" ] == "urgent"
        assert "park_reason_captured_at" in queue.pushed[ 0 ][ "abstract" ]

    def test_unresolvable_recipient_warns_loudly_and_skips( self, monkeypatch, capsys ):
        """push_notification() accepts an unknown user_id SILENTLY, so a
        misconfigured key would otherwise vanish without trace — indistinguishable
        from a clean boot, which is the failure mode this detector exists to
        remove. It must be loud."""
        _patch_user_lookup( monkeypatch, None )
        queue = RecordingQueue()

        assert schema_drift.push_drift_notification( REPORT, "ghost@example.com", queue ) is False
        assert queue.pushed == []
        err = capsys.readouterr().err
        assert "does not resolve to a user" in err
        assert "ghost@example.com" in err
        assert "alarm of record" in err


class TestDeliverDriftNotification:

    @pytest.mark.asyncio
    async def test_delivers_successfully( self, monkeypatch ):
        _patch_user_lookup( monkeypatch, FakeUser() )
        queue = RecordingQueue()
        assert await schema_drift.deliver_drift_notification( REPORT, "rick@example.com", queue ) is True

    @pytest.mark.asyncio
    async def test_delivery_failure_is_swallowed( self, monkeypatch, capsys ):
        """The second channel must never be able to damage the first."""
        def boom( *args, **kwargs ):
            raise RuntimeError( "notification backend down" )

        monkeypatch.setattr( schema_drift, "push_drift_notification", boom )

        assert await schema_drift.deliver_drift_notification( REPORT, "rick@example.com", RecordingQueue() ) is False
        assert "CRITICAL log stands" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_slow_delivery_is_abandoned_at_the_timeout( self, monkeypatch, capsys ):
        import time as _time

        def slow( *args, **kwargs ):
            _time.sleep( 2.0 )
            return True

        monkeypatch.setattr( schema_drift, "push_drift_notification", slow )

        result = await schema_drift.deliver_drift_notification(
            REPORT, "rick@example.com", RecordingQueue(), timeout_seconds=0.05
        )
        assert result is False
        assert "CRITICAL log stands" in capsys.readouterr().err


class TestScheduleDriftNotification:
    """The pre-yield call site: must schedule without blocking, or no-op."""

    @pytest.mark.asyncio
    async def test_schedules_a_task_when_configured_and_drifted( self, monkeypatch ):
        _patch_user_lookup( monkeypatch, FakeUser() )
        queue = RecordingQueue()

        task = schema_drift.schedule_drift_notification( REPORT, "rick@example.com", queue )
        assert task is not None
        # Nothing has run yet: create_task only QUEUES the coroutine. This is the
        # whole "post-yield" mechanism — the loop must resume before it executes.
        assert queue.pushed == []

        await task
        assert len( queue.pushed ) == 1

    @pytest.mark.asyncio
    async def test_no_drift_schedules_nothing( self ):
        assert schema_drift.schedule_drift_notification( None, "rick@example.com", RecordingQueue() ) is None

    @pytest.mark.asyncio
    async def test_missing_queue_schedules_nothing( self ):
        assert schema_drift.schedule_drift_notification( REPORT, "rick@example.com", None ) is None

    def test_no_running_loop_is_survivable( self, capsys ):
        """Called outside an event loop it must warn and return, never raise —
        a scheduling failure cannot be allowed to abort boot."""
        assert schema_drift.schedule_drift_notification( REPORT, "rick@example.com", RecordingQueue() ) is None
        assert "CRITICAL log stands" in capsys.readouterr().err


class TestEmptyRecipientDefault:
    """🔴 THE DEFAULT CONFIGURATION — the one every unconfigured server runs.

    Rick's ratified spec: empty key ⇒ the notification is NOT attempted and the
    CRITICAL log still fires. Both halves are asserted. A test asserting only
    'no notify' would pass just as happily if the entire alarm had gone silent,
    which is the exact failure this pair exists to exclude."""

    @pytest.mark.asyncio
    async def test_empty_recipient_attempts_no_notification( self ):
        queue = RecordingQueue()
        assert schema_drift.schedule_drift_notification( REPORT, "", queue ) is None
        assert queue.pushed == []

    @pytest.mark.asyncio
    async def test_none_recipient_attempts_no_notification( self ):
        queue = RecordingQueue()
        assert schema_drift.schedule_drift_notification( REPORT, None, queue ) is None
        assert queue.pushed == []

    def test_critical_log_still_fires_with_no_recipient_configured( self, sqlite_url, monkeypatch, capsys ):
        """The other half: log-only is a DEGRADED channel, not a silent one."""
        monkeypatch.setattr( "cosa.rest.postgres_models.Base", SampleBase )
        queue  = RecordingQueue()

        report = emit_startup_drift_alarm( database_url=sqlite_url )
        schema_drift.schedule_drift_notification( report, "", queue )

        assert report is not None
        assert queue.pushed == []
        assert "CRITICAL" in capsys.readouterr().err
