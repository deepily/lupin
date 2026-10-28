"""
Unit tests for semdup.proof.proof_cli: the run folder in, the spec and wiring out.

The run folder is written by label_prep.prepare, label_prep.save_doc and label_prep.rewrite_record, the labels by the page's own writer.
Only jscpd, the model and the real tree are stood in for.
"""
import json
import pathlib
import shutil

import pytest

from cosa.repo.doc_lint import model_transport
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.repo.semdup import extract as ex
from cosa.repo.semdup.proof import label_load as ll
from cosa.repo.semdup.proof import label_prep as lp
from cosa.repo.semdup.proof import proof_cli as pc
from cosa.repo.semdup.proof import proof_run as pr
from tests.unit.test_semdup_proof_label_load import answer, truth_of
from tests.unit.test_semdup_proof_run import Toy, source_of

NO_JSCPD = lambda root, dirs, cfg: { "duplicates": [] }


class CountingJscpd:
    """A jscpd stand-in that reports no clones and remembers every call."""

    def __init__( self ):
        self.calls = []

    def __call__( self, root, dirs, cfg ):
        self.calls.append( ( root, list( dirs ) ) )
        return { "duplicates": [] }


class World:
    """A toy pool written out as a real labelling run folder."""

    def __init__( self, tmp_path, config_sha=None ):
        self.toy     = Toy( tmp_path )
        self.run_dir = tmp_path / "run"
        planted      = self.toy.spec[ "planted" ]
        mono         = { "defs": self.toy.spec[ "monolith_defs" ], "pairs": self.toy.spec[ "monolith_pairs" ], "blob": "blob" }
        for i, p in enumerate( planted ):
            dst = self.run_dir / pc.KEY_DIR / pc.REWRITES_DIR / f"{i:03d}" / p[ "rewrite" ][ "file" ]
            dst.parent.mkdir( parents=True )
            shutil.copyfile( self.toy.root / p[ "rewrite" ][ "file" ], dst )
        lp.save_doc( self.run_dir / pc.KEY_DIR / pc.PLANTED_FILE, { "planted": planted } )
        made         = lp.prepare( planted, mono, [ "rick", "second" ], 3, self.run_dir, config_sha or self.toy.cfg[ "config_sha" ] )
        self.key     = pathlib.Path( made[ "key" ] )
        self.packets = { r: pk.packet_path( self.run_dir / "packets", r ) for r in made[ "packets" ] }

    def label_both( self, flip=() ):
        """Have both reviewers label every item; return ( the two labels paths, the truth )."""
        truth = truth_of( self.toy )
        answer( self.packets, self.key, "rick", truth )
        answer( self.packets, self.key, "second", truth, flip=flip )
        return [ str( pl.labels_path( self.packets[ r ] ) ) for r in ( "rick", "second" ) ], truth

    def parts( self, jscpd=None ):
        """Return what live_parts would, with the toy's wiring."""
        counted = jscpd or CountingJscpd()
        wiring  = { **self.toy.wiring, "structural_pairs": pc.structural_source( self.toy.root, {}, self.toy.cfg, counted ) }
        return { "run": pc.load_run( self.run_dir ), "mono_defs": self.toy.spec[ "monolith_defs" ],
                 "distractors": [ *self.toy.spec[ "distractors" ], *[ p[ "original" ] for p in self.toy.spec[ "planted" ] ] ], "wiring": wiring }


@pytest.fixture
def world( tmp_path ):
    """A fresh run folder under the toy pool's own frozen config."""
    return World( tmp_path )


@pytest.fixture
def venue( world, tmp_path, monkeypatch ):
    """Point main at the toy's frozen config and a temporary project root."""
    monkeypatch.setattr( pc.frozen, "frozen_path", lambda: world.toy.wiring[ "frozen_path" ] )
    monkeypatch.setattr( pc.frozen, "live_config", lambda: world.toy.cfg )
    monkeypatch.setattr( pc.cu, "get_project_root", lambda: str( tmp_path ) )
    monkeypatch.setattr( model_transport, "configure", lambda cli_path=None, cwd=None: None )
    monkeypatch.setattr( model_transport, "cli_version", lambda path: "9.9" )
    return world


def refuse_run( spec, wiring ):
    """A proof_run stand-in that fails the test if main reaches it."""
    raise AssertionError( "proof_run must not be called" )


# ---- load_run, monolith_spec, check_originals, plant_failures, build_spec -------------------------------------------

