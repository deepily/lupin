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
OLD_C = '''def spin():
    """Alpha holds. Beta holds. Gamma holds."""
'''
NEW_C = OLD_C.replace( " Gamma holds.", "" )
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
    ( root / "src" / "mod_c.py" ).write_text( OLD_C )
    git( "add", "." )
    git( "commit", "-qm", "old" )
    old = git( "rev-parse", "HEAD" )
    ( root / "src" / "mod_a.py" ).write_text( NEW_A )
    ( root / "src" / "mod_c.py" ).write_text( NEW_C )
    git( "add", "." )
    git( "commit", "-qm", "new" )
    new = git( "rev-parse", "HEAD" )
    # the working tree differs from both commits: the runner must read git, not the disk
    ( root / "src" / "mod_a.py" ).write_text( "# working tree only\n" )
    return { "root": str( root ), "old": old, "new": new, "tmp": tmp_path }


class FakeModels:
    """
    The fake reader replies with the whole text; the fake grader scores 1 when every key point occurs in the answer.
    reader_script and grader_script hold raw replies used in order, one per call; None means the default reply, and
    an Exception instance is raised from the call. Once a script runs out the default reply is used.
    """

    def __init__( self, reader_script=None, grader_script=None ):
        self.calls         = []
        self.reader_script = list( reader_script or [] )
        self.grader_script = list( grader_script or [] )

    async def __call__( self, prompt, options ):
        self.calls.append( ( options.model, options.system_prompt, prompt ) )
        is_reader = options.system_prompt == reader_rig.READER_SYSTEM
        script    = self.reader_script if is_reader else self.grader_script
        scripted  = script.pop( 0 ) if script else None
        if isinstance( scripted, Exception ): raise scripted
        if scripted is not None:
            text = scripted
        elif is_reader:
            body = re.search( r"<text_(\w+)>\n(.*?)\n</text_\1>", prompt, re.DOTALL ).group( 2 )
            text = json.dumps( { "answer": body } )
        else:
            key    = re.search( r"<key_(\w+)>\n(.*?)\n</key_\1>", prompt, re.DOTALL ).group( 2 )
            answer = re.search( r"<answer_(\w+)>\n(.*?)\n</answer_\1>", prompt, re.DOTALL ).group( 2 )
            text   = json.dumps( { "score": 1 if all( p in answer for p in key.split( "; " ) ) else 0 } )
        yield object()          # a message that is not an assistant message: the tracker must pass it through
        yield AssistantMessage( content=[ TextBlock( text ) ], model=options.model )

    def by( self, model ):
        return [ c for c in self.calls if c[ 0 ] == model ]


QA   = q( "qa", "src/mod_a.py", "What does fn_a return for an empty list?", [ "empty dict", "Never raises" ], common_wrong_answer="WRONGANSWER-xyz", verified="ran it", symbols=[ "fn_a" ] )
QB1  = q( "qb1", "src/mod_b.py", "What does the box do?", [ "lid stays shut" ] )
QB2  = q( "qb2", "src/mod_b.py", "What sticks?", [ "sticks in cold weather" ] )
QB3  = q( "qb3", "src/mod_b.py", "What does open_it do?", [ "Open the lid" ] )
QC1  = q( "qc1", "src/mod_c.py", "What holds first?", [ "Alpha holds" ] )
QC2  = q( "qc2", "src/mod_c.py", "What holds second?", [ "Beta holds" ] )
QC3  = q( "qc3", "src/mod_c.py", "What holds third?", [ "Gamma holds" ] )


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
    assert code == 2 and "passes a cap" in capsys.readouterr().err
    assert models.calls == []


def test_grader_cap_refusal_makes_no_call( repo, capsys ):
    code, models = run( repo, [ QA ], **{ "--grader-cap": "3" } )
    assert code == 2 and "passes a cap" in capsys.readouterr().err
    assert models.calls == []


