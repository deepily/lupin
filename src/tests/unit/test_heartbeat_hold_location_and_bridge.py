#!/usr/bin/env python3
"""
Row 011f1f90 — location signal + arbiter bridge reader (branch coverage).

Covers the functions Clayton added to heartbeat_hold.py so the arbiter's honored-hold
VETO can see a hold that leaked to a repo root, WITHOUT letting the now-functioning
misplaced hold go silent:

  - hold_correct_zone()    — success (deep) · fail-closed SHALLOW → None · exception → None
  - hold_is_misplaced()    — outside/inside/None-zone/unresolvable-path
  - read_hold_via_bridge() — all five reason paths (bridge+cwd / no_bridge /
                             bridge_without_cwd / bridge_error / log_fn=None)
  - report_hold_files()    — the new first-class `misplaced` field + list + count +
                             the top-level `location_zone` (str, or None when unjudgeable)

The bridge reader LAZY-imports find_session_by_id inside the function, so it is patched
at its SOURCE module (Clayton's pointer), not a name bound into heartbeat_hold. Nothing
here touches the real ~/.claude or the live fleet data root — every path is tmp_path or a
monkeypatched seam.
"""

import json
from pathlib import Path

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh

_BRIDGE_SRC = "lupin_cli.claude_code.hooks.lib.session_bridge.find_session_by_id"


# ─────────────────────────────────────────────────────────────────────────────
# hold_correct_zone — the tree a correctly-placed hold must live under
# ─────────────────────────────────────────────────────────────────────────────

class TestHoldCorrectZone:

    def test_success_returns_the_fleet_root_parent_resolved( self ):
        zone = hh.hold_correct_zone()
        assert zone is not None
        assert zone == hh.fleet_data_root().parent.resolve()
        assert len( zone.parts ) >= 2                    # today's real root is deep — the shallow guard is latent

    def test_a_SHALLOW_zone_fails_closed_to_none( self, monkeypatch ):
        """Row 011f1f90 (Rachel/Mr Radio): a zone at the filesystem root is an ancestor of
        EVERY path, so hold_is_misplaced would return False for everything and the detector
        would go permanently silent while LOOKING healthy. Fewer than 2 path parts → None so
        the caller refuses to judge and surfaces it loudly, never a false all-clear."""
        # fleet_data_root() = /x → .parent = / → parts ("/",) len 1 < 2
        monkeypatch.setattr( hh, "fleet_data_root", lambda repo_root=None: Path( "/x" ) )
        assert hh.hold_correct_zone() is None

    def test_resolution_failure_returns_none_never_raises( self, monkeypatch ):
        def _boom( repo_root=None ):
            raise RuntimeError( "root unresolvable" )
        monkeypatch.setattr( hh, "fleet_data_root", _boom )
        assert hh.hold_correct_zone() is None

    # ── the STRUCTURAL guard (Mr Radio's ruling): swept_roots decides "too broad" ──

    def _fleet_at( self, monkeypatch, tmp_path, *rel ):
        """Point fleet_data_root at tmp_path/<rel...> so the zone is its parent — deep
        enough to clear the parts-count floor, so ONLY the structural check is under test."""
        fdr = tmp_path.joinpath( *rel )
        fdr.mkdir( parents=True, exist_ok=True )
        monkeypatch.setattr( hh, "fleet_data_root", lambda repo_root=None: fdr )
        return fdr, fdr.parent.resolve()                 # (fleet_data_root, zone)

    def test_a_swept_repo_root_UNDER_the_zone_is_too_broad( self, tmp_path, monkeypatch ):
        """The /mnt-class failure the parts-count floor cannot catch: DEEPILY_DATA_DIR=/mnt
        → zone /mnt is an ancestor of the real repo roots at /mnt/DATA01/.../<repo>. When a
        swept repo root sits under the zone (and is not the fleet subtree), the zone spans
        real repo roots → too broad to judge → None."""
        fdr, zone = self._fleet_at( monkeypatch, tmp_path, "data", "lupin" )   # zone = tmp/data
        rogue = tmp_path / "data" / "DATA01" / "some-repo"; rogue.mkdir( parents=True )
        assert hh.hold_correct_zone( swept_roots=[ str( rogue ) ] ) is None

    def test_swept_roots_in_a_SIBLING_tree_are_safe( self, tmp_path, monkeypatch ):
        """Today's real shape: repos live under .../projects/<repo>, holds under
        .../projects-data/<repo> — SIBLINGS. No swept root is under the zone → judgeable."""
        fdr, zone = self._fleet_at( monkeypatch, tmp_path, "projects-data", "lupin" )
        sibling = tmp_path / "projects" / "lupin"; sibling.mkdir( parents=True )
        assert hh.hold_correct_zone( swept_roots=[ str( sibling ) ] ) == zone

    def test_fleet_data_root_own_subtree_is_EXCLUDED_from_the_broadness_check( self, tmp_path, monkeypatch ):
        """fleet_data_root itself legitimately lives UNDER the zone (it is where correct
        holds go), so a swept root that IS the fleet root — or its subtree — must NOT trip
        the too-broad guard."""
        fdr, zone = self._fleet_at( monkeypatch, tmp_path, "projects-data", "lupin" )
        sub = fdr / "worktrees"; sub.mkdir()
        assert hh.hold_correct_zone( swept_roots=[ str( fdr ), str( sub ) ] ) == zone

    def test_an_unresolvable_swept_root_entry_is_skipped_not_fatal( self, tmp_path, monkeypatch ):
        """A root entry that cannot be resolved (None) is skipped, not raised on — the
        remaining roots still decide. With no under-zone root, the zone stays judgeable."""
        fdr, zone = self._fleet_at( monkeypatch, tmp_path, "projects-data", "lupin" )
        assert hh.hold_correct_zone( swept_roots=[ None ] ) == zone


