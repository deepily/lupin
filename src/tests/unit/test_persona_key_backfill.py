#!/usr/bin/env python3
"""
Unit tests for the Phase-2 persona-key backfill probe.

scan_stragglers / backfill_persona_keys find and (with apply=True) UPDATE any
historical owner_persona / accountable_manager value that is not already its
canonical key. The DB IO is exercised through a fake row object + a fake session
so these are pure, fast unit tests; the _run CLI/DB boundary is # pragma no-cover.
"""
import os
import sys

import pytest


# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import persona_key_backfill as bf


class _Row:
    """A TaskItem double exposing id + the persona-typed columns."""
    def __init__( self, id, owner_persona=None, accountable_manager=None ):
        self.id                  = id
        self.owner_persona       = owner_persona
        self.accountable_manager = accountable_manager


class _FakeQuery:
    def __init__( self, rows ):
        self._rows = rows

    def all( self ):
        return self._rows


class _FakeSession:
    """Minimal Session double: .query( Model ).all() returns the seeded rows."""
    def __init__( self, rows ):
        self._rows = rows

    def query( self, _model ):
        return _FakeQuery( self._rows )


# ---------------------------------------------------------------------------
# scan_stragglers
# ---------------------------------------------------------------------------

def test_scan_already_canonical_is_noop():
    rows = [ _Row( "1", owner_persona="maria", accountable_manager="mr radio" ) ]
    assert bf.scan_stragglers( rows ) == [ ]


def test_scan_none_and_empty_columns_skipped():
    rows = [ _Row( "1", owner_persona=None, accountable_manager="" ) ]
    assert bf.scan_stragglers( rows ) == [ ]


def test_scan_flags_accented_and_punctuated_stragglers():
    rows = [ _Row( "1", owner_persona="María", accountable_manager="Mr. Radio" ) ]
    plans = bf.scan_stragglers( rows )
    assert plans == [
        { "id": "1", "column": "owner_persona",       "old": "María",     "new": "maria",    "skip": False },
        { "id": "1", "column": "accountable_manager", "old": "Mr. Radio", "new": "mr radio", "skip": False },
    ]


def test_scan_flags_uppercase_and_double_space():
    rows = [ _Row( "1", owner_persona="TIBERIUS" ), _Row( "2", owner_persona="mr  radio" ) ]
    plans = bf.scan_stragglers( rows )
    assert [ ( p[ "old" ], p[ "new" ] ) for p in plans ] == [ ( "TIBERIUS", "tiberius" ), ( "mr  radio", "mr radio" ) ]


def test_scan_uncanonicalizable_value_is_skip_flagged_not_blanked():
    # An all-punctuation persona (should not exist) canonicalizes to "" — it is
    # surfaced with skip=True so the caller never blanks the column.
    rows = [ _Row( "1", owner_persona="!!! ..." ) ]
    plans = bf.scan_stragglers( rows )
    assert plans == [ { "id": "1", "column": "owner_persona", "old": "!!! ...", "new": "", "skip": True } ]


# ---------------------------------------------------------------------------
# backfill_persona_keys (dry-run vs apply)
# ---------------------------------------------------------------------------

def _patch_taskitem( monkeypatch ):
    # backfill_persona_keys imports TaskItem only to name the query model; the
    # fake session ignores the argument, so any sentinel works.
    import cosa.rest.postgres_models as pm
    monkeypatch.setattr( pm, "TaskItem", object, raising=False )


def test_backfill_dry_run_reports_without_mutating( monkeypatch ):
    _patch_taskitem( monkeypatch )
    row     = _Row( "1", owner_persona="María" )
    session = _FakeSession( [ row ] )
    report  = bf.backfill_persona_keys( session, apply=False )
    assert report[ "scanned" ] == 1
    assert report[ "applied" ] == 0
    assert len( report[ "stragglers" ] ) == 1
    assert row.owner_persona == "María"                       # DRY-RUN: untouched


def test_backfill_apply_updates_stragglers( monkeypatch ):
    _patch_taskitem( monkeypatch )
    row     = _Row( "1", owner_persona="María", accountable_manager="Mr. Radio" )
    session = _FakeSession( [ row ] )
    report  = bf.backfill_persona_keys( session, apply=True )
    assert report[ "applied" ] == 2
    assert row.owner_persona       == "maria"                 # APPLY: rewritten
    assert row.accountable_manager == "mr radio"


def test_backfill_apply_is_noop_when_already_canonical( monkeypatch ):
    _patch_taskitem( monkeypatch )
    row     = _Row( "1", owner_persona="maria", accountable_manager="mr radio" )
    session = _FakeSession( [ row ] )
    report  = bf.backfill_persona_keys( session, apply=True )
    assert report[ "applied" ] == 0 and report[ "stragglers" ] == [ ]
    assert row.owner_persona == "maria"                       # unchanged


def test_backfill_apply_skips_uncanonicalizable_value( monkeypatch ):
    _patch_taskitem( monkeypatch )
    row     = _Row( "1", owner_persona="!!! ..." )
    session = _FakeSession( [ row ] )
    report  = bf.backfill_persona_keys( session, apply=True )
    assert report[ "applied" ] == 0                           # skip=True plan NOT applied
    assert row.owner_persona == "!!! ..."                     # column NEVER blanked


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