def test_cap_check_allows_for_the_retries( repo, capsys ):
    # 4 reader and 4 grader calls owed, each possibly made 3 times: 11 is one short of the worst case
    code, models = run( repo, [ QA ], **{ "--reader-cap": "11", "--grader-cap": "1000" } )
    assert code == 2 and "worst case with 3 attempts" in capsys.readouterr().err and models.calls == []
    code, models = run( repo, [ QA ], **{ "--reader-cap": "1000", "--grader-cap": "11" } )
    assert code == 2 and models.calls == []


def test_caps_at_exactly_the_worst_case_are_allowed( repo ):
    code, models = run( repo, [ QA ], **{ "--reader-cap": "12", "--grader-cap": "12" } )
    assert code == 0 and len( models.by( READER ) ) == 4 and len( models.by( GRADER ) ) == 2   # equal answers share one grade


def test_calls_already_used_count_against_the_cap( repo, capsys ):
    assert run( repo, [ QA ], **{ "--reader-cap": "12", "--grader-cap": "12" } )[ 0 ] == 0
    ledger = repo[ "tmp" ] / "ledger.jsonl"
    ledger.unlink()                      # results forgotten, call count kept: the run is owed again
    code, models = run( repo, [ QA ], **{ "--reader-cap": "12", "--grader-cap": "12" } )
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
    assert "cap check uses the worst case of 3 attempts per call: reader 24, grader 24" in out
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

def file_result( old, new, compared, dropped=0 ):
    """A score_file-shaped result with the fields summarize reads."""
    return { "old_total": old, "new_total": new, "compared": compared, "dropped": dropped, "old_answered": compared, "new_answered": compared, "unscored_records": [], "salvaged_records": [] }


def test_summarize_adds_file_totals_so_each_file_counts_by_its_pairs():
    per_file = { "a": file_result( 2, 0, 2 ), "b": file_result( 2, 6, 6 ) }       # file a: 1 question x 2 runs; file b: 3 questions x 2 runs
    got = rr.summarize( per_file )
    assert got == { "compared": 8, "dropped": 0, "salvaged": 0, "old_answered": 8, "new_answered": 8, "unscored": 0, "old_total": 4, "new_total": 6,
                    "old_mean": 0.5, "new_mean": 0.75, "passes": True, "verdict": "PASS" }          # an unweighted mean of file means would be 0.5 too: see the end-to-end test
    assert rr.summarize( { "a": file_result( 2, 0, 2 ) } )[ "verdict" ] == "FAIL"


def test_overall_tie_across_files_passes():
    per_file = { "a": file_result( 3, 1, 3 ), "b": file_result( 1, 3, 3 ) }       # file a loses 2, file b gains 2: totals 4 and 4
    got = rr.summarize( per_file )
    assert got[ "old_total" ] == got[ "new_total" ] == 4 and got[ "passes" ] is True and got[ "verdict" ] == "PASS"


def test_summarize_with_nothing_compared_has_no_means_and_is_incomplete():
    got = rr.summarize( { "a": file_result( 0, 0, 0, dropped=2 ) } )
    assert got[ "old_mean" ] is None and got[ "new_mean" ] is None and got[ "verdict" ] == "INCOMPLETE" and got[ "passes" ] is None


class Scripted:
    """Stands in for reader_rig.score_text: each call returns the next scripted item, or raises it."""

    def __init__( self, items ):
        self.items = list( items )
        self.calls = 0

    async def __call__( self, *args, **kwargs ):
        self.calls += 1
        item = self.items.pop( 0 )
        if isinstance( item, Exception ): raise item
        return item


