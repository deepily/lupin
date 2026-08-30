"""
Coverage ramp for `src/scripts/scan-prose-task-refs.py` — a straggler at zero on the
coverage-gate frame (unit + cosa, one data file), claimed in
`src/rnd/v0.2.1/2026.08.30-coverage-straggler-claim-ledger.md`.

LOAD MECHANISM: by-path `importlib.util.spec_from_file_location`. The dashed filename is not
an identifier, and by-path load beats `runpy` for the two reasons
`test_rejoin_done_blocked_rows.py` gives: runpy re-runs the module-level `LUPIN_ROOT` guard
and hands back no namespace to patch, while by-path load gives both a namespace and the
ability to RE-load, which is the only way to reach a bootstrap branch that has already run
before any test starts.

🔴 THIS SCRIPT READS THE LIVE TASK STORE, AND A READ CAN STILL LIE. It only reads — nothing
here can write a row — but an escape to a real store would make these tests depend on
whatever the fleet's board happens to hold today, which is the kind of green that passes for
the wrong reason. Two independent controls, because one of them is exactly that kind:
  1. A PLUGIN-LEVEL TRIPWIRE on `urllib.request.urlopen`, the single choke point every HTTP
     call passes through, installed autouse for the whole module. It has its own test proving
     it BITES, since a tripwire nobody has seen fire is a decoration.
  2. Every seam injected at the MODULE attribute — `mod._request`, `mod.read_api_key`,
     `mod.load_task_store_settings` — so a missed patch surfaces as an error rather than as a
     silent read of the real board.

WHAT IS AND IS NOT FAKED. `scan_rows` and `TERMINAL_STATUSES` are the pure detector and are
used FOR REAL here; they have their own tests and stubbing them would only prove my fakes
agree with each other. What this file pins is the SCRIPT's own work: paging, the truncation
report, the status map, the terminal filter, and the exit codes — the only thing a caller
reads.

⚠️ THE TRUNCATION ARM IS THE POINT OF THE SCRIPT. Exit 3 exists because a partial scan
reporting CLEAN is a false green. Two tests pin it: that it reaches the exit code with no
findings, and that it outranks findings rather than being absorbed into a 1.
"""

import importlib.util
import json
import os
import sys
import urllib.request

import pytest


_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_PATH = os.path.join( _ROOT, "src", "scripts", "scan-prose-task-refs.py" )
_NAME = "scan_prose_task_refs_under_test"


def _load():
    """Import the dashed-filename script by path and return its namespace."""
    spec   = importlib.util.spec_from_file_location( _NAME, _PATH )
    module = importlib.util.module_from_spec( spec )
    sys.modules[ _NAME ] = module
    spec.loader.exec_module( module )
    return module


class EscapedToTheNetwork( AssertionError ):
    """Raised when a test would have reached the fleet's real task store."""


@pytest.fixture( autouse=True )
def _no_network( monkeypatch ):
    def _tripwire( *a, **k ):
        raise EscapedToTheNetwork(
            "a test reached urllib.request.urlopen — this script pages the REAL fleet board, "
            "so an escape here makes the result depend on today's rows"
        )
    monkeypatch.setattr( urllib.request, "urlopen", _tripwire )


