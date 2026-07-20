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
