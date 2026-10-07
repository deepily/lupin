"""
history_destination: every history-labelled dropped claim has its quote at a destination.

REAL_SORT and REAL_WORKSHEET are rows copied from the one-package trial of 2026-10-05 (Tiberius's sort of the
git_loc_delta rewrite and its claim worksheet), not written for this file. The destinations are made up, in a
small real git repo in a temp directory.
"""

import io
import json
import subprocess

import pytest

from cosa.repo.doc_lint import history_destination as hd

REAL_SORT = [
    {"n": 5, "class": "H", "quote": "", "note": "Process history: which review pass checked the references."},
    {"n": 6, "class": "H", "quote": "", "note": "Date the field was added; the new text keeps the requirement and the schema v2 name."},
    {"n": 8, "class": "H", "quote": "", "note": "Bug ids."},
    {"n": 10, "class": "J", "quote": "The roll-up once reported numbers that were self-consistent and wrong.", "note": "Claim stated in the new text. Only 'for weeks' and 'confidently' dropped, which are incident colour."},
    {"n": 13, "class": "H", "quote": "", "note": "Who did the extension."},
]

REAL_WORKSHEET = [
    {"n": 5, "id": "src/cosa/repo/git_loc_delta/analyzer.py::<module>#0", "claim": "The reuse map references were verified during the REUSE pre-pass.", "quote": "Reuse map references (verified during REUSE pre-pass):", "history_tagged": False},
    {"n": 6, "id": "src/cosa/repo/git_loc_delta/analyzer.py::__init__#0", "claim": "repo_name is the explicit repo identity, added in schema v2 on 2026-05-21.", "quote": "repo_name is the explicit repo identity (added 2026-05-21 schema v2)", "history_tagged": True},
    {"n": 8, "id": "src/cosa/repo/git_loc_delta/analyzer.py::__init__#0", "claim": "The documented behavior relates to bugs bbff93a3 and 37a8beeb.", "quote": "bugs bbff93a3 / 37a8beeb", "history_tagged": True},
    {"n": 10, "id": "src/cosa/repo/git_loc_delta/coverage_guard.py::<module>#0", "claim": "Before the fix, the roll-up reported numbers that were self-consistent but wrong, and this went on for weeks.", "quote": "The roll-up had been reporting\nnumbers that were **self-consistent and confidently wrong** for weeks", "history_tagged": False},
    {"n": 13, "id": "src/cosa/repo/git_loc_delta/csv_writer.py::<module>#0", "claim": "Schema v2 was extended by Rachel.", "quote": "extended by Rachel 🕊️", "history_tagged": False},
]

N5   = "Reuse map references (verified during REUSE pre-pass):"
N6   = "repo_name is the explicit repo identity (added 2026-05-21 schema v2)"
N8   = "bugs bbff93a3 / 37a8beeb"
N13  = "extended by Rachel 🕊️"

COMMIT_BODY = f"""Rewrite the git_loc_delta docstrings

History kept here:
{N5.upper()}
`repo_name` is the explicit repo identity (added 2026-05-21
schema v2)
Bugs bbff93a3 /
37a8beeb were the trigger.
"""

DESIGN_DOC = f"# Design\n\nNotes: {N13}\n"

NORMAL_KEYS = { "sort", "worksheet", "destinations", "labels", "history_claims", "found", "missing", "rows", "design_lines", "refused", "message", "pass" }


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "docs" ).mkdir()
    ( tmp_path / "docs" / "design.md" ).write_text( DESIGN_DOC, encoding="utf-8" )
    ( tmp_path / "pkg" ).mkdir()
    ( tmp_path / "pkg" / "__init__.py" ).write_text( '"""Package.\n\nDesign: docs/design.md\n"""\n', encoding="utf-8" )
    ( tmp_path / "pkg" / "mod.py" ).write_text( '"""Module.\n\nDesign: docs/gone.md\n"""\n', encoding="utf-8" )
    _git( tmp_path, "add", "." )
    ( tmp_path / "msg.txt" ).write_text( COMMIT_BODY, encoding="utf-8" )
    _git( tmp_path, "commit", "-q", "-F", "msg.txt" )
    return tmp_path


