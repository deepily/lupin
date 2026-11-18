"""
The merge-pyramid reuse gate: outcome lines a branch adds, judged against a real call log.

Every repository and data folder here is temporary. The call log and search record are the real ones
copied from a seat, as in test_reuse_refusals. Nothing calls a model and nothing touches the shared data folder.
"""
import io
import json
import pathlib
import subprocess

import pytest

from lupin_mcp import reuse_merge_gate as mg
from lupin_mcp import reuse_refusals as rr
from lupin_mcp import reuse_review_gate as gate
from tests.unit.test_reuse_refusals import GOOD, NOT_IN_LOG, BAD_SHAPE, RULINGS, TEMPLATE, RID, SID, REAL_LOG, REAL_RECORD

GIT = [ "git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false" ]


def git( repo, *args ):
    """Ensures: runs one git command in repo, raising on failure, and returns its stdout."""
    return subprocess.run( [ *GIT, "-C", str( repo ), *args ], check=True, capture_output=True, text=True ).stdout


@pytest.fixture
def repo( tmp_path ):
    """Ensures: a repository with one commit on main and HEAD on a new branch `feat`."""
    path = tmp_path / "repo"
    path.mkdir()
    git( path, "init", "-q", "-b", "main" )
    ( path / "README.md" ).write_text( "# repo\n", encoding="utf-8" )
    git( path, "add", "README.md" )
    git( path, "commit", "-q", "-m", "base" )
    git( path, "checkout", "-q", "-b", "feat" )
    return path


@pytest.fixture
def data( tmp_path ):
    """Ensures: a temporary data folder holding the real call log and the real search record."""
    folder = tmp_path / "data"
    ( folder / "call-log" ).mkdir( parents=True )
    ( folder / "call-log" / "real.jsonl" ).write_text( REAL_LOG.read_text( encoding="utf-8" ), encoding="utf-8" )
    ( folder / "search-records" ).mkdir()
    ( folder / "search-records" / f"{SID}.json" ).write_text( REAL_RECORD.read_text( encoding="utf-8" ), encoding="utf-8" )
    return folder


def ini( tmp_path, value="true", extra="" ):
    """Ensures: returns an ini file path holding the gating key, then the extra lines."""
    path = tmp_path / "lupin-app.ini"
    path.write_text( f"[x]\nreuse review gating = {value}\n{extra}", encoding="utf-8" )
    return str( path )


SEARCHED = "\n".join( f"SEARCHED {sym} :: {SID} :: none :: nothing near it" for sym in ( "lupin_mcp.new_helper", "m.q" ) )   # the line each ruling of RULINGS needs


def commit_doc( repo, name, *lines, rulings=True ):
    """Ensures: commits a Markdown file with the rulings, a template and these lines."""
    body = "# review\n\n" + ( RULINGS + "\n" + SEARCHED + "\n\n" if rulings else "" ) + "```text\n" + TEMPLATE + "\n```\n\n" + "\n".join( lines ) + "\n"
    ( repo / name ).write_text( body, encoding="utf-8" )
    git( repo, "add", name )
    git( repo, "commit", "-q", "-m", f"add {name}" )


def default_since( repo ):
    """Ensures: returns the commit main names, or HEAD when there is no main."""
    code = subprocess.run( [ "git", "-C", str( repo ), "rev-parse", "--verify", "--quiet", "main" ], capture_output=True, text=True )
    return code.stdout.strip() if code.returncode == 0 else sha_of( repo )


def run( repo, data, tmp_path, *extra, value="true", lines="" ):
    """Ensures: returns ( exit code, text ) of the command on repo, with a since unless given."""
    if "reuse merge gate since" not in lines: lines = f"reuse merge gate since = {default_since( repo )}\n{lines}"
    if "reuse searched since" not in lines: lines = f"reuse searched since = {default_since( repo )}\n{lines}"
    out  = io.StringIO()
    code = mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, value, lines ), *extra ], out=out )
    return code, out.getvalue()


def count( text, name ):
    """Ensures: returns the number printed on the summary line `name: N`."""
    return int( [ l for l in text.splitlines() if l.startswith( f"{name}: " ) ][ -1 ].split( ": " )[ 1 ] )


def test_a_branch_whose_outcome_line_holds_up_passes_and_is_recorded( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, data, tmp_path )
    assert code == 0 and "REUSE GATE PASSED: every outcome line the branch adds holds up." in text
    assert ( count( text, "Total Tests" ), count( text, "Passed" ), count( text, "Failed" ), count( text, "Errors" ) ) == ( 2, 2, 0, 0 ), "one scan check plus one line"
    assert len( ( data / rr.REFUSALS_NAME ).read_text( encoding="utf-8" ).splitlines() ) == 1
    run( repo, data, tmp_path )
    assert len( ( data / rr.REFUSALS_NAME ).read_text( encoding="utf-8" ).splitlines() ) == 1, "a second run on the same text adds no record"


def test_with_gating_on_a_refused_line_fails_and_names_the_line_and_the_reason( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD, NOT_IN_LOG, BAD_SHAPE )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "REUSE GATE FAILED: 2 refusals or missing outcome lines." in text
    assert f"REFUSED review.md line " in text and NOT_IN_LOG in text and "is not in the log" in text and BAD_SHAPE in text
    assert ( count( text, "Total Tests" ), count( text, "Passed" ), count( text, "Failed" ), count( text, "Errors" ) ) == ( 4, 2, 2, 2 )