def test_load_run_reads_the_planted_pairs_and_the_key_the_writers_left( world ):
    run = pc.load_run( world.run_dir )
    assert [ p[ "rewrite" ][ "id" ] for p in run[ "planted" ] ] == [ p[ "rewrite" ][ "id" ] for p in world.toy.spec[ "planted" ] ]
    assert ( run[ "seed" ], run[ "monolith_blob" ], run[ "config_sha" ] ) == ( 3, "blob", world.toy.cfg[ "config_sha" ] ) and len( run[ "items" ] ) == 6


def test_monolith_spec_turns_the_keys_monolith_items_into_sorted_pairs_with_their_source( world ):
    run   = pc.load_run( world.run_dir )
    pairs = pc.monolith_spec( run[ "items" ], world.toy.spec[ "monolith_defs" ] )
    want  = sorted( ( { "ids": sorted( p[ "ids" ] ), "source": p[ "source" ] } for p in world.toy.spec[ "monolith_pairs" ] ), key=lambda p: p[ "ids" ] )
    assert pairs == want and { p[ "source" ] for p in pairs } == { "structural", "neighbour", "nominated" }


def test_monolith_spec_names_the_ids_the_pinned_monolith_does_not_define( world ):
    run     = pc.load_run( world.run_dir )
    gone    = world.toy.m[ "m5" ][ "id" ]
    mono    = [ d for d in world.toy.spec[ "monolith_defs" ] if d[ "id" ] != gone ]
    with pytest.raises( ValueError, match=f"the pinned monolith does not define {gone}" ): pc.monolith_spec( run[ "items" ], mono )


def test_check_originals_passes_when_every_original_is_still_in_the_tree_and_names_the_stale_one_when_not( world ):
    planted = world.toy.spec[ "planted" ]
    now     = [ p[ "original" ] for p in planted ]
    assert pc.check_originals( planted, now ) is None
    with pytest.raises( ValueError, match=r"1 planted originals changed since the run was planted: o2\.py#o2" ): pc.check_originals( planted, [ d for d in now if d[ "name" ] != "o2" ] )


def test_plant_failures_counts_only_pairs_both_reviewers_labelled_false( world ):
    planted = world.toy.spec[ "planted" ]
    k       = [ pr.label_key( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) for p in planted ]
    first   = { k[ 0 ]: False, k[ 1 ]: False, k[ 2 ]: True }
    second  = { k[ 0 ]: False, k[ 1 ]: True }
    assert pc.plant_failures( planted, first, second ) == [ k[ 0 ] ]
    assert pc.plant_failures( planted, { k[ 0 ]: False }, {} ) == []
    assert pc.plant_failures( planted, {}, {} ) == []


def test_build_spec_carries_the_keys_seed_and_the_callers_labels_and_refuses_a_stale_original( world ):
    run    = pc.load_run( world.run_dir )
    mono   = world.toy.spec[ "monolith_defs" ]
    dist   = [ *world.toy.spec[ "distractors" ], *[ p[ "original" ] for p in world.toy.spec[ "planted" ] ] ]
    spec   = pc.build_spec( run, mono, dist, { "a|b": True }, [ "x" ] )
    assert spec[ "seed" ] == 3 and spec[ "labels" ] == { "a|b": True } and spec[ "plant_failures" ] == [ "x" ] and len( spec[ "monolith_pairs" ] ) == 3
    with pytest.raises( ValueError, match="planted originals changed" ): pc.build_spec( run, mono, world.toy.spec[ "distractors" ], {}, [] )


# ---- rewrite_sources, staged_name, stage_pool ---------------------------------------------------------------------

def test_rewrite_sources_finds_the_ith_rewrite_under_its_three_digit_folder( world ):
    found = pc.rewrite_sources( world.run_dir, world.toy.spec[ "planted" ] )
    r2    = world.toy.r[ "r2" ]
    assert found[ r2[ "id" ] ] == ( "001", ( world.run_dir / "key" / "rewrites" / "001" / "r2.py" ).resolve() )


def test_rewrite_sources_names_a_rewrite_whose_file_is_missing( world ):
    ( world.run_dir / "key" / "rewrites" / "002" / "r3.py" ).unlink()
    with pytest.raises( FileNotFoundError, match=world.toy.r[ "r3" ][ "id" ] ): pc.rewrite_sources( world.run_dir, world.toy.spec[ "planted" ] )


