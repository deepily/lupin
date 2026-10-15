"""
The fresh-needs driver: pinned file, three-part estimate, seeded sample, fixed settings.

Nothing here reaches Jev. The flip driver is replaced by a recorder that parses the arguments with its real parser.
The fresh-needs file of the run is never opened: the tests write a scratch file of their own under the same layout.
"""
import json
import subprocess
from pathlib import Path

import pytest

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_phase5_run as p5
from lupin_mcp import reuse_stage1 as s1
from tests.unit.test_reuse_e2e_cli import put
from tests.unit.test_reuse_flip_run import rows_of


class Scratch:
    """A projects-data directory with a 30-row needs file under the pinned layout."""

    def __init__( self, tmp_path, monkeypatch ):
        folder = tmp_path / "projects-data" / p5.FRESH_NEEDS_DIR
        folder.mkdir( parents=True )
        self.projects_data = str( tmp_path / "projects-data" )
        self.sha           = put( folder / p5.FRESH_NEEDS_NAME, { "format": frun.NEEDS_FORMAT, "needs": rows_of( 30 ) } )
        monkeypatch.setattr( p5, "FRESH_SHA_PREFIX", self.sha[ :8 ] )


@pytest.fixture
def scratch( tmp_path, monkeypatch ):
    return Scratch( tmp_path, monkeypatch )


@pytest.fixture
def recorder( monkeypatch ):
    """Stands in for the flip driver's cli: parses with the real parser, then records."""
    seen = []
    def fake( argv ):
        frun._parser().parse_args( argv )
        seen.append( argv )
        return 7
    monkeypatch.setattr( frun, "cli", fake )
    return seen


def items_of( n=30 ):
    return [ { "member": f"n{i:02d}", "need": f"need {i}", "exclude": None, "kind": "distinct" } for i in range( n ) ]


def test_estimate_parts_pin_each_part_and_the_sum_to_literals():
    parts = p5.estimate_parts()
    assert parts == { "run": 368_040_000, "canary": 61_400_000, "sample": 24_536_000, "total": 453_976_000 }
    assert parts[ "total" ] == parts[ "run" ] + parts[ "canary" ] + parts[ "sample" ]


def test_estimate_parts_follow_needs_repeats_and_sample():
    parts = p5.estimate_parts( needs=2, repeats=3, sample=1 )
    assert parts[ "run" ] == 6 * 2_453_600
    assert parts[ "sample" ] == 2_453_600


def test_estimate_lines_show_three_parts_then_the_total_with_dollars():
    lines = p5.estimate_lines( p5.estimate_parts() )
    assert lines[ :3 ] == [ "run: 368.0 M tokens", "canary: 61.4 M tokens", "sample: 24.5 M tokens" ]
    assert lines[ 3 ].startswith( "total: 454.0 M tokens, about $19.07 at $0.042 per M, 15.13 M per need" )
    assert "estimate, not measured" in lines[ 3 ]


def test_pick_sample_is_ten_members_in_file_order_and_repeatable():
    items = items_of()
    first = p5.pick_sample( items, "seed-one" )
    assert len( first ) == 10 and len( set( first ) ) == 10
    assert first == sorted( first )
    assert first == p5.pick_sample( items, "seed-one" )
    assert set( first ) <= { i[ "member" ] for i in items }


def test_pick_sample_changes_with_the_seed_and_the_order_of_the_file_does_not_matter():
    items = items_of()
    assert p5.pick_sample( items, "seed-one" ) != p5.pick_sample( items, "seed-two" )          # positive control: the seed is what decides
    assert set( p5.pick_sample( list( reversed( items ) ), "seed-one" ) ) == set( p5.pick_sample( items, "seed-one" ) )


@pytest.mark.parametrize( "seed", [ "", "   ", None, 7 ] )
def test_pick_sample_refuses_an_empty_seed( seed ):
    with pytest.raises( s1.DriverRefused, match="seed" ): p5.pick_sample( items_of(), seed )


@pytest.mark.parametrize( "size", [ 0, 31, -1 ] )
def test_pick_sample_refuses_a_size_outside_the_needs( size ):
    with pytest.raises( s1.DriverRefused, match="between 1 and 30" ): p5.pick_sample( items_of(), "s", size=size )


def test_needs_path_joins_the_pinned_layout_and_ignores_a_trailing_slash():
    assert p5.needs_path( "/x/projects-data/" ) == f"/x/projects-data/{p5.FRESH_NEEDS_DIR}/{p5.FRESH_NEEDS_NAME}"
    assert p5.needs_path( "/x/projects-data" ) == p5.needs_path( "/x/projects-data/" )


