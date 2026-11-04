"""
The plants' purpose lines: sources, the writer's store and the merged store.
"""
import json
import pathlib
import subprocess
import types

import pytest

from cosa.repo.symindex.candidates import purpose_lines as pl
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import planted_pool, planted_purposes as pp
from tests.unit.test_reuse_needset_first_thousand import real_pair


@pytest.fixture
def main_root( tmp_path ):
    """A git working tree that ignores everything under io, as the main checkout does."""
    root = tmp_path / "main"
    root.mkdir()
    subprocess.run( [ "git", "init", "-q", str( root ) ], check=True )
    ( root / ".gitignore" ).write_text( "io/**\n", encoding="utf-8" )
    ( root / "io" / "run" ).mkdir( parents=True )
    return root


def two_pairs():
    """Return a Python pair and a TypeScript pair whose rewrites hold text."""
    py, ts = real_pair( 0 ), real_pair( 1 )
    ts = { **ts, "rewrite": { **ts[ "rewrite" ], "lang": "ts", "text": "destroy(): void {\n  this.x = 1;\n}" } }
    return [ py, ts ]


def screen_all():
    """Return a screen that sends every entry and finds nothing wrong with a line."""
    return pl.Screen( lambda entries: ( entries, [ ] ), lambda text: [ ] )


def test_git_ignore_is_asked_of_git_and_a_tracked_place_is_not_ignored( main_root ):
    assert pp.is_ignored( main_root / "io" / "run" / "x.py", main_root ) is True and pp.is_ignored( main_root / "src" / "x.py", main_root ) is False


def test_each_rewrite_is_copied_to_the_run_folder_and_the_symbols_point_at_the_copy_by_a_path_from_the_main_checkout( main_root ):
    pairs = two_pairs()
    rows  = pp.stage_sources( pairs, main_root / "io" / "run", main_root )
    py, ts = ( main_root / "io" / "run" / "planted-src" / f"{p[ 'rewrite' ][ 'id' ]}.{s}" for p, s in zip( pairs, ( "py", "ts" ) ) )
    assert py.read_text( encoding="utf-8" ) == pairs[ 0 ][ "rewrite" ][ "text" ] and ts.read_text( encoding="utf-8" ) == pairs[ 1 ][ "rewrite" ][ "text" ]
    assert [ r[ "file" ] for r in rows ] == [ f"io/run/planted-src/d-rew00.py", "io/run/planted-src/d-rew01.ts" ] and [ r[ "id" ] for r in rows ] == [ "d-rew00", "d-rew01" ]
    assert rows[ 1 ][ "line" ] == 1 and rows[ 1 ][ "end_line" ] == 3 and rows[ 0 ][ "pin" ] == planted_pool.planted_entry( pairs[ 0 ][ "rewrite" ] )[ "pin" ] and rows[ 1 ][ "lang" ] == "ts"
    on_disk = [ json.loads( line ) for line in ( main_root / "io" / "run" / pp.SYMBOLS ).read_text( encoding="utf-8" ).splitlines() ]
    assert on_disk == rows and all( r[ "doc" ] == "" for r in rows )


def test_the_planted_entry_keeps_the_rewrites_recorded_file_and_only_the_symbols_row_names_the_copy( main_root ):
    pair = two_pairs()[ 0 ]
    row  = pp.stage_sources( [ pair ], main_root / "io" / "run", main_root )[ 0 ]
    assert planted_pool.planted_entry( pair[ "rewrite" ] )[ "file" ] == pair[ "rewrite" ][ "file" ] != row[ "file" ]


def test_sources_outside_the_main_checkout_or_in_a_tracked_place_or_in_an_unknown_language_are_refused_by_name( main_root, tmp_path ):
    pair = two_pairs()[ 0 ]
    with pytest.raises( er.NeedsetError ) as outside: pp.stage_sources( [ pair ], tmp_path / "elsewhere", main_root )
    assert outside.value.code == er.PLANT_SOURCE_OUTSIDE
    ( main_root / "src" ).mkdir()
    with pytest.raises( er.NeedsetError ) as tracked: pp.stage_sources( [ pair ], main_root / "src", main_root )
    assert tracked.value.code == er.PLANT_SOURCE_TRACKED and not ( main_root / "src" / "planted-src" / "d-rew00.py" ).exists()
    odd = { **pair, "rewrite": { **pair[ "rewrite" ], "lang": "rb" } }
    with pytest.raises( er.NeedsetError ) as unknown: pp.stage_sources( [ odd ], main_root / "io" / "run", main_root )
    assert unknown.value.code == er.PLANT_LANG_UNKNOWN