def _files( tmp_path, sort=REAL_SORT, worksheet=REAL_WORKSHEET ):
    sort_path = tmp_path / "sort.jsonl"
    sort_path.write_text( "\n".join( json.dumps( r, ensure_ascii=False ) for r in sort ) + "\n", encoding="utf-8" )
    sheet_path = tmp_path / "worksheet.json"
    sheet_path.write_text( json.dumps( worksheet, ensure_ascii=False ), encoding="utf-8" )
    return str( sort_path ), str( sheet_path )


def _run( repo, out, *extra, sort=REAL_SORT, worksheet=REAL_WORKSHEET ):
    sort_path, sheet_path = _files( out.parent if out.parent != repo else repo, sort, worksheet )
    stream = io.StringIO()
    code   = hd.main( [ "--repo-root", str( repo ), "--sort", sort_path, "--worksheet", sheet_path, "--out", str( out ), *extra ], stream )
    return code, stream.getvalue(), json.loads( ( out / hd.RESULT_NAME ).read_text( encoding="utf-8" ) )


def test_every_history_claim_found_across_a_commit_body_and_a_design_doc_passes( repo, tmp_path ):
    sha = _git( repo, "rev-parse", "HEAD" )
    code, text, result = _run( repo, tmp_path / "out", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ) )
    assert code == 0 and result[ "pass" ] is True and set( result ) == NORMAL_KEYS
    assert ( result[ "history_claims" ], result[ "found" ], result[ "missing" ] ) == ( 4, 4, 0 ) and result[ "refused" ] is None
    assert result[ "labels" ] == { "H": 4, "J": 1, "M": 0, "L": 0, "U": 0 }
    where = { r[ "n" ]: r[ "where" ] for r in result[ "rows" ] }
    assert where == { 5: [ f"commit:{sha}" ], 6: [ f"commit:{sha}" ], 8: [ f"commit:{sha}" ], 13: [ f"design:{repo}/docs/design.md" ] }
    assert result[ "destinations" ] == [ f"design:{repo}/docs/design.md", f"commit:{sha}" ]
    assert text == "PASS 4 of 4 history claims found\n"


def test_a_history_claim_with_no_destination_text_fails_names_itself_and_exits_1( repo, tmp_path ):
    code, text, result = _run( repo, tmp_path / "out", "--commit", "HEAD" )
    assert code == 1 and result[ "pass" ] is False and result[ "missing" ] == 1
    assert [ r[ "n" ] for r in result[ "rows" ] if not r[ "found" ] ] == [ 13 ]
    assert f"MISSING n 13 {REAL_WORKSHEET[ 4 ][ 'id' ]}: {N13}" in text and text.endswith( "FAIL 3 of 4 history claims found\n" )


def test_a_fragment_or_the_start_of_a_longer_token_does_not_count( repo, tmp_path ):
    ( repo / "msg2.txt" ).write_text( "Reuse map references\nbugs bbff93a3 / 37a8beeb9\nrepo_name is the explicit repo identity\n" + N13 + "\n", encoding="utf-8" )
    _git( repo, "commit", "-q", "--allow-empty", "-F", "msg2.txt" )
    code, _, result = _run( repo, tmp_path / "out", "--commit", "HEAD" )
    assert code == 1 and result[ "found" ] == 1 and [ r[ "n" ] for r in result[ "rows" ] if r[ "found" ] ] == [ 13 ]


