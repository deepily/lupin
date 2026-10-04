"""
The reader-rig runner: questions file checks, the documentation-only text, the call-cap refusal,
resume from the ledger and the weighted arithmetic. No test contacts a model: a fake query_fn
answers, and each repo is a throwaway git repo with two commits of a made-up module.

The fake reader replies with the whole text it was given. The fake grader scores 1 when the key
occurs in that reply, so a sentence lost from the new text really lowers the new score.
"""

import asyncio
import json
import re
import subprocess

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from cosa.repo.doc_lint import harness_runner, model_transport, reader_rig
from cosa.repo.doc_lint import reader_rig_run as rr

OLD_A = '''"""Module for parked rows."""

# the chase window is ten minutes


def fn_a( items ):
    """Return an empty dict when items is empty. Never raises."""
    secret_body_line = 42
    return {}
'''
NEW_A = OLD_A.replace( " Never raises.", "" )
OLD_B = '''class Box:
    """A box holds one thing: the lid stays shut."""

    @staticmethod
    async def open_it( lid, *, force=False ) -> bool:
        """Open the lid. It sticks in cold weather."""
        hidden_body = 1
        return hidden_body
'''
NEW_B = OLD_B
READER = "reader-m"
GRADER = "grader-m"


def q( qid, file, question, points, **extra ):
    return dict( { "id": qid, "file": file, "question": question, "key_points": points }, **extra )


def write_json( path, data ):
    path.write_text( json.dumps( data ) )
    return str( path )


@pytest.fixture( autouse=True )
def clean_transport():
    yield
    model_transport.set_budget( None, {} )
    model_transport.configure()


@pytest.fixture
def repo( tmp_path ):
    root = tmp_path / "repo"
    ( root / "src" ).mkdir( parents=True )

    def git( *args ):
        return subprocess.run( [ "git", "-C", str( root ), "-c", "user.name=t", "-c", "user.email=t@t", *args ], capture_output=True, text=True, check=True ).stdout.strip()

    git( "init", "-q" )
    ( root / "src" / "mod_a.py" ).write_text( OLD_A )
    ( root / "src" / "mod_b.py" ).write_text( OLD_B )
    git( "add", "." )
    git( "commit", "-qm", "old" )
    old = git( "rev-parse", "HEAD" )
    ( root / "src" / "mod_a.py" ).write_text( NEW_A )
    git( "add", "." )
    git( "commit", "-qm", "new" )
    new = git( "rev-parse", "HEAD" )
    # the working tree differs from both commits: the runner must read git, not the disk
    ( root / "src" / "mod_a.py" ).write_text( "# working tree only\n" )
    return { "root": str( root ), "old": old, "new": new, "tmp": tmp_path }


class FakeModels:
    def __init__( self ):
        self.calls = []

    async def __call__( self, prompt, options ):
        self.calls.append( ( options.model, options.system_prompt, prompt ) )
        if options.system_prompt == reader_rig.READER_SYSTEM:
            body = re.search( r"<text_(\w+)>\n(.*?)\n</text_\1>", prompt, re.DOTALL ).group( 2 )
            text = json.dumps( { "answer": body } )
        else:
            key    = re.search( r"<key_(\w+)>\n(.*?)\n</key_\1>", prompt, re.DOTALL ).group( 2 )
            answer = re.search( r"<answer_(\w+)>\n(.*?)\n</answer_\1>", prompt, re.DOTALL ).group( 2 )
            text   = json.dumps( { "score": 1 if all( p in answer for p in key.split( "; " ) ) else 0 } )
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )

    def by( self, model ):
        return [ c for c in self.calls if c[ 0 ] == model ]


QA   = q( "qa", "src/mod_a.py", "What does fn_a return for an empty list?", [ "empty dict", "Never raises" ], common_wrong_answer="WRONGANSWER-xyz", verified="ran it", symbols=[ "fn_a" ] )
QB1  = q( "qb1", "src/mod_b.py", "What does the box do?", [ "lid stays shut" ] )
QB2  = q( "qb2", "src/mod_b.py", "What sticks?", [ "sticks in cold weather" ] )
QB3  = q( "qb3", "src/mod_b.py", "What does open_it do?", [ "Open the lid" ] )