@pytest.fixture
def mod( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", _ROOT )
    return _load()


SETTINGS = { "api_base_url": "http://store.invalid", "timeout_seconds": 5 }

# Canonical 36-char ids, plainly synthetic. `CANONICAL_UUID_RE` fixes every group width, so
# these are what the detector's canonical tier actually matches.
DEAD_ID = "00a6bde2-1111-4222-8333-444444444444"
LIVE_ID = "1dd41cde-5555-4666-8777-888888888888"


def _row( row_id, status, body=None, title=None, blocked_by=None ):
    return { "id": row_id, "status": status, "title": title,
             "body": body, "blocked_by": blocked_by or [ ] }


def _raise( error ):
    def _boom( *a, **k ): raise error
    return _boom


class RanAway( AssertionError ):
    """The paging loop did not terminate."""


# The fake serves its last page forever once the script asks past the end, which is what
# lets a `has_more: true` page with no rows be tested at all. That same property means a
# BROKEN loop guard spins forever instead of failing — measured: removing the `not batch`
# arm got the test process SIGKILLed rather than reddened, and a hang blocks the tier while
# an rc of -9 is not a verdict about anything. The cap converts a runaway into a red.
MAX_PAGES = 20


@pytest.fixture
def wired( mod, monkeypatch ):
    """
    Seams at the module attribute, plus a settable board. Tests mutate `pages` to drive
    `fetch_board` and read `calls` to assert on the query the script actually sent.
    """
    state = { "pages": [ { "tasks": [ ], "has_more": False } ], "calls": [ ] }

    def _request( method, url, api_key, timeout ):
        state[ "calls" ].append( ( method, url, api_key, timeout ) )
        if len( state[ "calls" ] ) > MAX_PAGES:
            raise RanAway( f"fetch_board asked for more than {MAX_PAGES} pages — the paging "
                           f"loop is not terminating" )
        index = min( len( state[ "calls" ] ) - 1, len( state[ "pages" ] ) - 1 )
        return ( True, 200, state[ "pages" ][ index ] )

    monkeypatch.setattr( mod, "_request", _request )
    monkeypatch.setattr( mod, "read_api_key", lambda: "test-key" )
    monkeypatch.setattr( mod, "load_task_store_settings", lambda: SETTINGS )
    return state


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

    def test_the_page_size_is_the_routers_hard_cap_not_a_tunable( self, mod ):
        """500 is `le=500` on the endpoint; a larger value would 422 every page."""
        assert mod.PAGE_SIZE == 500


class TestTheTripwireItself:
    """
    A control that has never been seen to fire is indistinguishable from no control. This is
    the arm that proves the other tests' silence means something.
    """

    def test_reaching_the_network_raises_rather_than_reading_the_real_board( self ):
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


# ── fetch_board ───────────────────────────────────────────────────────────────

class TestFetchBoard:

    def test_an_empty_board_returns_no_rows_and_is_not_truncated( self, mod, wired ):
        assert mod.fetch_board( SETTINGS, "k", 2000 ) == ( [ ], False )

    def test_a_single_page_is_returned_whole( self, mod, wired ):
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued" ), _row( "b", "done" ) ],
                               "has_more": False } ]

        rows, truncated = mod.fetch_board( SETTINGS, "k", 2000 )

        assert [ r[ "id" ] for r in rows ] == [ "a", "b" ]
        assert truncated is False

    def test_the_query_asks_for_terminal_unscoped_and_unhidden_rows( self, mod, wired ):
        """
        All three are load-bearing: terminal rows supply the STATUS MAP a citation resolves
        against, and a parked or out-of-scope row still has a body that can cite a dead id.
        """
        mod.fetch_board( SETTINGS, "k", 2000 )

        url = wired[ "calls" ][ 0 ][ 1 ]
        assert "include_terminal=true"  in url
        assert "unscoped_audit=true"    in url
        assert "hide_parked=false"      in url
        assert f"limit={mod.PAGE_SIZE}" in url

    def test_paging_continues_while_has_more_and_advances_the_offset_by_rows_seen( self, mod, wired ):
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued" ), _row( "b", "queued" ) ],
                               "has_more": True },
                             { "tasks": [ _row( "c", "queued" ) ], "has_more": False } ]

        rows, truncated = mod.fetch_board( SETTINGS, "k", 2000 )

        assert [ r[ "id" ] for r in rows ] == [ "a", "b", "c" ]
        assert truncated is False
        assert "offset=0" in wired[ "calls" ][ 0 ][ 1 ]
        assert "offset=2" in wired[ "calls" ][ 1 ][ 1 ]

    def test_an_empty_batch_stops_the_loop_even_when_the_store_claims_more( self, mod, wired ):
        """
        The `not batch` arm. Without it a store answering `has_more: true` with no rows spins
        forever — the offset never advances, so the next page is identical.
        """
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued" ) ], "has_more": True },
                             { "tasks": [ ], "has_more": True } ]

        rows, truncated = mod.fetch_board( SETTINGS, "k", 2000 )

        assert [ r[ "id" ] for r in rows ] == [ "a" ]
        assert truncated is False
        assert len( wired[ "calls" ] ) == 2

    def test_reaching_max_rows_reports_truncated_rather_than_paging_on( self, mod, wired ):
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued" ), _row( "b", "queued" ) ],
                               "has_more": True },
                             { "tasks": [ _row( "c", "queued" ) ], "has_more": False } ]

        rows, truncated = mod.fetch_board( SETTINGS, "k", 1 )

        assert truncated is True
        assert [ r[ "id" ] for r in rows ] == [ "a", "b" ]
        assert len( wired[ "calls" ] ) == 1

    def test_a_failed_request_raises_rather_than_returning_an_empty_board( self, mod, monkeypatch ):
        """
        The whole reason `ok` is checked: an unchecked 401 becomes an empty board that scans
        CLEAN, which is a false green about the fleet's rows.
        """
        monkeypatch.setattr( mod, "_request",
                             lambda *a: ( False, 401, { "error": "bad api key" } ) )
        with pytest.raises( RuntimeError ) as excinfo:
            mod.fetch_board( SETTINGS, "k", 2000 )
        assert "401"         in str( excinfo.value )
        assert "bad api key" in str( excinfo.value )

    def test_a_failure_carrying_detail_instead_of_error_still_names_the_cause( self, mod, monkeypatch ):
        monkeypatch.setattr( mod, "_request",
                             lambda *a: ( False, 422, { "detail": "limit must be <= 500" } ) )
        with pytest.raises( RuntimeError ) as excinfo:
            mod.fetch_board( SETTINGS, "k", 2000 )
        assert "limit must be <= 500" in str( excinfo.value )

    def test_a_failure_with_neither_key_falls_back_to_the_whole_body( self, mod, monkeypatch ):
        """The last `or` arm — an unrecognised error shape must still reach the operator."""
        monkeypatch.setattr( mod, "_request",
                             lambda *a: ( False, 500, { "unexpected": "shape" } ) )
        with pytest.raises( RuntimeError ) as excinfo:
            mod.fetch_board( SETTINGS, "k", 2000 )
        assert "unexpected" in str( excinfo.value )


