#!/usr/bin/env python3
"""
The approval-settings store (row 80513825): reads, writes, outage behaviour, one-time import.

Covers the DB-backed paths of `task_approval_settings` and the repository under it. The
repository arms run against a real (in-memory sqlite) database with only this table created;
the outage and import arms use the in-memory backend the autouse fixture installs.
"""
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cosa.rest.task_approval_settings as approval
from cosa.rest.db.repositories.approval_setting_repository import ApprovalSettingRepository
from cosa.rest.postgres_models import ApprovalSetting
from tests.helpers.approval_settings_fixtures import MemoryBackend, seed, stamped_json


# ── the repository, against a real database ─────────────────────────────────────────────

@pytest.fixture
def session():
    engine = create_engine( "sqlite://" )
    ApprovalSetting.__table__.create( engine )
    with sessionmaker( bind=engine )() as db:
        yield db


def test_repository_upserts_and_reads_back( session ):
    repo = ApprovalSettingRepository( session )
    assert repo.get_all() == {}

    repo.upsert_many( { "enforcement_active": True, "approvers": [ "a" ] }, "rick@example.com" )
    repo.upsert_many( { "enforcement_active": False }, "someone@example.com" )

    assert repo.get_all() == { "enforcement_active": False, "approvers": [ "a" ] }
    assert repo.has_key( "approvers" ) and not repo.has_key( "nope" )
    row = session.get( ApprovalSetting, "enforcement_active" )
    assert row.updated_by == "someone@example.com" and row.updated_ts is not None


# ── the DB backend wires get_db to the repository ───────────────────────────────────────

def test_the_db_backend_round_trips_through_get_db( monkeypatch, session ):
    from contextlib import contextmanager
    import cosa.rest.db.database as database

    @contextmanager
    def fake_get_db():
        yield session
        session.commit()

    monkeypatch.setattr( database, "get_db", fake_get_db )
    backend = approval._DbBackend()

    backend.write( { "manager_pull_disabled": False }, "rick@example.com" )
    assert backend.load() == { "manager_pull_disabled": False }


# ── reads: cache, empty store, outage ───────────────────────────────────────────────────

def test_an_empty_store_reads_as_no_overrides():
    assert approval._read_overrides() == { key: None for key in approval._STORED_KEYS }


def test_a_stored_value_is_served_and_cached_for_the_ttl( monkeypatch ):
    seed( { "enforcement_active": True } )
    assert approval._read_overrides()[ "enforcement_active" ] is True

    approval._backend.rows[ "enforcement_active" ] = False       # another process writes
    assert approval._read_overrides()[ "enforcement_active" ] is True     # still inside the TTL

    monkeypatch.setattr( approval, "CACHE_TTL_SECONDS", 0 )
    assert approval._read_overrides()[ "enforcement_active" ] is False


def test_an_unreadable_store_falls_back_to_ini_and_says_so_loudly( capsys ):
    approval._backend.fail_with = ConnectionError( "db down" )

    assert approval._read_overrides() == { key: None for key in approval._STORED_KEYS }
    # the per-key direction the docstring promises
    assert approval.get_manager_pull_disabled() is True          # fails CLOSED
    assert approval.get_enforcement_active() in ( True, False )  # the INI decides

    out = capsys.readouterr().out
    assert "🔴" in out and "db down" in out and "fails OPEN" in out and "fails CLOSED" in out


def test_the_outage_line_is_rate_limited( capsys ):
    approval._backend.fail_with = ConnectionError( "db down" )
    approval._read_overrides()
    approval._read_overrides()
    assert capsys.readouterr().out.count( "🔴" ) == 1

    approval._outage_logged_at = time.monotonic() - approval.OUTAGE_LOG_INTERVAL_SECONDS - 1
    approval._read_overrides()
    assert capsys.readouterr().out.count( "🔴" ) == 1


def test_a_failed_read_is_not_cached():
    approval._backend.fail_with = ConnectionError( "db down" )
    approval._read_overrides()

    approval._backend.fail_with = None
    approval._backend.rows      = { "enforcement_active": True }
    assert approval._read_overrides()[ "enforcement_active" ] is True


# ── writes ──────────────────────────────────────────────────────────────────────────────

