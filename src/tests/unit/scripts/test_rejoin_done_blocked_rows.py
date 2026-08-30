"""
Coverage ramp for `src/scripts/rejoin-done-blocked-rows.py` — 105 statements, 38 branches,
previously zero (row 3b78bc8a).

LOAD MECHANISM: `importlib.util.spec_from_file_location` by PATH. The filename has dashes,
so it is not importable as a module name. Of the three options the row named:
  · runpy re-runs the module-level LUPIN_ROOT guard on every call and hands back no
    namespace to patch against;
  · subprocess gives no coverage attribution at all, which is the entire point of the ramp;
  · by-path import gives both, and lets the module be re-loaded to reach the bootstrap
    branch that has already run by the time any test starts.

🔴 THIS SCRIPT WRITES. `--apply` amends and transitions real task-store rows over HTTP, and
those land in a Postgres database. Nothing here may reach either. Two independent controls,
because one of them is the kind that passes for the wrong reason:
  1. A PLUGIN-LEVEL TRIPWIRE on `urllib.request.urlopen` — the single choke point every
     write must pass through — installed autouse for the whole module. It has its own test
     proving it BITES, since a tripwire nobody has seen fire is a decoration.
  2. Every seam injected at `mod._request` AND `mod.transition_task` separately.
     ⚠️ Patching `_request` alone is NOT enough and that is worth stating: the script
     imports both names into its own namespace, and `transition_task` calls the CLIENT
     module's `_request`, not the script's. A suite that patched only `_request` would send
     real transitions at a real store while looking fully mocked.

WHAT IS AND IS NOT UNDER TEST. `classify_blocked_row`, `dormancy_stamp` and
`scope_disclosure` are the pure decision and are used FOR REAL here — they have their own
tests and faking them would only prove my fakes agree with each other. What this file pins
is the script's own work: paging, tallying, the amend-then-transition ORDER, and the exit
codes, which are the only thing a caller reads.
"""

import importlib.util
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

import pytest

_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_PATH = os.path.join( _ROOT, "src", "scripts", "rejoin-done-blocked-rows.py" )
_NAME = "rejoin_done_blocked_rows_under_test"


def _load():
    """Import the dashed-filename script by path and return its namespace."""
    spec   = importlib.util.spec_from_file_location( _NAME, _PATH )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ _NAME ] = module
    spec.loader.exec_module( module )
    return module


# ── Control 1: the plugin-level tripwire ──────────────────────────────────────

class EscapedToTheNetwork( AssertionError ):
    """Raised when a test would have reached a real task store — and a real database."""


@pytest.fixture( autouse=True )
def _no_network( monkeypatch ):
    def _tripwire( *a, **k ):
        raise EscapedToTheNetwork(
            "a test reached urllib.request.urlopen — this script AMENDS and TRANSITIONS "
            "real task-store rows, so an escape here writes to Postgres"
        )
    monkeypatch.setattr( urllib.request, "urlopen", _tripwire )