def test_exact_tie_passes_even_when_per_run_scores_differ( repo, monkeypatch ):
    # 3 questions, 3 runs. Old right per run ( 1, 3, 3 ), new ( 2, 2, 3 ): both 7, though the mean of the per-run scores is
    # 0.7777777777777778 for old and 0.7777777777777777 for new, so a float >= on those means calls the tie a loss
    old_runs = [ [ 1, 0, 0 ], [ 1, 1, 1 ], [ 1, 1, 1 ] ]
    new_runs = [ [ 1, 1, 0 ], [ 1, 0, 1 ], [ 1, 1, 1 ] ]
    items    = [ float( x ) for o, n in zip( old_runs, new_runs ) for pair in zip( o, n ) for x in pair ]
    monkeypatch.setattr( reader_rig, "score_text", Scripted( items ) )
    out  = str( repo[ "tmp" ] / "tie.json" )
    code = rr.main( argv( repo, questions_file( repo, [ QC1, QC2, QC3 ] ), out=out, **{ "--runs": "3" } ), query_fn=FakeModels() )
    report = json.load( open( out ) )
    file   = report[ "files" ][ "src/mod_c.py" ]
    assert sum( file[ "old_scores" ] ) / 3 > sum( file[ "new_scores" ] ) / 3
    assert code == 0 and file[ "old_total" ] == file[ "new_total" ] == 7 and file[ "passes" ] is True and file[ "verdict" ] == "PASS"
    assert report[ "overall" ][ "passes" ] is True and report[ "overall" ][ "verdict" ] == "PASS"


def test_a_one_answer_loss_fails_the_per_file_verdict( repo, monkeypatch ):
    items = [ 1.0 ] * 17 + [ 0.0 ]          # 3 questions x 3 runs x 2 texts: only the last new answer is wrong
    monkeypatch.setattr( reader_rig, "score_text", Scripted( items ) )
    out  = str( repo[ "tmp" ] / "loss.json" )
    code = rr.main( argv( repo, questions_file( repo, [ QC1, QC2, QC3 ] ), out=out, **{ "--runs": "3" } ), query_fn=FakeModels() )
    file = json.load( open( out ) )[ "files" ][ "src/mod_c.py" ]
    assert code == 0 and ( file[ "old_total" ], file[ "new_total" ], file[ "passes" ], file[ "verdict" ] ) == ( 9, 8, False, "FAIL" )


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
    assert report[ "overall" ] == { "questions": 4, "compared": 8, "dropped": 0, "salvaged": 0, "old_answered": 8, "new_answered": 8, "unscored": 0,
                                    "old_total": 8, "new_total": 6, "old_mean": 1.0, "new_mean": 0.75, "passes": False, "verdict": "FAIL" }    # an unweighted mean of the file means would be 0.5
    assert "overall: questions=4 compared=8 dropped=0 salvaged=0 old_total=8 new_total=6 verdict=FAIL" in printed
    assert f"calls spent {READER}: " in printed and f"calls spent {GRADER}: " in printed


def test_report_names_revisions_models_and_hashes( repo ):
    out  = str( repo[ "tmp" ] / "report.json" )
    path = questions_file( repo, [ QA ] )
    assert rr.main( argv( repo, path, out=out ), query_fn=FakeModels() ) == 0
    report = json.load( open( out ) )
    assert report[ "old_rev" ] == repo[ "old" ] and report[ "new_rev" ] == repo[ "new" ] and len( report[ "old_rev" ] ) == 40
    assert report[ "questions_sha256" ] == __import__( "hashlib" ).sha256( open( path, "rb" ).read() ).hexdigest()
    assert ( report[ "reader_model" ], report[ "grader_model" ], report[ "runs" ] ) == ( READER, GRADER, 2 )
    assert report[ "prompt_version" ] == reader_rig.PROMPT_VERSION and report[ "attempts" ] == 3
    assert report[ "calls_spent" ] == { READER: 4, GRADER: 2 }


def test_file_prefix_finds_a_bare_file_name( repo, capsys ):
    bare = [ dict( QA, file="mod_a.py" ) ]
    assert run( repo, bare, **{ "--runs": "1" } )[ 0 ] == 2        # without the prefix the old refusal still fires
    out  = str( repo[ "tmp" ] / "pfx.json" )
    code, models = run( repo, bare, extra=[ "--file-prefix", "src/" ], **{ "--out": out } )
    report = json.load( open( out ) )
    assert code == 0 and models.calls
    assert report[ "file_prefix" ] == "src/" and report[ "paths_read" ] == [ "src/mod_a.py" ] and list( report[ "files" ] ) == [ "src/mod_a.py" ]