def test_a_write_records_who_and_is_visible_at_once():
    approval.set_overrides( updated_by="rick@example.com", enforcement_active=True )

    assert approval._backend.rows[ "enforcement_active" ] is True
    assert approval._backend.updated_by[ "enforcement_active" ] == "rick@example.com"
    assert approval.get_enforcement_active() is True             # cache invalidated by the write


def test_a_write_preserves_every_other_stored_key():
    seed( { "approvers": [ "maria" ], "enforcement_active": True } )
    approval.set_overrides( manager_pull_disabled=False )
    assert approval._backend.rows == { "approvers": [ "maria" ], "enforcement_active": True,
                                       "manager_pull_disabled": False }


def test_the_stamp_key_is_not_writable():
    with pytest.raises( ValueError ):
        approval.set_overrides( **{ approval.STAMP_KEY: "x" } )


def test_boot_runs_the_legacy_import_after_the_migration():
    """
    The import is only a control if boot calls it, and a control nobody calls is decoration.
    Source predicate over lupin_app/main.py: the import call follows the migrate call.
    """
    import os
    path   = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "lupin_app", "main.py" )
    source = open( path ).read()
    assert source.count( "import_legacy_override_file()" ) == 1
    assert source.index( "run_migrations_to_head( debug=app_debug )" ) < source.index( "import_legacy_override_file()" )


def test_the_pull_toggle_write_records_who():
    assert approval.set_manager_pull_disabled( False, updated_by="rick@example.com" ) is False
    assert approval._backend.updated_by[ "manager_pull_disabled" ] == "rick@example.com"


def test_a_write_to_an_unreachable_store_raises_oserror_and_changes_nothing():
    approval._backend.fail_with = ConnectionError( "db down" )
    with pytest.raises( OSError, match="could not write" ):
        approval.set_overrides( enforcement_active=True )
    assert approval._backend.rows == {}


# ── the one-time import of the retired file ─────────────────────────────────────────────

@pytest.fixture
def legacy_dir( tmp_path, monkeypatch ):
    monkeypatch.setenv( "LUPIN_FLOW_RATIO_DIR", str( tmp_path ) )
    return tmp_path


def test_the_legacy_path_falls_back_to_the_fleet_data_root( monkeypatch ):
    monkeypatch.delenv( "LUPIN_FLOW_RATIO_DIR", raising=False )
    monkeypatch.setattr( approval, "fleet_data_root", lambda: "/data/lupin" )
    assert approval.legacy_override_path() == "/data/lupin/flow-ratio/task-approval-settings.json"


def test_import_copies_valid_keys_once_and_writes_the_marker( legacy_dir, capsys ):
    ( legacy_dir / approval.OVERRIDE_FILENAME ).write_text( stamped_json( {
        "enforcement_active": True, "manager_pull_disabled": True,
        "approvers": [ "cheech" ], "unknown_key": 1, "default_to_holding": "banana",
    } ) )

    result = approval.import_legacy_override_file()

    assert result == { "status": "imported",
                       "imported": [ "approvers", "enforcement_active", "manager_pull_disabled" ] }
    rows = approval._backend.rows
    assert rows[ "enforcement_active" ] is True and rows[ "approvers" ] == [ "cheech" ]
    assert "default_to_holding" not in rows and "unknown_key" not in rows
    assert approval._backend.updated_by[ "approvers" ] == "legacy-file-migration"
    assert approval.LEGACY_IMPORT_MARKER in rows
    out = capsys.readouterr().out
    assert "default_to_holding='banana' skipped" in out
    assert "imported: approvers=['cheech']" in out and "imported: enforcement_active=True" in out
    assert approval.get_enforcement_active() is True             # read through the table


def test_a_second_import_reads_nothing_even_if_the_file_changed( legacy_dir ):
    path = legacy_dir / approval.OVERRIDE_FILENAME
    path.write_text( stamped_json( { "enforcement_active": False } ) )
    approval.import_legacy_override_file()

    path.write_text( stamped_json( { "enforcement_active": True } ) )
    calls = approval._backend.write_calls
    assert approval.import_legacy_override_file() == { "status": "already-imported", "imported": [] }
    assert approval._backend.write_calls == calls
    assert approval.get_enforcement_active() is False


def test_import_with_no_file_still_writes_the_marker( legacy_dir ):
    assert approval.import_legacy_override_file() == { "status": "no-file", "imported": [] }
    assert approval.LEGACY_IMPORT_MARKER in approval._backend.rows


