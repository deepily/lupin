"""Census guard: no client definition carries a scrub token; the server breaches are pinned."""
import functools
import pathlib
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import blind as bl
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.symindex import spec as sp

CLIENT_DIR = "src/lupin_app/static/js"
# The frozen server commit of plan 7.1 does not exist yet, so the server census reads the working tree. This is the one constant to change at the freeze.
CENSUS_SERVER_COMMIT = None
# Whoever merges Phase 1 items 1.2 and 1.3 (record_search, the SEARCHED parser and rulings) adds scrub-token definitions to src/lupin_mcp and turns this red.
# The fix is to update this pin in the same commit as a visible, reviewed diff that names row 1afc9fee, never to widen it quietly.
# INTERIM, waiting on parking item P8 (row 1afc9fee): whether the frozen server keeps src/lupin_mcp, drops its breaching candidates from the pool, or goes
# unscorable. Measured 2026-10-24 over 8,804 server definitions: these 19 carry a scrub token. Any other breach turns the census red, and so does a pinned
# definition that stops breaching, so the pin cannot go stale. Nothing here changes the run-time rule: blind_definition still raises for every one of them.
PINNED_BREACHES = frozenset( {
    ( "src/lupin_mcp/cosa_voice_mcp.py", "check_exists" ),
    ( "src/lupin_mcp/cosa_voice_mcp.py", "fetch_similar" ),
    ( "src/lupin_mcp/cosa_voice_mcp.py", "read_capability" ),
    ( "src/lupin_mcp/fleet_cap_ini_io.py", "_key_pattern" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "exclusions_by_symbol" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "main" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "receipts_by_symbol" ),
    ( "src/lupin_mcp/reuse_seeded_miss_e2e.py", "candidate_scenario" ),
    ( "src/lupin_mcp/reuse_tools.py", "_need_impl" ),
    ( "src/lupin_mcp/reuse_tools.py", "_receipt_shape_ok" ),
    ( "src/lupin_mcp/reuse_tools.py", "_run_question" ),
    ( "src/lupin_mcp/reuse_tools.py", "check_exists_impl" ),
    ( "src/lupin_mcp/reuse_tools.py", "fetch_similar_impl" ),
    ( "src/lupin_mcp/reuse_tools.py", "index_sha" ),
    ( "src/lupin_mcp/reuse_tools.py", "read_capability_impl" ),
    ( "src/lupin_mcp/reuse_tools.py", "receipt_id" ),
    ( "src/lupin_mcp/reuse_tools.py", "replay_impl" ),
    ( "src/lupin_mcp/reuse_tools.py", "run_question" ),
    ( "src/lupin_mcp/reuse_tools.py", "sweep_need_impl" ),
    # Item 1.2, the recorded search (row 1afc9fee, as the comment above says): four new definitions that name the reuse tools or the SEARCHED line.
    ( "src/lupin_mcp/cosa_voice_mcp.py", "record_search" ),
    ( "src/lupin_mcp/reuse_search.py", "_search" ),
    ( "src/lupin_mcp/reuse_search.py", "receipt_source" ),
    ( "src/lupin_mcp/reuse_search.py", "record_search_impl" ),
} )
# The arm labels come from the Phase 5 harness at the freeze. Until then the census runs without them, which is only honest while the server commit is unfrozen.
ARM_LABELS = ()
SCRUB = bl.scrub_tokens( ARM_LABELS )


def breaches( definitions ):
    """Return the ( file, name ) pairs of the definitions that blind_definition refuses."""
    found = set()
    for d in definitions:
        try:
            bl.blind_definition( d, SCRUB )
        except err.SemdupError as e:
            assert e.code == err.BLINDNESS_BREACH
            found.add( ( d[ "file" ], d[ "name" ] ) )
    return found


def client_definitions():
    """Extract every definition of the tracked client script files."""
    root = cu.get_project_root()
    out  = subprocess.run( [ "git", "ls-files", "--", CLIENT_DIR ], cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    files = [ pathlib.Path( root ) / f for f in out if f.endswith( ex.SCRIPT_SUFFIXES ) and not f.endswith( ( ".d.ts", ".min.js" ) ) ]
    return ex.extract_tree( root, files, "server" )[ "definitions" ]


@functools.lru_cache( maxsize=1 )
def server_definitions():
    """Extract every Python definition of the server packages in the working tree, once per run."""
    root  = pathlib.Path( cu.get_project_root() )
    files = [ f for f in sp.all_files( sp.spec_for( root ) ) if str( f ).endswith( ".py" ) ]
    return tuple( ex.extract_tree( root, files, "server" )[ "definitions" ] )


def test_no_definition_of_the_existing_client_carries_a_scrub_token():
    definitions = client_definitions()
    assert len( definitions ) > 1000
    assert breaches( definitions ) == set()


def test_the_server_breaches_are_exactly_the_pinned_ones_and_every_pinned_one_still_breaches():
    assert CENSUS_SERVER_COMMIT is None
    found = breaches( server_definitions() )
    assert found - PINNED_BREACHES == set(), "a definition outside the pin carries a scrub token"
    assert PINNED_BREACHES - found == set(), "a pinned definition no longer breaches; shrink the pin"
    assert len( PINNED_BREACHES ) == 23                                                    # 19 measured on 24 October, plus the four of item 1.2


def test_each_pinned_definition_still_makes_blind_definition_raise_at_run_time():
    pinned = [ d for d in server_definitions() if ( d[ "file" ], d[ "name" ] ) in PINNED_BREACHES ]
    assert len( pinned ) == len( PINNED_BREACHES )
    for d in pinned:
        with pytest.raises( err.SemdupError ) as caught:
            bl.blind_definition( d, SCRUB )
        assert caught.value.code == err.BLINDNESS_BREACH


def test_assert_blind_itself_raises_on_the_text_of_each_pinned_definition():
    """A prompt built from a pinned definition is refused by assert_blind itself."""
    pinned = [ d for d in server_definitions() if ( d[ "file" ], d[ "name" ] ) in PINNED_BREACHES ]
    assert len( pinned ) == 23
    for d in pinned:
        shown = "\n".join( ( d[ "file" ], d[ "name" ], d[ "sig" ], bl.strip_comment_lines( d[ "text" ], d[ "lang" ], SCRUB ) ) )
        with pytest.raises( err.SemdupError ) as caught:
            bl.assert_blind( f"Definition under review:\n{shown}\nRule on every candidate.", SCRUB )
        assert caught.value.code == err.BLINDNESS_BREACH


def test_the_census_cannot_be_frozen_with_an_empty_arm_label_list():
    """Once the server commit is set, the arm labels must be set too."""
    assert CENSUS_SERVER_COMMIT is None or len( ARM_LABELS ) > 0


def test_the_guard_goes_red_when_a_definition_carrying_a_token_is_added(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    ( root / "clean.py" ).write_text( "def clean():\n    return 1\n", encoding="utf-8" )
    assert breaches( ex.extract_tree( root, [ root / "clean.py" ], "server" )[ "definitions" ] ) == set()
    ( root / "dirty.py" ).write_text( "def dirty():\n    return check_exists( 'x' )\n", encoding="utf-8" )
    found = breaches( ex.extract_tree( root, [ root / "clean.py", root / "dirty.py" ], "server" )[ "definitions" ] )
    assert found == { ( "dirty.py", "dirty" ) }