def test_the_writer_is_asked_for_the_plants_by_id_and_its_lines_land_in_the_run_folders_own_store( main_root ):
    pairs, asked = two_pairs(), []

    def writer( ids ):
        asked.append( ids )
        return { i: f"Does the job of {i}." for i in ids }

    report = pp.write_lines( pairs, main_root / "io" / "run", main_root, writer, screen_all() )
    store  = main_root / "io" / "run" / "purpose-plants" / "purpose.jsonl"
    assert asked == [ [ "d-rew00", "d-rew01" ] ] and report[ "written" ] == 2 and pp.lines_path( main_root / "io" / "run" ) == str( store )
    rows = [ json.loads( line ) for line in store.read_text( encoding="utf-8" ).splitlines() ]
    assert [ r[ "purpose" ] for r in rows ] == [ "Does the job of d-rew00.", "Does the job of d-rew01." ] and {r[ "writer_version" ] for r in rows} == { "bounded-cc-1" }
    again = pp.write_lines( pairs, main_root / "io" / "run", main_root, writer, screen_all() )
    assert again[ "kept" ] == 2 and asked == [ [ "d-rew00", "d-rew01" ] ], "a stored line is kept and the writer is not asked again"


def test_the_lines_are_read_by_pin_and_a_plant_with_none_is_listed_and_a_missing_store_lists_every_plant( main_root, tmp_path ):
    pairs = two_pairs()
    pp.write_lines( pairs, main_root / "io" / "run", main_root, lambda ids: { ids[ 0 ]: "  Does the first.  " }, screen_all() )
    lines, without = pp.load_lines( pp.lines_path( main_root / "io" / "run" ), pairs )
    assert lines == { planted_pool.planted_entry( pairs[ 0 ][ "rewrite" ] )[ "pin" ]: "Does the first." } and without == [ "d-rew01" ]
    assert pp.load_lines( str( tmp_path / "none.jsonl" ), pairs ) == ( { }, [ "d-rew00", "d-rew01" ] )
    blank = tmp_path / "blank.jsonl"
    blank.write_text( json.dumps( { "pin": planted_pool.planted_entry( pairs[ 0 ][ "rewrite" ] )[ "pin" ], "purpose": "   " } ) + "\n", encoding="utf-8" )
    assert pp.load_lines( str( blank ), pairs )[ 1 ] == [ "d-rew00", "d-rew01" ], "a blank line is no line"


def test_the_merged_store_holds_the_live_rows_then_the_plants_and_never_touches_the_live_file( tmp_path ):
    live = tmp_path / "live.jsonl"
    live.write_text( json.dumps( { "pin": "p1", "purpose": "Live one." } ) + "\n" + json.dumps( { "pin": "p2", "purpose": "Live two." } ), encoding="utf-8" )      # no final newline
    before = live.read_bytes()
    out = pp.merged_store( str( live ), { "p9": "Plant nine.", "p2": "Plant two." }, tmp_path / "run" / "merged.jsonl" )
    assert pl.load_lines( out ) == { "p1": { "pin": "p1", "purpose": "Live one." }, "p2": { "pin": "p2", "purpose": "Live two." }, "p9": { "pin": "p9", "purpose": "Plant nine." } }
    assert live.read_bytes() == before and pathlib.Path( out ).read_text( encoding="utf-8" ).count( "\n" ) == 3, "the live pin is not overwritten and every row is a line"
    only = pp.merged_store( None, { "p5": "Alone." }, tmp_path / "run" / "alone.jsonl" )
    assert pl.load_lines( only ) == { "p5": { "pin": "p5", "purpose": "Alone." } }
    empty = tmp_path / "empty.jsonl"
    empty.write_text( "", encoding="utf-8" )
    assert pl.load_lines( pp.merged_store( str( empty ), { "p6": "Six." }, tmp_path / "run" / "six.jsonl" ) ) == { "p6": { "pin": "p6", "purpose": "Six." } }


def test_the_command_stages_the_sources_asks_one_writer_and_prints_its_report( main_root, tmp_path, capsys, monkeypatch ):
    pairs = two_pairs()
    seen  = {}

    def factory( root, base_url, environ, index=None, out_dir=None ):
        seen.update( root=root, base_url=base_url, index=index, out_dir=out_dir )
        return lambda ids: { i: "A line." for i in ids }

    planted = tmp_path / "planted.json"
    planted.write_text( "x", encoding="utf-8" )
    monkeypatch.setattr( pp.positive_control, "load_pairs", lambda path: pairs )
    code = pp.main( [ "--root", str( main_root ), "--run-dir", str( main_root / "io" / "run" ), "--planted", str( planted ), "--base-url", "http://x" ], environ={ }, writer_factory=factory, screen=screen_all() )
    printed = json.loads( capsys.readouterr().out )
    assert code == 0 and printed[ "written" ] == 2 and seen[ "index" ] == f"{main_root}/io/run/{pp.SYMBOLS}" and seen[ "out_dir" ] == f"{main_root}/io/run/{pp.OUT_DIR}" and seen[ "base_url" ] == "http://x"
