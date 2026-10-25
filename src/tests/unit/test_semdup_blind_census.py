"""Census guard: no client definition carries a scrub token; server breaches are dropped."""
import functools
import pathlib
import subprocess

import pytest

import cosa.utils.util as cu
from cosa.repo.semdup import blind as bl
from cosa.repo.semdup import errors as err
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup import frozen as fz
from cosa.repo.symindex import spec as sp

CLIENT_DIR = "src/lupin_app/static/js"
# The frozen server commit of plan 7.1 does not exist yet, so the server census reads the working tree. This is the one constant to change at the freeze.
CENSUS_SERVER_COMMIT = None
# The arm labels the frozen configuration scrubs; the census proves neither occurs in any definition, so a label cannot make a run unscorable.
ARM_LABELS = fz.ARM_LABELS
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


def breaches_ids( definitions ):
    """Return the ids of the definitions that blind_definition refuses, asked of it one by one."""
    names = breaches( definitions )
    return [ d[ "id" ] for d in definitions if ( d[ "file" ], d[ "name" ] ) in names ]


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


def test_every_server_definition_that_carries_a_scrub_token_is_dropped_by_the_pipeline_and_would_still_raise_if_shown():
    """Compute the drop from the working tree, so no pin can go stale."""
    definitions = list( server_definitions() )
    dropped     = bl.breaching_ids( definitions, SCRUB )
    assert dropped == sorted( breaches_ids( definitions ) ) and len( dropped ) > 0
    by_id       = { d[ "id" ]: d for d in definitions }
    for i in dropped:
        d = by_id[ i ]
        with pytest.raises( err.SemdupError ) as caught:
            bl.blind_definition( d, SCRUB )
        assert caught.value.code == err.BLINDNESS_BREACH
        shown = "\n".join( ( d[ "file" ], d[ "name" ], d[ "sig" ], bl.strip_comment_lines( d[ "text" ], d[ "lang" ], SCRUB ) ) )
        with pytest.raises( err.SemdupError ) as caught:
            bl.assert_blind( f"Definition under review:\n{shown}\nRule on every candidate.", SCRUB )
        assert caught.value.code == err.BLINDNESS_BREACH


# The 29 definitions measured as breaching when the drop was decided (row 1afc9fee). This is a floor, not an exact list: a new breach is dropped too, and
# these must each stay dropped, so one that stops being dropped turns its own test red.
FLOOR_DROPPED = (
    ( "src/lupin_mcp/cosa_voice_mcp.py", "check_exists" ),
    ( "src/lupin_mcp/cosa_voice_mcp.py", "fetch_similar" ),
    ( "src/lupin_mcp/cosa_voice_mcp.py", "read_capability" ),
    ( "src/lupin_mcp/cosa_voice_mcp.py", "record_search" ),
    ( "src/lupin_mcp/fleet_cap_ini_io.py", "_key_pattern" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "_receipt_symbol" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "_search_status" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "exclusions_by_symbol" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "main" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "parse_searched" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "receipts_by_symbol" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "run_gate" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "searches_by_symbol" ),
    ( "src/lupin_mcp/reuse_exit_gate.py", "unparsed_searched_lines" ),
    ( "src/lupin_mcp/reuse_search.py", "_search" ),
    ( "src/lupin_mcp/reuse_search.py", "receipt_source" ),
    ( "src/lupin_mcp/reuse_search.py", "record_search_impl" ),
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
)


@pytest.mark.parametrize( "file, name", FLOOR_DROPPED )
def test_each_floor_definition_is_dropped_by_the_pipeline_and_still_raises_if_shown( file, name ):
    """Name each definition, so one that stops being dropped turns this red alone."""
    found = [ d for d in server_definitions() if d[ "file" ] == file and d[ "name" ] == name ]
    assert len( found ) == 1
    assert found[ 0 ][ "id" ] in bl.breaching_ids( server_definitions(), SCRUB )
    with pytest.raises( err.SemdupError ) as caught:
        bl.blind_definition( found[ 0 ], SCRUB )
    assert caught.value.code == err.BLINDNESS_BREACH


def test_the_floor_list_names_twenty_nine_distinct_definitions():
    assert len( FLOOR_DROPPED ) == len( set( FLOOR_DROPPED ) ) == 29


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