def test_staged_name_puts_a_rewrite_under_proof_new_and_anything_else_under_tree( world ):
    rewrites = pc.rewrite_sources( world.run_dir, world.toy.spec[ "planted" ] )
    assert pc.staged_name( world.toy.r[ "r1" ], rewrites ) == "proof-new/000/r1.py"
    assert pc.staged_name( world.toy.o[ "o1" ], rewrites ) == "tree/o1.py"


def test_stage_pool_keeps_a_rewrite_apart_from_its_original_and_copies_each_file_once( tmp_path ):
    root = tmp_path / "repo"
    root.mkdir()
    ( root / "same.py" ).write_text( source_of( "f", [ "MARKA" ], 2 ) + "\n\n" + source_of( "g", [ "MARKB" ], 3 ), encoding="utf-8" )
    defs = ex.extract_tree( root, [ root / "same.py" ], "server" )[ "definitions" ]
    rew  = tmp_path / "rw.py"
    rew.write_text( "REWRITTEN\n", encoding="utf-8" )
    f    = defs[ 0 ]
    new  = { **f, "id": "newid", "origin": "new" }
    tmp, where = pc.stage_pool( root, [ *defs, new ], { "newid": ( "000", rew ) } )
    with tmp:
        base = pathlib.Path( tmp.name )
        assert ( base / "tree" / "same.py" ).read_text( encoding="utf-8" ).startswith( "def f" )
        assert ( base / "proof-new" / "000" / "same.py" ).read_text( encoding="utf-8" ) == "REWRITTEN\n"
        assert where[ ( "proof-new/000/same.py", f[ "line" ], f[ "end_line" ] ) ] == "newid" and where[ ( "tree/same.py", f[ "line" ], f[ "end_line" ] ) ] == f[ "id" ]
        assert len( where ) == 3


# ---- staged_pairs on real duplicates ------------------------------------------------------------------------------

class Dups:
    """Two identical functions: one in the tree, one as a rewrite."""

    def __init__( self, tmp_path, extra="" ):
        self.toy     = Toy( tmp_path )
        self.root    = tmp_path / "repo"
        self.root.mkdir()
        body         = source_of( "twin", [ "MARKA", "MARKB" ], 7 )
        ( self.root / "srv.py" ).write_text( body + extra, encoding="utf-8" )
        self.orig    = [ d for d in ex.extract_tree( self.root, [ self.root / "srv.py" ], "server" )[ "definitions" ] if d[ "name" ] == "twin" ][ 0 ]
        self.rewrite = lp.rewrite_record( { "rewrite_text": body }, self.orig, tmp_path / "run" / "key" / "rewrites", 0 )
        self.planted = [ { "original": self.orig, "rewrite": self.rewrite, "stratum": "fable_planted" } ]
        self.sources = pc.rewrite_sources( tmp_path / "run", self.planted )


def test_staged_pairs_finds_a_real_clone_and_maps_it_back_to_the_pool_ids( tmp_path ):
    d     = Dups( tmp_path )
    jscpd = CountingJscpd()
    pairs = pc.staged_pairs( d.root, [ d.orig, d.rewrite ], d.sources, d.toy.cfg, jscpd )
    assert [ p[ "ids" ] for p in pairs ] == [ sorted( [ d.orig[ "id" ], d.rewrite[ "id" ] ] ) ] and pairs[ 0 ][ "source" ] == "dups"
    assert d.orig[ "id" ] != d.rewrite[ "id" ] and len( jscpd.calls ) == 1 and jscpd.calls[ 0 ][ 1 ] == [ "tree", "proof-new" ]


def test_staged_pairs_drops_a_clone_pair_that_touches_a_definition_the_pool_does_not_hold( tmp_path, monkeypatch ):
    d      = Dups( tmp_path, extra="\n\n" + source_of( "twin_too", [ "MARKA", "MARKB" ], 7 ) )
    merged = []
    real   = pc.structural.clone_pairs
    monkeypatch.setattr( pc.structural, "clone_pairs", lambda *lists: merged.extend( real( *lists ) ) or merged )
    pairs  = pc.staged_pairs( d.root, [ d.orig, d.rewrite ], d.sources, d.toy.cfg, NO_JSCPD )
    assert len( merged ) == 3, "dups found the original, the rewrite and the unheld twin_too as three mutual pairs"
    assert [ p[ "ids" ] for p in pairs ] == [ sorted( [ d.orig[ "id" ], d.rewrite[ "id" ] ] ) ]