def test_zero_history_claims_is_a_pass_that_says_so_and_needs_no_destination( repo, tmp_path ):
    code, text, result = _run( repo, tmp_path / "out", sort=[ REAL_SORT[ 3 ] ], worksheet=[ REAL_WORKSHEET[ 3 ] ] )
    assert code == 0 and result[ "pass" ] is True and result[ "history_claims" ] == 0 and result[ "rows" ] == []
    assert result[ "message" ] == "history_claims: 0, nothing to check" and text == "PASS history_claims: 0, nothing to check\n"


def test_a_sort_row_that_carries_id_and_old_quote_overrides_the_worksheet( repo, tmp_path ):
    sort = [ { "n": 99, "class": "H", "id": "x.py::f#0", "old_quote": "history kept here" } ]
    code, _, result = _run( repo, tmp_path / "out", "--commit", "HEAD", sort=sort, worksheet=[] )
    assert code == 0 and result[ "rows" ][ 0 ][ "id" ] == "x.py::f#0" and result[ "rows" ][ 0 ][ "found" ] is True


def test_the_design_lines_of_a_package_are_a_second_check( repo, tmp_path ):
    for rel in ( "pkg/sub/deep.py", "pkg_other/x.py" ):
        ( repo / rel ).parent.mkdir( exist_ok=True )
        ( repo / rel ).write_text( '"""Other.\n\nDesign: docs/gone.md\n"""\n', encoding="utf-8" )
    _git( repo, "add", "." )
    code, text, result = _run( repo, tmp_path / "out", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ), "--package", "pkg/" )
    assert code == 1 and result[ "design_lines" ][ "checked" ] is True and result[ "missing" ] == 0 and result[ "pass" ] is False
    assert result[ "design_lines" ][ "dead" ] == [ "pkg/mod.py:3: Design path 'docs/gone.md' does not exist" ]
    assert "DEAD DESIGN pkg/mod.py:3: Design path 'docs/gone.md' does not exist" in text
    ( repo / "pkg" / "mod.py" ).write_text( '"""Module."""\n', encoding="utf-8" )
    code, _, result = _run( repo, tmp_path / "out2", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ), "--package", "pkg" )
    assert code == 0 and result[ "design_lines" ] == { "checked": True, "dead": [], "not_checked": [] }
    code, _, result = _run( repo, tmp_path / "out3", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ) )
    assert result[ "design_lines" ] == { "checked": False, "dead": [], "not_checked": [] }


def test_a_foreign_design_line_in_a_package_is_listed_as_not_checked_and_does_not_fail( repo, tmp_path ):
    ( repo / "pkg" ).mkdir( exist_ok=True )
    ( repo / "pkg" / "mod.py" ).write_text( '"""Mod.\n\nDesign: /mnt/DATA01/x/y.md\n"""\n', encoding="utf-8" )
    _git( repo, "add", "." )
    code, text, result = _run( repo, tmp_path / "out", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ), "--package", "pkg" )
    assert code == 0 and result[ "design_lines" ][ "dead" ] == []
    assert result[ "design_lines" ][ "not_checked" ] == [ "pkg/mod.py:3: Design path '/mnt/DATA01/x/y.md' is outside the tree" ]
    assert "Design paths not checked: 1\n" in text and text.endswith( "history claims found\n" )