def test_bare_file_name_without_prefix_is_refused_as_not_in_commit( repo, capsys ):
    assert run( repo, [ dict( QA, file="mod_a.py" ) ] )[ 0 ] == 2
    assert "mod_a.py is not in commit" in capsys.readouterr().err


def test_bad_file_prefixes_are_refused_with_no_call( repo, capsys ):
    for bad in ( "/src/", "src/../", "..", "a/../b/" ):
        code, models = run( repo, [ QA ], extra=[ "--file-prefix", bad ] )
        assert code == 2 and "--file-prefix" in capsys.readouterr().err
        assert models.calls == []


# ---- off-contract replies: retry, then unscored ------------------------------------------------

def calls_used( repo, model ):
    return model_transport.calls_used( model, str( repo[ "tmp" ] / "ledger.jsonl.calls" ) )


def test_a_reply_with_text_after_the_json_is_retried_and_then_scored( repo ):
    models = FakeModels( grader_script=[ '{"score": 1} Hope that helps!' ] )
    code, _ = run( repo, [ QA ], models, **{ "--runs": "1" } )
    assert code == 0
    assert len( models.by( READER ) ) == 2          # the reader answer was cached once it parsed, so the retry cost a grader call only
    assert len( models.by( GRADER ) ) == 3 and calls_used( repo, GRADER ) == 3    # the retry is a real call, charged to the cap


def test_a_reply_that_never_parses_is_unscored_on_both_identical_texts_with_one_set_of_calls( repo, capsys ):
    out    = str( repo[ "tmp" ] / "unscored.json" )
    models = FakeModels( grader_script=[ "nope", "nope", "nope" ] )     # mod_b reads the same in both revisions: one question, one set of attempts
    code, _ = run( repo, [ QB1 ], models, **{ "--runs": "1", "--out": out } )
    printed = capsys.readouterr()
    report  = json.load( open( out ) )
    file    = report[ "files" ][ "src/mod_b.py" ]
    assert code == 3 and len( models.by( GRADER ) ) == 3 and len( models.by( READER ) ) == 1    # not 6: the new text is not retried for the same words
    assert ( file[ "compared" ], file[ "dropped" ], file[ "old_total" ], file[ "new_total" ] ) == ( 0, 1, 0, 0 )
    assert ( file[ "old_answered" ], file[ "new_answered" ], file[ "verdict" ], file[ "passes" ] ) == ( 0, 0, "INCOMPLETE", None )
    old, new = file[ "unscored_records" ]
    for record, label in ( ( old, "old" ), ( new, "new" ) ):
        assert ( record[ "file" ], record[ "text" ], record[ "run" ], record[ "id" ], record[ "step" ], record[ "raws" ] ) == ( "src/mod_b.py", label, 0, "qb1", "grader", [ "nope" ] * 3 )
        assert record[ "error" ].startswith( "ReaderParseError" )
    overall = report[ "overall" ]
    assert ( overall[ "unscored" ], overall[ "dropped" ], overall[ "verdict" ], overall[ "passes" ] ) == ( 2, 1, "INCOMPLETE", None )    # 2 records, 1 dropped pair
    assert "verdict=INCOMPLETE" in printed.out and "UNSCORED: 2 answers" in printed.err and "1 pairs dropped" in printed.err


def test_the_new_text_failing_alone_drops_the_pair_and_exits_3( repo ):
    out    = str( repo[ "tmp" ] / "new-alone.json" )
    models = FakeModels( grader_script=[ None, "bad", "bad", "bad" ] )       # the old text grades fine; the new text fails all 3 attempts
    code, _ = run( repo, [ QA ], models, **{ "--runs": "1", "--out": out } )
    file   = json.load( open( out ) )[ "files" ][ "src/mod_a.py" ]
    [ record ] = file[ "unscored_records" ]
    assert code == 3 and ( file[ "compared" ], file[ "dropped" ], file[ "old_total" ], file[ "new_total" ] ) == ( 0, 1, 0, 0 )
    assert ( file[ "old_answered" ], file[ "new_answered" ], file[ "passes" ] ) == ( 1, 0, None ) and record[ "text" ] == "new"