def argv( repo, qpath, out=None, **over ):
    base = { "--old-rev": repo[ "old" ], "--new-rev": repo[ "new" ], "--questions": qpath, "--reader-model": READER, "--grader-model": GRADER,
             "--runs": "2", "--ledger": str( repo[ "tmp" ] / "ledger.jsonl" ), "--reader-cap": "1000", "--grader-cap": "1000", "--repo": repo[ "root" ] }
    if out is not None: base[ "--out" ] = out
    base.update( over )
    return [ x for k, v in base.items() for x in ( k, v ) ]


def questions_file( repo, qs ):
    return write_json( repo[ "tmp" ] / "q.json", { "count": len( qs ), "questions": qs } )


def run( repo, qs, models=None, extra=None, **over ):
    models = models or FakeModels()
    code   = rr.main( argv( repo, questions_file( repo, qs ), **over ) + ( extra or [] ), query_fn=models )
    return code, models


# ---- questions file refusals ------------------------------------------------------------------

def test_count_mismatch_is_refused_with_no_model_call( repo, capsys ):
    path = write_json( repo[ "tmp" ] / "q.json", { "count": 3, "questions": [ QA ] } )
    models = FakeModels()
    assert rr.main( argv( repo, path ), query_fn=models ) == 2
    assert "count is 3" in capsys.readouterr().err
    assert models.calls == []


def test_repeated_id_is_refused( repo, capsys ):
    code, models = run( repo, [ QA, dict( QB1, id="qa" ) ] )
    assert code == 2 and "id 'qa' repeats" in capsys.readouterr().err
    assert models.calls == []


def test_question_without_key_points_is_refused( repo, capsys ):
    for bad in ( dict( QA, key_points=[] ), { k: v for k, v in QA.items() if k != "key_points" }, dict( QA, key_points=[ "ok", " " ] ) ):
        code, models = run( repo, [ bad ] )
        assert code == 2 and "has no key_points" in capsys.readouterr().err
        assert models.calls == []


def test_other_malformed_questions_files_are_refused( repo, capsys ):
    tmp = repo[ "tmp" ]
    cases = { "not json": "{nope", "list": "[]", "empty": json.dumps( { "count": 0, "questions": [] } ),
              "bare question": json.dumps( { "count": 1, "questions": [ "text" ] } ),
              "no file": json.dumps( { "count": 1, "questions": [ { k: v for k, v in QA.items() if k != "file" } ] } ) }
    for name, body in cases.items():
        path = tmp / f"{name.replace( ' ', '-' )}.json"
        path.write_text( body )
        assert rr.main( argv( repo, str( path ) ), query_fn=FakeModels() ) == 2, name
    assert "no file" in capsys.readouterr().err


# ---- extraction -------------------------------------------------------------------------------

def test_extraction_keeps_docs_and_comments_and_drops_code_bodies():
    text = rr.extract_doc_text( OLD_A )
    assert "Return an empty dict when items is empty. Never raises." in text
    assert "# the chase window is ten minutes" in text
    assert "def fn_a(items):" in text
    assert "secret_body_line" not in text and "return {}" not in text
    assert text.index( "Module for parked rows" ) < text.index( "chase window" ) < text.index( "def fn_a" )


def test_extraction_covers_classes_async_methods_and_decorators():
    text = rr.extract_doc_text( OLD_B )
    assert "class Box:" in text and "A box holds one thing" in text
    assert "async def open_it(lid, *, force=False) -> bool:" in text
    assert "hidden_body" not in text and "staticmethod" not in text


def test_extraction_keeps_indented_and_end_of_line_comments_and_nested_defs():
    text = rr.extract_doc_text( 'def outer():\n    """Outer doc."""\n    # indented note\n    x = 1  # trailing note\n'
                                '    def inner( a ):\n        """Inner doc."""\n        return a\n' )
    assert "# indented note" in text and "# trailing note" in text
    assert "def inner(a):" in text and "Inner doc." in text and "x = 1" not in text
    assert text.index( "def outer" ) < text.index( "# indented note" ) < text.index( "def inner" )


def test_extraction_refuses_source_that_does_not_parse():
    with pytest.raises( rr.RunRefused, match="does not parse" ):
        rr.extract_doc_text( "def broken(:\n", "x.py" )


# ---- reading from git -------------------------------------------------------------------------

def test_text_comes_from_git_not_the_working_tree( repo ):
    models = FakeModels()
    assert run( repo, [ QA ], models )[ 0 ] == 0
    readers = [ c[ 2 ] for c in models.by( READER ) ]
    assert readers and not any( "working tree only" in p for p in readers )
    assert any( "Never raises" in p for p in readers ) and any( "chase window" in p for p in readers )


