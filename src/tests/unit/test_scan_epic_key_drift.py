"""
Fixture suite for src/scripts/scan-epic-key-drift.py — the epic-key detector's caller.

WHY THE CALLER GETS ITS OWN SUITE. The pure detector is tested next door; everything that
can go wrong HERE is about the fetch, and the dangerous direction is silence. A 401 that
returned an empty list would scan CLEAN — a confident negative to a question the scan
never got to ask, the same shape as the two-database trap in CLAUDE.md §TESTING VENUES.
So the load-bearing cases are:

    · a non-ok response must EXIT 2, never 0
    · an unreadable epic-story list must SKIP the slug check, not flag every row
    · truncation must EXIT 3 and say the result is partial

Delete any of those and the suite still passes while the script can report a clean board
it never actually read.
"""

import importlib.util
import json
from urllib.parse import parse_qs, urlparse

import pytest

import cosa.utils.util as cu


SPEC = importlib.util.spec_from_file_location(
    "scan_epic_key_drift", cu.get_project_root() + "/src/scripts/scan-epic-key-drift.py"
)
scan = importlib.util.module_from_spec( SPEC )
SPEC.loader.exec_module( scan )


SETTINGS = { "api_base_url": "http://localhost:7999", "timeout_seconds": 5 }


def _page( tasks, has_more=False ):
    return ( True, 200, { "tasks": tasks, "has_more": has_more } )


def _row( row_id, key ):
    return { "id": row_id, "correlation_key": key, "status": "queued",
             "title": f"row {row_id}", "project": "lupin" }


# ── fetch_board ───────────────────────────────────────────────────────────────────

def test_fetch_board_returns_rows_and_no_truncation( monkeypatch ):
    monkeypatch.setattr( scan, "_request", lambda *a, **k: _page( [ _row( "a", "epic:x" ) ] ) )
    rows, truncated = scan.fetch_board( SETTINGS, "key", 2000 )

    assert [ r[ "id" ] for r in rows ] == [ "a" ]
    assert truncated is False


def test_fetch_board_pages_until_has_more_is_false( monkeypatch ):
    pages = [ _page( [ _row( "a", "epic:x" ) ], has_more=True ),
              _page( [ _row( "b", "epic:y" ) ], has_more=False ) ]
    monkeypatch.setattr( scan, "_request", lambda *a, **k: pages.pop( 0 ) )

    rows, truncated = scan.fetch_board( SETTINGS, "key", 2000 )
    assert [ r[ "id" ] for r in rows ] == [ "a", "b" ]
    assert truncated is False


def test_fetch_board_stops_and_reports_truncation_at_max_rows( monkeypatch ):
    monkeypatch.setattr( scan, "_request",
                         lambda *a, **k: _page( [ _row( "a", "epic:x" ) ], has_more=True ) )
    rows, truncated = scan.fetch_board( SETTINGS, "key", 1 )

    assert truncated is True
    assert len( rows ) == 1


# ── --max-rows is a real cap (row 9124b70a, Pocholo's patch, landed verbatim) ──────
#
# THE DEFECT. `fetch_board` asked for a flat `limit=PAGE_SIZE` whatever the caller passed,
# so `--max-rows` was a page-stop THRESHOLD, not a cap: `--max-rows 100` fetched 500 and
# then announced "truncated at 100 rows" — the one figure whose job is to say how partial
# a scan was, and it could not be trusted.
#
# 🔴 WHY NO TEST ABOVE CAUGHT IT, WHICH IS THE MORE USEFUL HALF. The fakes above are
# `lambda *a, **k` — they return their page WHOLE whatever was asked, so a capped request
# and an uncapped one produce identical data. Even the max_rows=1 case is blind: it hands
# back one row either way. The assertions were not weak, they were BLIND, and an assertion
# audit passes them clean every time. Two conditions are needed to see this bug at all: a
# cap BELOW the page size, and a fake that HONOURS the limit it was asked for. Every test
# below asserts on the REQUEST the script issued, never on the verdict it reached.

def _limit_of( url ):
    """The `limit=` the script actually asked for — the request, not the verdict."""
    return int( parse_qs( urlparse( url ).query )[ "limit" ][ 0 ] )


def _honouring_pages( monkeypatch, available, has_more=True ):
    """
    A fake that SLICES its page to the requested limit, the way a real router does.

    A fake that ignores `limit` cannot tell a capped request from an uncapped one, which
    is exactly how this defect survived a full suite.
    """
    calls = [ ]

    def _request( method, url, api_key, timeout, body=None ):
        calls.append( url )
        limit = _limit_of( url )
        return _page( available[ :limit ], has_more=has_more )

    monkeypatch.setattr( scan, "_request", _request )
    return calls


