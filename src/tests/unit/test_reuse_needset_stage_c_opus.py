"""
The Opus pair judge, run against a stand-in model: no model call and no run folder.
"""
import json
import random

import pytest

from cosa.repo.doc_lint import model_transport
from lupin_mcp.reuse_needset import stage_c, stage_c_opus as so
from lupin_mcp.reuse_needset import stage_c_score as sc


def pair_of( n, label="same_job", stratum="flag", a="def a(): pass", b="def b(): pass", unsure=False, raters=2 ):
    """Return one read_pairs-shaped row."""
    return { "pair": f"pair-{n}", "stratum": stratum, "label": label, "unsure": unsure, "raters": raters, "a_id": "x", "b_id": "y", "a_text": a, "b_text": b }


def reply( f=0.9, r=0.8, choice="reuse" ):
    """Return a well-formed reply text."""
    return json.dumps( { "forward": { "choice": choice, "fit": f }, "reverse": { "choice": choice, "fit": r } } )


def test_judged_and_split_pairs_by_report():
    report = { "results": [ { "pair": "pair-1" }, { "pair": "pair-1" }, { "pair": "pair-2" } ] }
    assert so.judged_pairs( report ) == { "pair-1", "pair-2" }
    pairs = [ pair_of( 1 ), pair_of( 2 ), pair_of( 3 ) ]
    rated, left = so.split_pairs( pairs, so.judged_pairs( report ) )
    assert [ p[ "pair" ] for p in rated ] == [ "pair-1", "pair-2" ] and [ p[ "pair" ] for p in left ] == [ "pair-3" ]


def test_prompt_hides_the_label_and_the_suffix_is_in_neither_text():
    p = pair_of( 1, label="not_same", stratum="monolith:neighbour", a="x", b="y" )
    text = so.build_prompt( p, 2, random.Random( 1 ) )
    assert "not_same" not in text and "neighbour" not in text and "run: 2" in text
    suffix = text.split( "<A-" )[ 1 ].split( ">" )[ 0 ]
    assert f"</B-{suffix}>" in text and f"<A-{suffix}>\nx\n" in text


def test_suffix_is_redrawn_when_it_occurs_in_a_text():
    first = "%08x" % random.Random( 3 ).getrandbits( 32 )
    p = pair_of( 1, a=f"has {first} inside" )
    text = so.build_prompt( p, 1, random.Random( 3 ) )
    assert f"<A-{first}>" not in text


def test_parse_reply_reads_good_fenced_and_bad_replies():
    good = so.parse_reply( reply( 0.4, 0.6, "extend" ) )
    assert good[ "forward" ] == { "answered": True, "choice": "extend", "confidence": None, "p_overlap": 0.4 } and good[ "reverse" ][ "p_overlap" ] == 0.6
    assert so.parse_reply( "```json\n" + reply() + "\n```" )[ "forward" ][ "answered" ]
    for bad in ( "not json", "{}", json.dumps( { "forward": { "choice": "maybe", "fit": 0.5 }, "reverse": { "choice": "reuse", "fit": 0.5 } } ),
                 reply( f=1.5 ), reply( f=True ), json.dumps( { "forward": { "choice": "reuse", "fit": "x" }, "reverse": { "choice": "reuse", "fit": 0.1 } } ) ):
        got = so.parse_reply( bad )
        assert not got[ "forward" ][ "answered" ] and not got[ "reverse" ][ "answered" ]


def test_judge_pair_row_shape_and_failure_rows():
    seen = []
    row = so.judge_pair( pair_of( 1, unsure=True, raters=3 ), 2, lambda s, u: seen.append( ( s, u ) ) or reply( 0.7, 0.2 ), 5 )
    assert row[ "status" ] == "answered" and row[ "side_b" ][ "p_overlap" ] == 0.7 and row[ "side_a" ][ "p_overlap" ] == 0.2
    assert ( row[ "pair" ], row[ "repeat" ], row[ "stratum" ], row[ "label" ], row[ "unsure" ], row[ "raters" ], row[ "cue" ] ) == ( "pair-1", 2, "flag", "same_job", True, 3, False )
    assert seen[ 0 ][ 0 ] == so.SYSTEM
    assert so.judge_pair( pair_of( 1 ), 1, lambda s, u: "junk", 5 )[ "status" ] == "unanswered"
    def boom( s, u ): raise model_transport.ModelCallError( "down" )
    dead = so.judge_pair( pair_of( 1 ), 1, boom, 5 )
    assert dead[ "status" ] == "unanswered" and dead[ "error" ] == "down" and not dead[ "side_b" ][ "answered" ]


