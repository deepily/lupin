"""
Loss tracing: the four stages, the alternatives, the resumable run and the report.

The checker and the probe are fakes that give every need a different answer, so two stages swapped reddens a test.
"""
import asyncio
import copy
import itertools
import json
import math

import pytest

from cosa.repo.doc_lint import harness_report, harness_runner
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import agent_probe, draft, finalize, loss_trace, schema
from lupin_mcp.reuse_needset import errors as er

COMMIT  = "0123456789abcdef0123456789abcdef01234567"
DRAFTER = { "model": draft.DRAFTER_MODEL, "prompt_version": "v1", "server": "max-plan" }
AGREED  = { "choice": "AS_PROPOSED", "symbols": [], "final_source": "agreed" }
ROOT    = "/tree"
FROZEN  = { "index_manifest": "a" * 64, "symbols_sha": "b" * 40, "vector_build_info_sha": "c" * 64 }
LT      = loss_trace
SENTENCE = "A function that adds up a list of numbers but stops once a ceiling has been reached."


def final_need( n, kind="near_copy", lang="py", route=None, source="twin" ):
    """Return a final matched need whose key is the single symbol k<n>."""
    rec = schema.new_need( kind, lang, f"seed.s{n}", route, [ f"k{n}" ], lang, source, f"{SENTENCE} Number {n}.", COMMIT, DRAFTER )
    rec = copy.deepcopy( rec )
    rec[ "check" ], rec[ "status" ] = { "model": "claude-opus-5-5", "result": "agree", "note": "n", "mechanical": [] }, "checked"
    return finalize.final_row( rec, AGREED )


def final_nothing( n, lang="py" ):
    """Return a final nothing need."""
    rec = schema.new_need( "nothing", lang, None, None, [], None, None, f"A function that does job number {n} and returns its answer to the caller.", COMMIT, DRAFTER )
    rec = copy.deepcopy( rec )
    rec[ "check" ], rec[ "status" ] = { "model": "claude-opus-5-5", "result": "agree", "note": "n", "mechanical": [] }, "checked"
    return finalize.final_row( rec, AGREED )


def whole( sym ): return { "path": f"{ROOT}/{sym}.py", "offset": None, "limit": None }


def where( sym ): return { "file": f"{sym}.py", "line": 10, "end_line": 20 }


class World:
    """The fake checker and probe: a script per need id, with every call counted."""

    def __init__( self ):
        self.script, self.asks, self.probes = {}, [], []

    def add( self, need, asked, shortlist, verdict="UNCERTAIN_READ_SOURCE", reads=(), rulings=None ):
        self.script[ need[ "id" ] ] = { "asked": asked, "shortlist": shortlist, "verdict": verdict, "reads": list( reads ), "rulings": rulings }

    def ask( self, need, ctx ):
        self.asks.append( need[ "id" ] )
        s = self.script[ need[ "id" ] ]
        return { "id": f"r-{need[ 'id' ]}", "verdict": s[ "verdict" ], "index_sha": "idx1", "shortlist": [ { "id": i } for i in s[ "shortlist" ] ],
                 "candidate_stage": { "ids": [ i for i in s[ "asked" ] if i not in s[ "asked" ][ -1: ] ], "widened_ids": s[ "asked" ][ -1: ] } }

    async def probe( self, sentence, receipt, root, model ):
        self.probes.append( receipt[ "id" ] )
        s = next( v for k, v in self.script.items() if f"r-{k}" == receipt[ "id" ] )
        return { "rulings": s[ "rulings" ], "reads": s[ "reads" ], "reply": "", "transcript": [ { "type": "text", "text": receipt[ "id" ] } ] }


def trace( world, need ): return asyncio.run( LT.trace_need( need, None, world.probe, ROOT, "claude-opus-5-5", ask=world.ask, where=where ) )