def test_staged_pairs_maps_a_class_wrapped_typescript_rewrite_recorded_by_its_member_name( tmp_path ):
    toy    = Toy( tmp_path )
    root   = tmp_path / "repo"
    root.mkdir()
    method = "destroy() {\n    const tags = [ 'MARKA', 'MARKB' ];\n    const out = [];\n    for ( const item of this.items ) {\n        out.push( item * 7 );\n    }\n    return out;\n}\n"
    ( root / "widget.ts" ).write_text( f"class Widget {{\n{method}}}\n", encoding="utf-8" )
    orig   = ex.extract_tree( root, [ root / "widget.ts" ], "server" )[ "definitions" ][ 0 ]
    new    = lp.rewrite_record( { "rewrite_text": method }, orig, tmp_path / "run" / "key" / "rewrites", 0 )
    assert new[ "name" ] == "destroy" and orig[ "name" ] == "Widget.destroy"
    stage, where = pc.stage_pool( root, [ orig, new ], pc.rewrite_sources( tmp_path / "run", [ { "original": orig, "rewrite": new } ] ) )
    with stage:
        staged = ex.extract_tree( stage.name, [ pathlib.Path( stage.name ) / "proof-new" / "000" / "widget.ts" ], "server" )[ "definitions" ]
    assert staged[ 0 ][ "name" ] == "PlantedWrapper.destroy" and new[ "name" ] == "destroy"
    assert where[ ( "proof-new/000/widget.ts", staged[ 0 ][ "line" ], staged[ 0 ][ "end_line" ] ) ] == new[ "id" ]
    pairs = pc.staged_pairs( root, [ orig, new ], pc.rewrite_sources( tmp_path / "run", [ { "original": orig, "rewrite": new } ] ), toy.cfg, NO_JSCPD )
    assert [ p[ "ids" ] for p in pairs ] == [ sorted( [ orig[ "id" ], new[ "id" ] ] ) ]


def test_staged_pairs_refuses_a_pool_definition_the_staged_extraction_cannot_find( tmp_path ):
    d     = Dups( tmp_path )
    moved = { **d.orig, "line": d.orig[ "line" ] + 40 }
    with pytest.raises( ValueError, match=f"1 pool definitions were not found in the staged tree: {moved[ 'id' ]}" ):
        pc.staged_pairs( d.root, [ moved, d.rewrite ], d.sources, d.toy.cfg, NO_JSCPD )


def test_structural_source_stages_once_per_set_of_ids_so_the_second_slot_stages_nothing( tmp_path ):
    d     = Dups( tmp_path )
    jscpd = CountingJscpd()
    pairs = pc.structural_source( d.root, d.sources, d.toy.cfg, jscpd )
    first = pairs( [ d.orig, d.rewrite ] )
    again = pairs( [ d.rewrite, d.orig ] )
    assert again is first and len( jscpd.calls ) == 1
    pairs( [ d.rewrite ] )
    assert len( jscpd.calls ) == 2


# ---- label_state ------------------------------------------------------------------------------------------------

def test_label_state_with_fewer_than_two_files_counts_them_and_owes_the_second_reviewer( world ):
    paths, _ = world.label_both()
    none     = pc.label_state( [], world.key, None )
    one      = pc.label_state( paths[ :1 ], world.key, None )
    assert none[ "labels" ] is None and none[ "failures" ] == [] and "0 given" in none[ "owed" ] and none[ "counts" ] == {}
    assert one[ "labels" ] is None and "1 given" in one[ "owed" ] and one[ "counts" ] == { paths[ 0 ]: 6 }


def test_label_state_with_two_agreeing_files_resolves_the_labels_and_lists_no_failures( world ):
    paths, truth = world.label_both()
    state        = pc.label_state( paths, world.key, None )
    assert state[ "owed" ] is None and state[ "labels" ] == truth and state[ "failures" ] == [] and list( state[ "counts" ].values() ) == [ 6, 6 ]


def test_label_state_with_a_disagreement_and_no_ruling_keeps_the_reason_and_the_failures( world ):
    odd          = world.toy.key( "m1", "m5" )
    paths, _     = world.label_both( flip=( odd, ) )
    state        = pc.label_state( paths, world.key, None )
    assert state[ "labels" ] is None and "1 disagreements have no ruling" in state[ "owed" ] and state[ "failures" ] == []
    assert pc.label_state( paths, world.key, { odd: True } )[ "labels" ][ odd ] is True


