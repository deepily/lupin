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


def ini( tmp_path, value="true" ):
    """Ensures: returns the path of an ini file holding the gating key with this value."""
    path = tmp_path / "lupin-app.ini"
    path.write_text( f"[x]\nreuse review gating = {value}\n", encoding="utf-8" )
    return str( path )


def commit_doc( repo, name, *lines, rulings=True ):
    """Ensures: commits a Markdown file with the rulings, a template and these lines."""
    body = "# review\n\n" + ( RULINGS + "\n\n" if rulings else "" ) + "```text\n" + TEMPLATE + "\n```\n\n" + "\n".join( lines ) + "\n"
    ( repo / name ).write_text( body, encoding="utf-8" )
    git( repo, "add", name )
    git( repo, "commit", "-q", "-m", f"add {name}" )


def run( repo, data, tmp_path, *extra, value="true" ):
    """Ensures: returns ( exit code, printed text ) of the command on repo."""
    out  = io.StringIO()
    code = mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path, value ), *extra ], out=out )
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
    ( repo / "code.py" ).write_text( NOT_IN_LOG + "\n", encoding="utf-8" )
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
    monkeypatch.setenv( gate.INI_OVERRIDE, ini( tmp_path ) )
    out = io.StringIO()
    assert mg.main( [ "--root", str( repo ) ], out=out ) == 0 and ( data / rr.REFUSALS_NAME ).exists()


def test_the_command_prints_to_standard_output_by_default( repo, data, tmp_path, capsys ):
    commit_doc( repo, "review.md", GOOD )
    assert mg.main( [ "--root", str( repo ), "--data-dir", str( data ), "--ini", ini( tmp_path ) ] ) == 0
    assert "REUSE GATE PASSED" in capsys.readouterr().out