def test_the_record_names_its_run_and_question_and_overall_counts_both_texts( repo ):
    out    = str( repo[ "tmp" ] / "late.json" )
    models = FakeModels( reader_script=[ None ] * 8 + [ "", "", "" ] )      # the 9th reader call is run 2, third question
    code, _ = run( repo, [ QB1, QB2, QB3 ], models, **{ "--runs": "3", "--out": out } )
    report  = json.load( open( out ) )
    records = report[ "files" ][ "src/mod_b.py" ][ "unscored_records" ]
    assert code == 3 and [ ( r[ "text" ], r[ "run" ], r[ "id" ], r[ "step" ] ) for r in records ] == [ ( "old", 2, "qb3", "reader" ), ( "new", 2, "qb3", "reader" ) ]
    assert ( report[ "overall" ][ "compared" ], report[ "overall" ][ "dropped" ], report[ "overall" ][ "unscored" ] ) == ( 8, 1, 2 )


def test_without_out_the_unscored_records_go_to_stderr( repo, capsys ):
    code, _ = run( repo, [ QB1 ], FakeModels( grader_script=[ "nope" ] * 3 ), **{ "--runs": "1" } )
    lines   = [ json.loads( line ) for line in capsys.readouterr().err.splitlines() if line.startswith( "{" ) ]
    assert code == 3 and [ ( r[ "text" ], r[ "raws" ] ) for r in lines ] == [ ( "old", [ "nope" ] * 3 ), ( "new", [ "nope" ] * 3 ) ]


class Spender( FakeModels ):
    """A fake whose first call also charges the grader's call count, as a peer process would."""

    def __init__( self, calls_path ):
        super().__init__()
        self.calls_path = calls_path

    async def __call__( self, prompt, options ):
        if not self.calls:
            with open( self.calls_path, "a", encoding="utf-8" ) as f: f.write( "".join( json.dumps( { "model": GRADER, "n": i } ) + "\n" for i in range( 100 ) ) )
        async for message in super().__call__( prompt, options ): yield message


def test_a_cap_reached_mid_run_writes_the_report_and_exits_3( repo, capsys ):
    out    = str( repo[ "tmp" ] / "cap.json" )
    models = Spender( str( repo[ "tmp" ] / "ledger.jsonl.calls" ) )
    code, _ = run( repo, [ QA, QB1 ], models, **{ "--runs": "1", "--grader-cap": "12", "--out": out } )
    report  = json.load( open( out ) )
    records = [ r for f in report[ "files" ].values() for r in f[ "unscored_records" ] ]
    assert code == 3 and len( models.by( READER ) ) == 1 and models.by( GRADER ) == []      # the refused call never reached a model; nothing after it ran
    assert [ ( r[ "file" ], r[ "text" ], r[ "step" ] ) for r in records ] == [ ( "src/mod_a.py", "old", "cap" ), ( "src/mod_a.py", "new", "cap" ), ( "src/mod_b.py", "old", "cap" ), ( "src/mod_b.py", "new", "cap" ) ]
    assert "no model was contacted" in records[ 0 ][ "error" ] and records[ 0 ][ "raws" ] == []
    assert ( report[ "overall" ][ "dropped" ], report[ "overall" ][ "compared" ], report[ "overall" ][ "verdict" ], report[ "overall" ][ "passes" ] ) == ( 2, 0, "INCOMPLETE", None )


def test_an_empty_reader_reply_is_unscored_at_the_reader_step( repo ):
    out = str( repo[ "tmp" ] / "empty.json" )
    code, models = run( repo, [ QB1 ], FakeModels( reader_script=[ "", "", "" ] ), **{ "--runs": "1", "--out": out } )
    old, new = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ][ "unscored_records" ]
    assert code == 3 and ( old[ "text" ], new[ "text" ], old[ "step" ], old[ "raws" ] ) == ( "old", "new", "reader", [ "" ] * 3 )
    assert old[ "error" ].startswith( "ModelCallError" ) and len( models.by( READER ) ) == 3