def matched_set():
    """Return ( needs, world ): eight matched needs, each lost at its own place."""
    w, needs = World(), [ final_need( n ) for n in range( 8 ) ]
    k = [ f"k{n}" for n in range( 8 ) ]
    w.add( needs[ 0 ], [ k[ 0 ], "x" ], [ k[ 0 ] ], reads=[ whole( k[ 0 ] ) ], rulings={ k[ 0 ]: "DUPLICATE" } )                         # FOUND
    w.add( needs[ 1 ], [ "x", "y" ], [ "x" ] )                                                                                         # NOT_RETRIEVED
    w.add( needs[ 2 ], [ k[ 2 ], "x" ], [ "x" ] )                                                                                      # NOT_RATED_RELEVANT
    w.add( needs[ 3 ], [ k[ 3 ] ], [ k[ 3 ] ], reads=[ whole( "other" ) ], rulings={ k[ 3 ]: "DUPLICATE" } )                         # NOT_READ: another file
    w.add( needs[ 4 ], [ k[ 4 ] ], [ k[ 4 ] ], reads=[ { **whole( k[ 4 ] ), "offset": 12, "limit": 50 } ], rulings={ k[ 4 ]: "DUPLICATE" } )   # NOT_READ: range excludes the head
    w.add( needs[ 5 ], [ k[ 5 ] ], [ k[ 5 ] ], reads=[ whole( k[ 5 ] ) ], rulings={ k[ 5 ]: "DISTINCT" } )                           # NOT_RULED_SAME_JOB
    w.add( needs[ 6 ], [ k[ 6 ], "alt" ], [ k[ 6 ], "alt" ], reads=[ whole( k[ 6 ] ), whole( "alt" ) ], rulings={ k[ 6 ]: "DISTINCT", "alt": "EXTEND" } )   # ALT_MATCH
    w.add( needs[ 7 ], [ k[ 7 ] ], [ k[ 7 ] ], reads=[ whole( k[ 7 ] ) ], rulings={ k[ 7 ]: "EXTEND" } )                              # FOUND by extend
    return needs, w


EXPECTED = [ LT.FOUND, LT.NOT_RETRIEVED, LT.NOT_RATED_RELEVANT, LT.NOT_READ, LT.NOT_READ, LT.NOT_RULED_SAME_JOB, LT.ALT_MATCH, LT.FOUND ]


def test_each_matched_need_is_lost_at_the_first_stage_that_fails():
    needs, w = matched_set()
    got      = [ trace( w, n ) for n in needs ]
    assert [ r[ "lost_at" ] for r in got ] == EXPECTED
    assert got[ 6 ][ "alt" ] == [ "alt" ] and all( r[ "alt" ] == [] for i, r in enumerate( got ) if i != 6 )
    assert got[ 0 ][ "key" ] == [ "k0" ] and got[ 0 ][ "evidence" ][ "read" ] == [ "k0" ] and got[ 3 ][ "evidence" ][ "read" ] == []


def test_the_probe_runs_only_for_a_need_whose_key_reached_the_shortlist():
    needs, w = matched_set()
    for n in needs: trace( w, n )
    assert w.asks == [ n[ "id" ] for n in needs ]
    assert w.probes == [ f"r-{needs[ i ][ 'id' ]}" for i in ( 0, 3, 4, 5, 6, 7 ) ]


def test_a_key_symbol_that_was_asked_listed_and_read_is_only_found_when_the_same_symbol_was_ruled():
    ev = { "verdict": "X", "asked": [ "a", "b" ], "shortlist": [ "a", "b" ], "read": [ "b" ], "rulings": { "a": "DUPLICATE", "b": "DISTINCT" } }
    assert LT.classify( "near_copy", [ "a", "b" ], ev )[ "lost_at" ] == LT.NOT_RULED_SAME_JOB
    assert LT.classify( "near_copy", [ "a", "b" ], dict( ev, read=[ "a", "b" ] ) )[ "lost_at" ] == LT.FOUND
    assert LT.classify( "near_copy", [ "a", "b" ], dict( ev, shortlist=[ "b" ], read=[ "a", "b" ] ) )[ "lost_at" ] == LT.NOT_RULED_SAME_JOB
    assert LT.classify( "near_copy", [ "a", "z" ], dict( ev, asked=[ "b" ] ) )[ "lost_at" ] == LT.NOT_RETRIEVED


def test_an_alternative_only_replaces_not_ruled_same_job_and_never_an_earlier_loss():
    ev = { "verdict": "X", "asked": [ "k", "alt" ], "shortlist": [ "k", "alt" ], "read": [ "alt" ], "rulings": { "k": "DISTINCT", "alt": "DUPLICATE" } }
    assert LT.classify( "near_copy", [ "k" ], ev ) == { "lost_at": LT.NOT_READ, "alt": [] }
    assert LT.classify( "near_copy", [ "k" ], dict( ev, read=[ "k", "alt" ] ) ) == { "lost_at": LT.ALT_MATCH, "alt": [ "alt" ] }
    assert LT.classify( "near_copy", [ "k", "alt" ], dict( ev, read=[ "k", "alt" ] ) ) == { "lost_at": LT.FOUND, "alt": [] }