@pytest.mark.parametrize( "sort_text, worksheet, extra, message", [
    ( None, REAL_WORKSHEET, [], "FileNotFoundError" ),
    ( "not json\n", REAL_WORKSHEET, [], "line 1 is not JSON" ),
    ( "[1]\n", REAL_WORKSHEET, [], "line 1 needs an integer n and a class" ),
    ( "{\"n\": 1}\n", REAL_WORKSHEET, [], "line 1 needs an integer n and a class" ),
    ( "{\"n\": \"1\", \"class\": \"H\"}\n", REAL_WORKSHEET, [], "line 1 needs an integer n and a class" ),
    ( "{\"n\": 1, \"class\": \"H\"}\n", {}, [], "must hold a JSON list of dicts" ),
    ( "{\"n\": 1, \"class\": \"X\"}\n", REAL_WORKSHEET, [], "class 'X' is not one of H J M L U" ),
    ( "{\"n\": 1, \"class\": \"H\"}\n{\"n\": 1, \"class\": \"J\"}\n", REAL_WORKSHEET, [], "line 2: n 1 appears twice" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", { "n": 5 }, [], "must hold a JSON list of dicts" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ 1 ], [], "must hold a JSON list of dicts" ),
    ( "", [ REAL_WORKSHEET[ 0 ], REAL_WORKSHEET[ 1 ] ], [], "the sort lacks claims of" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", REAL_WORKSHEET, [], "the sort lacks claims of" ),
    ( "{\"n\": 5, \"class\": \"H\", \"old_quote\": [\"a\"]}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--commit", "HEAD" ], "old_quote must be a string" ),
    ( "{\"n\": 5, \"class\": \"H\", \"id\": 5}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--commit", "HEAD" ], "id must be a string" ),
    ( "{\"n\": 5, \"class\": \"H\", \"quote\": 3}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--commit", "HEAD" ], "quote must be a string" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ { "n": 5, "id": "a", "quote": 123 } ], [ "--commit", "HEAD" ], "claim n 5: quote must be a string" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ { "n": 5, "id": 7, "quote": "q" } ], [ "--commit", "HEAD" ], "claim n 5: id must be a string" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ { "n": "5" } ], [], "must hold a JSON list of dicts" ),
    ( "{\"n\": 7, \"class\": \"H\"}\n", [], [ "--commit", "HEAD" ], "history claim n 7 has no quote" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ { "n": 5, "id": "a", "quote": "  `` " } ], [ "--commit", "HEAD" ], "history claim n 5 has no quote" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ REAL_WORKSHEET[ 0 ] ], [], "no destination" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--commit", "no-such-rev" ], "git log no-such-rev failed" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--design", "/no/such/design.md" ], "FileNotFoundError" ),
    ( "{\"n\": 5, \"class\": \"H\"}\n", [ REAL_WORKSHEET[ 0 ] ], [ "--commit", "HEAD", "--package", "pkg" ], None ),
] )
def test_a_refusal_writes_a_full_result_and_exits_2( repo, tmp_path, sort_text, worksheet, extra, message ):
    sort_path  = tmp_path / "sort.jsonl"
    sheet_path = tmp_path / "worksheet.json"
    if sort_text is not None: sort_path.write_text( sort_text, encoding="utf-8" )
    sheet_path.write_text( json.dumps( worksheet ), encoding="utf-8" )
    if message is None:
        ( repo / "pkg" / "mod.py" ).write_text( "def (:\n", encoding="utf-8" )
        message = "SyntaxError"
    stream = io.StringIO()
    code   = hd.main( [ "--repo-root", str( repo ), "--sort", str( sort_path ), "--worksheet", str( sheet_path ), "--out", str( tmp_path / "out" ), *extra ], stream )
    result = json.loads( ( tmp_path / "out" / hd.RESULT_NAME ).read_text( encoding="utf-8" ) )
    assert code == 2 and set( result ) == NORMAL_KEYS and result[ "pass" ] is False and message in result[ "refused" ]
    assert ( result[ "history_claims" ], result[ "found" ], result[ "missing" ], result[ "rows" ] ) == ( 0, 0, 0, [] )
    assert stream.getvalue() == f"REFUSED: {result[ 'refused' ]}\n" and result[ "message" ] == result[ "refused" ]


