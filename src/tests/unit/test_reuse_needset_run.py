"""
The drafting run on a small made-up world with fake models.
"""
import json

import pytest

from cosa.repo.doc_lint import harness_runner
from lupin_mcp.reuse_needset import draft, keys, pool, quota, run, schema
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset.pool import Measure
from tests.unit.needset_freeze_helpers import pair_once
from tests.unit.test_reuse_needset_keys import Asker as SecondAsker
from tests.unit.test_reuse_needset_keys import Vectors, absence_world, own_shingles

DRAW_SEED = 20260615
SPLIT     = { "near_copy": 4, "work_alike": 4, "cross_language": 2 }
SENTENCE  = "A function that adds up a list of numbers but stops once a ceiling has been reached."
NOTHING   = "A function that checks whether two files hold the same rows in a different order."
COMMIT    = "0123456789abcdef0123456789abcdef01234567"


def make_record( id, file, lang ):
    """Return a kept-pool record."""
    return { "id": id, "file": file, "name": id.split( "." )[ -1 ], "lang": lang, "doc": f"Does the job of {id}.", "kind": "function", "sig": "(x)", "line": 1 }


def build_world():
    """Return ( by_id, kept, ctx, twins ) for 24 symbols and four twin pairs."""
    kept = []
    for lang, ext, folder in ( ( "py", "py", "pkg" ), ( "ts", "ts", "web" ) ):
        for f, name in enumerate( ( "alpha", "bravo" ) ):
            for n in range( 6 ): kept.append( make_record( f"{folder}.{name}.{lang}fn{f * 6 + n}", f"{folder}/{name}.{ext}", lang ) )
    by_id    = { r[ "id" ]: r for r in kept }
    ids      = sorted( by_id )
    measures = { i: Measure( 40, own_shingles( i ) ) for i in ids }
    bodies   = { i: f"def body_{i.replace( '.', '_' )}(): return word_{n}" for n, i in enumerate( ids ) }
    vectors  = Vectors( ids, [ [ 1.0, 0.01 * n, 0.0 ] for n in range( len( ids ) ) ] )
    twins    = {}
    for a, b in ( ( "pkg.alpha.pyfn0", "pkg.alpha.pyfn1" ), ( "pkg.alpha.pyfn2", "pkg.alpha.pyfn3" ), ( "web.alpha.tsfn0", "web.alpha.tsfn1" ), ( "web.alpha.tsfn2", "web.alpha.tsfn3" ) ):
        twins[ a ], twins[ b ] = [ b ], [ a ]
    return by_id, kept, keys.KeyContext( kept, measures, bodies, DRAW_SEED, vectors ), twins


def strip_fn( rec ):
    """Return a stand-in for strip.strip_member."""
    return { "kind": "function", "text": f"def NAME( ARG ):\n    return word_of_{rec[ 'id' ].replace( '.', '_' )}", "forbidden": [ rec[ "name" ] ] }


class Model:
    """A fake drafter with one ruling for every same-job question and a fixed sentence per draft."""

    def __init__( self, same="yes", leak=None ):
        """Remember the same-job ruling and an optional ( marker, sentence ) draft."""
        self.same, self.leak, self.calls, self.systems = same, leak, 0, []

    def __call__( self, system, prompt ):
        """Answer a ruling, a nothing draft or a draft."""
        self.calls += 1
        self.systems.append( system )
        if '"same_job"' in prompt: return json.dumps( { "same_job": self.same } )
        if self.leak is not None and self.leak[ 0 ] in prompt: return self.leak[ 1 ]
        return NOTHING if "plausibly need next" in prompt else SENTENCE


def make_env( tmp_path, ask=None, seed=DRAW_SEED, smoke=False, with_none=True, name="ledger.jsonl", wrap_second=None, freeze_from="built" ):
    """Build a run.Env over the small world, freezing a real index unless freeze_from is given."""
    if freeze_from == "built": freeze_from = pair_once( tmp_path )
    by_id, kept, ctx, twins = build_world()
    book    = draft.SharedLedger( harness_runner.Ledger( str( tmp_path / name ), binding="test" ) )
    ask     = Model() if ask is None else ask
    stage, vectors, _ = absence_world()
    second  = SecondAsker( "NEVER", field="any_does_it" )
    second_call = second if wrap_second is None else wrap_second( second )
    none_fn = draft.make_none_drafter( stage, vectors, lambda text: [ 1.0, 0.0 ], lambda i: "does a thing", second_call,
                                       harness_runner.Ledger( str( tmp_path / "second.jsonl" ), binding="test" ), "claude-opus-5-5" ) if with_none else None
    return run.Env( by_id, kept, ctx, twins, strip_fn, ask, book, draft.DRAFTER_MODEL, "max-plan", COMMIT, seed, SPLIT, "test", "2026-10-24T22:00:00-04:00",
                    none_draft_fn=none_fn, parallel=2, smoke=smoke, freeze_from=freeze_from )