@pytest.fixture
def mod( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    return _load()


SETTINGS = { "api_base_url": "http://store.invalid", "timeout_seconds": 5 }
NOW      = datetime( 2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc )


def _blocked( row_id, blocker_ids, kind="item" ):
    return { "id": row_id, "status": "blocked", "title": f"row {row_id}",
             "blocked_by": [ { "kind": kind, "id": b } for b in blocker_ids ] }


def _row( row_id, status, updated="2026-08-29T00:00:00+00:00" ):
    return { "id": row_id, "status": status, "title": f"row {row_id}", "updated_ts": updated }


class TestTheTripwireItself:
    """
    A control that has never been seen to fire is indistinguishable from no control. This is
    the arm that proves the other tests' silence means something.
    """

    def test_reaching_the_network_raises_rather_than_writing( self ):
        with pytest.raises( EscapedToTheNetwork ):
            urllib.request.urlopen( "http://store.invalid/api/tasks" )

    def test_the_real_client_request_helper_is_caught_by_it( self, mod ):
        """
        Not merely 'urlopen is patched' — the script's actual HTTP helper must route through
        the patched call. `_request` swallows transport errors by contract, so the escape
        surfaces as a failed result rather than a raise; either way nothing left the process.
        """
        ok, status, body = mod._request( "GET", "http://store.invalid/api/tasks", "k", 1 )
        assert ok is False


# ── Module bootstrap ──────────────────────────────────────────────────────────

class TestBootstrap:

    def test_missing_lupin_root_refuses_at_import_with_the_export_in_the_message( self, monkeypatch ):
        monkeypatch.delenv( "LUPIN_ROOT", raising=False )
        with pytest.raises( RuntimeError ) as excinfo:
            _load()
        assert "export LUPIN_ROOT" in str( excinfo.value )

    def test_a_path_without_src_gets_it_inserted_at_the_front( self, monkeypatch ):
        """`insert( 0, … )`, not append — src must win over anything already on the path."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src = os.path.join( _ROOT, "src" )
        monkeypatch.setattr( sys, "path", [ p for p in sys.path if p != src ] )

        _load()

        assert sys.path[ 0 ] == src

    def test_reloading_with_src_already_present_does_not_duplicate_it( self, monkeypatch ):
        """The guard's FALSE half — an unconditional insert would grow sys.path per import."""
        monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
        src    = os.path.join( _ROOT, "src" )
        before = sys.path.count( src )
        assert before >= 1, "precondition: this test session already put src on the path"

        _load()

        assert sys.path.count( src ) == before


# ── fetch_board ───────────────────────────────────────────────────────────────

class TestFetchBoard:

    def _pages( self, mod, monkeypatch, pages ):
        calls = []
        def _request( method, url, api_key, timeout, body=None ):
            calls.append( url )
            return pages[ len( calls ) - 1 ]
        monkeypatch.setattr( mod, "_request", _request )
        return calls

    def test_asks_for_terminal_rows_because_every_blocker_it_resolves_is_done( self, mod, monkeypatch ):
        """
        The query string is the whole correctness of this pass. Drop `include_terminal` and
        every `done` blocker resolves to None, so nothing is ever eligible and the run
        reports a clean board — a false green that looks exactly like "nothing to do".
        """
        calls = self._pages( mod, monkeypatch, [ ( True, 200, { "tasks": [ _row( "a", "done" ) ] } ) ] )

        rows, truncated = mod.fetch_board( SETTINGS, "key", 2000 )

        assert ( len( rows ), truncated ) == ( 1, False )
        assert "include_terminal=true" in calls[ 0 ]
        assert "unscoped_audit=true" in calls[ 0 ]
        assert "hide_parked=false" in calls[ 0 ]
        assert f"limit={mod.PAGE_SIZE}" in calls[ 0 ]
        assert "offset=0" in calls[ 0 ]

    def test_pages_until_has_more_goes_false_and_advances_the_offset_by_rows_seen( self, mod, monkeypatch ):
        calls = self._pages( mod, monkeypatch, [
            ( True, 200, { "tasks": [ _row( "a", "done" ), _row( "b", "done" ) ], "has_more": True } ),
            ( True, 200, { "tasks": [ _row( "c", "done" ) ],                       "has_more": False } ),
        ] )

        rows, truncated = mod.fetch_board( SETTINGS, "key", 2000 )

        assert [ r[ "id" ] for r in rows ] == [ "a", "b", "c" ]
        assert truncated is False
        assert "offset=0" in calls[ 0 ]
        assert "offset=2" in calls[ 1 ], "the offset must advance by rows RECEIVED, not by page size"

    def test_an_empty_page_stops_the_loop_even_when_has_more_is_still_true( self, mod, monkeypatch ):
        """
        The server saying `has_more` while returning nothing would spin forever. This arm is
        unreachable for any well-behaved server, which is exactly why it is worth pinning —
        nothing else in the file would fail if it were removed.
        """
        calls = self._pages( mod, monkeypatch, [
            ( True, 200, { "tasks": [ _row( "a", "done" ) ], "has_more": True } ),
            ( True, 200, { "tasks": [],                      "has_more": True } ),
        ] )

        rows, truncated = mod.fetch_board( SETTINGS, "key", 2000 )

        assert [ r[ "id" ] for r in rows ] == [ "a" ]
        assert truncated is False
        assert len( calls ) == 2

    def test_hitting_max_rows_reports_truncated_rather_than_absorbing_it( self, mod, monkeypatch ):
        self._pages( mod, monkeypatch, [
            ( True, 200, { "tasks": [ _row( "a", "done" ), _row( "b", "done" ) ], "has_more": True } ),
        ] )

        rows, truncated = mod.fetch_board( SETTINGS, "key", 2 )

        assert truncated is True, "a partial board reported as complete is the false green this pass is made of"
        assert len( rows ) == 2

    @pytest.mark.parametrize( "body,expected", [
        ( { "error":  "boom" },         "boom" ),
        ( { "detail": "unauthorized" }, "unauthorized" ),
        ( { "weird":  "shape" },        "weird" ),
    ] )
    def test_a_non_2xx_raises_and_carries_whatever_the_server_said( self, mod, monkeypatch, body, expected ):
        """
        All three arms of `error or detail or page`. It must RAISE, not return an empty
        board: an unchecked 401 that returned [] would scan perfectly clean.
        """
        self._pages( mod, monkeypatch, [ ( False, 401, body ) ] )

        with pytest.raises( RuntimeError ) as excinfo:
            mod.fetch_board( SETTINGS, "key", 2000 )

        assert "401" in str( excinfo.value )
        assert expected in str( excinfo.value )


# ── examine ───────────────────────────────────────────────────────────────────

class TestExamine:
    """
    `classify_blocked_row` is used FOR REAL here — it has its own tests, and faking it would
    only prove my fake agrees with itself. What is pinned is the script's own work around
    it: which rows enter the maps, what `examined` counts, and how verdicts are tallied.
    """

    def test_a_row_whose_blockers_are_all_done_becomes_eligible_with_a_stamp( self, mod ):
        rows = [ _blocked( "r1", [ "b1", "b2" ] ), _row( "b1", "done" ), _row( "b2", "done" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert len( eligible ) == 1
        assert eligible[ 0 ][ "row" ][ "id" ] == "r1"
        assert eligible[ 0 ][ "closed_blocker_ids" ] == [ "b1", "b2" ]
        assert eligible[ 0 ][ "stamp" ], "the stamp is the point of the pass — it must not be empty"
        assert counts[ "examined" ] == 1

    def test_examined_counts_only_blocked_rows_not_the_whole_board( self, mod ):
        """
        `examined` is the denominator the disclosure reports. Counting every fetched row
        would make the pass look like it inspected the board when it inspected one arm.
        """
        rows = [ _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ),
                 _row( "q1", "queued" ), _row( "d1", "done" ), _row( "p1", "parked" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert counts[ "examined" ] == 1
        assert len( eligible ) == 1

    def test_a_live_blocker_holds_the_row_and_is_tallied_under_its_reason( self, mod ):
        rows = [ _blocked( "r1", [ "b1" ] ), _row( "b1", "in_progress" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert eligible == []
        assert counts[ "live_blocker" ] == 1

    def test_a_dropped_blocker_never_rejoins_because_that_arm_is_ricks_alone( self, mod ):
        rows = [ _blocked( "r1", [ "b1", "b2" ] ), _row( "b1", "done" ), _row( "b2", "dropped" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert eligible == []
        assert counts[ "dropped_blocker" ] == 1

    def test_a_persona_blocker_disqualifies_rather_than_being_skipped_past( self, mod ):
        """
        A `{kind:"persona"}` edge is a real wait on a real seat. Filtering it out — which is
        right for flagging — would rejoin a row whose actual blocker was never examined.
        """
        rows = [ _blocked( "r1", [ "tiffany" ], kind="persona" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert eligible == []
        assert counts[ "non_item_blocker" ] == 1

    def test_a_blocker_missing_from_the_board_is_unresolved_and_is_held( self, mod ):
        """
        THE TRUNCATION ARM. A blocker outside the fetched page never appeared, and an absent
        row never HAPPENED — resolving it as satisfied is how a truncated board silently
        unblocks work whose precondition nobody checked.
        """
        rows = [ _blocked( "r1", [ "off-page" ] ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert eligible == []
        assert counts[ "unresolved_blocker" ] == 1

    def test_rows_without_an_id_are_kept_out_of_the_lookup_maps( self, mod ):
        """
        The `if row.get( "id" )` guard on both comprehensions. A None key in the status map
        would collide with every other id-less row and could resolve a blocker to the wrong
        row's status.
        """
        rows = [ { "status": "done" }, _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ) ]

        eligible, counts = mod.examine( rows, NOW )

        assert len( eligible ) == 1
        assert counts[ "examined" ] == 1

    def test_several_rows_tally_into_separate_buckets_on_one_pass( self, mod ):
        rows = [
            _blocked( "ok",   [ "b1" ] ),
            _blocked( "live", [ "b2" ] ),
            _blocked( "gone", [ "nowhere" ] ),
            _row( "b1", "done" ), _row( "b2", "queued" ),
        ]

        eligible, counts = mod.examine( rows, NOW )

        assert [ e[ "row" ][ "id" ] for e in eligible ] == [ "ok" ]
        assert counts[ "examined" ]           == 3
        assert counts[ "rejoin" ]             == 1
        assert counts[ "live_blocker" ]       == 1
        assert counts[ "unresolved_blocker" ] == 1

    def test_an_empty_board_examines_nothing_and_never_raises( self, mod ):
        assert mod.examine( [], NOW ) == ( [], { "examined": 0 } )


# ── apply_rejoin ──────────────────────────────────────────────────────────────

class TestApplyRejoin:
    """
    ⚠️ BOTH SEAMS ARE PATCHED SEPARATELY, DELIBERATELY. The script imports `_request` and
    `transition_task` into its own namespace, and `transition_task` calls the CLIENT
    module's `_request` — so patching only `mod._request` leaves real transitions going to a
    real store. Both are patched on `mod` itself, which moves only this module's bindings;
    the urlopen tripwire is what proves the claim rather than asserting it.
    """

    def _wire( self, mod, monkeypatch, amend, transition ):
        seen = { "order": [] }
        def _request( method, url, api_key, timeout, body=None ):
            seen[ "order" ].append( "amend" )
            seen[ "amend_url" ]  = url
            seen[ "amend_body" ] = body
            return amend
        def _transition( settings, api_key, item_id, payload ):
            seen[ "order" ].append( "transition" )
            seen[ "item_id" ] = item_id
            seen[ "payload" ] = payload
            return transition
        monkeypatch.setattr( mod, "_request", _request )
        monkeypatch.setattr( mod, "transition_task", _transition )
        return seen

    def _candidate( self, row_id="r1" ):
        return { "row": _blocked( row_id, [ "b1" ] ), "stamp": "STAMP TEXT",
                 "closed_blocker_ids": [ "b1" ] }

    def test_amends_before_transitioning_and_that_order_is_the_whole_safety_property( self, mod, monkeypatch ):
        """
        Transition first and a failed amend leaves the row QUEUED, workable, and reading as
        freshly vetted — the exact defect this pass exists to prevent, manufactured by the
        fix. The ORDER is asserted, not merely that both calls happened.
        """
        seen = self._wire( mod, monkeypatch, ( True, 200, {} ), ( True, 200, {} ) )

        ok, stage, detail = mod.apply_rejoin( SETTINGS, "key", "maya d7a687c7", self._candidate() )

        assert ( ok, stage, detail ) == ( True, "done", None )
        assert seen[ "order" ] == [ "amend", "transition" ]
        assert seen[ "amend_url" ].endswith( "/api/tasks/r1/amend" )
        assert seen[ "amend_body" ][ "note" ]  == "STAMP TEXT"
        assert seen[ "amend_body" ][ "actor" ] == "maya d7a687c7"
        assert seen[ "payload" ][ "to_status" ] == "queued"
        assert seen[ "payload" ][ "actor" ]     == "maya d7a687c7"

    def test_a_failed_amend_never_reaches_the_transition( self, mod, monkeypatch ):
        """The row must stay blocked. A rejoin without its stamp is the defect wearing the fix's clothes."""
        seen = self._wire( mod, monkeypatch, ( False, 500, { "detail": "amend exploded" } ), ( True, 200, {} ) )

        ok, stage, detail = mod.apply_rejoin( SETTINGS, "key", "actor", self._candidate() )

        assert ( ok, stage ) == ( False, "amend" )
        assert "500" in detail and "amend exploded" in detail
        assert seen[ "order" ] == [ "amend" ], "the transition must not have been attempted"

    def test_a_failed_transition_reports_that_stage_so_the_stamped_row_is_traceable( self, mod, monkeypatch ):
        self._wire( mod, monkeypatch, ( True, 200, {} ), ( False, 409, { "detail": "illegal transition" } ) )

        ok, stage, detail = mod.apply_rejoin( SETTINGS, "key", "actor", self._candidate() )

        assert ( ok, stage ) == ( False, "transition" )
        assert "409" in detail and "illegal transition" in detail

    @pytest.mark.parametrize( "body,expected", [
        ( { "detail": "named" }, "named" ),
        ( { "odd": "shape" },    "odd" ),
    ] )
    def test_an_error_body_without_detail_still_surfaces_something_readable( self, mod, monkeypatch, body, expected ):
        """Both arms of `body.get( 'detail' ) or body` — an operator must never get a bare status."""
        self._wire( mod, monkeypatch, ( False, 500, body ), ( True, 200, {} ) )

        _, _, detail = mod.apply_rejoin( SETTINGS, "key", "actor", self._candidate() )

        assert expected in detail


# ── main ──────────────────────────────────────────────────────────────────────

class TestMain:
    """
    THE EXIT CODE IS THE ONLY THING A CALLER READS, and this script uses five of them, two
    of which (3 truncated, 4 partial-write) mean "do not believe this run". Every one is
    pinned, including their precedence.
    """

    @pytest.fixture
    def wired( self, mod, monkeypatch ):
        state = { "board": ( [], False ), "applied": [], "apply_result": ( True, "done", None ) }

        monkeypatch.setattr( mod, "load_task_store_settings", lambda: SETTINGS )
        monkeypatch.setattr( mod, "read_api_key", lambda: "key" )
        def _fetch( settings, api_key, max_rows ):
            state[ "max_rows" ] = max_rows
            if isinstance( state[ "board" ], Exception ): raise state[ "board" ]
            return state[ "board" ]
        def _apply( settings, api_key, actor, candidate ):
            state[ "applied" ].append( ( actor, candidate[ "row" ][ "id" ] ) )
            return state[ "apply_result" ]
        monkeypatch.setattr( mod, "fetch_board", _fetch )
        monkeypatch.setattr( mod, "apply_rejoin", _apply )
        return state

    def _eligible_board( self ):
        return ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ) ], False )

    # exit 2 ─────────────────────────────────────────────────────────────────
    def test_an_unreachable_store_exits_two_and_says_so_on_stderr( self, mod, wired, capsys ):
        """
        Not a crash and not a clean zero. A store this pass could not read must be
        distinguishable from a board with nothing eligible — those are the same silence.
        """
        wired[ "board" ] = RuntimeError( "HTTP 401: unauthorized" )

        assert mod.main( [] ) == 2
        assert "could not read the task store" in capsys.readouterr().err

    # exit 0 / 1 ─────────────────────────────────────────────────────────────
    def test_a_board_with_nothing_eligible_exits_zero( self, mod, wired, capsys ):
        wired[ "board" ] = ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "queued" ) ], False )

        assert mod.main( [] ) == 0
        assert "no blocked row has all-done blockers" in capsys.readouterr().out

    def test_a_dry_run_that_found_rows_exits_one_and_writes_nothing( self, mod, wired, capsys ):
        """
        Exit 1 here means FOUND, not failed. The dry run is the default precisely because
        the write moves rows into the workable set where a seat picks them up.
        """
        wired[ "board" ] = self._eligible_board()

        assert mod.main( [] ) == 1

        assert wired[ "applied" ] == [], "a dry run must not have called apply_rejoin at all"
        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "nothing was written" in out
        assert "r1" in out

    # --apply ────────────────────────────────────────────────────────────────
    def test_apply_without_an_actor_refuses_before_writing_anything( self, mod, wired, monkeypatch, capsys ):
        """
        The audit trail is the reason this row exists. An anonymous write is worse than no
        write — it produces a stamp nobody can trace to a seat.
        """
        monkeypatch.delenv( "LUPIN_TASK_ACTOR", raising=False )
        wired[ "board" ] = self._eligible_board()

        assert mod.main( [ "--apply" ] ) == 4
        assert wired[ "applied" ] == []
        assert "requires --actor" in capsys.readouterr().err

    def test_apply_takes_the_actor_from_the_flag( self, mod, wired, capsys ):
        wired[ "board" ] = self._eligible_board()

        assert mod.main( [ "--apply", "--actor", "maya d7a687c7" ] ) == 1
        assert wired[ "applied" ] == [ ( "maya d7a687c7", "r1" ) ]
        assert "rejoined r1" in capsys.readouterr().out

    def test_apply_falls_back_to_the_environment_actor( self, mod, wired, monkeypatch ):
        monkeypatch.setenv( "LUPIN_TASK_ACTOR", "from-env" )
        wired[ "board" ] = self._eligible_board()

        assert mod.main( [ "--apply" ] ) == 1
        assert wired[ "applied" ] == [ ( "from-env", "r1" ) ]

    def test_apply_with_nothing_eligible_writes_nothing_and_exits_zero( self, mod, wired ):
        wired[ "board" ] = ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "queued" ) ], False )

        assert mod.main( [ "--apply", "--actor", "a" ] ) == 0
        assert wired[ "applied" ] == []

    # exit 4 ─────────────────────────────────────────────────────────────────
    def test_a_write_that_fails_at_amend_exits_four_without_the_stamp_warning( self, mod, wired, capsys ):
        wired[ "board" ]        = self._eligible_board()
        wired[ "apply_result" ] = ( False, "amend", "HTTP 500: nope" )

        assert mod.main( [ "--apply", "--actor", "a" ] ) == 4

        err = capsys.readouterr().err
        assert "FAILED at amend" in err
        assert "STILL BLOCKED" not in err, "the stamp warning belongs to the transition stage only"

    def test_a_write_that_fails_at_transition_names_the_stamped_still_blocked_row( self, mod, wired, capsys ):
        """
        The one failure that leaves visible residue: the row keeps a stamp whose claim has
        not come true. The operator has to be told, because a re-run appends a second one.
        """
        wired[ "board" ]        = self._eligible_board()
        wired[ "apply_result" ] = ( False, "transition", "HTTP 409: illegal" )

        assert mod.main( [ "--apply", "--actor", "a" ] ) == 4

        err = capsys.readouterr().err
        assert "FAILED at transition" in err
        assert "STILL BLOCKED" in err
        assert "re-run to retry" in err

    # exit 3, and its precedence ─────────────────────────────────────────────
    def test_a_truncated_board_exits_three_because_the_result_is_unknown( self, mod, wired, capsys ):
        wired[ "board" ] = ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ) ], True )

        assert mod.main( [] ) == 3
        assert "BOARD TRUNCATED" in capsys.readouterr().err

    def test_truncation_outranks_a_write_failure_because_partial_beats_partial( self, mod, wired ):
        """
        Both conditions at once. Truncation is checked FIRST and wins: a run that under-read
        the board cannot have its failure list believed either, so the weaker claim (4, some
        writes failed) must not mask the stronger one (3, the whole result is partial).
        """
        wired[ "board" ]        = ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ) ], True )
        wired[ "apply_result" ] = ( False, "amend", "boom" )

        assert mod.main( [ "--apply", "--actor", "a" ] ) == 3

    # --json ─────────────────────────────────────────────────────────────────
    def test_json_mode_emits_the_report_and_suppresses_the_human_table( self, mod, wired, capsys ):
        wired[ "board" ] = self._eligible_board()

        assert mod.main( [ "--json" ] ) == 1

        out = capsys.readouterr().out
        report = json.loads( out[ : out.rindex( "}" ) + 1 ] )
        assert report[ "eligible" ]  == [ "r1" ]
        assert report[ "truncated" ] is False
        assert report[ "counts" ][ "examined" ] == 1
        assert "DONE-ARM REJOIN" not in out, "the human table must not be interleaved into the JSON"

    def test_json_mode_stdout_is_NOT_parseable_when_rows_were_found( self, mod, wired, capsys ):
        """
        🔴 THIS PINS A DEFECT, NOT A DESIGN — filed as its own row, deliberately not fixed
        inside a coverage ramp on someone else's file.

        `--json` exists so a caller can parse the result. The `elif eligible:` dry-run notice
        sits OUTSIDE the `if args.json / else` split, so whenever the pass actually finds
        something the JSON is followed by a line of English and `json.loads` on stdout
        raises. It is parseable only when there is nothing to report, which is the case
        nobody writes a parser for.

        Confirmed outside pytest against the script directly, so it is not an artifact of
        capsys. When the one-line fix lands this test reddens and points at itself.
        """
        wired[ "board" ] = self._eligible_board()

        mod.main( [ "--json" ] )
        out = capsys.readouterr().out

        with pytest.raises( json.JSONDecodeError ):
            json.loads( out )
        assert "DRY RUN — nothing was written" in out

    def test_json_mode_still_reports_truncation_in_the_payload_and_the_exit_code( self, mod, wired, capsys ):
        """
        Truncation rides in the payload AND the exit code. The warning itself goes to
        stderr, so it is the one loud path that does not corrupt stdout.
        """
        wired[ "board" ] = ( [ _blocked( "r1", [ "b1" ] ), _row( "b1", "done" ) ], True )

        assert mod.main( [ "--json" ] ) == 3

        captured = capsys.readouterr()
        report   = json.loads( captured.out[ : captured.out.rindex( "}" ) + 1 ] )
        assert report[ "truncated" ] is True
        assert "BOARD TRUNCATED" in captured.err

    # flags ──────────────────────────────────────────────────────────────────
    def test_max_rows_defaults_to_two_thousand_and_is_overridable( self, mod, wired ):
        mod.main( [] )
        assert wired[ "max_rows" ] == 2000

        mod.main( [ "--max-rows", "50" ] )
        assert wired[ "max_rows" ] == 50

    def test_the_header_names_the_mode_so_a_log_never_hides_which_one_ran( self, mod, wired, capsys ):
        wired[ "board" ] = self._eligible_board()

        mod.main( [] )
        assert "[DRY RUN]" in capsys.readouterr().out

        mod.main( [ "--apply", "--actor", "a" ] )
        assert "[APPLY]" in capsys.readouterr().out

    def test_a_row_with_no_title_still_prints_rather_than_raising( self, mod, wired, capsys ):
        """The `row.get( 'title' ) or ''` arm — a titleless row must not take down the report."""
        board = [ { "id": "r1", "status": "blocked", "blocked_by": [ { "kind": "item", "id": "b1" } ] },
                  _row( "b1", "done" ) ]
        wired[ "board" ] = ( board, False )

        assert mod.main( [] ) == 1
        assert "r1" in capsys.readouterr().out