def test_with_gating_off_the_same_refusals_are_reported_and_the_run_passes( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD, NOT_IN_LOG, BAD_SHAPE )
    code, text = run( repo, data, tmp_path, value="false" )
    assert code == 0 and "Report-only: 2" in text and "gating is off (report only)" in text and "REFUSED review.md" in text
    assert ( count( text, "Failed" ), count( text, "Errors" ) ) == ( 0, 0 ), "report only never reads as a failed suite"
    assert "REUSE GATE PASSED: report only, 2 would be refused." in text


def test_a_branch_that_adds_no_definitions_and_no_outcome_lines_passes( repo, data, tmp_path ):
    commit_doc( repo, "notes.md", "just prose", rulings=False )
    code, text = run( repo, data, tmp_path )
    assert code == 0 and ( count( text, "Total Tests" ), count( text, "Passed" ) ) == ( 1, 1 ) and not ( data / rr.REFUSALS_NAME ).exists()


def test_only_added_markdown_lines_are_read( repo, data, tmp_path ):
    ( repo / "code.py" ).write_text( 'TEXT = """\n' + NOT_IN_LOG + '\n"""\n', encoding="utf-8" )
    ( repo / "doc.txt" ).write_text( NOT_IN_LOG + "\n", encoding="utf-8" )
    git( repo, "add", "code.py", "doc.txt" )
    git( repo, "commit", "-q", "-m", "not markdown" )
    ( repo / "README.md" ).write_text( "# repo\n" + NOT_IN_LOG + "\n", encoding="utf-8" )
    git( repo, "commit", "-q", "-a", "-m", "a modified markdown file" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and text.count( "REFUSED" ) == 1 and "REFUSED README.md line 2" in text, "the modified file's added line is read, the other files are not"
    git( repo, "rm", "-q", "README.md" )
    git( repo, "commit", "-q", "-m", "delete the markdown file" )
    assert run( repo, data, tmp_path )[ 0 ] == 0, "a deleted file adds no line"


def test_an_added_line_that_looks_like_a_file_header_is_read_as_a_line( repo ):
    ( repo / "odd.md" ).write_text( "++ b/other.md\n", encoding="utf-8" )
    git( repo, "add", "odd.md" )
    git( repo, "commit", "-q", "-m", "odd" )
    assert mg.added_text_by_file( repo, git( repo, "rev-parse", "main" ).strip() ) == { "odd.md": "++ b/other.md" }
    ( repo / "odd.md" ).write_text( "keep\n\nkeep\n++ b/other.md\n", encoding="utf-8" )
    git( repo, "commit", "-q", "-a", "-m", "odd again" )
    assert mg.added_text_by_file( repo, git( repo, "rev-parse", "main" ).strip() ) == { "odd.md": "keep\n\nkeep\n++ b/other.md" }, "added lines keep their own line numbers"


def test_every_new_definition_of_the_diff_needs_an_outcome_line( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "added": [ "lupin_mcp.new_helper", "lupin_mcp.other_new" ], "removed": [], "changed": [] } ), encoding="utf-8" )
    code, text = run( repo, data, tmp_path, "--diff", str( diff ) )
    assert code == 1 and "MISSING lupin_mcp.other_new is new in the diff and has no outcome line" in text and "lupin_mcp.new_helper is new" not in text
    assert ( count( text, "Total Tests" ), count( text, "Passed" ), count( text, "Failed" ) ) == ( 4, 3, 1 )
    diff.write_text( json.dumps( { "added": [ "lupin_mcp.new_helper" ] } ), encoding="utf-8" )
    assert run( repo, data, tmp_path, "--diff", str( diff ) )[ 0 ] == 0


def test_a_definition_with_no_outcome_line_is_only_reported_when_gating_is_off( repo, data, tmp_path ):
    commit_doc( repo, "notes.md", "prose", rulings=False )
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "added": [ "m.q" ] } ), encoding="utf-8" )
    code, text = run( repo, data, tmp_path, "--diff", str( diff ), value="false" )
    assert code == 0 and "MISSING m.q is new in the diff" in text and "Report-only: 1" in text


def test_a_diff_that_reports_a_changed_algorithm_could_not_be_checked( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "algorithm_changed": True } ), encoding="utf-8" )
    code, text = run( repo, data, tmp_path, "--diff", str( diff ) )
    assert code == mg.EXIT_NOT_CHECKED == 3 and "the pin algorithm changed" in text and "Total Tests" not in text and not ( data / rr.REFUSALS_NAME ).exists()


@pytest.mark.parametrize( "value", [ "maybe", "" ] )
def test_an_unreadable_gating_key_could_not_be_checked_before_anything_is_read( repo, data, tmp_path, value ):
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, data, tmp_path, value=value )
    assert code == 3 and f"`{gate.GATING_KEY}` could not be read. Nothing was checked." in text and "Total Tests" not in text and not ( data / rr.REFUSALS_NAME ).exists()


def test_a_repository_with_no_base_could_not_be_checked( tmp_path, data ):
    path = tmp_path / "bare-history"
    path.mkdir()
    git( path, "init", "-q", "-b", "other" )
    ( path / "a.md" ).write_text( "x\n", encoding="utf-8" )
    git( path, "add", "a.md" )
    git( path, "commit", "-q", "-m", "only" )
    code, text = run( path, data, tmp_path )
    assert code == 3 and "git names no merge base for HEAD; pass --base. Nothing was checked." in text