def test_unknown_revision_and_missing_file_are_refused( repo, capsys ):
    assert run( repo, [ QA ], **{ "--old-rev": "no-such-rev" } )[ 0 ] == 2
    assert "does not resolve" in capsys.readouterr().err
    assert run( repo, [ dict( QA, file="src/gone.py" ) ] )[ 0 ] == 2
    assert "is not in commit" in capsys.readouterr().err


def test_equal_models_and_bad_cli_path_are_refused( repo, capsys ):
    assert run( repo, [ QA ], **{ "--grader-model": READER } )[ 0 ] == 2
    assert "must differ" in capsys.readouterr().err
    assert run( repo, [ QA ], **{ "--claude-cli-path": "/no/such/binary" } )[ 0 ] == 2
    assert "not an executable" in capsys.readouterr().err


def test_default_repo_is_the_project_root( repo, capsys, monkeypatch ):
    monkeypatch.setattr( rr.cu, "get_project_root", lambda: repo[ "root" ] )
    args = argv( repo, questions_file( repo, [ QA ] ) )
    i    = args.index( "--repo" )
    assert rr.main( args[ :i ] + args[ i + 2: ] + [ "--dry-run" ], query_fn=FakeModels() ) == 0
    assert "src/mod_a.py: 1 questions" in capsys.readouterr().out


# ---- call caps --------------------------------------------------------------------------------

def test_reader_cap_refusal_makes_no_call( repo, capsys ):
    code, models = run( repo, [ QA ], **{ "--reader-cap": "3" } )   # 1 question x 2 texts x 2 runs = 4 reader calls
    assert code == 2 and "pass a cap" in capsys.readouterr().err
    assert models.calls == []


def test_grader_cap_refusal_makes_no_call( repo, capsys ):
    code, models = run( repo, [ QA ], **{ "--grader-cap": "3" } )
    assert code == 2 and "pass a cap" in capsys.readouterr().err
    assert models.calls == []


def test_caps_at_exactly_the_worst_case_are_allowed( repo ):
    code, models = run( repo, [ QA ], **{ "--reader-cap": "4", "--grader-cap": "4" } )
    assert code == 0 and len( models.by( READER ) ) == 4 and len( models.by( GRADER ) ) == 2   # equal answers share one grade


def test_calls_already_used_count_against_the_cap( repo, capsys ):
    assert run( repo, [ QA ], **{ "--reader-cap": "4", "--grader-cap": "4" } )[ 0 ] == 0
    ledger = repo[ "tmp" ] / "ledger.jsonl"
    ledger.unlink()                      # results forgotten, call count kept: the run is owed again
    code, models = run( repo, [ QA ], **{ "--reader-cap": "4", "--grader-cap": "4" } )
    assert code == 2 and models.calls == []


# ---- resume, dry run and the projection --------------------------------------------------------

def test_second_run_against_the_same_ledger_makes_zero_calls( repo, capsys ):
    code, first = run( repo, [ QA, QB1 ] )
    assert code == 0 and first.calls
    spent = model_transport.calls_used( READER, str( repo[ "tmp" ] / "ledger.jsonl.calls" ) )
    code, second = run( repo, [ QA, QB1 ] )
    assert code == 0 and second.calls == []
    assert model_transport.calls_used( READER, str( repo[ "tmp" ] / "ledger.jsonl.calls" ) ) == spent


def test_dry_run_prints_sizes_and_projection_and_calls_nothing( repo, capsys ):
    code, models = run( repo, [ QA, QB1, QB2 ], extra=[ "--dry-run" ] )
    out = capsys.readouterr().out
    assert code == 0 and models.calls == []
    assert f"src/mod_a.py: 1 questions, old text {len( rr.extract_doc_text( OLD_A ) )} chars, new text {len( rr.extract_doc_text( NEW_A ) )} chars" in out
    assert "src/mod_b.py: 2 questions" in out
    assert "projected calls: reader 8 (cap 1000, used 0), grader 8" in out    # a: 1 question x 2 texts x 2 runs = 4; b: 2 questions x 1 text (old == new) x 2 runs = 4
    assert not ( repo[ "tmp" ] / "ledger.jsonl.calls" ).exists()


