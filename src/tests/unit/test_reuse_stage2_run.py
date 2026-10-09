"""
The labelled-pair driver on a stand-in: plan, both questions over the candidates, rows.

The index is the generated one of the end-to-end tests. The new question is a stub that knows the twins.
Nothing here reaches Jev.
"""
import hashlib
import json

import pytest

from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_stage2_fit as fit
from lupin_mcp import reuse_stage2_run as s2
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_e2e_run import Env, IDS, make_wide_repo

MEMBERS = IDS[ :12 ]


def record_of( members=MEMBERS ):
    """Ensures: a negatives record: one twin, three lexical and two random candidates each."""
    out = {}
    for i, m in enumerate( members ):
        out[ m ] = { "twins": [ IDS[ i + 50 ] ], "lexical": [ IDS[ i + 60 ], IDS[ i + 61 ], IDS[ i + 62 ] ], "random": [ IDS[ i + 70 ], IDS[ i + 71 ] ], "held_out": [] }
    return { "format": "stage2-negatives-1", "members": out }


def put( path, record ):
    text = json.dumps( record, sort_keys=True )
    path.write_text( text, encoding="utf-8" )
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def by_id_of( scratch ): return { e[ "id" ]: e for e in rt.prepare( rt.ReuseContext( scratch.root, scratch.data ) )[ 1 ] }


def stub_new( ctx, need, entries ):
    """A new-question stand-in that rates the twin numbers 50 to 61 highly."""
    answered = { e[ "id" ]: { "provides": 0.9 if int( e[ "id" ][ -3: ] ) in range( 50, 62 ) else 0.1, "coverage": 0.8, "score": 2.5 } for e in entries }
    return { "answered": answered, "unasked": [], "malformed": [],
             "stats": { "failed": 0, "not_checked": 0, "stopped_by": None, "requests": 1, "attempt_counts": { "n429": 0, "n529": 0 } } }


@pytest.fixture
def wired( monkeypatch ):
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", stub_new )


def plan_of( scratch, tmp_path, members=MEMBERS ):
    path = tmp_path / "negatives.json"
    sha  = put( path, record_of( members ) )
    return s2.load_plan( path, sha, by_id_of( scratch ) )


def test_the_plan_lists_each_member_with_its_twins_then_lexical_then_random_candidates( tmp_path ):
    scratch = Env( tmp_path )
    items, twins = plan_of( scratch, tmp_path )
    assert [ i[ "member" ] for i in items ] == sorted( MEMBERS ) and len( items ) == 12
    first = items[ 0 ]
    assert [ e[ "id" ] for e in first[ "entries" ] ] == [ IDS[ 50 ], IDS[ 60 ], IDS[ 61 ], IDS[ 62 ], IDS[ 70 ], IDS[ 71 ] ]
    assert first[ "need" ] == rt.entry_text( by_id_of( scratch )[ first[ "member" ] ] ) and twins[ IDS[ 0 ] ] == { IDS[ 50 ] }


def test_a_candidate_listed_twice_is_asked_once( tmp_path ):
    scratch = Env( tmp_path )
    record = record_of( MEMBERS[ :1 ] )
    record[ "members" ][ IDS[ 0 ] ][ "random" ].append( IDS[ 60 ] )
    path = tmp_path / "negatives.json"
    sha  = put( path, record )
    items, _ = s2.load_plan( path, sha, by_id_of( scratch ) )
    assert [ e[ "id" ] for e in items[ 0 ][ "entries" ] ].count( IDS[ 60 ] ) == 1


def test_the_plan_refuses_a_wrong_hash_a_wrong_format_an_unindexed_id_and_a_member_with_no_candidate( tmp_path ):
    scratch = Env( tmp_path )
    by_id   = by_id_of( scratch )
    path    = tmp_path / "negatives.json"
    sha     = put( path, record_of() )
    with pytest.raises( s2.e2e.FrozenInputRefused, match="sha256" ): s2.load_plan( path, "0" * 64, by_id )
    bad = record_of(); bad[ "format" ] = "other"
    with pytest.raises( s2.e2e.FrozenInputRefused, match="format" ): s2.load_plan( path, put( path, bad ), by_id )
    bad = record_of(); bad[ "members" ][ IDS[ 0 ] ][ "lexical" ].append( "cosa.nowhere.gone" )
    with pytest.raises( s2.e2e.FrozenInputRefused, match="not in the index" ): s2.load_plan( path, put( path, bad ), by_id )
    bad = record_of(); bad[ "members" ][ "cosa.nowhere.member" ] = bad[ "members" ].pop( IDS[ 0 ] )
    with pytest.raises( s2.e2e.FrozenInputRefused, match="not in the index" ): s2.load_plan( path, put( path, bad ), by_id )
    bad = record_of(); bad[ "members" ][ IDS[ 0 ] ].update( twins=[], lexical=[], random=[] )
    with pytest.raises( s2.e2e.FrozenInputRefused, match="no candidate" ): s2.load_plan( path, put( path, bad ), by_id )