def test_label_state_counts_a_planted_pair_both_reviewers_ruled_false_as_a_failure( world ):
    r3o3         = world.toy.key( "r3", "o3" )
    truth        = truth_of( world.toy )
    truth[ r3o3 ] = False
    for r in world.packets: answer( world.packets, world.key, r, truth )
    paths        = [ str( pl.labels_path( world.packets[ r ] ) ) for r in ( "rick", "second" ) ]
    assert pc.label_state( paths, world.key, None )[ "failures" ] == [ r3o3 ]


# ---- live_parts --------------------------------------------------------------------------------------------------

def test_live_parts_wires_the_run_folder_the_pools_and_the_ledger_beside_the_proof_records( world, tmp_path, monkeypatch ):
    seen = {}

    class Tmp:
        def cleanup( self ): seen[ "cleaned" ] = True

    monkeypatch.setattr( pc.cu, "get_project_root", lambda: str( tmp_path / "proj" ) )
    monkeypatch.setattr( pc.frozen, "live_config", lambda: world.toy.cfg )
    monkeypatch.setattr( pc.frozen, "frozen_path", lambda: "frozen.json" )
    monkeypatch.setattr( pc.model_transport, "cli_version", lambda path: "9.9" )
    prep    = lambda root, vectors: seen.update( vectors=vectors ) or { "client": "C", "server_defs": [ world.toy.o[ "o1" ] ], "client_defs": [ world.toy.d[ "d1" ] ] }
    mono    = lambda root, n: seen.update( n=n ) or ( Tmp(), [ world.toy.m[ "m1" ] ] )
    parts   = pc.live_parts( tmp_path, world.run_dir, world.toy.cfg, 2, prep_wiring=prep, monolith=mono, jscpd=NO_JSCPD )
    w       = parts[ "wiring" ]
    assert seen[ "cleaned" ] and seen[ "n" ] == world.toy.cfg[ "min_nodes" ] and seen[ "vectors" ] == world.run_dir / "vectors"
    assert [ d[ "name" ] for d in parts[ "distractors" ] ] == [ "o1", "d1" ] and parts[ "mono_defs" ] == [ world.toy.m[ "m1" ] ]
    assert w[ "client" ] == "C" and w[ "parallel" ] == 2 and w[ "data_dir" ] == str( tmp_path / "proj" ) + "/io" and w[ "frozen_path" ] == "frozen.json"
    assert w[ "cache_dir" ] == world.run_dir / "vectors" and w[ "clock" ]() [ 4 ] == "-"
    assert callable( w[ "structural_pairs" ] ) and "ledger" not in w and not ( tmp_path / "proj" ).exists()


def test_proof_ledger_makes_the_proof_folder_and_binds_the_ledger_to_the_binary( tmp_path, monkeypatch ):
    monkeypatch.setattr( pc.model_transport, "cli_version", lambda path: "9.9" )
    ledger = pc.proof_ledger( str( tmp_path ), "/bin/claude" )
    folder = tmp_path.joinpath( *pr.PROOF_FOLDER )
    assert ledger is not None and "claude_cli=/bin/claude|version=9.9" in ( folder / pc.LEDGER_NAME ).read_text( encoding="utf-8" )


# ---- main ---------------------------------------------------------------------------------------------------------

def test_main_check_prints_the_sizes_computes_the_pairs_once_and_never_runs_the_proof( venue, capsys ):
    paths, _ = venue.label_both()
    jscpd    = CountingJscpd()
    made     = []
    def make_parts( *a ): made.append( a ) or None; return venue.parts( jscpd )
    argv     = [ "--run-dir", str( venue.run_dir ), "--check", *[ x for p in paths for x in ( "--labels", p ) ] ]
    rc       = pc.main( argv, make_parts=make_parts, run_proof=refuse_run )
    out      = json.loads( capsys.readouterr().out )
    assert rc == 0 and len( made ) == 1 and len( jscpd.calls ) == 1
    assert out[ "status" ] == "checked" and out[ "planted" ] == 3 and out[ "monolith_pairs" ] == 3 and out[ "owed" ] is None
    assert out[ "plant_failures" ] == 0 and out[ "config_sha" ] == venue.toy.cfg[ "config_sha" ] and out[ "pool" ][ "size" ] == 14