# ─────────────────────────────────────────────────────────────────────────────
# hold_is_misplaced — is this hold OUTSIDE the fleet data root?
# ─────────────────────────────────────────────────────────────────────────────

class TestHoldIsMisplaced:

    def test_a_hold_outside_the_zone_is_misplaced( self, tmp_path ):
        zone   = tmp_path / "projects-data"; zone.mkdir()
        leaked = tmp_path / "lupin" / ".heartbeat-hold-x.json"
        leaked.parent.mkdir(); leaked.write_text( "{}" )
        assert hh.hold_is_misplaced( leaked, zone.resolve() ) is True

    def test_a_hold_inside_the_zone_is_not_misplaced( self, tmp_path ):
        zone = tmp_path / "projects-data"; ( zone / "lupin" ).mkdir( parents=True )
        good = zone / "lupin" / ".heartbeat-hold-x.json"; good.write_text( "{}" )
        assert hh.hold_is_misplaced( good, zone.resolve() ) is False

    def test_a_none_zone_never_over_flags( self ):
        # cannot judge → fail-safe False, never flags a hold it cannot place
        assert hh.hold_is_misplaced( "/anywhere/.heartbeat-hold-x.json", None ) is False

    def test_an_unresolvable_path_never_over_flags( self, tmp_path ):
        # Path( None ).resolve() raises inside the guard → fail-safe False
        assert hh.hold_is_misplaced( None, tmp_path.resolve() ) is False


# ─────────────────────────────────────────────────────────────────────────────
# read_hold_via_bridge — the arbiter's per-session resilient reader
# ─────────────────────────────────────────────────────────────────────────────