def nothing_world():
    w, needs = World(), [ final_nothing( n ) for n in range( 4 ) ]
    w.add( needs[ 0 ], [ "x" ], [] )                                                                                      # nothing found: correct, no probe
    w.add( needs[ 1 ], [ "x" ], [ "x" ], verdict="REUSE" )                                                                # the checker said reuse: false match, no probe
    w.add( needs[ 2 ], [ "x", "y" ], [ "x", "y" ], reads=[ whole( "y" ) ], rulings={ "x": "DISTINCT", "y": "DUPLICATE" } )   # the probe ruled y the same job
    w.add( needs[ 3 ], [ "x" ], [ "x" ], reads=[ whole( "x" ) ], rulings={ "x": "DISTINCT" } )                           # the probe agreed nothing exists
    return needs, w


def test_a_nothing_need_is_a_false_match_when_the_checker_or_the_probe_says_a_symbol_does_the_job():
    needs, w = nothing_world()
    got      = [ trace( w, n ) for n in needs ]
    assert [ r[ "lost_at" ] for r in got ] == [ LT.CORRECT_NO_MATCH, LT.FALSE_MATCH, LT.FALSE_MATCH, LT.CORRECT_NO_MATCH ]
    assert [ r[ "alt" ] for r in got ] == [ [], [], [ "y" ], [] ] and w.probes == [ f"r-{needs[ 2 ][ 'id' ]}", f"r-{needs[ 3 ][ 'id' ]}" ]


def test_a_confirmed_alternative_extends_the_key_and_the_same_evidence_finds_the_need():
    needs, w = matched_set()
    rec      = trace( w, needs[ 6 ] )
    bigger   = LT.extend_key( needs[ 6 ], [ "alt" ] )
    assert bigger[ "key" ][ "symbols" ] == [ "alt", "k6" ] and bigger[ "key" ][ "version" ] == needs[ 6 ][ "key" ][ "version" ] + 1 and bigger[ "key" ][ "provenance" ] == "reviewer_confirmed"
    assert bigger[ "id" ] == needs[ 6 ][ "id" ] and needs[ 6 ][ "key" ][ "symbols" ] == [ "k6" ]
    again = LT.retrace( rec, bigger )
    assert again[ "lost_at" ] == LT.FOUND and again[ "key" ] == [ "alt", "k6" ] and again[ "evidence" ] == rec[ "evidence" ] and rec[ "lost_at" ] == LT.ALT_MATCH
    assert LT.retrace( rec, needs[ 6 ] )[ "lost_at" ] == LT.ALT_MATCH and len( w.asks ) == 1 and len( w.probes ) == 1


def test_an_unconfirmed_alternative_is_counted_as_not_ruled_same_job_when_the_summary_asks_for_it():
    needs, w = matched_set()
    rec      = trace( w, needs[ 6 ] )
    assert rec[ "lost_at" ] == LT.ALT_MATCH and LT.summarize( [ rec ] )[ "misses" ] == 1


def test_the_items_for_the_reviewers_are_built_for_alternatives_and_false_matches_only():
    needs, w = matched_set()
    nothing, w2 = nothing_world()
    recs  = [ trace( w, n ) for n in needs ] + [ trace( w2, n ) for n in nothing ]
    items = LT.confirmation_items( recs, needs + nothing, lambda i: f"source of {i}" )
    kinds = { n[ "id" ]: n for n in needs + nothing }
    assert [ i[ "item_id" ] for i in items ] == [ needs[ 6 ][ "id" ], nothing[ 1 ][ "id" ], nothing[ 2 ][ "id" ] ]
    assert items[ 0 ][ "payload" ][ "key_sources" ] == [ "source of alt" ] and items[ 0 ][ "payload" ][ "need" ] == kinds[ needs[ 6 ][ "id" ] ][ "need" ]
    assert items[ 1 ][ "payload" ][ "nothing_exists" ] is True and items[ 1 ][ "payload" ][ "hits" ] == [ "source of x" ] and items[ 2 ][ "payload" ][ "hits" ] == [ "source of y" ]
    assert all( "verdict" not in json.dumps( i ) and "rulings" not in json.dumps( i ) for i in items )


