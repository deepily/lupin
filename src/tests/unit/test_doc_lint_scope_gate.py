"""
The whole-scope documentation gate: zero findings in every swept file, or a red exit.

Each test builds a scratch git tree and runs the gate's real entry point over it. The three exit
codes are pinned by name, because the merge pyramid reads 2 as not executed and 1 as failed.
"""

import io
import subprocess

import pytest

from cosa.repo.doc_lint import scope_gate, word_list

WORDS = [ "not", "never", "the" ]
CLEAN = '"""\nAdd two numbers.\n"""\n\n\ndef add( a, b ):\n    """\n    Return the sum of a and b.\n    """\n    return a + b\n'
LOUD  = '"""\nThis module is VERY IMPORTANT and must NEVER be changed.\n"""\n'


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _write( root, rel, text ):
    path = root / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    if isinstance( text, bytes ): path.write_bytes( text )
    else: path.write_text( text, encoding="utf-8" )


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    _write( tmp_path, "src/conf/dm-tutor-lowercase-words.txt", "\n".join( WORDS ) + "\n" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _run( root ):
    out  = io.StringIO()
    code = scope_gate.main( [ "--repo-root", str( root ) ], out=out )
    return code, out.getvalue()


def test_a_clean_scope_exits_zero_and_states_its_denominator( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/b.py", "x = 1\n" )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_CLEAN == 0
    assert "Docstrings checked: 2\n" in text
    assert "Total Tests: 2\nPassed: 2\nFailed: 0\nErrors: 0\n" in text
    assert text.endswith( "DOCLINT GATE PASSED: all 2 files clean.\n" )


def test_one_planted_finding_exits_one_and_names_the_file_line_and_rule( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_FINDINGS == 1
    assert "    src/app/loud.py:2: caps: ALL-CAPS word NEVER\n" in text
    assert "src/app/a.py:" not in text
    assert "Total Tests: 2\nPassed: 1\nFailed: 1\nErrors: 1\n" in text
    assert text.endswith( "DOCLINT GATE FAILED: 1 findings in 1 of 2 files.\n" )


def test_two_findings_in_one_file_count_as_one_failed_file_and_two_errors( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", '"""\nThis module must NEVER change.\n\nIt is NOT optional.\n"""\n' )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_FINDINGS
    assert "Total Tests: 2\nPassed: 1\nFailed: 1\nErrors: 2\n" in text
    assert text.endswith( "DOCLINT GATE FAILED: 2 findings in 1 of 2 files.\n" )


def test_a_finding_in_a_held_or_test_file_does_not_fail_the_gate( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/lupin_mcp/tool.py", LOUD )
    _write( repo, "src/tests/unit/test_loud.py", LOUD )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_CLEAN
    assert "Total Tests: 1\n" in text


def test_a_tree_with_no_swept_file_is_refused_not_passed( repo ):
    _write( repo, "src/lupin_mcp/tool.py", CLEAN )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_NOT_CHECKED == 2
    assert text.startswith( "REFUSING: no swept file found under " )
    assert "PASSED" not in text


def test_a_root_that_is_not_a_git_tree_is_refused( tmp_path ):
    code, text = _run( tmp_path )

    assert code == scope_gate.EXIT_NOT_CHECKED
    assert text.startswith( "REFUSING: the gate could not run. Nothing was checked. git ls-files failed" )
    word_list._state[ "root" ] = None


def test_a_missing_word_list_is_refused_not_read_as_clean( tmp_path ):
    _git( tmp_path, "init", "-q" )
    _write( tmp_path, "src/app/loud.py", LOUD )
    _git( tmp_path, "add", "src" )

    code, text = _run( tmp_path )

    assert code == scope_gate.EXIT_NOT_CHECKED
    assert text.startswith( "REFUSING: the gate could not run. Nothing was checked." )
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def test_a_file_that_is_not_utf8_is_a_finding_and_is_still_counted( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/binary.py", b"\xff\xfe\x00bad" )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_FINDINGS
    assert "    src/app/binary.py:1: unreadable: could not be read: " in text
    assert "Total Tests: 2\nPassed: 1\nFailed: 1\nErrors: 1\n" in text


def test_a_file_that_does_not_parse_is_a_finding_and_adds_no_docstrings( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/broken.py", "def (:\n" )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_FINDINGS
    assert "    src/app/broken.py:1: parse-error: " in text
    assert "Docstrings checked: 2\n" in text


def test_the_word_list_comes_from_the_words_root_not_from_the_tree_being_read( repo, tmp_path_factory ):
    other = tmp_path_factory.mktemp( "other" )
    _git( other, "init", "-q" )
    _write( other, "src/app/loud.py", LOUD )
    _write( other, "src/conf/dm-tutor-lowercase-words.txt", "" )
    _git( other, "add", "src" )

    with_own_list   = scope_gate.check( str( other ) )
    with_given_list = scope_gate.check( str( other ), str( repo ) )

    assert with_own_list[ "findings" ] == []
    assert [ f.rule for f in with_given_list[ "findings" ] ] == [ "caps" ]

    out  = io.StringIO()
    code = scope_gate.main( [ "--repo-root", str( other ), "--words-root", str( repo ) ], out=out )
    assert code == scope_gate.EXIT_FINDINGS


def test_check_returns_the_counts_and_the_findings( repo ):
    _write( repo, "src/app/a.py", CLEAN )
    _write( repo, "src/app/loud.py", LOUD )
    _git( repo, "add", "src" )

    result = scope_gate.check( str( repo ) )

    assert sorted( result ) == [ "docstrings", "files", "findings", "not_checked" ]
    assert result[ "not_checked" ] == []
    assert result[ "files" ] == 2 and result[ "docstrings" ] == 3
    assert { f.path for f in result[ "findings" ] } == { "src/app/loud.py" }


FOREIGN = '"""\nDo a thing.\n\nDesign: /mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/x.md\n"""\n'


def _gate_in_tree( tmp_path, name ):
    root = tmp_path / name
    root.mkdir( parents=True )
    _git( root, "init", "-q" )
    _write( root, "src/conf/dm-tutor-lowercase-words.txt", "\n".join( WORDS ) + "\n" )
    _write( root, "src/app/a.py", FOREIGN )
    _git( root, "add", "src" )
    return _run( root )


def test_a_foreign_design_path_gives_one_verdict_under_a_host_style_and_a_container_style_root( tmp_path ):
    host = _gate_in_tree( tmp_path, "mnt/lupin" )
    box  = _gate_in_tree( tmp_path, "var/lupin" )
    assert host == box
    assert host[ 0 ] == scope_gate.EXIT_CLEAN


def test_not_checked_paths_are_printed_and_counted_but_never_move_failed_or_errors( repo ):
    _write( repo, "src/app/a.py", FOREIGN )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_CLEAN
    assert "not checked: src/app/a.py:4: Design path '/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/x.md' is outside the tree\n" in text
    assert "Design paths not checked: 1\n" in text
    assert "Total Tests: 1\nPassed: 1\nFailed: 0\nErrors: 0\n" in text
    for key in ( "Total Tests:", "Passed:", "Failed:", "Not executed:" ):
        assert [ ln for ln in text.splitlines() if "not checked" in ln.lower() and key in ln ] == []


def test_an_in_root_dead_design_path_still_fails_the_gate( repo ):
    _write( repo, "src/app/a.py", FOREIGN.replace( "/mnt/DATA01/include/www.deepily.ai/projects/planning-is-prompting/src/rnd/x.md", "src/rnd/missing.md" ) )
    _git( repo, "add", "src" )

    code, text = _run( repo )

    assert code == scope_gate.EXIT_FINDINGS
    assert "dead-design" in text and "Failed: 1\nErrors: 1\n" in text