def test_a_named_base_replaces_the_default_and_a_unknown_one_is_not_checked( repo, data, tmp_path ):
    git( repo, "checkout", "-q", "-b", "side", "main" )
    commit_doc( repo, "one.md", NOT_IN_LOG )
    git( repo, "checkout", "-q", "-b", "feat2" )
    commit_doc( repo, "two.md", GOOD )
    assert run( repo, data, tmp_path )[ 0 ] == 1, "measured from main, the first file's bad line is part of the branch"
    code, text = run( repo, data, tmp_path, "--base", "side" )
    assert code == 0 and "REFUSED" not in text, "measured from side, only the second file counts"
    assert mg.resolve_base( repo, "no-such-branch" ) is None and mg.resolve_base( repo ) == git( repo, "rev-parse", "main" ).strip()


def test_the_origin_main_name_is_tried_when_main_is_absent( repo ):
    git( repo, "update-ref", "refs/remotes/origin/main", "main" )
    git( repo, "branch", "-q", "-m", "main", "trunk" )
    assert mg.resolve_base( repo ) == git( repo, "rev-parse", "origin/main" ).strip()


def test_a_diff_git_cannot_produce_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    assert mg.added_text_by_file( repo, "0" * 40 ) is None
    monkeypatch.setattr( mg, "added_text_by_file", lambda root, sha: None )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "git could not diff" in text


def test_a_git_that_cannot_start_answers_127(  repo, monkeypatch ):
    def boom( *a, **k ): raise OSError( "no git" )
    monkeypatch.setattr( mg.subprocess, "run", boom )
    assert mg._git( repo, [ "status" ] ) == ( 127, "" )


def test_the_data_folder_and_the_flag_default_to_the_shared_choices( repo, data, tmp_path, monkeypatch ):
    commit_doc( repo, "review.md", GOOD )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( data ) )
    monkeypatch.setenv( gate.INI_OVERRIDE, ini( tmp_path, extra=f"reuse merge gate since = {default_since( repo )}\nreuse searched since = {default_since( repo )}\n" ) )
    out = io.StringIO()
    assert mg.main( [ "--root", str( repo ) ], out=out ) == 0 and ( data / rr.REFUSALS_NAME ).exists()


def test_the_command_prints_to_standard_output_by_default( repo, data, tmp_path, capsys ):
    commit_doc( repo, "review.md", GOOD )
    assert mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, extra=f"reuse merge gate since = {default_since( repo )}\nreuse searched since = {default_since( repo )}\n" ) ] ) == 0
    assert "REUSE GATE PASSED" in capsys.readouterr().out


@pytest.mark.parametrize( "content", [ None, "not json", "[1, 2]", '{"added": "m.q"}' ] )
def test_a_diff_file_that_is_missing_or_not_a_symbol_index_diff_could_not_be_checked( repo, data, tmp_path, content ):
    commit_doc( repo, "review.md", GOOD )
    diff = tmp_path / "diff.json"
    if content is not None: diff.write_text( content, encoding="utf-8" )
    code, text = run( repo, data, tmp_path, "--diff", str( diff ) )
    assert code == 3 and "Nothing was checked." in text and "Total Tests" not in text and not ( data / rr.REFUSALS_NAME ).exists()


def test_an_unreadable_call_log_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    commit_doc( repo, "review.md", GOOD )
    def boom( folder ): raise OSError( "log folder unreadable" )
    monkeypatch.setattr( mg.eg, "merge_call_logs", boom )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "OSError: log folder unreadable. Nothing was checked." in text


def test_a_record_that_cannot_be_written_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    commit_doc( repo, "review.md", GOOD )
    def boom( folder, text, verdicts ): raise OSError( "disk full" )
    monkeypatch.setattr( mg.rr, "record", boom )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "OSError: disk full. Nothing was checked." in text and "Total Tests" not in text


def test_a_data_folder_that_cannot_be_made_could_not_be_checked( repo, tmp_path ):
    blocker = tmp_path / "a-file"
    blocker.write_text( "x", encoding="utf-8" )
    code, text = run( repo, blocker / "data", tmp_path )
    assert code == 3 and "Nothing was checked." in text and "Total Tests" not in text


def commit_code( repo, name, text ):
    """Ensures: commits a source file with this text."""
    ( repo / name ).parent.mkdir( parents=True, exist_ok=True )
    ( repo / name ).write_text( text, encoding="utf-8" )
    git( repo, "add", name )
    git( repo, "commit", "-q", "-m", f"code {name}" )


def worktrees( repo ):
    """Ensures: returns the paths git lists as working trees of repo."""
    return [ l[ 9: ] for l in git( repo, "worktree", "list", "--porcelain" ).splitlines() if l.startswith( "worktree " ) ]