def test_same_seed_gives_same_prompt():
    prompts = []
    for _ in range( 2 ): so.judge_pair( pair_of( 1 ), 1, lambda s, u: prompts.append( u ) or reply(), 9 )
    assert prompts[ 0 ] == prompts[ 1 ]


def test_run_pairs_orders_rows_and_tabulate_scores_them():
    pairs = [ pair_of( i, label="same_job" if i % 2 else "not_same", stratum="flag" ) for i in range( 1, 25 ) ]
    def ask( system, user ):
        same = "def same" in user
        return reply( 0.9 if same else 0.1, 0.5 )
    for p in pairs: p[ "a_text" ] = "def same()" if p[ "label" ] == "same_job" else "def other()"
    rows = so.run_pairs( pairs, ask, 1, workers=3 )
    assert [ ( r[ "pair" ], r[ "repeat" ] ) for r in rows ] == [ ( p[ "pair" ], n ) for p in pairs for n in so.REPEATS ]
    tab = so.tabulate( rows, resamples=50 )
    assert tab[ "pairs" ] == 24 and tab[ "unanswered" ] == [ ] and tab[ "figures" ][ "auc" ][ "primary" ] == 1.0
    assert tab[ "figures" ][ "counts" ] == { sc.SAME: 12, sc.NOT_SAME: 12 }


def test_tabulate_names_a_pair_with_no_answer():
    rows = [ so.judge_pair( pair_of( 1, label="same_job" ), n, lambda s, u: "junk", 1 ) for n in so.REPEATS ] \
         + [ so.judge_pair( pair_of( 2, label="same_job" ), n, lambda s, u: reply(), 1 ) for n in so.REPEATS ] \
         + [ so.judge_pair( pair_of( 3, label="not_same" ), n, lambda s, u: reply( 0.2 ), 1 ) for n in so.REPEATS ]
    tab = so.tabulate( rows, resamples=20 )
    assert tab[ "unanswered" ] == [ "pair-1" ] and tab[ "pairs" ] == 2


def test_opus_ask_reads_the_judge_key_and_sends_one_prompt( monkeypatch ):
    calls = []
    async def fake( model, system, user, query_fn=None ):
        calls.append( ( model, system, user, query_fn ) )
        return "text"
    monkeypatch.setattr( so.model_transport, "complete", fake )
    monkeypatch.setattr( so.chs, "model_id", lambda key: f"model-of-{key}" )
    assert so.opus_ask()( "s", "u" ) == "text" and calls[ 0 ][ 0 ] == "model-of-duplicate check judge model"
    assert so.opus_ask( "given", query_fn="q" )( "s", "u" ) == "text" and calls[ 1 ][ 0 ] == "given" and calls[ 1 ][ 3 ] == "q"


@pytest.fixture
def staged( tmp_path, monkeypatch ):
    """Stand in for the answer key: three pairs, one already rated."""
    pairs = [ pair_of( i, label="same_job" if i % 2 else "not_same" ) for i in range( 1, 4 ) ]
    monkeypatch.setattr( stage_c, "read_pairs", lambda *a, **k: pairs )
    report = tmp_path / "report.json"
    report.write_text( json.dumps( { "results": [ { "pair": "pair-1" } ] } ), encoding="utf-8" )
    base = [ "--answer-key", "k", "--packet", "p", "--labels-dir", "l", "--report", str( report ), "--out", str( tmp_path / "out.json" ), "--cli-path", "claude" ]
    return base, tmp_path


def test_main_plan_calls_no_model( staged ):
    base, _ = staged
    assert so.main( base, ask=lambda s, u: pytest.fail( "no call expected" ) ) == { "live": False, "left": 2, "rated": 1, "chosen": 2 }
    assert so.main( base + [ "--only", "all" ] )[ "chosen" ] == 3 and so.main( base + [ "--only", "rated" ] )[ "chosen" ] == 1


def test_main_live_writes_rows_and_figures( staged, monkeypatch ):
    base, tmp = staged
    seen = []
    monkeypatch.setattr( so.model_transport, "configure", lambda cli_path=None, cwd=None: seen.append( cli_path ) )
    monkeypatch.setattr( so.chs, "model_id", lambda key: "claude-test" )
    out = so.main( base + [ "--live", "--workers", "2" ], ask=lambda s, u: reply() )
    assert out[ "live" ] and out[ "chosen" ] == 2 and out[ "calls" ] == 6 and seen == [ "claude" ]
    saved = json.loads( ( tmp / "out.json" ).read_text( encoding="utf-8" ) )
    assert saved[ "model" ] == "claude-test" and saved[ "only" ] == "left" and len( saved[ "rows" ] ) == 6
    monkeypatch.setattr( so, "opus_ask", lambda: ( lambda s, u: reply() ) )
    assert so.main( base + [ "--live", "--only", "rated" ] )[ "calls" ] == 3