def test_normalize_folds_case_wraps_and_backticks_and_quote_found_needs_the_whole_quote():
    assert hd.normalize( "  A `Quote`\n   WRAPPED\tHere " ) == "a quote wrapped here"
    assert hd.quote_found( "a quote wrapped", "x A\n`quote` Wrapped here" ) is True
    assert hd.quote_found( "quote wrap", "a quote wrapped" ) is False and hd.quote_found( "uote wrapped", "a quote wrapped" ) is False
    assert hd.quote_found( "``", "anything" ) is False and hd.quote_found( "", "anything" ) is False
    assert hd.quote_found( "foo", "foo_bar" ) is False and hd.quote_found( "bar", "foo_bar" ) is False and hd.quote_found( "_x", "a_x" ) is False and hd.quote_found( "_x", "a _x b" ) is True
    assert hd.quote_found( "foo_", "foo_bar" ) is False and hd.quote_found( "foo_", "a foo_ b" ) is True
    assert hd.quote_found( "(a)", "x(a) y" ) is True and hd.quote_found( "(a)", "see (a)b" ) is True and hd.quote_found( "end.", "the end.5" ) is True


def test_blank_lines_in_the_sort_are_skipped( tmp_path ):
    path = tmp_path / "s.jsonl"
    path.write_text( '\n{"n": 1, "class": "H"}\n   \n', encoding="utf-8" )
    assert hd.load_sort( str( path ) ) == [ { "n": 1, "class": "H" } ]


def test_main_defaults_to_stdout_and_sys_argv( repo, tmp_path, monkeypatch, capsys ):
    sort_path, sheet_path = _files( tmp_path )
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( repo ), "--sort", sort_path, "--worksheet", sheet_path, "--out", str( tmp_path / "o" / "deeper" ), "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ) ] )
    assert hd.main() == 0
    assert capsys.readouterr().out == "PASS 4 of 4 history claims found\n" and ( tmp_path / "o" / "deeper" / hd.RESULT_NAME ).exists()


def test_two_commits_are_two_destinations_and_an_older_commit_is_read_by_its_own_body( repo, tmp_path ):
    old = _git( repo, "rev-parse", "HEAD" )
    ( repo / "msg3.txt" ).write_text( "Unrelated second commit\n", encoding="utf-8" )
    _git( repo, "commit", "-q", "--allow-empty", "-F", "msg3.txt" )
    code, _, result = _run( repo, tmp_path / "out", "--commit", "HEAD", "--commit", old, "--design", str( repo / "docs" / "design.md" ) )
    assert code == 0 and [ d for d in result[ "destinations" ] if d.startswith( "commit:" ) ][ 1 ] == f"commit:{old}"
    code, _, result = _run( repo, tmp_path / "out2", "--commit", "HEAD", "--design", str( repo / "docs" / "design.md" ) )
    assert code == 1 and result[ "missing" ] == 3


def test_a_relative_design_path_is_read_from_the_repo_root_not_the_current_directory( repo, tmp_path, monkeypatch ):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir( elsewhere )
    code, _, result = _run( repo, tmp_path / "out", "--commit", "HEAD", "--design", "docs/design.md" )
    assert code == 0 and result[ "destinations" ][ 0 ] == "design:docs/design.md"


def test_the_commit_sha_line_is_not_part_of_the_commit_text( repo, tmp_path ):
    sha = _git( repo, "rev-parse", "HEAD" )
    code, _, result = _run( repo, tmp_path / "out", "--commit", "HEAD", sort=[ { "n": 1, "class": "H" } ], worksheet=[ { "n": 1, "id": "x", "quote": sha } ] )
    assert code == 1 and result[ "missing" ] == 1


def test_any_exception_inside_the_check_becomes_a_refusal_with_a_full_result( repo, tmp_path, monkeypatch ):
    def boom( text ): raise KeyError( "odd" )
    monkeypatch.setattr( hd, "normalize", boom )
    sort_path, sheet_path = _files( tmp_path )
    code = hd.main( [ "--repo-root", str( repo ), "--sort", sort_path, "--worksheet", sheet_path, "--out", str( tmp_path / "out" ), "--commit", "HEAD" ], io.StringIO() )
    result = json.loads( ( tmp_path / "out" / hd.RESULT_NAME ).read_text( encoding="utf-8" ) )
    assert code == 2 and set( result ) == NORMAL_KEYS and result[ "refused" ] == "KeyError: 'odd'"