def test_a_new_function_with_no_outcome_line_is_found_from_git_and_refused( repo, data, tmp_path ):
    commit_code( repo, "pkg/mod.py", "def old():\n    return 1\n" )
    git( repo, "branch", "-f", "main", "HEAD" )
    commit_code( repo, "pkg/mod.py", "def old():\n    return 2\n\n\ndef fresh():\n    return 3\n\n\nclass K:\n    def method( self ):\n        return 4\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:pkg.mod.fresh is new in the diff" in text and "MISSING repo:pkg.mod.K.method is new in the diff" in text
    assert "old is new" not in text, "a function whose text changed is not a new definition"
    assert ( count( text, "Total Tests" ), count( text, "Failed" ) ) == ( 3, 2 )
    assert worktrees( repo ) == [ str( repo ) ], "both detached worktrees are removed"


def test_a_ruling_and_an_outcome_line_cover_a_new_function( repo, data, tmp_path ):
    commit_code( repo, "pkg/mod.py", "def fresh():\n    return 3\n" )
    ( repo / "review.md" ).write_text( f"RULING repo:pkg.mod.fresh :: DUPLICATE :: reuse-receipt: {RID}\nSEARCHED repo:pkg.mod.fresh :: {SID} :: none :: nothing near it\n{GOOD}\n", encoding="utf-8" )
    git( repo, "add", "review.md" )
    git( repo, "commit", "-q", "-m", "review" )
    code, text = run( repo, data, tmp_path )
    assert code == 0 and "MISSING" not in text and "1 outcome lines and 1 new definitions" in text


def test_a_branch_with_a_new_function_is_only_reported_when_gating_is_off( repo, data, tmp_path ):
    commit_code( repo, "pkg/mod.py", "def fresh():\n    return 3\n" )
    code, text = run( repo, data, tmp_path, value="false" )
    assert code == 0 and "MISSING repo:pkg.mod.fresh" in text and "Report-only: 1" in text


def test_a_given_diff_replaces_the_definitions_found_from_git( repo, data, tmp_path ):
    commit_code( repo, "pkg/mod.py", "def fresh():\n    return 3\n" )
    diff = tmp_path / "diff.json"
    diff.write_text( json.dumps( { "added": [] } ), encoding="utf-8" )
    code, text = run( repo, data, tmp_path, "--diff", str( diff ) )
    assert code == 0 and "MISSING" not in text


def test_a_script_file_gets_the_file_stem_id( repo, data, tmp_path, monkeypatch ):
    commit_code( repo, "static/js/a.ts", "export function foo() {}\n" )
    def fake( root, files, origin ):
        return { "definitions": [] if root.name.endswith( "-base" ) else [ { "lang": "ts", "file": "static/js/a.ts", "name": "foo", "line": 1 } ],
                 "skipped_python": [], "skipped_script": [], "script_accounts": [], "repeated_ids": [] }
    monkeypatch.setattr( mg.extract, "extract_tree", fake )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:static.js.a.foo is new in the diff" in text


def test_a_changed_file_that_is_not_source_python_could_not_be_checked( repo, data, tmp_path ):
    commit_code( repo, "pkg/broken.py", "def (:\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "pkg/broken.py did not parse, so its definitions cannot be listed" in text and "Nothing was checked." in text and "Total Tests" not in text
    assert worktrees( repo ) == [ str( repo ) ], "the worktrees are removed after a failure too"


def test_a_window_git_cannot_build_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    def boom( *a, **k ): raise RuntimeError( "git rev-parse failed" )
    monkeypatch.setattr( mg.daily, "window_of", boom )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "RuntimeError: git rev-parse failed. Nothing was checked." in text


def test_a_script_extraction_that_does_not_close_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    commit_code( repo, "static/js/a.ts", "export function foo() {}\n" )
    account = { "file": "static/js/a.ts", "reported": 1, "anonymous_walked": 0, "function_like_total": 2 }
    monkeypatch.setattr( mg.extract, "extract_tree", lambda root, files, origin: { "definitions": [], "skipped_python": [], "skipped_script": [], "script_accounts": [ account ], "repeated_ids": [] } )
    code, text = run( repo, data, tmp_path )
    assert code == 3 and "DuplicateCheckError" in text and "1 reported + 0 anonymous != 2 function-like nodes" in text


def test_a_file_the_symbol_index_does_not_hold_lists_no_definitions( repo, data, tmp_path ):
    commit_code( repo, "tests/test_thing.py", "def test_it():\n    return 1\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 0 and "MISSING" not in text and "0 new definitions" in text
    commit_code( repo, "pkg/mod.py", "def fresh():\n    return 3\n" )
    assert "MISSING repo:pkg.mod.fresh" in run( repo, data, tmp_path )[ 1 ], "an indexed file beside it is listed"


def test_a_branch_that_changes_no_indexed_file_makes_no_worktree( repo, data, tmp_path, monkeypatch ):
    def boom( *a, **k ): raise AssertionError( "a worktree was made" )
    monkeypatch.setattr( mg.source_at, "ensure_worktree", boom )
    commit_doc( repo, "review.md", GOOD )
    assert run( repo, data, tmp_path )[ 0 ] == 0


def sha_of( repo, rev="HEAD" ):
    """Ensures: returns the full sha of a revision."""
    return git( repo, "rev-parse", rev ).strip()


def test_the_base_is_the_nearest_merge_base_among_the_branches_named( repo, data, tmp_path ):
    commit_doc( repo, "old.md", NOT_IN_LOG )
    git( repo, "branch", "-f", "integration", "HEAD" )
    commit_doc( repo, "new.md", GOOD )
    assert mg.resolve_base( repo, [ "main", "integration" ] ) == sha_of( repo, "integration" ), "integration lies nearer HEAD than the stale main"
    assert mg.resolve_base( repo, [ "integration", "main" ] ) == sha_of( repo, "integration" ), "the order of the names does not matter"
    assert mg.resolve_base( repo, [ "nope", "main" ] ) == sha_of( repo, "main" ), "a name git does not know is passed over"
    assert mg.resolve_base( repo, "integration" ) == sha_of( repo, "integration" )
    code, text = run( repo, data, tmp_path, lines="reuse merge gate base = main integration\n" )
    assert code == 0 and "REFUSED" not in text, "the key makes the branch be measured from integration, so old.md is not part of it"
    assert run( repo, data, tmp_path )[ 0 ] == 1, "without the key the stale main is the base and old.md's bad line counts"
    assert run( repo, data, tmp_path, "--base", "main", lines="reuse merge gate base = integration\n" )[ 0 ] == 1, "--base wins over the key"


def test_the_base_names_default_when_the_key_is_absent_empty_or_doubled( tmp_path ):
    assert mg.read_names( ini( tmp_path ) ) == list( mg.BASE_CANDIDATES )
    assert mg.read_names( ini( tmp_path, extra="reuse merge gate base =\n" ) ) == list( mg.BASE_CANDIDATES )
    assert mg.read_names( ini( tmp_path, extra="reuse merge gate base = a\nreuse merge gate base = b\n" ) ) == list( mg.BASE_CANDIDATES )
    assert mg.read_names( ini( tmp_path, extra="reuse merge gate base = a  b\n" ) ) == [ "a", "b" ]


def test_the_since_key_reads_a_commit_or_nothing_and_refuses_text_that_is_not_a_commit( tmp_path ):
    assert mg.read_since( ini( tmp_path ) ) is None, "absent"
    assert mg.read_since( ini( tmp_path, extra="reuse merge gate since =\n" ) ) is None, "empty"
    assert mg.read_since( ini( tmp_path, extra="reuse merge gate since = abc1234\n" ) ) == "abc1234"
    with pytest.raises( ValueError, match="not a commit" ): mg.read_since( ini( tmp_path, extra="reuse merge gate since = latest\n" ) )


def test_lines_and_definitions_added_before_the_since_commit_are_exempt( repo, data, tmp_path ):
    commit_doc( repo, "old.md", NOT_IN_LOG )
    commit_code( repo, "pkg/old.py", "def early():\n    return 1\n" )
    since = sha_of( repo )
    commit_code( repo, "pkg/late.py", "def late():\n    return 2\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:pkg.old.early" in text and "MISSING repo:pkg.late.late" in text and "REFUSED old.md" in text
    code, text = run( repo, data, tmp_path, lines=f"reuse merge gate since = {since}\n" )
    assert code == 1 and "MISSING repo:pkg.late.late" in text and "early" not in text and "REFUSED" not in text, "only what came after since is checked"
    assert ( count( text, "Total Tests" ), count( text, "Failed" ) ) == ( 2, 1 )


def test_a_since_commit_the_branch_does_not_contain_exempts_nothing( repo, data, tmp_path ):
    git( repo, "checkout", "-q", "-b", "other", "main" )
    commit_doc( repo, "other.md", GOOD )
    elsewhere = sha_of( repo )
    git( repo, "checkout", "-q", "feat" )
    commit_doc( repo, "old.md", NOT_IN_LOG )
    code, text = run( repo, data, tmp_path, lines=f"reuse merge gate since = {elsewhere}\n" )
    assert code == 1 and "REFUSED old.md" in text, "a branch cut before the since commit is checked from its merge base"


def test_the_effective_base_is_the_later_of_the_merge_base_and_since( repo ):
    commit_doc( repo, "one.md", GOOD )
    middle = sha_of( repo )
    commit_doc( repo, "two.md", GOOD )
    tip, root_sha = sha_of( repo ), sha_of( repo, "main" )
    assert mg.effective_base( repo, root_sha, None ) == root_sha, "no since, no move"
    assert mg.effective_base( repo, root_sha, middle[ :9 ] ) == middle, "since lies between the base and HEAD: the base moves up to it, as a full sha"
    assert mg.effective_base( repo, tip, middle ) == tip, "since older than the base moves nothing"
    git( repo, "checkout", "-q", "-b", "side", root_sha )
    commit_doc( repo, "side.md", GOOD )
    assert mg.effective_base( repo, root_sha, sha_of( repo ) ) == sha_of( repo ), "a side commit that is HEAD itself is inside"
    git( repo, "checkout", "-q", "feat" )
    assert mg.effective_base( repo, root_sha, sha_of( repo, "side" ) ) == root_sha, "a commit HEAD does not contain moves nothing"


def test_a_since_commit_git_does_not_know_could_not_be_checked( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, data, tmp_path, lines="reuse merge gate since = deadbee\n" )
    assert code == 3 and "`reuse merge gate since` names deadbee, which git does not know. Nothing was checked." in text and "Total Tests" not in text


def test_a_since_value_that_is_not_a_commit_could_not_be_checked( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, data, tmp_path, lines="reuse merge gate since = latest\n" )
    assert code == 3 and "which is not a commit. Nothing was checked." in text and "Total Tests" not in text


def test_a_renamed_file_makes_only_its_new_functions_new( repo, data, tmp_path ):
    both = "def same():\n    return 1\n\n\ndef keep():\n    return 2\n"
    commit_code( repo, "pkg/m.py", both )
    git( repo, "branch", "-f", "main", "HEAD" )
    git( repo, "mv", "pkg/m.py", "pkg/n.py" )
    ( repo / "pkg" / "n.py" ).write_text( both + "\n\ndef fresh():\n    return 3\n", encoding="utf-8" )
    git( repo, "add", "pkg/n.py" )
    git( repo, "commit", "-q", "-m", "rename and add" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:pkg.n.fresh is new in the diff" in text, "the function added in the renamed file is new"
    assert "pkg.n.same" not in text and "pkg.n.keep" not in text, "the functions the old path held are not new under the new one"
    assert ( count( text, "Total Tests" ), count( text, "Failed" ) ) == ( 2, 1 )


FLIP_SINCE  = "2e91a63f2d26ee2645030da6304aaef39d418eeb"                                     # Rick, 10 Nov 2026 (row 5f8fc615): moved from d0180365c, the v0.2.2 squash merge, to the branch tip that night; the older definitions are back-filled by row
FLIP_BASE   = "main"                                                                       # the branch v0.2.3 merges into
SEARCHED_FLIP = "f20d11273013611a585dacd41be92a58d56245a8"                                 # Cheech, 14 Nov 2026 (row 7571c610): the tip the SEARCHED check starts after
FLIP_VALUES = { mg.SINCE_KEY: FLIP_SINCE, mg.BASE_KEY: FLIP_BASE, mg.SEARCHED_SINCE_KEY: SEARCHED_FLIP }


@pytest.mark.parametrize( "key", [ mg.SINCE_KEY, mg.BASE_KEY, mg.SEARCHED_SINCE_KEY ] )
def test_the_shipped_ini_defines_each_new_key_once_with_its_flip_value_and_the_explainer_describes_it( key ):
    root = pathlib.Path( mg.__file__ ).resolve().parents[ 2 ]
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ):
        text = ( root / "src" / "conf" / name ).read_text( encoding="utf-8" )
        rows = [ l for l in text.splitlines() if l.startswith( f"{key} " ) ]
        assert len( rows ) == 1, f"{key} is defined {len( rows )} times in {name}"
        if name == "lupin-app.ini": assert rows[ 0 ].split( "=", 1 )[ 1 ].strip() == FLIP_VALUES[ key ], "the flip sets both keys in the commit that turns gating on"
        else: assert "Keep it defined exactly once." in rows[ 0 ] and len( rows[ 0 ] ) > 200
    ini_path = str( root / "src" / "conf" / "lupin-app.ini" )
    assert mg.read_since( ini_path ) == FLIP_SINCE and mg.read_names( ini_path ) == [ FLIP_BASE ]
    assert mg.read_since( ini_path, mg.SEARCHED_SINCE_KEY ) == SEARCHED_FLIP
    assert gate.read_gating( ini_path, quiet=True ) is True, "gating is on, and the longer key names do not make the gating key read as doubled"


@pytest.mark.parametrize( "lines", [ "", "reuse merge gate since =\n", "reuse merge gate since = aaaaaaa\nreuse merge gate since = bbbbbbb\n" ] )
def test_gating_on_with_an_empty_since_could_not_be_checked_and_says_why( repo, data, tmp_path, lines ):
    commit_doc( repo, "review.md", GOOD )
    out  = io.StringIO()
    code = mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, "true", lines ) ], out=out )
    text = out.getvalue()
    assert code == 3 and "`reuse review gating` is true and `reuse merge gate since` is empty" in text and "Set both in one commit. Nothing was checked." in text
    assert "Total Tests" not in text and not ( data / rr.REFUSALS_NAME ).exists(), "nothing was scanned or recorded"


def test_an_empty_since_is_allowed_while_gating_is_off_and_a_set_one_is_allowed_while_it_is_on( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    out  = io.StringIO()
    code = mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, "false" ) ], out=out )
    assert code == 0 and "gating is off (report only)" in out.getvalue(), "the shipped state: gating false, since empty"
    code, text = run( repo, data, tmp_path, value="true" )
    assert code == 0 and "REUSE GATE PASSED" in text, "gating true with a since set runs the gate"