def test_a_small_cap_is_asked_for_rather_than_a_whole_page( monkeypatch ):
    calls = _honouring_pages( monkeypatch, [ _row( f"r{i}", "epic:x" ) for i in range( 50 ) ] )

    scan.fetch_board( SETTINGS, "key", 3 )

    assert _limit_of( calls[ 0 ] ) == 3


def test_a_cap_larger_than_a_page_still_asks_for_only_a_page( monkeypatch ):
    """The router's `le=500` is a hard cap; asking for more is a 422, not a bigger page."""
    calls = _honouring_pages( monkeypatch, [ _row( "a", "epic:x" ) ], has_more=False )

    scan.fetch_board( SETTINGS, "key", 5000 )

    assert _limit_of( calls[ 0 ] ) == scan.PAGE_SIZE


def test_each_later_page_asks_for_only_the_room_that_is_left( monkeypatch ):
    calls = _honouring_pages( monkeypatch, [ _row( f"r{i}", "epic:x" ) for i in range( 4 ) ] )

    rows, truncated = scan.fetch_board( SETTINGS, "key", 7 )

    assert [ _limit_of( c ) for c in calls ] == [ 7, 3 ]
    assert len( rows ) == 7
    assert truncated is True


def test_the_rows_returned_never_exceed_the_cap( monkeypatch ):
    for cap in ( 1, 2, 7, 25 ):
        _honouring_pages( monkeypatch, [ _row( f"r{i}", "epic:x" ) for i in range( 50 ) ] )
        rows, _ = scan.fetch_board( SETTINGS, "key", cap )

        assert len( rows ) <= cap, f"--max-rows {cap} fetched {len( rows )}"


def test_a_non_positive_cap_still_asks_for_at_least_one_row( monkeypatch ):
    """
    `argparse` accepts `--max-rows 0` and the router rejects `limit=0`, so without the
    clamp the run dies on a 422 instead of returning an honest result. The `max( 1, … )`
    arm, reachable only from a caller passing a non-positive cap.
    """
    calls = _honouring_pages( monkeypatch, [ _row( f"r{i}", "epic:x" ) for i in range( 5 ) ] )

    rows, truncated = scan.fetch_board( SETTINGS, "key", 0 )

    assert _limit_of( calls[ 0 ] ) == 1
    assert ( len( rows ), truncated ) == ( 1, True )


def test_fetch_board_breaks_on_an_empty_batch_even_when_has_more_lies( monkeypatch ):
    """has_more=True with an empty batch would loop forever; the empty batch wins."""
    monkeypatch.setattr( scan, "_request", lambda *a, **k: _page( [ ], has_more=True ) )
    rows, truncated = scan.fetch_board( SETTINGS, "key", 2000 )

    assert rows == [ ]
    assert truncated is False


@pytest.mark.parametrize( "body,expected_fragment", [
    ( { "detail": "Missing auth. Provide X-API-Key" }, "Missing auth" ),
    ( { "error": "boom" },                             "boom" ),
    ( { },                                             "{}" ),
] )
def test_fetch_board_raises_on_a_non_ok_response( monkeypatch, body, expected_fragment ):
    """THE load-bearing case. An empty board scans CLEAN, so a 401 must never become one."""
    monkeypatch.setattr( scan, "_request", lambda *a, **k: ( False, 401, body ) )

    with pytest.raises( RuntimeError ) as error:
        scan.fetch_board( SETTINGS, "", 2000 )
    assert "401" in str( error.value )
    assert expected_fragment in str( error.value )


def test_fetch_board_include_terminal_changes_the_query( monkeypatch ):
    seen = { }
    def fake( method, url, key, timeout ):
        seen[ "url" ] = url
        return _page( [ ] )
    monkeypatch.setattr( scan, "_request", fake )

    scan.fetch_board( SETTINGS, "key", 2000, include_terminal=True )
    assert "include_terminal=true" in seen[ "url" ]

    scan.fetch_board( SETTINGS, "key", 2000, include_terminal=False )
    assert "include_terminal=false" in seen[ "url" ]


# ── fetch_known_epic_keys ─────────────────────────────────────────────────────────

def test_fetch_known_epic_keys_drops_the_readme_key( monkeypatch ):
    monkeypatch.setattr( scan, "_request", lambda *a, **k: (
        True, 200, { "stories": { "epic:a": { }, "epic:b": { }, "_README": "notes" } } ) )

    assert sorted( scan.fetch_known_epic_keys( SETTINGS, "key" ) ) == [ "epic:a", "epic:b" ]