def table():
    """Return the 12-need quota used by the run tests: cells of one and of two needs."""
    return quota.plan_quota( 12, 10, 2, 0.5, SPLIT )


def test_a_plan_is_written_once_and_a_resume_with_the_same_plan_is_accepted( tmp_path ):
    path = tmp_path / "plan.json"
    run.write_or_check_plan( path, { "a": 1 } )
    run.write_or_check_plan( path, { "a": 1 } )
    assert json.loads( path.read_text() ) == { "a": 1 }
    with pytest.raises( er.NeedsetError ) as e: run.write_or_check_plan( path, { "a": 2 } )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN and json.loads( path.read_text() ) == { "a": 1 }


def test_a_near_copy_job_holds_the_twins_as_the_key_and_a_seed_without_twins_has_none( tmp_path ):
    env  = make_env( tmp_path )
    got  = run.near_copy_job( env, "pkg.alpha.pyfn0", "py" )
    assert [ r[ "id" ] for r in got[ "keys" ] ] == [ "pkg.alpha.pyfn1" ] and got[ "seed" ][ "id" ] == "pkg.alpha.pyfn0" and got[ "write_lang" ] == "py"
    assert got[ "meta" ] == { "route": None, "key_source": "twin", "key_lang": "py" } and "pkg_alpha_pyfn0" in got[ "stripped" ][ "text" ]
    assert run.near_copy_job( env, "pkg.alpha.pyfn4", "py" ) is None


def test_a_routed_job_records_the_route_the_source_and_the_other_language_for_cross_language( tmp_path ):
    env  = make_env( tmp_path )
    vec  = run.routed_job( env, "work_alike", "pkg.alpha.pyfn0", "py", keys.ROUTE_VECTOR )
    assert vec[ "meta" ][ "route" ] == "vector" and vec[ "meta" ][ "key_source" ] == "vector" and vec[ "meta" ][ "asked" ] == 1 and vec[ "meta" ][ "key_lang" ] == "py"
    assert vec[ "keys" ][ 0 ][ "lang" ] == "py" and vec[ "keys" ][ 0 ][ "id" ] != "pkg.alpha.pyfn0"
    samp = run.routed_job( env, "work_alike", "pkg.alpha.pyfn0", "py", keys.ROUTE_SAMPLED )
    assert samp[ "meta" ][ "route" ] == "sampled" and samp[ "meta" ][ "key_source" ] in schema.SAMPLED_SOURCES
    cross = run.routed_job( env, "cross_language", "pkg.alpha.pyfn0", "py", keys.ROUTE_VECTOR )
    assert cross[ "meta" ][ "key_lang" ] == "ts" and cross[ "write_lang" ] == "py"
    assert env.ask.systems and set( env.ask.systems ) == { run.SAME_JOB_SYSTEM }
    refuse = make_env( tmp_path, ask=Model( same="no" ), name="no.jsonl" )
    assert run.routed_job( refuse, "work_alike", "pkg.alpha.pyfn0", "py", keys.ROUTE_VECTOR ) is None


def test_a_nothing_job_lists_the_entry_line_of_each_symbol_of_the_file_in_that_language( tmp_path ):
    env = make_env( tmp_path )
    got = run.nothing_job( env, "pkg/alpha.py", "py" )
    assert got[ "seed" ] == "pkg/alpha.py" and len( got[ "lines" ] ) == 6 and all( l.startswith( "pkg.alpha.pyfn" ) for l in got[ "lines" ] )
    assert got[ "meta" ] == { "route": None, "key_source": None, "key_lang": None } and got[ "write_lang" ] == "py"


def test_each_kind_gets_its_own_job_maker_and_routes_are_split_half_and_half( tmp_path ):
    env   = make_env( tmp_path )
    order = [ f"pkg.alpha.pyfn{n}" for n in range( 6 ) ]
    assert run.job_maker( env, "near_copy", "py", order )( "pkg.alpha.pyfn0" )[ "meta" ][ "key_source" ] == "twin"
    assert run.job_maker( env, "nothing", "py", [ "pkg/alpha.py" ] )( "pkg/alpha.py" )[ "seed" ] == "pkg/alpha.py"
    make   = run.job_maker( env, "work_alike", "py", order )
    routes = [ make( s )[ "meta" ][ "route" ] for s in order ]
    assert sorted( routes ) == [ "sampled" ] * 3 + [ "vector" ] * 3
    again  = run.job_maker( make_env( tmp_path, name="again.jsonl" ), "work_alike", "py", list( reversed( order ) ) )
    assert [ again( s )[ "meta" ][ "route" ] for s in order ] == routes