def test_projection_matches_the_calls_actually_made( repo ):
    qs   = [ QA, QB1 ]
    code, models = run( repo, qs )
    assert code == 0
    config = reader_rig.ReaderConfig( READER, GRADER, 2 )
    texts  = [ rr.extract_doc_text( OLD_A ), rr.extract_doc_text( NEW_A ) ]
    empty  = harness_runner.Ledger( str( repo[ "tmp" ] / "fresh.jsonl" ) )
    owed   = rr.projected_calls( texts, rr.rig_questions( [ QA ] ), config, empty )
    assert owed == { "reader": 4, "grader": 4 }
    assert rr.projected_calls( texts, rr.rig_questions( [ QA ] ), config, harness_runner.Ledger( str( repo[ "tmp" ] / "ledger.jsonl" ) ) ) == { "reader": 0, "grader": 0 }


def test_projection_counts_a_missing_grade_for_a_finished_read( tmp_path ):
    config = reader_rig.ReaderConfig( READER, GRADER, 1 )
    text   = "some text"
    item   = { "id": "q", "question": "Why?", "key": "because" }
    ledger = harness_runner.Ledger( str( tmp_path / "l.jsonl" ) )
    base   = "|".join( [ harness_runner.text_hash( text ), harness_runner.text_hash( "Why?" ), reader_rig.PROMPT_VERSION ] )
    ledger.put( f"read|{base}|{READER}|0", "an answer" )
    assert rr.projected_calls( [ text ], [ item ], config, ledger ) == { "reader": 0, "grader": 1 }
    ledger.put( f"grade|{base}|{harness_runner.text_hash( 'because' + chr( 0 ) + 'an answer' )}|{GRADER}", 1 )
    assert rr.projected_calls( [ text ], [ item ], config, ledger ) == { "reader": 0, "grader": 0 }


# ---- what reaches the prompts -----------------------------------------------------------------

def test_grader_prompt_never_says_old_or_new_or_names_the_file( repo ):
    code, models = run( repo, [ QA ] )
    assert code == 0
    for _, system, prompt in models.by( GRADER ):
        for body in ( system, prompt ):
            assert not re.search( r"\b(old|new)\b", body, re.IGNORECASE ), body
            assert "mod_a" not in body and "src/" not in body
        assert re.findall( r"<(\w+?)_[0-9a-f]+>", prompt ) == [ "question", "key", "answer" ]


def test_common_wrong_answer_and_other_fields_never_reach_a_prompt( repo ):
    code, models = run( repo, [ QA ] )
    assert code == 0
    for _, system, prompt in models.calls:
        assert "WRONGANSWER-xyz" not in prompt + system and "ran it" not in prompt and "fn_a\"" not in prompt
    assert rr.rig_questions( [ QA ] ) == [ { "id": "qa", "question": QA[ "question" ], "key": "empty dict; Never raises" } ]


# ---- arithmetic and the report ----------------------------------------------------------------

def result( old_scores, new_scores, n ):
    """A run_reader_test-shaped result for n questions, totals derived the way the rig derives them."""
    return { "old_scores": old_scores, "new_scores": new_scores, "old_total": sum( round( x * n ) for x in old_scores ), "new_total": sum( round( x * n ) for x in new_scores ) }


def test_summarize_weights_files_by_question_count():
    per_file = { "a": result( [ 1.0, 1.0 ], [ 0.0, 0.0 ], 1 ), "b": result( [ 1 / 3, 1 / 3 ], [ 1.0, 1.0 ], 3 ) }   # old totals 2 + 2, new totals 0 + 6
    got = rr.summarize( per_file, { "a": 1, "b": 3 } )
    assert got == { "questions": 4, "old_mean": 0.5, "new_mean": 0.75, "old_total": 4, "new_total": 6, "passes": True }
    assert rr.summarize( { "a": result( [ 1.0 ], [ 0.0 ], 2 ) }, { "a": 2 } )[ "passes" ] is False


def test_overall_tie_across_files_passes():
    per_file = { "a": result( [ 1.0 ], [ 1 / 3 ], 3 ), "b": result( [ 1 / 3 ], [ 1.0 ], 3 ) }    # file a loses 2, file b gains 2: totals 4 and 4
    got = rr.summarize( per_file, { "a": 3, "b": 3 } )
    assert got[ "old_total" ] == got[ "new_total" ] == 4 and got[ "passes" ] is True


