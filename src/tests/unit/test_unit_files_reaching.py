"""
Unit tests for the git-based list of unit test files that reach a module.

Each case builds a real git repository, because the thing under test is what `git grep` and
`git diff --cached` report. The repository holds a .ts test beside the .py tests.
"""
import io
import subprocess

import pytest

from tests.helpers import unit_files_reaching as ufr


def _git( root, *args ):
    """Run one git command in a test repository and return the finished process."""
    return subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, check=True )


@pytest.fixture
def repo( tmp_path ):
    """
    A real repository: tracked unit tests in the two default folders, and a .ts test.

    Ensures:
        - src/tests/unit holds test_a.py and test_b.py (both name full_answer) and notes.test.ts (names it too)
        - src/cosa/tests/unit holds test_c.py, which names context_baseline only
        - everything is committed
    """
    for rel, text in ( ( "src/tests/unit/test_a.py", "import full_answer\n" ),
                       ( "src/tests/unit/test_b.py", "# full_answer again\n" ),
                       ( "src/tests/unit/notes.test.ts", "// full_answer in a TypeScript test\n" ),
                       ( "src/cosa/tests/unit/test_c.py", "import context_baseline\n" ),
                       ( "src/tests/unit/test_d.py", "import something_else\n" ) ):
        path = tmp_path / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text )
    _git( tmp_path, "init", "-q" )
    _git( tmp_path, "config", "user.email", "t@t.t" )
    _git( tmp_path, "config", "user.name", "t" )
    _git( tmp_path, "add", "-A" )
    _git( tmp_path, "commit", "-qm", "init" )
    return tmp_path


def test_a_ts_file_that_names_the_term_is_left_out_of_the_list( repo ):
    hit = subprocess.run( [ "git", "-C", str( repo ), "grep", "-l", "-F", "-e", "full_answer", "--", "src/tests/unit" ], capture_output=True, text=True ).stdout
    assert "src/tests/unit/notes.test.ts" in hit.split( "\n" )
    assert ufr.unit_files_reaching( [ "full_answer" ], repo ) == [ "src/tests/unit/test_a.py", "src/tests/unit/test_b.py" ]


def test_every_term_counts_and_both_default_folders_are_searched( repo ):
    assert ufr.unit_files_reaching( [ "full_answer", "context_baseline" ], repo ) == [ "src/cosa/tests/unit/test_c.py", "src/tests/unit/test_a.py", "src/tests/unit/test_b.py" ]


def test_a_term_found_nowhere_gives_an_empty_list( repo ):
    assert ufr.unit_files_reaching( [ "no_such_module" ], repo ) == []


def test_a_staged_py_file_joins_the_list_and_a_staged_ts_file_does_not( repo ):
    ( repo / "src/tests/unit/test_new.py" ).write_text( "x = 1\n" )
    ( repo / "src/tests/unit/new.test.ts" ).write_text( "const x = 1\n" )
    _git( repo, "add", "src/tests/unit/test_new.py", "src/tests/unit/new.test.ts" )
    assert ufr.unit_files_reaching( [ "context_baseline" ], repo ) == [ "src/cosa/tests/unit/test_c.py", "src/tests/unit/test_new.py" ]
    assert ufr.unit_files_reaching( [ "context_baseline" ], repo, include_staged=False ) == [ "src/cosa/tests/unit/test_c.py" ]


def test_a_py_file_staged_for_deletion_is_left_out_even_when_it_held_the_term( repo ):
    _git( repo, "rm", "-q", "src/tests/unit/test_a.py" )
    assert not ( repo / "src/tests/unit/test_a.py" ).exists()
    assert ufr.unit_files_reaching( [ "full_answer" ], repo ) == [ "src/tests/unit/test_b.py" ]
    assert ufr.unit_files_reaching( [ "no_such_module" ], repo ) == []


def test_a_term_with_a_dot_is_a_fixed_string_not_a_pattern( repo ):
    ( repo / "src/tests/unit/test_dot.py" ).write_text( "import coXsa\n" )
    _git( repo, "add", "src/tests/unit/test_dot.py" )
    _git( repo, "commit", "-qm", "dot" )
    assert ufr.unit_files_reaching( [ "co.sa" ], repo ) == []
    ( repo / "src/tests/unit/test_dot.py" ).write_text( "import co.sa\n" )
    assert ufr.unit_files_reaching( [ "co.sa" ], repo ) == [ "src/tests/unit/test_dot.py" ]


def test_the_pathspecs_decide_where_to_search( repo ):
    assert ufr.unit_files_reaching( [ "context_baseline", "full_answer" ], repo, pathspecs=( "src/cosa/tests/unit", ) ) == [ "src/cosa/tests/unit/test_c.py" ]


def test_no_terms_is_refused( repo ):
    with pytest.raises( ValueError, match="at least one term" ):
        ufr.unit_files_reaching( [], repo )


def test_a_git_failure_is_raised_with_the_command_named( tmp_path ):
    with pytest.raises( RuntimeError, match="git grep" ):
        ufr.unit_files_reaching( [ "x" ], tmp_path / "not_a_repo" )


def test_main_prints_one_path_per_line_and_returns_zero( repo ):
    out = io.StringIO()
    assert ufr.main( [ "full_answer" ], out=out, root=repo ) == 0
    assert out.getvalue().split( "\n" ) == [ "src/tests/unit/test_a.py", "src/tests/unit/test_b.py", "" ]


def test_main_with_no_terms_returns_two_and_prints_nothing( repo, monkeypatch ):
    out = io.StringIO()
    monkeypatch.setattr( ufr.sys, "argv", [ "unit_files_reaching" ] )
    assert ufr.main( out=out, root=repo ) == 2 and out.getvalue() == ""


def test_main_reads_the_command_line_when_given_no_argv( repo, monkeypatch ):
    out = io.StringIO()
    monkeypatch.setattr( ufr.sys, "argv", [ "unit_files_reaching", "context_baseline" ] )
    assert ufr.main( out=out, root=repo ) == 0 and out.getvalue() == "src/cosa/tests/unit/test_c.py\n"