def test_a_script_member_the_symbol_index_cannot_hold_is_not_a_new_definition( repo, data, tmp_path ):
    # The duplicate extractor finds object-literal members and the index does not, so no outcome line could ever cover them.
    commit_code( repo, "static/js/a.js", "export function top() { return 1; }\nexport const api = {\n    canFlip: () => true,\n    plain() { return 2; },\n};\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:static.js.a.top is new in the diff" in text
    assert "canFlip" not in text and "plain" not in text, "the index does not hold them, so nothing can be owed for them"
    assert ( count( text, "Total Tests" ), count( text, "Failed" ) ) == ( 2, 1 )


def test_a_function_nested_in_a_function_is_not_a_new_definition( repo, data, tmp_path ):
    commit_code( repo, "pkg/mod.py", "def outer():\n    def inner():\n        return 1\n    return inner\n\n\nclass K:\n    def m( self ):\n        def deep():\n            return 2\n        return deep\n" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:pkg.mod.outer is new" in text and "MISSING repo:pkg.mod.K.m is new" in text
    assert "<locals>" not in text, "a nested helper is never listed, so no outcome line is owed for it"
    assert ( count( text, "Total Tests" ), count( text, "Failed" ) ) == ( 3, 2 )


def test_a_ruling_with_no_searched_line_is_refused_naming_the_definition_and_a_searched_line_clears_it( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD, rulings=False )
    ( repo / "bare.md" ).write_text( f"RULING repo:pkg.mod.bare :: DUPLICATE :: reuse-receipt: {RID}\n", encoding="utf-8" )
    git( repo, "add", "bare.md" )
    git( repo, "commit", "-q", "-m", "bare" )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "MISSING repo:pkg.mod.bare has a RULING line and no SEARCHED line" in text
    ( repo / "bare.md" ).write_text( f"RULING repo:pkg.mod.bare :: DUPLICATE :: reuse-receipt: {RID}\nSEARCHED repo:pkg.mod.bare :: {SID} :: none :: nothing near it\n", encoding="utf-8" )
    git( repo, "commit", "-q", "-am", "searched" )
    code, text = run( repo, data, tmp_path )
    assert "no SEARCHED line" not in text


def test_a_ruling_with_no_searched_line_from_before_since_is_exempt( repo, data, tmp_path ):
    ( repo / "old.md" ).write_text( f"RULING repo:pkg.mod.bare :: DUPLICATE :: reuse-receipt: {RID}\n", encoding="utf-8" )
    git( repo, "add", "old.md" )
    git( repo, "commit", "-q", "-m", "old ruling" )
    since = sha_of( repo )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "no SEARCHED line" in text
    code, text = run( repo, data, tmp_path, lines=f"reuse merge gate since = {since}\n" )
    assert code == 0 and "no SEARCHED line" not in text, "a ruling on main before since stays exempt"


def test_a_ruling_before_the_searched_since_commit_is_exempt_while_since_still_reads_it( repo, data, tmp_path ):
    ( repo / "old.md" ).write_text( f"RULING repo:pkg.mod.bare :: DUPLICATE :: reuse-receipt: {RID}\n", encoding="utf-8" )
    git( repo, "add", "old.md" )
    git( repo, "commit", "-q", "-m", "old ruling" )
    later = sha_of( repo )
    commit_doc( repo, "new.md", GOOD )
    code, text = run( repo, data, tmp_path )
    assert code == 1 and "repo:pkg.mod.bare has a RULING line and no SEARCHED line" in text, "searched since at the merge base reads the old ruling"
    code, text = run( repo, data, tmp_path, lines=f"reuse searched since = {later}\n" )
    assert code == 0 and "no SEARCHED line" not in text, "searched since after it exempts it, and a later document still passes"
    ( repo / "late.md" ).write_text( f"RULING repo:pkg.mod.late :: DUPLICATE :: reuse-receipt: {RID}\n", encoding="utf-8" )
    git( repo, "add", "late.md" )
    git( repo, "commit", "-q", "-m", "late ruling" )
    code, text = run( repo, data, tmp_path, lines=f"reuse searched since = {later}\n" )
    assert code == 1 and "repo:pkg.mod.late has a RULING line and no SEARCHED line" in text and "repo:pkg.mod.bare" not in text, "a ruling after it is still judged"


def test_a_searched_diff_git_cannot_produce_could_not_be_checked( repo, data, tmp_path, monkeypatch ):
    commit_doc( repo, "review.md", GOOD )
    later = sha_of( repo )
    commit_doc( repo, "second.md", GOOD )
    real  = mg.added_text_by_file
    monkeypatch.setattr( mg, "added_text_by_file", lambda root, sha: real( root, sha ) if sha != later else None )
    code, text = run( repo, data, tmp_path, lines=f"reuse searched since = {later}\n" )
    assert code == 3 and f"git could not diff {later}" in text


@pytest.mark.parametrize( "lines", [ "", "reuse searched since =\n", "reuse searched since = aaaaaaa\nreuse searched since = bbbbbbb\n" ] )
def test_gating_on_with_an_empty_searched_since_could_not_be_checked_and_says_why( repo, data, tmp_path, lines ):
    commit_doc( repo, "review.md", GOOD )
    out  = io.StringIO()
    code = mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, "true", f"reuse merge gate since = {default_since( repo )}\n{lines}" ) ], out=out )
    text = out.getvalue()
    assert code == 3 and "`reuse review gating` is true and `reuse searched since` is empty" in text and "Nothing was checked." in text
    assert "Total Tests" not in text, "nothing was scanned"