@pytest.mark.parametrize( "response", [
    ( False, 500, { "detail": "boom" } ),          # non-ok
    ( True,  200, [ "not", "a", "dict" ] ),        # wrong body type
    ( True,  200, { "stories": "not a dict" } ),   # wrong stories type
    ( True,  200, { } ),                           # no stories key
] )
def test_fetch_known_epic_keys_returns_none_rather_than_empty( monkeypatch, response ):
    """None, NOT []. An empty list would make audit_rows flag EVERY epic key as unknown —
    an unreadable key list must not manufacture findings."""
    monkeypatch.setattr( scan, "_request", lambda *a, **k: response )
    assert scan.fetch_known_epic_keys( SETTINGS, "key" ) is None


def test_fetch_known_epic_keys_returns_none_when_the_request_explodes( monkeypatch ):
    def boom( *a, **k ): raise OSError( "socket died" )
    monkeypatch.setattr( scan, "_request", boom )

    assert scan.fetch_known_epic_keys( SETTINGS, "key" ) is None


# ── render ────────────────────────────────────────────────────────────────────────

def test_render_prints_each_finding_and_the_reach( capsys ):
    from cosa.rest.task_store_epic_keys import audit_rows
    rows   = [ _row( "abcdef1234", None ), _row( "beef", "cascade-quick-ask" ) ]
    report = audit_rows( rows, known_epic_keys=[ "epic:x" ] )

    scan.render( report, rows, [ "epic:x" ], truncated=False, include_terminal=False )
    out = capsys.readouterr().out

    assert "BLANK" in out
    assert "FOREIGN" in out
    assert "abcdef12" in out               # id truncated to 8
    assert "REACH OF THIS SCAN" in out


def test_render_says_so_when_the_board_is_clean( capsys ):
    from cosa.rest.task_store_epic_keys import audit_rows
    rows   = [ _row( "a", "epic:x" ) ]
    report = audit_rows( rows, known_epic_keys=[ "epic:x" ] )

    scan.render( report, rows, [ "epic:x" ], truncated=False, include_terminal=False )
    assert "every row carries a known epic key" in capsys.readouterr().out


def test_render_survives_a_finding_with_no_id_or_title( capsys ):
    from cosa.rest.task_store_epic_keys import audit_rows
    report = audit_rows( [ { } ], known_epic_keys=[ "epic:x" ] )

    scan.render( report, [ { } ], [ "epic:x" ], truncated=False, include_terminal=False )
    assert "?" in capsys.readouterr().out


# ── main ──────────────────────────────────────────────────────────────────────────

def _wire( monkeypatch, rows, truncated=False, known=None ):
    monkeypatch.setattr( scan, "load_task_store_settings", lambda: SETTINGS )
    monkeypatch.setattr( scan, "read_api_key", lambda *a, **k: "key" )
    monkeypatch.setattr( scan, "fetch_board", lambda *a, **k: ( rows, truncated ) )
    monkeypatch.setattr( scan, "fetch_known_epic_keys", lambda *a, **k: known )


def test_main_exits_zero_on_a_clean_board( monkeypatch, capsys ):
    _wire( monkeypatch, [ _row( "a", "epic:x" ) ], known=[ "epic:x" ] )
    assert scan.main( [ ] ) == 0
    assert "every row carries a known epic key" in capsys.readouterr().out


def test_main_exits_one_when_a_row_is_ungrouped( monkeypatch, capsys ):
    _wire( monkeypatch, [ _row( "a", None ) ], known=[ "epic:x" ] )
    assert scan.main( [ ] ) == 1


def test_main_exits_one_on_a_foreign_key_that_a_blank_check_would_pass( monkeypatch ):
    """The reason this detector exists rather than a create-time blank check."""
    _wire( monkeypatch, [ _row( "a", "cascade-quick-ask" ) ], known=[ "epic:x" ] )
    assert scan.main( [ ] ) == 1


def test_main_exits_two_when_the_store_cannot_be_read( monkeypatch, capsys ):
    monkeypatch.setattr( scan, "load_task_store_settings", lambda: SETTINGS )
    monkeypatch.setattr( scan, "read_api_key", lambda *a, **k: "" )
    def boom( *a, **k ): raise RuntimeError( "HTTP 401: Missing auth" )
    monkeypatch.setattr( scan, "fetch_board", boom )

    assert scan.main( [ ] ) == 2
    err = capsys.readouterr().err
    assert "could not read the task store" in err
    assert "never a pass" in err


def test_main_exits_three_and_warns_when_truncated( monkeypatch, capsys ):
    _wire( monkeypatch, [ _row( "a", "epic:x" ) ], truncated=True, known=[ "epic:x" ] )

    assert scan.main( [ "--max-rows", "1" ] ) == 3
    assert "BOARD TRUNCATED" in capsys.readouterr().err