# ── main ──────────────────────────────────────────────────────────────────────

class TestMainExitCodes:

    def test_an_unreachable_store_exits_2_and_says_so_on_stderr( self, mod, monkeypatch, capsys ):
        monkeypatch.setattr( mod, "read_api_key", lambda: "k" )
        monkeypatch.setattr( mod, "load_task_store_settings", lambda: SETTINGS )
        monkeypatch.setattr( mod, "fetch_board", _raise( RuntimeError( "HTTP 401" ) ) )

        assert mod.main( [ ] ) == 2

        err = capsys.readouterr().err
        assert "could not read the task store" in err
        assert "HTTP 401"                      in err

    def test_a_clean_board_exits_0_and_says_nothing_was_found( self, mod, wired, capsys ):
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body="no ids here" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 0
        assert "(no dead id-citations found)" in capsys.readouterr().out

    def test_a_body_citing_a_terminal_id_with_no_edge_exits_1_and_names_both_rows( self, mod, wired, capsys ):
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", title="the citing row",
                                                body=f"blocked behind {DEAD_ID}" ),
                                          _row( DEAD_ID, "done" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 1

        out = capsys.readouterr().out
        assert "the citing row"     in out
        assert DEAD_ID[ :8 ]        in out
        assert "no blocked_by edge" in out

    def test_a_titleless_citing_row_still_prints_rather_than_raising( self, mod, wired, capsys ):
        """The `row_title or ''` arm — a titleless row must not take down the whole report."""
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body=f"see {DEAD_ID}" ),
                                          _row( DEAD_ID, "dropped" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 1
        assert DEAD_ID[ :8 ] in capsys.readouterr().out

    def test_a_truncated_board_exits_3_even_when_the_scan_found_nothing( self, mod, wired, capsys ):
        """
        The false-green this exit code exists for: a partial scan with no findings is UNKNOWN,
        not clean, so 3 must beat the 0 the report alone would have produced.
        """
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued", body="nothing cited" ),
                                          _row( "b", "queued", body="nothing cited" ) ],
                               "has_more": True } ]

        assert mod.main( [ "--max-rows", "1" ] ) == 3

        captured = capsys.readouterr()
        assert "BOARD TRUNCATED" in captured.err
        assert "PARTIAL"         in captured.err
        assert "(no dead id-citations found)" in captured.out

    def test_a_truncated_board_with_findings_still_exits_3_not_1( self, mod, wired ):
        """Truncation outranks findings: the count is a floor, not a total."""
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body=f"see {DEAD_ID}" ),
                                          _row( DEAD_ID, "done" ) ],
                               "has_more": True } ]

        assert mod.main( [ "--max-rows", "1" ] ) == 3