def test_a_searched_since_that_is_not_a_known_commit_could_not_be_checked( repo, data, tmp_path ):
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, data, tmp_path, lines="reuse searched since = latest\n" )
    assert code == 3 and "`reuse searched since` holds 'latest', which is not a commit" in text
    code, text = run( repo, data, tmp_path, lines="reuse searched since = abcdef1\n" )
    assert code == 3 and "`reuse searched since` names abcdef1, which git does not know" in text


# ---- receipts logged in another registered repo (row a71018e9) ----

@pytest.fixture
def fleet( tmp_path, monkeypatch, data ):
    """
    Build a fleet folder with an empty log for `repo` and the real log for `other`.

    Ensures:
        - DEEPILY_DATA_DIR names the fleet folder
        - `other` holds the real call log and the real search record
        - returns ( this repo's data folder, other's data folder )
    """
    from cosa.repo.symindex.candidates import storage_paths
    base = tmp_path / "fleet"
    monkeypatch.setenv( "DEEPILY_DATA_DIR", str( base ) )
    subdir = storage_paths.data_subdir()
    own, other = base / "repo" / subdir, base / "other" / subdir
    ( own / "call-log" ).mkdir( parents=True )
    ( other / "call-log" ).mkdir( parents=True )
    ( other / "search-records" ).mkdir()
    ( other / "call-log" / "real.jsonl" ).write_text( ( data / "call-log" / "real.jsonl" ).read_text( encoding="utf-8" ), encoding="utf-8" )
    ( other / "search-records" / f"{SID}.json" ).write_text( ( data / "search-records" / f"{SID}.json" ).read_text( encoding="utf-8" ), encoding="utf-8" )
    return own, other