def test_the_old_question_asks_only_the_candidates_and_gives_a_row_for_each( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": s2.ask_old_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    rec = e2r.run_searches( scratch.env(), "s2-run", items[ :2 ], twins, 10 ** 8 )
    assert sum( scratch.posts ) == 12 and len( scratch.posts ) == 2                                   # six candidates a member, one request each
    for search in rec[ "searches" ]:
        assert search[ "status" ] == "complete" and len( search[ "rows" ] ) == 6 and all( r[ "p_overlap" ] is not None and r[ "unasked" ] is False for r in search[ "rows" ] )
        assert search[ "read" ]["verdict"] == "STAGE2"


def test_the_new_question_is_refused_until_it_is_wired( tmp_path, monkeypatch ):
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", None )
    scratch = Env( tmp_path, asks={ "new": s2.ask_new_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    with pytest.raises( s1.DriverRefused, match="not wired" ): e2r.run_searches( scratch.env(), "s2-run", items[ :1 ], twins, 10 ** 8 )


def test_both_questions_make_rows_the_fit_script_reads_and_the_twin_is_found( tmp_path, wired ):
    scratch = Env( tmp_path, asks={ "old": s2.ask_old_pairs, "new": s2.ask_new_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    rec  = e2r.run_searches( scratch.env(), "s2-run", items, twins, 10 ** 8 )
    rows = s2.rows_from_run( rec[ "searches" ], twins )
    assert len( rows ) == 12 * 6 and sum( 1 for r in rows if r[ "label" ] ) == 12
    fit.check_rows( rows )
    got = fit.evaluate( rows, { "reuse": 0.7, "threshold": 0.5, "floor": 0.3, "coverage": 0.5 } )
    assert got[ "members" ] == 12 and got[ "twins_on_shortlist" ] == 12 and got[ "unusable" ] == 0


def test_a_row_is_unusable_when_either_question_left_the_candidate_unasked_or_malformed():
    twins = { "m": { "t" } }
    def search( q, rows ): return { "member": "m", "question": q, "status": "complete", "rows": rows }
    old = search( "old", [ { "candidate": "t", "p_overlap": 0.9, "malformed": None, "unasked": False }, { "candidate": "x", "p_overlap": None, "malformed": None, "unasked": True },
                           { "candidate": "y", "p_overlap": 0.2, "malformed": None, "unasked": False } ] )
    new = search( "new", [ { "candidate": "t", "provides": 0.8, "coverage": 0.7, "score": 2.0, "malformed": None, "unasked": False },
                           { "candidate": "x", "provides": 0.1, "coverage": 0.1, "score": 0.5, "malformed": None, "unasked": False },
                           { "candidate": "y", "provides": None, "coverage": None, "score": None, "malformed": "coverage: levels", "unasked": False } ] )
    rows = {  r[ "candidate" ]: r for r in s2.rows_from_run( [ old, new ], twins ) }
    assert rows[ "t" ] == { "member": "m", "candidate": "t", "label": True, "provides": 0.8, "coverage": 0.7, "score": 2.0, "p_overlap": 0.9, "malformed": None, "unasked": False }
    assert rows[ "x" ][ "unasked" ] is True and rows[ "x" ][ "label" ] is False
    assert rows[ "y" ][ "malformed" ] == "coverage: levels" and rows[ "y" ][ "provides" ] is None


def test_a_member_with_only_one_question_run_gives_no_rows():
    twins = { "m": { "t" } }
    only_old = { "member": "m", "question": "old", "status": "complete", "rows": [ { "candidate": "t", "p_overlap": 0.9, "malformed": None, "unasked": False } ] }
    skipped  = { "member": "n", "question": "old", "status": "not_run", "causes": [ "ceiling" ] }
    assert s2.rows_from_run( [ only_old, skipped ], twins ) == []


def test_the_rows_file_is_written_whole_and_refuses_rows_the_fit_cannot_read( tmp_path ):
    good = [ { "member": "m", "candidate": "t", "label": True, "provides": 0.8, "coverage": 0.7, "score": 2.0, "p_overlap": 0.9, "malformed": None, "unasked": False } ]
    path = tmp_path / "rows.json"
    s2.write_rows( path, good )
    assert json.loads( path.read_text( encoding="utf-8" ) ) == { "format": s2.ROWS_FORMAT, "rows": good }
    with pytest.raises( ValueError, match="missing key" ): s2.write_rows( tmp_path / "bad.json", [ { "member": "m" } ] )
    assert not ( tmp_path / "bad.json" ).exists()


def test_the_stage_two_canary_projects_over_the_plan_and_holds_to_the_estimate_it_was_given( tmp_path, wired ):
    scratch = Env( tmp_path, asks={ "old": s2.ask_old_pairs, "new": s2.ask_new_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    spec   = s2.spec_for( len( items ), 5_000_000 )
    report = e2r.run_canary( scratch.env(), items, twins, 10 ** 8, spec=spec )
    assert spec == { "prefix": "s2", "members": 12, "estimate": 5_000_000, "canary_members": 5 } and report[ "run_name" ] == "s2-canary"
    assert report[ "projection_tokens" ] == report[ "tokens" ] * 12 // 5 and report[ "allowance_tokens" ] == min( 7_500_000, 10 ** 9 - report[ "tokens" ] )
    e2r.approve_canary( scratch.env(), "cheech", "read it", spec=spec )
    rec = e2r.run_full( scratch.env(), items, twins, 10 ** 8, spec=spec )
    assert rec[ "run_name" ] == "s2-run" and len( rec[ "searches" ] ) == 14 and rec[ "totals" ][ "complete" ] == 14          # seven members after the canary's five, two questions each


def command_args( scratch, tmp_path, *command, extra=() ):
    path = tmp_path / "negatives.json"
    sha  = put( path, record_of() )
    return [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.path ) ] + list( extra ) + list( command[ :1 ] ) + \
           [ "--negatives", str( path ), "--negatives-sha", sha ] + list( command[ 1: ] )


def test_the_command_line_runs_canary_approval_run_and_rows_on_the_stand_in( tmp_path, wired, capsys ):
    scratch = Env( tmp_path )
    assert s2.cli( [ "--root", str( scratch.root ), "--data", str( scratch.data ), "--ledger", str( scratch.path ), "status" ] ) == 0
    both = [ "--questions", "old,new" ]
    assert s2.cli( command_args( scratch, tmp_path, "canary", "--ceiling", "100000000", "--estimate-tokens", "5000000", extra=both ) ) == 0
    assert "ledger total before the first send: 0" in capsys.readouterr().out
    assert s2.cli( command_args( scratch, tmp_path, "run", "--ceiling", "100000000", "--estimate-tokens", "5000000", extra=both ) ) == 2
    assert s2.cli( command_args( scratch, tmp_path, "approve", "--by", "cheech", "--why", "read", "--estimate-tokens", "5000000", extra=both ) ) == 0
    assert s2.cli( command_args( scratch, tmp_path, "run", "--ceiling", "100000000", "--estimate-tokens", "5000000", extra=both ) ) == 0
    out_path = tmp_path / "rows.json"
    assert s2.cli( command_args( scratch, tmp_path, "rows", "--estimate-tokens", "5000000", "--out", str( out_path ), extra=both ) ) == 0
    rows = json.loads( out_path.read_text( encoding="utf-8" ) )[ "rows" ]
    assert len( rows ) == 12 * 6 and "rows written" in capsys.readouterr().out


def test_the_command_line_refuses_the_new_question_while_it_is_unwired_and_a_missing_estimate( tmp_path, capsys, monkeypatch ):
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", None )
    scratch = Env( tmp_path )
    assert s2.cli( command_args( scratch, tmp_path, "canary", "--ceiling", "100000000", "--estimate-tokens", "5000000", extra=[ "--questions", "old,new" ] ) ) == 2
    assert "not wired" in capsys.readouterr().err
    with pytest.raises( SystemExit ): s2.cli( command_args( scratch, tmp_path, "canary", "--ceiling", "100000000" ) )          # argparse: --estimate-tokens is required


def test_a_run_with_no_root_is_refused( monkeypatch, capsys ):
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )
    assert s2.cli( [ "status" ] ) == 2 and "--root" in capsys.readouterr().err


def test_the_member_listed_among_its_own_candidates_is_never_asked_about_itself( tmp_path ):
    scratch = Env( tmp_path )
    record = record_of( MEMBERS[ :1 ] )
    record[ "members" ][ IDS[ 0 ] ][ "lexical" ].append( IDS[ 0 ] )
    path = tmp_path / "negatives.json"
    sha  = put( path, record )
    items, _ = s2.load_plan( path, sha, by_id_of( scratch ) )
    assert IDS[ 0 ] not in [ e[ "id" ] for e in items[ 0 ][ "entries" ] ]


def test_a_candidate_the_new_question_left_unasked_or_answered_wrongly_gets_a_row_that_says_which( tmp_path, monkeypatch ):
    def partial( ctx, need, entries ):
        ids = [ e[ "id" ] for e in entries ]
        return { "answered": { i: { "provides": 0.5, "coverage": 0.5, "score": 1.0 } for i in ids[ 2: ] }, "unasked": [ ids[ 0 ] ], "malformed": [ { "id": ids[ 1 ], "reasons": [ "provides: bad", "coverage: bad" ] } ],
                 "stats": { "failed": 1, "not_checked": 0, "stopped_by": None, "requests": 1, "attempt_counts": { "n429": 0, "n529": 0 } } }
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", partial )
    scratch = Env( tmp_path, asks={ "new": s2.ask_new_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    rec  = e2r.run_searches( scratch.env(), "s2-run", items[ :1 ], twins, 10 ** 8 )
    rows = rec[ "searches" ][ 0 ][ "rows" ]
    assert ( rows[ 0 ][ "unasked" ], rows[ 0 ][ "malformed" ] ) == ( True, None )
    assert ( rows[ 1 ][ "unasked" ], rows[ 1 ][ "malformed" ] ) == ( False, "provides: bad; coverage: bad" ) and rows[ 2 ][ "provides" ] == 0.5
    assert rec[ "searches" ][ 0 ][ "causes" ] == [ "CALL_FAILED", "MALFORMED_ANSWER" ]


def test_an_unknown_question_name_is_refused_on_the_command_line( tmp_path, capsys ):
    scratch = Env( tmp_path )
    assert s2.cli( command_args( scratch, tmp_path, "canary", "--ceiling", "100000000", "--estimate-tokens", "5000000", extra=[ "--questions", "other" ] ) ) == 2
    assert "not one of" in capsys.readouterr().err


def test_an_old_answer_that_is_missing_or_wrong_gives_a_row_that_says_which( tmp_path ):
    scratch = Env( tmp_path, asks={ "old": s2.ask_old_pairs } )
    inner   = scratch.factory
    def damaging( budget ):
        transport = inner( budget )
        class Damage:
            def post_with_meta( self, body ):
                response, meta = transport.post_with_meta( body )
                keys = list( response[ "answers" ] )
                del response[ "answers" ][ keys[ 0 ] ]
                response[ "answers" ][ keys[ 1 ] ] = { "probabilities": { "reuse": 3.0, "extend": 0.0, "unrelated": 0.0 } }
                return response, meta
        return Damage()
    scratch.factory = damaging
    items, twins = plan_of( scratch, tmp_path )
    rows = e2r.run_searches( scratch.env(), "s2-run", items[ :1 ], twins, 10 ** 8 )[ "searches" ][ 0 ][ "rows" ]
    assert rows[ 0 ][ "unasked" ] is True and rows[ 0 ][ "p_overlap" ] is None
    assert rows[ 1 ][ "malformed" ] is not None and rows[ 1 ][ "p_overlap" ] is None and rows[ 2 ][ "p_overlap" ] is not None


def test_the_rows_of_a_stage_two_search_rank_best_first_and_a_candidate_at_exactly_half_is_on_the_shortlist( tmp_path, monkeypatch ):
    def graded( ctx, need, entries ):
        ids   = [ e[ "id" ] for e in entries ]
        marks = dict( zip( ids, [ 0.2, 0.5, 0.9, 0.4, 0.7, 0.1 ] ) )
        return { "answered": { i: { "provides": marks[ i ], "coverage": 0.5, "score": 1.0 } for i in ids }, "unasked": [], "malformed": [],
                 "stats": { "failed": 0, "not_checked": 0, "stopped_by": None, "requests": 1, "attempt_counts": { "n429": 0, "n529": 0 } } }
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", graded )
    scratch = Env( tmp_path, asks={ "new": s2.ask_new_pairs } )
    items, twins = plan_of( scratch, tmp_path )
    read = e2r.run_searches( scratch.env(), "s2-run", items[ :1 ], twins, 10 ** 8 )[ "searches" ][ 0 ]
    ids  = [ r[ "candidate" ] for r in read[ "rows" ] ]
    assert read[ "read" ] is not None
    result = s2.ask_new_pairs( None, items[ 0 ] )
    assert [ r[ "id" ] for r in result[ "nearest" ] ] == [ ids[ 2 ], ids[ 4 ], ids[ 1 ], ids[ 3 ], ids[ 0 ], ids[ 5 ] ]
    assert [ r[ "id" ] for r in result[ "shortlist" ] ] == [ ids[ 2 ], ids[ 4 ], ids[ 1 ] ]                           # 0.5 itself is in


def test_the_unwired_new_question_is_refused_by_the_name_check_before_any_ask_runs( monkeypatch ):
    monkeypatch.setattr( s2, "NEW_PAIR_ASK", None )
    with pytest.raises( s1.DriverRefused, match="not wired" ): s2._asks( [ "new" ] )
    with pytest.raises( s1.DriverRefused, match="not one of" ): s2._asks( [ "other" ] )
    assert list( s2._asks( [ "old" ] ) ) == [ "old" ]