def test_check_sha_pins_the_prefix_of_the_real_file():
    assert p5.FRESH_SHA_PREFIX == "0a0da7b7"
    full = "0a0da7b7" + "f" * 56
    assert p5.check_sha( full ) == full
    for bad in ( "1" * 64, None, 12 ):
        with pytest.raises( e2e.FrozenInputRefused, match="0a0da7b7" ): p5.check_sha( bad )


def run_args( scratch, command, *extra, live=False ):
    base = [ command, "--root", "/r", "--data", "/d", "--ledger", "/l", "--projects-data", scratch.projects_data, "--needs-sha", scratch.sha ]
    return base + ( [ "--live" ] if live else [] ) + list( extra )


def test_every_step_hands_the_flip_driver_the_fixed_settings( scratch, recorder, capsys ):
    total = str( p5.estimate_parts()[ "total" ] )
    path  = p5.needs_path( scratch.projects_data )
    fixed = [ "--prefix", "p5", "--estimate-tokens", total, "--repeats", "5", "--route", "full", "--question", "new" ]
    assert p5.main( run_args( scratch, "canary", "--ceiling", "9" ) ) == 7
    assert recorder[ -1 ] == [ "--root", "/r", "--data", "/d", "--ledger", "/l", "--pack-size", "50" ] + fixed + [ "canary", "--needs", path, "--needs-sha", scratch.sha, "--ceiling", "9" ]
    p5.main( run_args( scratch, "run", "--ceiling", "8", live=True ) )
    assert recorder[ -1 ][ 6: 9 ] == [ "--live", "--pack-size", "50" ]
    assert recorder[ -1 ][ -2: ] == [ "--ceiling", "8" ]
    p5.main( run_args( scratch, "approve", "--by", "cheech", "--why", "read the canary" ) )
    assert recorder[ -1 ][ -4: ] == [ "--by", "cheech", "--why", "read the canary" ]
    p5.main( run_args( scratch, "report" ) )
    assert recorder[ -1 ][ -5: ] == [ "report", "--needs", path, "--needs-sha", scratch.sha ]
    assert len( recorder ) == 4


def test_estimate_command_prints_the_parts_and_sends_nothing( recorder, capsys ):
    assert p5.main( [ "estimate" ] ) == 0
    out = capsys.readouterr().out
    assert "run: 368.0 M tokens" in out and "total: 454.0 M tokens" in out
    assert recorder == []


def test_sample_command_prints_the_seed_and_ten_members_from_the_checked_file( scratch, recorder, capsys ):
    assert p5.main( [ "sample", "--seed", "written-before-the-run", "--projects-data", scratch.projects_data, "--needs-sha", scratch.sha ] ) == 0
    record = json.loads( capsys.readouterr().out )
    assert record[ "seed" ] == "written-before-the-run" and len( record[ "members" ] ) == 10
    assert record[ "members" ] == p5.pick_sample( frun.load_flip_needs( p5.needs_path( scratch.projects_data ), scratch.sha ), "written-before-the-run" )
    assert recorder == []


def test_cli_returns_the_flip_drivers_code_and_two_after_a_refusal( scratch, recorder, capsys ):
    assert p5.cli( run_args( scratch, "report" ) ) == 7
    assert p5.cli( [ "sample", "--seed", " ", "--projects-data", scratch.projects_data, "--needs-sha", scratch.sha ] ) == 2
    assert "refused (DriverRefused)" in capsys.readouterr().err
    assert p5.cli( [ "sample", "--seed", "s", "--projects-data", scratch.projects_data, "--needs-sha", "9" * 64 ] ) == 2
    assert "refused (FrozenInputRefused)" in capsys.readouterr().err
    assert p5.cli( [ "sample", "--seed", "s", "--projects-data", scratch.projects_data, "--needs-sha", scratch.sha[ :8 ] + "0" * 56 ] ) == 2    # right prefix, wrong file
    assert "sha256" in capsys.readouterr().err


def test_a_wrong_hash_stops_a_step_before_the_flip_driver_is_called( scratch, recorder ):
    args = [ "run", "--root", "/r", "--data", "/d", "--ledger", "/l", "--projects-data", scratch.projects_data, "--needs-sha", "1" * 64, "--ceiling", "1" ]
    with pytest.raises( e2e.FrozenInputRefused ): p5.main( args )
    assert recorder == []


def test_only_this_driver_names_the_fresh_needs_file():
    root  = Path( subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], capture_output=True, text=True, check=True, cwd=Path( __file__ ).parent ).stdout.strip() )
    files = subprocess.run( [ "git", "ls-files", "*.py" ], capture_output=True, text=True, check=True, cwd=root ).stdout.split()
    assert len( files ) > 1000                                                                 # the population is the tree's python files, not an empty listing
    named = sorted( f for f in files if ( root / f ).exists() and p5.FRESH_NEEDS_NAME in ( root / f ).read_text( encoding="utf-8", errors="replace" ) )
    assert named == [ "src/lupin_mcp/reuse_phase5_run.py" ]