def test_a_receipt_logged_in_another_repos_call_log_is_refused_and_the_message_names_that_repo( repo, fleet, tmp_path ):
    own, other = fleet
    commit_doc( repo, "review.md", GOOD )
    code, text = run( repo, own, tmp_path )
    assert code == 1 and "REFUSED review.md" in text and "was logged in" not in text, "control: with no sibling log the line is refused, with no repo named"
    result = mg.run( repo, "main", None, own, own / "call-log", True, sibling_dirs=[ other ] )
    assert result[ "lines" ] == 1 and len( result[ "refusals" ] ) == 1, "the other repo's log never makes the line pass"
    reasons = result[ "refusals" ][ 0 ][ "reasons" ]
    assert f"receipt {RID} was logged in other's call log, so it searched that repo; re-run check_exists with root set to {repo}" in reasons
    assert any( "is not in the log" in r for r in reasons ), "the ordinary reason stays"


def test_the_command_names_the_repo_a_refused_receipt_was_logged_in( repo, fleet, tmp_path, monkeypatch ):
    own, _other = fleet
    commit_doc( repo, "review.md", GOOD )
    monkeypatch.setattr( mg.sym_paths, "registered_repo_names", lambda config=None: [ "repo", "other", "ghost" ] )
    code, text = run( repo, own, tmp_path )
    assert code == 1 and f"was logged in other's call log" in text and f"root set to {repo}" in text
    assert len( ( own / rr.REFUSALS_NAME ).read_text( encoding="utf-8" ).splitlines() ) == 1
    assert "was logged in other" in ( own / rr.REFUSALS_NAME ).read_text( encoding="utf-8" ), "the refusal record carries the same reason"