def make_ledger( tmp_path ): return harness_runner.Ledger( str( tmp_path / "trace.jsonl" ) )


def run_all( needs, w, ledger, model="claude-opus-5-5", parallel=3, commit="c1", sha="idx1" ):
    return asyncio.run( LT.trace_all( needs, None, ledger, ROOT, model, commit, FROZEN, FROZEN, index_sha=sha, probe=w.probe, ask=w.ask, where=where, parallel=parallel ) )


def test_trace_all_returns_the_records_in_order_and_a_second_run_makes_no_call( tmp_path ):
    needs, w = matched_set()
    ledger   = make_ledger( tmp_path )
    first    = run_all( needs, w, ledger )
    assert [ r[ "lost_at" ] for r in first ] == EXPECTED and len( w.asks ) == 8 and len( w.probes ) == 6 and len( ledger.entries ) == 8
    again    = run_all( needs, w, harness_runner.Ledger( str( tmp_path / "trace.jsonl" ) ) )
    assert again == first and len( w.asks ) == 8 and len( w.probes ) == 6


def test_a_changed_probe_model_or_prompt_version_is_a_ledger_miss( tmp_path, monkeypatch ):
    needs, w = matched_set()
    ledger   = make_ledger( tmp_path )
    run_all( needs, w, ledger )
    run_all( needs, w, ledger, model="claude-opus-5-6" )
    assert len( w.asks ) == 16
    monkeypatch.setattr( agent_probe, "INSTRUCTION", agent_probe.INSTRUCTION + "!" )
    run_all( needs, w, ledger )
    assert len( w.asks ) == 24 and len( ledger.entries ) == 24


def test_a_failing_probe_stops_the_pending_needs_and_keeps_the_finished_records( tmp_path ):
    needs, w = matched_set()
    ledger   = make_ledger( tmp_path )
    real     = w.probe

    async def failing( sentence, receipt, root, model ):
        if receipt[ "id" ] == f"r-{needs[ 4 ][ 'id' ]}": raise er.NeedsetError( er.PROBE_UNREADABLE, "boom" )
        return await real( sentence, receipt, root, model )

    with pytest.raises( er.NeedsetError ) as e: asyncio.run( LT.trace_all( needs, None, ledger, ROOT, "m", "c1", FROZEN, FROZEN, index_sha="idx1", probe=failing, ask=w.ask, where=where, parallel=3 ) )
    assert e.value.code == er.PROBE_UNREADABLE and sorted( w.asks ) == sorted( n[ "id" ] for n in needs[ :5 ] ) and len( ledger.entries ) == 4
    resumed = run_all( needs, w, harness_runner.Ledger( str( tmp_path / "trace.jsonl" ) ), model="m" )
    assert len( resumed ) == 8


def test_trace_all_refuses_a_smoke_need_an_unfinished_need_and_a_set_with_nothing_matched_before_any_call( tmp_path ):
    needs, w = matched_set()
    for bad in ( [ dict( needs[ 0 ], smoke=True ) ], [ dict( needs[ 0 ], status="checked" ) ], [ final_nothing( 1 ) ] ):
        with pytest.raises( er.NeedsetError ) as e: run_all( bad, w, make_ledger( tmp_path ) )
        assert e.value.code == er.BAD_NEED
    assert w.asks == []


def test_trace_all_builds_the_locator_from_the_index_when_none_is_given( tmp_path, monkeypatch ):
    needs, w = matched_set()
    monkeypatch.setattr( LT, "index_locator", lambda ctx: where )
    out = asyncio.run( LT.trace_all( needs[ :1 ], "ctx", make_ledger( tmp_path ), ROOT, "m", "c1", FROZEN, FROZEN, index_sha="idx1", probe=w.probe, ask=w.ask ) )
    assert out[ 0 ][ "lost_at" ] == LT.FOUND


def test_a_changed_checker_commit_index_sha_or_source_commit_is_a_ledger_miss( tmp_path ):
    needs, w = matched_set()
    ledger   = make_ledger( tmp_path )
    run_all( needs, w, ledger )
    run_all( needs, w, ledger )
    assert len( w.asks ) == 8
    run_all( needs, w, ledger, commit="c2" )
    assert len( w.asks ) == 16
    run_all( needs, w, ledger, sha="idx2" )
    assert len( w.asks ) == 24
    moved = [ dict( needs[ 0 ], source_commit="f" * 40 ) ]
    run_all( moved, w, ledger )
    assert len( w.asks ) == 25 and len( ledger.entries ) == 25