def test_a_transport_error_is_retried_and_then_unscored( repo ):
    out = str( repo[ "tmp" ] / "boom.json" )
    code, models = run( repo, [ QB1 ], FakeModels( reader_script=[ RuntimeError( "boom" ) ] * 3 ), **{ "--runs": "1", "--out": out } )
    old, _ = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ][ "unscored_records" ]
    assert code == 3 and old[ "step" ] == "reader" and "boom" in old[ "error" ] and old[ "raws" ] == [ "" ] * 3


def test_a_transport_error_that_clears_on_the_retry_is_scored( repo ):
    code, models = run( repo, [ QB1 ], FakeModels( reader_script=[ RuntimeError( "blip" ) ] ), **{ "--runs": "1" } )
    assert code == 0 and len( models.by( READER ) ) == 2


def test_the_raw_reply_is_cut_to_two_thousand_characters( repo ):
    out = str( repo[ "tmp" ] / "long.json" )
    run( repo, [ QB1 ], FakeModels( grader_script=[ "x" * 5000 ] * 3 ), **{ "--runs": "1", "--out": out } )
    old, _ = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ][ "unscored_records" ]
    assert [ len( raw ) for raw in old[ "raws" ] ] == [ rr.RAW_LIMIT ] * 3 and rr.RAW_LIMIT == 2000


def test_a_cap_reached_mid_run_is_not_retried_and_retries_count_against_it( tmp_path ):
    config = reader_rig.ReaderConfig( READER, GRADER, 1 )
    path   = str( tmp_path / "calls.jsonl" )
    model_transport.set_budget( path, { GRADER: 2 } )
    models = FakeModels( grader_script=[ "bad", "bad", "bad" ] )
    with pytest.raises( model_transport.CallBudgetExceeded ):
        asyncio.run( rr.score_question( "the lid stays shut.", rr.rig_questions( [ QB1 ] )[ 0 ], config, 0, harness_runner.Ledger( str( tmp_path / "l.jsonl" ) ), models ) )
    assert model_transport.calls_used( GRADER, path ) == 2 and len( models.by( GRADER ) ) == 2    # attempts 1 and 2 were charged; attempt 3 was refused


def test_score_question_uses_the_sdk_when_no_query_function_is_given( monkeypatch ):
    monkeypatch.setattr( model_transport, "sdk_query", FakeModels() )
    config = reader_rig.ReaderConfig( READER, GRADER, 1 )
    assert asyncio.run( rr.score_question( "the lid stays shut.", rr.rig_questions( [ QB1 ] )[ 0 ], config, 0, None, None ) ) == ( 1, None, None )


# ---- the grader that reasons first: salvage ---------------------------------------------------

REASON = "The key has two points: 1. an empty dict 2. never raises. The answer states both.\n"


@pytest.mark.parametrize( "reply, taken", [
    ( REASON + '{"score": 1}', '{"score": 1}' ),
    ( REASON + '{ "score" : 0 }', '{"score": 0}' ),
    ( REASON + '```json\n{"score": 1}\n```', '{"score": 1}' ),
    ( '\n' + REASON + '{"score":1}\n\n', '{"score": 1}' ),
] )
def test_reasoning_then_one_score_object_is_taken( reply, taken ):
    assert rr.take_score_object( reply ) == taken


@pytest.mark.parametrize( "reply", [
    '{"score": 1}',                                    # already a bare object: the rig takes it, nothing to salvage
    '```json\n{"score": 1}\n```',                      # a fenced bare object, likewise
    REASON,                                            # no object
    REASON + '{"score": 1} {"score": 0}',              # two objects
    'Example {"score": 1} and then the real one. {"score": 0}',     # two objects, one earlier in the text
    REASON + '{"score": 1} Hope that helps!',          # text after the object
    REASON + '{"score": 1}\n```\nmore',                # text after the closing fence
    REASON + '{"score": 2}',                           # a score other than 0 or 1
    REASON + '{"score": 10}',
    REASON + '{"score": true}',
    REASON + '{"score": 1.0}',
    REASON + '{"score": 1, "why": "both"}',            # another key
] )
def test_anything_else_is_not_salvaged( reply ):
    assert rr.take_score_object( reply ) is None