@pytest.mark.parametrize( "content", [ "{not json", json.dumps( [ 1, 2 ] ) ] )
def test_import_of_an_unusable_file_copies_nothing( legacy_dir, capsys, content ):
    ( legacy_dir / approval.OVERRIDE_FILENAME ).write_text( content )

    assert approval.import_legacy_override_file() == { "status": "unreadable", "imported": [] }
    assert set( approval._backend.rows ) == { approval.LEGACY_IMPORT_MARKER }
    assert "unusable" in capsys.readouterr().out


@pytest.mark.parametrize( "stamp", [ None, "forged" ] )
def test_an_unverified_file_imports_NOTHING_and_logs_the_values( legacy_dir, monkeypatch, capsys, stamp ):
    """
    Until the first boot import the file is writable by every seat, so an unstamped or forged
    file must not put approvers, accounts, enforcement or the rescission into the table.
    """
    monkeypatch.setenv( "JWT_SECRET_KEY", "test-secret" )
    body = { "manager_pull_disabled": False, "enforcement_active": False,
             "approvers": [ "mallory" ], "approver_accounts": { "m@x.com": "rick" } }
    if stamp is not None: body[ approval.STAMP_KEY ] = stamp
    ( legacy_dir / approval.OVERRIDE_FILENAME ).write_text( json.dumps( body ) )

    result = approval.import_legacy_override_file()

    assert result == { "status": "imported", "imported": [] }
    assert set( approval._backend.rows ) == { approval.LEGACY_IMPORT_MARKER }
    out = capsys.readouterr().out
    assert "approvers=['mallory'] NOT imported" in out
    assert "enforcement_active=False NOT imported" in out
    assert "manager_pull_disabled=False NOT imported" in out
    assert "approver_accounts={'m@x.com': 'rick'} NOT imported" in out
    assert "mallory" not in approval.get_approvers()
    assert approval.get_manager_pull_disabled() is True


def test_a_validly_stamped_file_edited_afterwards_imports_nothing( legacy_dir, monkeypatch ):
    """
    THE TAMPER CASE: the server's own writer stamped the file, then a seat edited one value.
    The stamp no longer matches the body, so nothing is imported. Positive control: the same
    file unedited imports (see the import-copies test), so this is not a reader that refuses all.
    """
    monkeypatch.setenv( "JWT_SECRET_KEY", "test-secret" )
    path = legacy_dir / approval.OVERRIDE_FILENAME
    path.write_text( stamped_json( { "manager_pull_disabled": True, "approvers": [ "maria" ] } ) )
    edited = json.loads( path.read_text() )
    edited[ "manager_pull_disabled" ] = False                    # the seat's edit; stamp untouched
    edited[ "approvers" ]           = [ "maria", "mallory" ]
    path.write_text( json.dumps( edited ) )

    assert approval.import_legacy_override_file()[ "imported" ] == []
    assert set( approval._backend.rows ) == { approval.LEGACY_IMPORT_MARKER }
    assert approval.get_manager_pull_disabled() is True
    assert "mallory" not in approval.get_approvers()


def test_a_file_that_cannot_be_checked_imports_nothing( legacy_dir, monkeypatch ):
    """No signing secret means "cannot check", which is not "verified"."""
    monkeypatch.setattr( approval, "_stamp_secret", lambda: None )
    ( legacy_dir / approval.OVERRIDE_FILENAME ).write_text( json.dumps( { "enforcement_active": True } ) )
    assert approval.import_legacy_override_file()[ "imported" ] == []


def test_import_honours_a_verified_stamp( legacy_dir, monkeypatch ):
    monkeypatch.setenv( "JWT_SECRET_KEY", "test-secret" )
    ( legacy_dir / approval.OVERRIDE_FILENAME ).write_text( stamped_json( { "manager_pull_disabled": False } ) )

    assert approval.import_legacy_override_file()[ "imported" ] == [ "manager_pull_disabled" ]
    assert approval._backend.rows[ "manager_pull_disabled" ] is False


def test_import_raises_when_the_database_is_unreachable():
    approval._backend.fail_with = ConnectionError( "db down" )
    with pytest.raises( ConnectionError ):
        approval.import_legacy_override_file()


def test_the_memory_backend_hands_out_copies():
    backend = MemoryBackend( { "approvers": [ "a" ] } )
    backend.load()[ "approvers" ].append( "b" )
    assert backend.load() == { "approvers": [ "a" ] }