def test_an_empty_checker_commit_index_sha_or_source_commit_is_refused_before_any_call( tmp_path ):
    needs, w = matched_set()
    for kwargs in ( { "commit": "" }, { "commit": None }, { "sha": " " }, { "sha": "none" }, { "sha": " None " } ):
        with pytest.raises( er.NeedsetError ) as e: run_all( needs, w, make_ledger( tmp_path ), **kwargs )
        assert e.value.code == er.BAD_NEED
    with pytest.raises( er.NeedsetError ) as e: run_all( [ dict( needs[ 0 ], source_commit="" ) ], w, make_ledger( tmp_path ) )
    assert e.value.code == er.BAD_NEED and "source_commit" in e.value.detail and w.asks == []


def test_the_index_sha_comes_from_the_context_when_none_is_given( tmp_path, monkeypatch ):
    needs, w = matched_set()
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), [], "from-ctx", "gen" ) )
    ledger = make_ledger( tmp_path )
    asyncio.run( LT.trace_all( needs[ :1 ], "ctx", ledger, ROOT, "m", "c1", FROZEN, FROZEN, probe=w.probe, ask=w.ask, where=where ) )
    asyncio.run( LT.trace_all( needs[ :1 ], "ctx", ledger, ROOT, "m", "c1", FROZEN, FROZEN, index_sha="from-ctx", probe=w.probe, ask=w.ask, where=where ) )
    assert len( w.asks ) == 1


def test_the_locator_reads_file_and_range_from_the_index_and_refuses_a_symbol_without_them( monkeypatch, tmp_path ):
    index = [ { "id": "a.f", "file": "a.py", "line": 3, "end_line": 9, "scope": "public" }, { "id": "a.g", "file": "a.py", "line": 12, "end_line": 15, "scope": "private" }, { "id": "a.h", "file": "a.py", "line": 20, "scope": "public" },
              { "id": "a.t", "file": "t.py", "line": 1, "end_line": 2, "scope": "test" } ]
    ( tmp_path / "symbols-all.jsonl" ).write_text( "".join( json.dumps( r ) + "\n" for r in index ), encoding="utf-8" )
    monkeypatch.setattr( rt, "prepare", lambda ctx: ( set(), [], "sha", str( tmp_path ) ) )
    loc = LT.index_locator( None )
    assert loc( "a.f" ) == { "file": "a.py", "line": 3, "end_line": 9 } and loc( "a.g" ) == { "file": "a.py", "line": 12, "end_line": 15 }
    for bad in ( "a.h", "a.t", "nope" ):                  # no end_line, a test-scope symbol a search never ranks, and an id the index lacks
        with pytest.raises( er.NeedsetError ) as e: loc( bad )
        assert e.value.code == er.RECEIPT_FIELD_ABSENT and bad in e.value.detail


def records_for_summary():
    def rec( kind, lang, lost, route=None ): return { "kind": kind, "write_lang": lang, "selection_route": route, "lost_at": lost }
    return ( [ rec( "near_copy", "py", LT.FOUND ) ] * 3 + [ rec( "work_alike", "ts", LT.NOT_RETRIEVED, "vector" ), rec( "work_alike", "ts", LT.FOUND, "vector" ),
              rec( "work_alike", "py", LT.NOT_RETRIEVED, "sampled" ), rec( "cross_language", "ts", LT.NOT_READ, "sampled" ) ]
             + [ rec( "nothing", "py", LT.CORRECT_NO_MATCH ), rec( "nothing", "py", LT.FALSE_MATCH ) ] )