def test_an_unregistered_repos_call_log_is_not_read_so_no_repo_is_named( repo, fleet, tmp_path, monkeypatch ):
    own, _other = fleet
    commit_doc( repo, "review.md", GOOD )
    monkeypatch.setattr( mg.sym_paths, "registered_repo_names", lambda config=None: [ "repo" ] )
    code, text = run( repo, own, tmp_path )
    assert code == 1 and "REFUSED review.md" in text and "was logged in" not in text


def test_an_explicit_log_folder_skips_the_other_repos( repo, fleet, tmp_path, monkeypatch ):
    own, _other = fleet
    commit_doc( repo, "review.md", GOOD )
    monkeypatch.setattr( mg.sym_paths, "registered_repo_names", lambda config=None: [ "other" ] )
    code, text = run( repo, own, tmp_path, "--log-dir", str( own / "call-log" ) )
    assert code == 1 and "was logged in" not in text


def test_a_line_that_is_refused_for_another_reason_or_holds_a_receipt_no_repo_logged_gets_no_repo_named( repo, fleet, tmp_path ):
    own, other = fleet
    commit_doc( repo, "review.md", GOOD, NOT_IN_LOG, BAD_SHAPE )
    result = mg.run( repo, "main", None, own, own / "call-log", True, sibling_dirs=[ other ] )
    named  = [ r for r in result[ "refusals" ] if any( "was logged in" in x for x in r[ "reasons" ] ) ]
    assert len( result[ "refusals" ] ) == 3 and len( named ) == 1 and named[ 0 ][ "line" ] == GOOD


def test_a_receipt_this_repo_logged_is_not_renamed_to_another_repo( repo, data, fleet, tmp_path ):
    _own, other = fleet
    commit_doc( repo, "review.md", GOOD )
    result = mg.run( repo, "main", None, data, data / "call-log", True, sibling_dirs=[ other ] )
    assert result[ "refusals" ] == [], "this repo holds the receipt, so the other repo's copy changes nothing"


def test_a_receipt_logged_in_two_repos_names_the_first( tmp_path ):
    for name in ( "a", "b" ):
        folder = tmp_path / name / "reuse-review" / "call-log"
        folder.mkdir( parents=True )
        ( folder / "x.jsonl" ).write_text( json.dumps( { "tool": "check_exists", "receipt_id": RID } ) + "\n", encoding="utf-8" )
    assert mg.foreign_receipts( [ tmp_path / "a" / "reuse-review", tmp_path / "b" / "reuse-review" ] ) == { RID: "a" }


def test_the_sibling_folders_are_the_registered_repos_with_a_call_log_other_than_this_one( repo, fleet, tmp_path ):
    own, other = fleet
    base = own.parent.parent
    ( base / "nolog" / own.name ).mkdir( parents=True )
    found = mg.sibling_data_dirs( repo, [ "repo", "other", "nolog", "ghost", "unlisted-is-not-here" ] )
    assert found == [ other ], "own repo, a repo with no call-log, and a repo with no folder are all left out"


def test_the_sibling_folders_default_to_the_registry( repo, fleet, monkeypatch ):
    _own, other = fleet
    monkeypatch.setattr( mg.sym_paths, "registered_repo_names", lambda config=None: [ "other" ] )
    assert mg.sibling_data_dirs( repo ) == [ other ]


def test_a_registry_that_cannot_be_read_could_not_be_checked( repo, fleet, tmp_path, monkeypatch ):
    own, _other = fleet
    commit_doc( repo, "review.md", GOOD )
    def boom( config=None ): raise mg.cand_errors.CandidateError( "x", "registry unreadable" )
    monkeypatch.setattr( mg.sym_paths, "registered_repo_names", boom )
    code, text = run( repo, own, tmp_path )
    assert code == 3 and "other registered repos' call logs could not be found" in text and "Total Tests" not in text