def test_the_tracker_hands_the_rig_only_the_object_and_keeps_the_raw_reply():
    class Inner:
        async def __call__( self, prompt, options ):
            yield object()
            yield AssistantMessage( content=[ TextBlock( REASON ), TextBlock( '{"score": 1}' ) ], model="m" )
            yield AssistantMessage( content=[], model="m" )          # a second assistant message with no text: it is dropped, only one is handed on

    class Options:
        system_prompt = reader_rig.GRADER_SYSTEM

    async def collect( tracker ):
        return [ m async for m in tracker( "p", Options() ) ]

    tracker  = rr.CallTracker( Inner() )
    messages = asyncio.run( collect( tracker ) )
    assert len( messages ) == 2 and not isinstance( messages[ 0 ], AssistantMessage )
    assert [ b.text for b in messages[ 1 ].content ] == [ '{"score": 1}' ]
    assert tracker.step == "grader" and tracker.salvaged == { "score": 1, "raw": REASON + '{"score": 1}' }
    assert tracker.salvaged[ "raw" ] == tracker.raw


def test_the_salvaged_raw_reply_is_cut_to_two_thousand_characters():
    long_reply = "reasoning " * 400 + '{"score": 1}'

    class Inner:
        async def __call__( self, prompt, options ):
            yield AssistantMessage( content=[ TextBlock( long_reply ) ], model="m" )

    class Options:
        system_prompt = reader_rig.GRADER_SYSTEM

    async def collect( tracker ):
        return [ m async for m in tracker( "p", Options() ) ]

    tracker = rr.CallTracker( Inner() )
    asyncio.run( collect( tracker ) )
    assert tracker.salvaged[ "score" ] == 1 and len( tracker.salvaged[ "raw" ] ) == 2000 and tracker.raw == long_reply


def test_a_salvaged_score_counts_and_is_recorded_per_text( repo, capsys ):
    out    = str( repo[ "tmp" ] / "salvage.json" )
    models = FakeModels( grader_script=[ REASON + '{"score": 1}', REASON + '{"score": 0}' ] )
    code, _ = run( repo, [ QA ], models, **{ "--runs": "1", "--out": out } )
    report  = json.load( open( out ) )
    file    = report[ "files" ][ "src/mod_a.py" ]
    assert code == 0 and len( models.by( GRADER ) ) == 2 and calls_used( repo, GRADER ) == 2       # taken on the first reply: no retry
    assert ( file[ "old_total" ], file[ "new_total" ], file[ "verdict" ] ) == ( 1, 0, "FAIL" )
    assert file[ "salvaged_records" ] == [ { "score": 1, "raw": REASON + '{"score": 1}', "file": "src/mod_a.py", "text": "old", "run": 0, "id": "qa" },
                                           { "score": 0, "raw": REASON + '{"score": 0}', "file": "src/mod_a.py", "text": "new", "run": 0, "id": "qa" } ]
    assert report[ "overall" ][ "salvaged" ] == 2 and report[ "strict_grader" ] is False


def test_a_salvaged_record_carries_its_run_and_question_and_both_identical_texts( repo ):
    # mod_b reads the same in both revisions. A grade is cached per answer, so a grader call at run 2 needs a new answer:
    # the 9th reader call (run 2, third question) answers differently, and the 4th grader call is the one that is salvaged
    out    = str( repo[ "tmp" ] / "late-salvage.json" )
    models = FakeModels( reader_script=[ None ] * 8 + [ '{"answer": "the lid stays shut, again"}' ], grader_script=[ None, None, None, REASON + '{"score": 1}' ] )
    code, _ = run( repo, [ QB1, QB2, QB3 ], models, **{ "--runs": "3", "--out": out } )
    file    = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ]
    assert code == 0 and file[ "dropped" ] == 0 and len( models.by( GRADER ) ) == 4
    assert file[ "salvaged_records" ] == [ { "score": 1, "raw": REASON + '{"score": 1}', "file": "src/mod_b.py", "text": label, "run": 2, "id": "qb3" } for label in ( "old", "new" ) ]