def test_the_summary_counts_by_outcome_kind_language_route_and_gives_the_miss_rate_and_its_bound():
    s = LT.summarize( records_for_summary() )
    assert s[ "matched" ] == 7 and s[ "by_lost_at" ] == { "FOUND": 4, "NOT_READ": 1, "NOT_RETRIEVED": 2 }
    assert s[ "by_kind" ] == { "cross_language": { "NOT_READ": 1 }, "near_copy": { "FOUND": 3 }, "work_alike": { "FOUND": 1, "NOT_RETRIEVED": 2 } }
    assert s[ "by_lang" ] == { "py": { "FOUND": 3, "NOT_RETRIEVED": 1 }, "ts": { "FOUND": 1, "NOT_READ": 1, "NOT_RETRIEVED": 1 } }
    assert s[ "not_retrieved_by_route" ] == { "sampled": { "needs": 2, "not_retrieved": 1 }, "vector": { "needs": 2, "not_retrieved": 1 } }
    assert s[ "nothing" ] == { "CORRECT_NO_MATCH": 1, "FALSE_MATCH": 1 } and s[ "misses" ] == 3 and s[ "miss_rate" ] == 3 / 7 and s[ "upper_bound" ] == harness_report.upper_bound( 3, 7 )
    with pytest.raises( er.NeedsetError ) as e: LT.summarize( [ { "kind": "nothing", "write_lang": "py", "selection_route": None, "lost_at": LT.CORRECT_NO_MATCH } ] )
    assert e.value.code == er.BAD_NEED


def test_scipy_importable():
    import scipy.stats   # noqa: F401  (the bound below needs it; this test fails by name when the interpreter lacks it)


def bisect_bound( misses, trials ):
    """Return the 95 percent bound by bisecting the binomial tail, apart from the library."""
    def tail( p ): return sum( math.comb( trials, k ) * p ** k * ( 1 - p ) ** ( trials - k ) for k in range( misses + 1 ) )
    low, high = 0.0, 1.0
    for _ in range( 60 ):
        mid = ( low + high ) / 2
        low, high = ( mid, high ) if tail( mid ) > 0.05 else ( low, mid )
    return high


@pytest.mark.parametrize( "misses, expected", [ ( 0, 0.0099 ), ( 3, 0.0256 ) ] )
def test_the_bound_for_300_matched_needs_is_pinned_to_a_value_computed_by_bisection( misses, expected ):
    got = harness_report.upper_bound( misses, 300 )
    assert round( got, 4 ) == expected and abs( got - bisect_bound( misses, 300 ) ) < 1e-9
    recs = [ { "kind": "near_copy", "write_lang": "py", "selection_route": None, "lost_at": LT.FOUND } ] * ( 300 - misses ) + [ { "kind": "near_copy", "write_lang": "py", "selection_route": None, "lost_at": LT.NOT_READ } ] * misses
    assert LT.summarize( recs )[ "upper_bound" ] == got


def test_the_report_prints_the_figures_before_and_after_the_confirmations( tmp_path ):
    recs   = records_for_summary()
    before = LT.summarize( recs )
    after  = LT.summarize( [ dict( r, lost_at=LT.FOUND ) if r[ "lost_at" ] == LT.NOT_READ else r for r in recs ] )
    meta   = { "checker_commit": COMMIT, "index_sha": "idx1", "probe_model": "claude-opus-5-5", "date": "2026-10-25" }
    LT.write_report( tmp_path, before, after, [ dict( r, transcript=[ "t" ] ) for r in recs ], meta )
    data = json.loads( ( tmp_path / "loss-report.json" ).read_text() )
    assert data[ "meta" ] == meta and data[ "before" ][ "misses" ] == 3 and data[ "after" ][ "misses" ] == 2 and len( data[ "rows" ] ) == 9 and all( "transcript" not in r for r in data[ "rows" ] )
    md = ( tmp_path / "loss-report.md" ).read_text()
    assert "| NOT_READ | 1 | 0 |" in md and "| FOUND | 4 | 5 |" in md and f"{before[ 'miss_rate' ]:.4f}" in md and f"{after[ 'upper_bound' ]:.4f}" in md
    assert "| sampled | 2 | 1 |" in md and "checker_commit: " + COMMIT in md


@pytest.mark.parametrize( "key, code", [ ( "index_manifest", er.INDEX_DIFFERS ), ( "symbols_sha", er.INDEX_DIFFERS ), ( "vector_build_info_sha", er.VECTORS_DIFFER ) ] )
def test_trace_all_refuses_a_run_whose_index_or_vectors_differ_from_the_frozen_set_before_any_call( tmp_path, key, code ):
    needs, w = matched_set()
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( LT.trace_all( needs, None, make_ledger( tmp_path ), ROOT, "m", "c1", FROZEN, dict( FROZEN, **{ key: "d" * 64 } ), index_sha="idx1", probe=w.probe, ask=w.ask, where=where ) )
    assert e.value.code == code and key in e.value.detail and w.asks == [] and w.probes == []