class TestMainReportContent:

    def test_terminal_rows_supply_the_status_map_but_are_not_themselves_scanned( self, mod, wired, capsys ):
        """
        The `scannable` filter. A done row's body may cite anything; scanning it would report
        findings against work nobody is waiting on.
        """
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body="clean" ),
                                          _row( "r2", "done",   body=f"cites {DEAD_ID}" ),
                                          _row( DEAD_ID, "done" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 0
        assert "3 board rows fetched, 1 non-terminal bodies scanned" in capsys.readouterr().out

    def test_a_row_without_an_id_is_kept_out_of_the_status_map( self, mod, wired ):
        """
        The comprehension's `if row.get( 'id' )` guard. A `None` key in the map would give
        every citation of an unknown id something to resolve against.
        """
        wired[ "pages" ] = [ { "tasks": [ { "status": "queued", "body": "no id on this row" },
                                          _row( "r1", "queued", body="clean" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 0

    def test_a_live_citation_is_not_a_finding( self, mod, wired ):
        """Only a TERMINAL cited id strands the citing row; a live one is an ordinary wait."""
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body=f"waiting on {LIVE_ID}" ),
                                          _row( LIVE_ID, "queued" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 0

    def test_a_terminal_citation_that_already_has_an_edge_is_suppressed( self, mod, wired ):
        """
        Double-counting control: `blocker_is_terminal` already reports an edge-covered strand
        on the read path, so counting it here too would inflate the number against a board
        that has not got worse.
        """
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body=f"see {DEAD_ID}",
                                                blocked_by=[ { "kind": "item", "id": DEAD_ID } ] ),
                                          _row( DEAD_ID, "done" ) ],
                               "has_more": False } ]

        assert mod.main( [ ] ) == 0

    def test_the_scope_disclosure_is_printed_on_the_human_path( self, mod, wired, capsys ):
        """`scan_rows` guarantees a caller cannot obtain counts without it; the script prints it."""
        rows = [ _row( "r1", "queued", body="clean" ) ]
        wired[ "pages" ] = [ { "tasks": rows, "has_more": False } ]

        mod.main( [ ] )

        out = capsys.readouterr().out
        assert mod.scan_rows( rows, { "r1": "queued" } )[ "scope" ] in out


class TestMainJsonMode:

    def test_json_mode_emits_the_report_plus_the_truncation_flag( self, mod, wired, capsys ):
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", title="t",
                                                body=f"see {DEAD_ID}" ),
                                          _row( DEAD_ID, "done" ) ],
                               "has_more": False } ]

        assert mod.main( [ "--json" ] ) == 1

        payload = json.loads( capsys.readouterr().out )
        assert payload[ "truncated" ] is False
        assert payload[ "bodies_scanned" ] == 1
        assert payload[ "findings" ][ 0 ][ "cited_id" ] == DEAD_ID
        assert payload[ "scope" ]

    def test_json_mode_carries_the_truncation_flag_when_the_board_was_cut_short( self, mod, wired, capsys ):
        """
        The flag must be IN the payload, not only on stderr — a machine reader that parses
        only stdout would otherwise treat a partial scan as complete.
        """
        wired[ "pages" ] = [ { "tasks": [ _row( "a", "queued", body="clean" ),
                                          _row( "b", "queued", body="clean" ) ],
                               "has_more": True } ]

        assert mod.main( [ "--json", "--max-rows", "1" ] ) == 3
        assert json.loads( capsys.readouterr().out )[ "truncated" ] is True

    def test_json_mode_prints_no_human_report_alongside_it( self, mod, wired, capsys ):
        """Anything but JSON on stdout breaks `| jq`, which is the only reason the flag exists."""
        wired[ "pages" ] = [ { "tasks": [ _row( "r1", "queued", body="clean" ) ],
                               "has_more": False } ]

        mod.main( [ "--json" ] )

        assert "PROSE-REF SCAN" not in capsys.readouterr().out


class TestMainArguments:

    def test_max_rows_defaults_to_2000( self, mod, wired, monkeypatch ):
        seen = { }
        def _fetch( settings, api_key, max_rows ):
            seen[ "max_rows" ] = max_rows
            return ( [ ], False )
        monkeypatch.setattr( mod, "fetch_board", _fetch )

        mod.main( [ ] )

        assert seen[ "max_rows" ] == 2000

    def test_max_rows_is_parsed_as_an_int_and_handed_through( self, mod, wired, monkeypatch ):
        seen = { }
        def _fetch( settings, api_key, max_rows ):
            seen[ "max_rows" ] = max_rows
            return ( [ ], False )
        monkeypatch.setattr( mod, "fetch_board", _fetch )

        mod.main( [ "--max-rows", "50" ] )

        assert seen[ "max_rows" ] == 50

    def test_the_settings_and_key_come_from_the_shared_client_not_from_argv( self, mod, wired ):
        """
        No `--api-base-url` / `--api-key` flags on purpose: a scanner pointed at a different
        store by a typo would report a clean board that is not this fleet's.
        """
        mod.main( [ ] )

        method, url, api_key, timeout = wired[ "calls" ][ 0 ]
        assert url.startswith( SETTINGS[ "api_base_url" ] )
        assert api_key == "test-key"
        assert timeout == SETTINGS[ "timeout_seconds" ]