def test_the_summary_line_prints_the_salvaged_count( repo, capsys ):
    run( repo, [ QA ], FakeModels( grader_script=[ REASON + '{"score": 1}', REASON + '{"score": 0}' ] ), **{ "--runs": "1" } )
    printed = capsys.readouterr().out
    assert "src/mod_a.py: questions=1 compared=1 dropped=0 salvaged=2" in printed and "overall: questions=1 compared=1 dropped=0 salvaged=2" in printed


def test_a_salvaged_score_is_not_recounted_from_the_ledger( repo ):
    run( repo, [ QA ], FakeModels( grader_script=[ REASON + '{"score": 1}', REASON + '{"score": 0}' ] ), **{ "--runs": "1" } )
    out = str( repo[ "tmp" ] / "again.json" )
    code, models = run( repo, [ QA ], **{ "--runs": "1", "--out": out } )
    report = json.load( open( out ) )
    assert code == 0 and models.calls == [] and report[ "overall" ][ "salvaged" ] == 0 and "this run only" in report[ "salvage_scope" ]


def test_a_salvaged_score_in_a_dropped_pair_is_not_recorded( repo ):
    out    = str( repo[ "tmp" ] / "dropped-salvage.json" )
    models = FakeModels( grader_script=[ REASON + '{"score": 1}', "nope", "nope", "nope" ] )     # the old text is salvaged; the new text never parses
    code, _ = run( repo, [ QA ], models, **{ "--runs": "1", "--out": out } )
    file    = json.load( open( out ) )[ "files" ][ "src/mod_a.py" ]
    assert code == 3 and file[ "dropped" ] == 1 and file[ "salvaged_records" ] == []


def test_a_reader_reply_is_never_touched_by_salvage( repo ):
    out = str( repo[ "tmp" ] / "reader.json" )
    reply = 'Let me think. {"score": 1}'            # the shape the grader salvage would take, in a reader reply
    code, models = run( repo, [ QB1 ], FakeModels( reader_script=[ reply ] * 3 ), **{ "--runs": "1", "--out": out } )
    file = json.load( open( out ) )[ "files" ][ "src/mod_b.py" ]
    old, _ = file[ "unscored_records" ]
    assert code == 3 and old[ "step" ] == "reader" and old[ "raws" ] == [ reply ] * 3 and file[ "salvaged_records" ] == []
    assert "reply is not JSON" in old[ "error" ]       # the rig saw the reply as written, not cut down to the object


def test_the_tracker_leaves_a_reader_reply_as_written():
    class Inner:
        async def __call__( self, prompt, options ):
            yield AssistantMessage( content=[ TextBlock( 'Let me think. {"score": 1}' ) ], model="m" )

    class Options:
        system_prompt = reader_rig.READER_SYSTEM

    async def collect( tracker ):
        return [ m async for m in tracker( "p", Options() ) ]

    tracker  = rr.CallTracker( Inner() )
    messages = asyncio.run( collect( tracker ) )
    assert [ b.text for b in messages[ 0 ].content ] == [ 'Let me think. {"score": 1}' ] and tracker.salvaged is None


def test_strict_grader_refuses_what_salvage_would_take( repo ):
    out    = str( repo[ "tmp" ] / "strict.json" )
    models = FakeModels( grader_script=[ REASON + '{"score": 1}' ] * 3 )
    code, _ = run( repo, [ QB1 ], models, extra=[ "--strict-grader" ], **{ "--runs": "1", "--out": out } )
    report  = json.load( open( out ) )
    old, _  = report[ "files" ][ "src/mod_b.py" ][ "unscored_records" ]
    assert code == 3 and report[ "strict_grader" ] is True and report[ "overall" ][ "salvaged" ] == 0
    assert old[ "step" ] == "grader" and old[ "raws" ] == [ REASON + '{"score": 1}' ] * 3 and len( models.by( GRADER ) ) == 3