class TestReadHoldViaBridge:

    def _spy_resilient( self, monkeypatch ):
        """Replace the delegate with a spy so we assert the cwd threaded to it without
        needing a real hold on disk. Returns the captured-call dict."""
        seen = { }
        def _resilient( session_id, cwd=None ):
            seen[ "session_id" ] = session_id
            seen[ "cwd" ]        = cwd
            return { "session_id": session_id, "cwd": cwd }
        monkeypatch.setattr( hh, "read_hold_resilient", _resilient )
        return seen

    def test_bridge_with_cwd_threads_it_and_never_logs( self, monkeypatch ):
        seen = self._spy_resilient( monkeypatch )
        monkeypatch.setattr( _BRIDGE_SRC, lambda sid: { "cwd": "/projects/planning-is-prompting" } )
        logs = [ ]
        out  = hh.read_hold_via_bridge( "sess-a", log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
        assert seen[ "cwd" ] == "/projects/planning-is-prompting"   # bridge cwd threaded through
        assert out[ "cwd" ] == "/projects/planning-is-prompting"
        assert logs == [ ]                                          # cwd-present path is SILENT (no per-tick noise)

    def test_no_bridge_falls_back_to_cwd_none_and_logs_once( self, monkeypatch ):
        seen = self._spy_resilient( monkeypatch )
        monkeypatch.setattr( _BRIDGE_SRC, lambda sid: None )
        logs = [ ]
        hh.read_hold_via_bridge( "sess-b", log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
        assert seen[ "cwd" ] is None
        assert logs == [ ( "arbiter_hold_reader_cwd_fallback",
                           { "session_id": "sess-b", "reason": "no_bridge" } ) ]

    def test_bridge_without_cwd_logs_its_own_reason( self, monkeypatch ):
        seen = self._spy_resilient( monkeypatch )
        monkeypatch.setattr( _BRIDGE_SRC, lambda sid: { "cwd": "" } )   # bridge exists, no cwd
        logs = [ ]
        hh.read_hold_via_bridge( "sess-c", log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
        assert seen[ "cwd" ] is None
        assert logs[ 0 ][ 1 ][ "reason" ] == "bridge_without_cwd"

    def test_bridge_error_is_caught_and_logged( self, monkeypatch ):
        seen = self._spy_resilient( monkeypatch )
        def _boom( sid ):
            raise RuntimeError( "bridge read blew up" )
        monkeypatch.setattr( _BRIDGE_SRC, _boom )
        logs = [ ]
        hh.read_hold_via_bridge( "sess-d", log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
        assert seen[ "cwd" ] is None
        assert logs[ 0 ][ 1 ][ "reason" ] == "bridge_error"

    def test_log_fn_none_on_a_fallback_never_crashes( self, monkeypatch ):
        seen = self._spy_resilient( monkeypatch )
        monkeypatch.setattr( _BRIDGE_SRC, lambda sid: None )
        # log_fn defaults to None — the fallback must not attempt to log, and must not raise
        out = hh.read_hold_via_bridge( "sess-e" )
        assert seen[ "cwd" ] is None
        assert out[ "session_id" ] == "sess-e"


class TestReadHoldResilientDedup:
    """read_hold_via_bridge delegates to read_hold_resilient, which searches
    [resolve_hold_base_dir(cwd), fleet_data_root()]. When cwd IS the fleet root the two
    candidates collapse to one and the duplicate is skipped rather than read twice."""

    def test_cwd_equal_to_fleet_root_is_deduped_to_one_candidate( self, tmp_path, monkeypatch ):
        fleet = tmp_path / "fleet"; fleet.mkdir()
        monkeypatch.setattr( hh, "fleet_data_root", lambda repo_root=None: fleet )
        _plant_hold( fleet, "sess-dup" )
        out = hh.read_hold_resilient( "sess-dup", cwd=str( fleet ) )   # cwd == fleet → dedup continue
        assert out is not None and out[ "session_id" ] == "sess-dup"


# ─────────────────────────────────────────────────────────────────────────────
# report_hold_files — the new first-class `misplaced` + `location_zone` fields
# ─────────────────────────────────────────────────────────────────────────────

def _plant_hold( base, sid ):
    d = { "session_id": sid, "held_at": "2026-06-07T12:00:00+00:00",
          "ttl_seconds": 900, "work_owed": True, "reason": "x" }
    p = base / f".heartbeat-hold-{sid}.json"
    p.write_text( json.dumps( d ) )
    return p


class TestReportHoldFilesLocation:

    def test_a_hold_outside_the_correct_zone_is_flagged_misplaced( self, tmp_path, monkeypatch ):
        # correct zone is elsewhere → the hold under tmp_path is OUTSIDE it → misplaced
        zone = tmp_path / "projects-data"; zone.mkdir()
        monkeypatch.setattr( hh, "hold_correct_zone", lambda swept_roots=None: zone.resolve() )
        leaked = _plant_hold( tmp_path, "leaked-1" )
        report = hh.report_hold_files( base_dirs=[ tmp_path ] )
        assert report[ "files" ][ 0 ][ "misplaced" ] is True
        assert report[ "misplaced_paths" ]      == [ str( leaked ) ]
        assert report[ "counts" ][ "misplaced" ] == 1
        assert report[ "location_zone" ]        == str( zone.resolve() )   # judged → the zone is named

    def test_a_hold_inside_the_correct_zone_is_not_flagged( self, tmp_path, monkeypatch ):
        # the swept dir IS the correct zone → the hold is correctly placed → not misplaced
        monkeypatch.setattr( hh, "hold_correct_zone", lambda swept_roots=None: tmp_path.resolve() )
        _plant_hold( tmp_path, "correct-1" )
        report = hh.report_hold_files( base_dirs=[ tmp_path ] )
        assert report[ "files" ][ 0 ][ "misplaced" ] is False
        assert report[ "misplaced_paths" ]      == [ ]
        assert report[ "counts" ][ "misplaced" ] == 0
        assert report[ "location_zone" ]        == str( tmp_path.resolve() )

    def test_an_unjudgeable_zone_reports_location_zone_none( self, tmp_path, monkeypatch ):
        # zone None (unresolved / fail-closed shallow) → location_zone None so the caller
        # can fire its distinct 'unjudged' event instead of a false 0-misplaced all-clear
        monkeypatch.setattr( hh, "hold_correct_zone", lambda swept_roots=None: None )
        _plant_hold( tmp_path, "cannot-judge-1" )
        report = hh.report_hold_files( base_dirs=[ tmp_path ] )
        assert report[ "location_zone" ]        is None
        assert report[ "files" ][ 0 ][ "misplaced" ] is False   # None zone → never over-flags
        assert report[ "counts" ][ "misplaced" ] == 0