def test_an_accepted_draft_becomes_a_valid_need_and_a_smoke_run_marks_it( tmp_path ):
    env    = make_env( tmp_path )
    record = { "seed": "pkg.alpha.pyfn0", "key": [ "pkg.alpha.pyfn1" ], "need": SENTENCE, "meta": { "route": None, "key_source": "twin", "key_lang": "py" } }
    need   = run.to_need( record, "near_copy", "py", env )
    schema.validate_need( need )
    assert need[ "seed" ] == "pkg.alpha.pyfn0" and need[ "key" ][ "symbols" ] == [ "pkg.alpha.pyfn1" ] and need[ "status" ] == "drafted" and "smoke" not in need
    assert need[ "drafter" ] == { "model": draft.DRAFTER_MODEL, "prompt_version": draft.prompt_version(), "server": "max-plan" } and need[ "source_commit" ] == COMMIT
    none = run.to_need( { "seed": "pkg/alpha.py", "key": [], "need": NOTHING, "meta": { "route": None, "key_source": None, "key_lang": None } }, "nothing", "py", env )
    assert none[ "seed" ] is None and none[ "key" ][ "symbols" ] == [] and none[ "selection_route" ] is None
    assert run.to_need( record, "near_copy", "py", make_env( tmp_path, smoke=True, name="s.jsonl" ) )[ "smoke" ] is True


def test_a_whole_run_writes_the_plan_the_drafts_and_the_report_and_fills_every_cell( tmp_path ):
    env    = make_env( tmp_path )
    got    = run.run_needset( env, table(), tmp_path )
    needs  = got[ "needs" ]
    assert len( needs ) == 12 == sum( n for row in table().values() for n in row.values() ) and all( n[ "status" ] == "drafted" and "smoke" not in n for n in needs )
    counts = {}
    for n in needs: counts[ ( n[ "kind" ], n[ "write_lang" ] ) ] = counts.get( ( n[ "kind" ], n[ "write_lang" ] ), 0 ) + 1
    assert counts == { ( k, l ): table()[ k ][ l ] for k in quota.ALL_KINDS for l in quota.LANGS if table()[ k ][ l ] }
    for n in needs: schema.validate_need( n )
    assert {  n[ "key" ][ "key_lang" ] for n in needs if n[ "kind" ] == "cross_language" } <= { "ts", "py" }
    assert all( n[ "key" ][ "key_lang" ] != n[ "write_lang" ] for n in needs if n[ "kind" ] == "cross_language" )
    assert all( n[ "key" ][ "source" ] == "twin" for n in needs if n[ "kind" ] == "near_copy" )
    assert all( n[ "seed" ] is None and n[ "key" ][ "symbols" ] == [] for n in needs if n[ "kind" ] == "nothing" )
    plan = json.loads( ( tmp_path / run.PLAN_FILE ).read_text() )
    assert plan == got[ "plan" ] and plan[ "pool_reader" ] == "read_searchable" and plan[ "seed" ] == DRAW_SEED and plan[ "source_commit" ] == COMMIT
    drafts = [ json.loads( l ) for l in ( tmp_path / run.DRAFTS_FILE ).read_text().splitlines() ]
    assert drafts == needs
    report = json.loads( ( tmp_path / run.REPORT_FILE ).read_text() )
    assert report == got[ "report" ] and report[ "format" ] == run.REPORT_FORMAT and report[ "smoke" ] is False
    assert report[ "counts" ] == { f"{k}/{l}": table()[ k ][ l ] for k in quota.ALL_KINDS for l in quota.LANGS if table()[ k ][ l ] } and max( report[ "counts" ].values() ) == 2
    assert report[ "census" ][ "near_copy" ] == { "ts": 4, "py": 4 } and set( report[ "replacements" ] ) == set( report[ "counts" ] )


def test_a_resumed_run_repeats_no_model_call_and_a_changed_plan_is_refused( tmp_path ):
    first  = make_env( tmp_path )
    one    = run.run_needset( first, table(), tmp_path )
    assert first.ask.calls > 0
    second = make_env( tmp_path )
    two    = run.run_needset( second, table(), tmp_path )
    assert second.ask.calls == 0 and two[ "needs" ] == one[ "needs" ]
    with pytest.raises( er.NeedsetError ) as e: run.run_needset( make_env( tmp_path, seed=DRAW_SEED + 1 ), table(), tmp_path )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN


def test_a_smoke_run_marks_every_need_and_the_report( tmp_path ):
    got = run.run_needset( make_env( tmp_path, smoke=True ), table(), tmp_path )
    assert all( n[ "smoke" ] is True for n in got[ "needs" ] ) and got[ "report" ][ "smoke" ] is True


def test_a_quota_without_nothing_needs_needs_no_nothing_drafter_and_a_zero_cell_is_skipped( tmp_path ):
    env = make_env( tmp_path, with_none=False )
    got = run.run_needset( env, quota.plan_quota( 10, 10, 0, 0.5, SPLIT ), tmp_path )
    assert len( got[ "needs" ] ) == 10 and not any( n[ "kind" ] == "nothing" for n in got[ "needs" ] )
    assert "nothing/py" not in got[ "report" ][ "counts" ]


def test_a_primary_that_fails_three_checks_is_replaced_by_the_next_seed_and_counted( tmp_path ):
    probe  = make_env( tmp_path )
    cells  = pool.cell_pool( probe.kept, probe.twins, set( probe.by_id ) )
    drawn  = quota.draw( cells, table(), DRAW_SEED )
    first  = drawn[ ( "near_copy", "py" ) ][ "primary" ][ 0 ]
    name   = first.split( "." )[ -1 ]
    leak   = ( f"word_of_{first.replace( '.', '_' )}", f"A function that adds up a list of numbers for {name} but stops once a ceiling has been reached." )
    env    = make_env( tmp_path, ask=Model( leak=leak ), name="leak.jsonl" )
    ( tmp_path / "leak" ).mkdir()
    got    = run.run_needset( env, table(), tmp_path / "leak" )
    cell   = next( c for c in got[ "cells" ] if c[ "cell" ] == "near_copy/py" )
    assert cell[ "original" ] == drawn[ ( "near_copy", "py" ) ][ "primary" ] and first in cell[ "original" ] and first not in cell[ "final" ]
    assert len( cell[ "final" ] ) == 2 and cell[ "replacements" ] == { er.NEED_LEAKS_KEY: 1 } and [ f[ "seed" ] for f in cell[ "failed" ] ] == [ first ]
    assert len( got[ "needs" ] ) == 12 and got[ "report" ][ "replacements" ][ "near_copy/py" ][ "total" ] == 1


def test_routes_depend_on_the_draw_seed_the_kind_and_the_language_of_the_cell( tmp_path ):
    env   = make_env( tmp_path )
    order = [ f"pkg.alpha.pyfn{n}" for n in range( 6 ) ]

    def routes( kind, lang, e=env ): return "".join( run.route_table( e, kind, lang, order )[ s ][ 0 ] for s in order )

    assert routes( "work_alike", "py" ) == "vvsssv" and routes( "work_alike", "ts" ) == "vssvsv" and routes( "cross_language", "py" ) == "vsvssv"
    assert routes( "work_alike", "py", make_env( tmp_path, seed=DRAW_SEED + 1, name="other.jsonl" ) ) != "vvsssv"


def test_a_nothing_job_leaves_out_the_symbols_of_the_other_language_in_the_same_file( tmp_path ):
    env = make_env( tmp_path )
    env.kept.append( make_record( "pkg.alpha.tsintruder", "pkg/alpha.py", "ts" ) )
    assert not any( "tsintruder" in l for l in run.nothing_job( env, "pkg/alpha.py", "py" )[ "lines" ] )
    assert [ l for l in run.nothing_job( env, "pkg/alpha.py", "ts" )[ "lines" ] ] == [ f"pkg.alpha.tsintruder(x) — Does the job of pkg.alpha.tsintruder." ]


def test_the_key_language_of_a_near_copy_is_the_language_of_its_twin( tmp_path ):
    env = make_env( tmp_path )
    env.twins[ "pkg.alpha.pyfn4" ], env.twins[ "web.alpha.tsfn4" ] = [ "web.alpha.tsfn4" ], [ "pkg.alpha.pyfn4" ]
    assert run.near_copy_job( env, "pkg.alpha.pyfn4", "py" )[ "meta" ][ "key_lang" ] == "ts"
    assert run.near_copy_job( env, "web.alpha.tsfn4", "ts" )[ "meta" ][ "key_lang" ] == "py"