def test_main_check_writes_nothing_not_even_the_proof_folder_or_the_ledger( venue, tmp_path, monkeypatch ):
    data = tmp_path / "data"
    def no_ledger( *a ): raise AssertionError( "--check must not make the ledger" )
    monkeypatch.setattr( pc, "proof_ledger", no_ledger )
    rc   = pc.main( [ "--run-dir", str( venue.run_dir ), "--check" ], make_parts=lambda *a: venue.parts(), run_proof=refuse_run )
    assert rc == 0 and not data.exists()


def test_main_check_without_labels_still_checks_and_reports_what_is_owed( venue, capsys ):
    rc  = pc.main( [ "--run-dir", str( venue.run_dir ), "--check" ], make_parts=lambda *a: venue.parts(), run_proof=refuse_run )
    out = json.loads( capsys.readouterr().out )
    assert rc == 0 and out[ "status" ] == "checked" and "two reviewers' labels files are needed" in out[ "owed" ] and out[ "labels" ] == {}


def test_main_without_two_resolved_label_files_returns_2_and_never_builds_the_parts( venue, capsys ):
    paths, _ = venue.label_both()
    def no_parts( *a ): raise AssertionError( "make_parts must not be called" )
    rc       = pc.main( [ "--run-dir", str( venue.run_dir ), "--labels", paths[ 0 ] ], make_parts=no_parts, run_proof=refuse_run )
    out      = json.loads( capsys.readouterr().out )
    assert rc == 2 and out[ "status" ] == "refused" and "1 given" in out[ "owed" ] and out[ "counts" ] == { paths[ 0 ]: 6 }


def test_main_refuses_an_unresolved_disagreement_without_a_ruling_and_takes_it_with_one( venue, tmp_path, capsys ):
    odd      = venue.toy.key( "m1", "m5" )
    paths, _ = venue.label_both( flip=( odd, ) )
    argv     = [ "--run-dir", str( venue.run_dir ), *[ x for p in paths for x in ( "--labels", p ) ] ]
    ruled    = tmp_path / "rulings.json"
    ruled.write_text( json.dumps( { odd: True } ), encoding="utf-8" )
    ran      = []
    def run_proof( spec, wiring ): ran.append( spec ); return { "status": "complete" }
    assert pc.main( argv, make_parts=lambda *a: venue.parts(), run_proof=refuse_run ) == 2
    assert "disagreements have no ruling" in json.loads( capsys.readouterr().out )[ "owed" ]
    assert pc.main( [ *argv, "--rulings", str( ruled ) ], make_parts=lambda *a: venue.parts(), run_proof=run_proof ) == 0
    assert len( ran ) == 1 and ran[ 0 ][ "labels" ][ odd ] is True and json.loads( capsys.readouterr().out ) == { "status": "complete" }


def test_main_runs_the_proof_once_with_the_resolved_labels_when_both_reviewers_agree( venue, capsys ):
    paths, truth = venue.label_both()
    ran          = []
    def run_proof( spec, wiring ): ran.append( ( spec, wiring ) ); return { "status": "complete", "counts": {} }
    rc           = pc.main( [ "--run-dir", str( venue.run_dir ), *[ x for p in paths for x in ( "--labels", p ) ] ], make_parts=lambda *a: venue.parts(), run_proof=run_proof )
    assert rc == 0 and len( ran ) == 1 and ran[ 0 ][ 0 ][ "labels" ] == truth and ran[ 0 ][ 0 ][ "seed" ] == 3
    assert ran[ 0 ][ 1 ][ "ledger" ] is not venue.toy.wiring[ "ledger" ] and ( venue.toy.wiring[ "data_dir" ].joinpath( *pr.PROOF_FOLDER ) / pc.LEDGER_NAME ).is_file()
    assert json.loads( capsys.readouterr().out )[ "status" ] == "complete"


def test_main_refuses_a_run_folder_planted_under_another_config_sha( tmp_path, monkeypatch ):
    other = World( tmp_path, config_sha="not-the-frozen-sha" )
    monkeypatch.setattr( pc.frozen, "frozen_path", lambda: other.toy.wiring[ "frozen_path" ] )
    monkeypatch.setattr( pc.frozen, "live_config", lambda: other.toy.cfg )
    monkeypatch.setattr( model_transport, "configure", lambda cli_path=None, cwd=None: None )
    def no_parts( *a ): raise AssertionError( "make_parts must not be called" )
    with pytest.raises( ValueError, match=f"planted under config not-the-frozen-sha, the frozen one is {other.toy.cfg[ 'config_sha' ]}" ):
        pc.main( [ "--run-dir", str( other.run_dir ), "--check" ], make_parts=no_parts, run_proof=refuse_run )