def test_exact_tie_passes_even_when_the_float_means_differ( repo, monkeypatch ):
    # 3 questions, 3 runs: per-run totals ( 1, 3, 3 ) against ( 2, 2, 3 ) are both 7, yet the float means are
    # 0.7777777777777778 against 0.7777777777777777, so a float >= calls the tie a loss
    scores = iter( [ 1 / 3, 1.0, 1.0, 2 / 3, 2 / 3, 1.0 ] )

    async def fake_score( *args, **kwargs ):
        return next( scores )

    monkeypatch.setattr( reader_rig, "score_text", fake_score )
    out  = str( repo[ "tmp" ] / "tie.json" )
    code = rr.main( argv( repo, questions_file( repo, [ QB1, QB2, QB3 ] ), out=out, **{ "--runs": "3" } ), query_fn=FakeModels() )
    file = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ]
    assert code == 0 and file[ "old_mean" ] > file[ "new_mean" ]
    assert file[ "old_total" ] == file[ "new_total" ] == 7 and file[ "passes" ] is True
    assert json.load( open( out ) )[ "overall" ][ "passes" ] is True


def test_a_one_answer_loss_still_fails_the_per_file_verdict( monkeypatch ):
    scores = iter( [ 1.0, 1.0, 1.0, 1.0, 1.0, 2 / 3 ] )

    async def fake_score( *args, **kwargs ):
        return next( scores )

    monkeypatch.setattr( reader_rig, "score_text", fake_score )
    got = asyncio.run( reader_rig.run_reader_test( "o", "n", rr.rig_questions( [ QB1, QB2, QB3 ] ), reader_rig.ReaderConfig( READER, GRADER, 3 ) ) )
    assert ( got[ "old_total" ], got[ "new_total" ], got[ "passes" ] ) == ( 9, 8, False )


def test_runs_below_one_is_refused_before_anything_else( repo, capsys ):
    for runs in ( "0", "-1" ):
        models = FakeModels()
        assert rr.main( argv( repo, "/no/such/questions.json", **{ "--runs": runs } ), query_fn=models ) == 2
        assert "--runs must be 1 or more" in capsys.readouterr().err
        assert models.calls == []


def test_per_file_and_overall_figures_end_to_end( repo, capsys ):
    out  = str( repo[ "tmp" ] / "report.json" )
    qs   = [ QA, QB1, QB2, QB3 ]
    code = rr.main( argv( repo, questions_file( repo, qs ), out=out ), query_fn=FakeModels() )
    printed = capsys.readouterr().out
    assert code == 0
    report = json.load( open( out ) )
    a, b   = report[ "files" ][ "src/mod_a.py" ], report[ "files" ][ "src/mod_b.py" ]
    assert ( a[ "old_mean" ], a[ "new_mean" ], a[ "passes" ], a[ "questions" ] ) == ( 1.0, 0.0, False, 1 )
    assert a[ "old_scores" ] == [ 1.0, 1.0 ] and a[ "new_scores" ] == [ 0.0, 0.0 ]
    assert ( b[ "old_mean" ], b[ "new_mean" ], b[ "passes" ], b[ "questions" ] ) == ( 1.0, 1.0, True, 3 )
    assert report[ "overall" ] == { "questions": 4, "old_mean": 1.0, "new_mean": 0.75, "old_total": 8, "new_total": 6, "passes": False }    # unweighted would be 0.5
    assert "overall: questions=4 old_mean=1.000 new_mean=0.750 passes=False" in printed
    assert f"calls spent {READER}: " in printed and f"calls spent {GRADER}: " in printed


def test_report_names_revisions_models_and_hashes( repo ):
    out  = str( repo[ "tmp" ] / "report.json" )
    path = questions_file( repo, [ QA ] )
    assert rr.main( argv( repo, path, out=out ), query_fn=FakeModels() ) == 0
    report = json.load( open( out ) )
    assert report[ "old_rev" ] == repo[ "old" ] and report[ "new_rev" ] == repo[ "new" ] and len( report[ "old_rev" ] ) == 40
    assert report[ "questions_sha256" ] == __import__( "hashlib" ).sha256( open( path, "rb" ).read() ).hexdigest()
    assert ( report[ "reader_model" ], report[ "grader_model" ], report[ "runs" ] ) == ( READER, GRADER, 2 )
    assert report[ "prompt_version" ] == reader_rig.PROMPT_VERSION
    assert report[ "calls_spent" ] == { READER: 4, GRADER: 2 }