def test_the_truncation_warning_reports_ROWS_FETCHED_not_the_flag_it_was_given( monkeypatch, capsys ):
    """
    Row `9124b70a`, half (b). The warning used to interpolate `args.max_rows` — the number
    ASKED FOR — while the run had fetched a different one, so the single figure whose job is
    to say how partial the scan was could not be trusted.

    🔴 THE TWO NUMBERS MUST DIFFER OR THE TEST CANNOT SEE THE BUG. `fetch_board` is stubbed
    through `_wire`, so this hands back a row count that is not the flag: two rows under
    `--max-rows 500`. An ordinary case, where an honoured cap makes the two equal, goes green
    against BOTH spellings — which is how the old wording survived.
    """
    _wire( monkeypatch, [ _row( "a", "epic:x" ), _row( "b", "epic:x" ) ],
           truncated=True, known=[ "epic:x" ] )

    assert scan.main( [ "--max-rows", "500" ] ) == 3

    err = capsys.readouterr().err
    assert "BOARD TRUNCATED at 2 rows" in err, (
        "the warning must report what was FETCHED; it said 500, the flag it was handed" )
    assert "500" not in err.split( "--max-rows" )[ 0 ], (
        "the asked-for figure must not appear as though it were the fetched one" )


def test_main_json_mode_emits_the_report_and_the_reach( monkeypatch, capsys ):
    _wire( monkeypatch, [ _row( "a", None ) ], known=[ "epic:x" ] )
    scan.main( [ "--json" ] )

    payload = json.loads( capsys.readouterr().out )
    assert payload[ "findings" ][ 0 ][ "reason" ] == "blank"
    assert payload[ "truncated" ] is False
    assert "REACH OF THIS SCAN" in payload[ "reach" ]


def test_main_skips_the_slug_check_when_the_story_list_is_unreadable( monkeypatch, capsys ):
    """known=None must NOT turn every epic key into a finding."""
    _wire( monkeypatch, [ _row( "a", "epic:whatever" ) ], known=None )

    assert scan.main( [ ] ) == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_main_key_root_reads_the_key_from_another_checkout( monkeypatch ):
    """The key file is gitignored and absent from every worktree — --key-root is how a
    worktree run reaches it, so the environ it passes must be the one asked for."""
    seen = { }
    monkeypatch.setattr( scan, "load_task_store_settings", lambda: SETTINGS )
    monkeypatch.setattr( scan, "read_api_key", lambda environ=None: seen.setdefault( "environ", environ ) or "key" )
    monkeypatch.setattr( scan, "fetch_board", lambda *a, **k: ( [ ], False ) )
    monkeypatch.setattr( scan, "fetch_known_epic_keys", lambda *a, **k: [ ] )

    scan.main( [ "--key-root", "/main/repo" ] )
    assert seen[ "environ" ] == { "LUPIN_ROOT": "/main/repo" }


def test_main_include_terminal_flag_reaches_fetch_board( monkeypatch ):
    seen = { }
    monkeypatch.setattr( scan, "load_task_store_settings", lambda: SETTINGS )
    monkeypatch.setattr( scan, "read_api_key", lambda *a, **k: "key" )
    monkeypatch.setattr( scan, "fetch_board",
                         lambda s, k, m, include_terminal=False: seen.setdefault( "t", include_terminal ) or ( [ ], False ) )
    monkeypatch.setattr( scan, "fetch_known_epic_keys", lambda *a, **k: [ ] )

    scan.main( [ "--include-terminal" ] )
    assert seen[ "t" ] is True


# ── the module-level bootstrap ────────────────────────────────────────────────────

def test_importing_without_lupin_root_raises_rather_than_guessing( monkeypatch ):
    """The PATH MANAGEMENT mandate's guard: no Path(__file__).parent chain, no silent
    default. An unset LUPIN_ROOT must be a loud RuntimeError, because the alternative is
    a scan that reads whichever tree the interpreter happened to be standing in."""
    # Resolve the path BEFORE unsetting the var — cu.get_project_root() falls back to
    # /var/lupin without it, and the test would fail on a missing file instead of on the
    # guard it is here to prove.
    script_path = cu.get_project_root() + "/src/scripts/scan-epic-key-drift.py"
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    spec   = importlib.util.spec_from_file_location(
        "scan_epic_key_drift_noroot", script_path
    )
    module = importlib.util.module_from_spec( spec )

    with pytest.raises( RuntimeError ) as error:
        spec.loader.exec_module( module )
    assert "LUPIN_ROOT not set" in str( error.value )
