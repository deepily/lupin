"""
The runner script of the reuse gate, driven in a scratch git tree.

The script is what the merge pyramid calls. These tests pin its exit codes: 0 clean or report only,
1 refused, 3 could not check. A run that could not check prints no summary block.
The test-suite job reads a block as a result and no block as not executed.
Every data folder and configuration file is temporary; nothing calls a model.
"""
import os
import shutil
import subprocess
import tempfile

import pytest

import cosa.utils.util as cu
from tests.unit.test_reuse_refusals import GOOD, NOT_IN_LOG, RULINGS, SID, REAL_LOG, REAL_RECORD

PROJECT_ROOT = cu.get_project_root()
GATE         = os.path.join( PROJECT_ROOT, "src", "tests", "run-reuse-gate.sh" )
RESOLVER     = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "resolve-venv-pytest.sh" )
VENV         = os.path.join( PROJECT_ROOT, ".venv" )
LINKED       = ( "cosa", "lupin_mcp", "lupin_cli", "conf" )                    # the packages the gate imports, linked from the real tree; conf holds the registry of repos the gate reads call logs from

# No skip when this tree has no .venv: the resolver also accepts the container interpreter, and a
# tree with neither fails these tests by name. The venv guard lists this file as one that breaks.


def _scratch_env( base=None ):
    """
    Return an environment in which git sees only the scratch tree.

    Ensures:
        - every GIT_ variable is dropped: a GIT_DIR left in the caller's environment, as a git hook leaves one, would send `git init` and `git commit` into the enclosing repo
          (measured 18 Nov 2026: the shared .git/config got core.bare = true and a seat's HEAD became the scratch commit "base")
        - GIT_CEILING_DIRECTORIES stops a search upward from the scratch tree at the temporary folder's parent
    """
    env = { k: v for k, v in ( base if base is not None else os.environ ).items() if not k.startswith( "GIT_" ) }
    env[ "GIT_CEILING_DIRECTORIES" ] = tempfile.gettempdir()
    return env


def _git( repo, *args ):
    subprocess.run( [ "git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args ], cwd=repo, check=True, timeout=60, capture_output=True, env=_scratch_env() )


@pytest.fixture
def repo( tmp_path ):
    """Ensures: a scratch tree on branch feat with the real runner and resolver."""
    root = tmp_path / "tree"
    ( root / "src" / "tests" ).mkdir( parents=True )
    ( root / "src" / "scripts" / "lib" ).mkdir( parents=True )
    shutil.copy( GATE, root / "src" / "tests" / "run-reuse-gate.sh" )
    shutil.copy( RESOLVER, root / "src" / "scripts" / "lib" / "resolve-venv-pytest.sh" )
    for name in LINKED: os.symlink( os.path.join( PROJECT_ROOT, "src", name ), root / "src" / name )
    if os.path.isdir( VENV ): os.symlink( VENV, root / ".venv" )
    _git( root, "init", "-q", "-b", "main" )
    ( root / "README.md" ).write_text( "# tree\n", encoding="utf-8" )
    _git( root, "add", "README.md" )
    _git( root, "commit", "-qm", "base" )
    _git( root, "checkout", "-q", "-b", "feat" )
    return root


@pytest.fixture
def env( tmp_path, repo ):
    """Ensures: an environment naming a call log folder and an ini with gating on, since set."""
    data = tmp_path / "data"
    ( data / "call-log" ).mkdir( parents=True )
    ( data / "call-log" / "real.jsonl" ).write_text( REAL_LOG.read_text( encoding="utf-8" ), encoding="utf-8" )
    ( data / "search-records" ).mkdir()
    ( data / "search-records" / f"{SID}.json" ).write_text( REAL_RECORD.read_text( encoding="utf-8" ), encoding="utf-8" )
    ini = tmp_path / "lupin-app.ini"
    since = subprocess.run( [ "git", "-C", str( repo ), "rev-parse", "main" ], capture_output=True, text=True, check=True, env=_scratch_env() ).stdout.strip()
    ini.write_text( f"[x]\nreuse review gating = true\nreuse merge gate since = {since}\nreuse searched since = {since}\n", encoding="utf-8" )
    return dict( _scratch_env(), LUPIN_REUSE_DATA_DIR=str( data ), LUPIN_REUSE_REVIEW_INI=str( ini ) )


def _commit_doc( repo, *lines ):
    ( repo / "review.md" ).write_text( "# review\n\n" + RULINGS + "\n" + "\n".join( f"SEARCHED {sym} :: {SID} :: none :: nothing near it" for sym in ( "lupin_mcp.new_helper", "m.q" ) ) + "\n\n" + "\n".join( lines ) + "\n", encoding="utf-8" )
    _git( repo, "add", "review.md" )
    _git( repo, "commit", "-qm", "review" )


def _run( repo, env, *args ):
    done = subprocess.run( [ "bash", str( repo / "src" / "tests" / "run-reuse-gate.sh" ), *args ], capture_output=True, text=True, timeout=120, env=env )
    return done.returncode, done.stdout + done.stderr


def test_a_branch_whose_outcome_line_holds_up_exits_zero_with_one_summary_block( repo, env ):
    _commit_doc( repo, GOOD )
    code, text = _run( repo, env )
    assert code == 0 and "Total Tests: 2\nPassed: 2\nFailed: 0\nErrors: 0\n" in text
    assert text.count( "Total Tests:" ) == 1 and text.rstrip( "\n" ).split( "\n" )[ -1 ].startswith( "REUSE GATE PASSED:" )


def test_a_refused_line_exits_one_and_names_the_line( repo, env ):
    _commit_doc( repo, GOOD, NOT_IN_LOG )
    code, text = _run( repo, env )
    assert code == 1 and "REFUSED review.md line" in text and NOT_IN_LOG in text and "Failed: 1" in text


def test_arguments_reach_the_gate( repo, env ):
    _commit_doc( repo, NOT_IN_LOG )
    code, text = _run( repo, env, "--base", "feat" )
    assert code == 0 and "Total Tests: 1\n" in text, "measured from the branch itself nothing is added"


def test_an_unreadable_key_exits_three_and_prints_no_summary( repo, env, tmp_path ):
    _commit_doc( repo, GOOD )
    ( tmp_path / "lupin-app.ini" ).write_text( "[x]\nreuse review gating = maybe\n", encoding="utf-8" )
    code, text = _run( repo, env )
    assert code == 3 and "Nothing was checked." in text and "Total Tests" not in text and "PASSED" not in text


def test_a_tree_with_no_main_exits_three_and_prints_no_summary( repo, env ):
    _git( repo, "branch", "-q", "-m", "main", "trunk" )
    code, text = _run( repo, env )
    assert code == 3 and "git names no merge base" in text and "Total Tests" not in text


def test_a_module_that_does_not_import_is_refused_not_passed( repo, env ):
    os.unlink( repo / "src" / "lupin_mcp" )
    code, text = _run( repo, env )
    assert code == 3 and "REFUSING: lupin_mcp.reuse_merge_gate does not import" in text and "Total Tests" not in text


def test_a_crash_is_not_read_as_a_gate_result( repo, env ):
    os.unlink( repo / "src" / "lupin_mcp" )
    ( repo / "src" / "lupin_mcp" ).mkdir()
    ( repo / "src" / "lupin_mcp" / "__init__.py" ).write_text( "", encoding="utf-8" )
    ( repo / "src" / "lupin_mcp" / "reuse_merge_gate.py" ).write_text( "import sys\nif __name__ == '__main__': sys.exit( 7 )\n", encoding="utf-8" )
    code, text = _run( repo, env )
    assert code == 3 and "REFUSING: the gate exited 7, which is not a gate result. Nothing was checked." in text


def test_gating_on_with_an_empty_since_exits_three_and_prints_no_summary( repo, env, tmp_path ):
    _commit_doc( repo, GOOD )
    ( tmp_path / "lupin-app.ini" ).write_text( "[x]\nreuse review gating = true\nreuse merge gate since =\n", encoding="utf-8" )
    code, text = _run( repo, env )
    assert code == 3 and "is true and `reuse merge gate since` is empty" in text and "Total Tests" not in text


def _start_merge( repo ):
    """Ensures: the tree is mid-merge, a side file staged and no merge commit written."""
    _git( repo, "checkout", "-q", "-b", "side", "main" )
    ( repo / "side.txt" ).write_text( "side\n", encoding="utf-8" )
    _git( repo, "add", "side.txt" )
    _git( repo, "commit", "-qm", "side" )
    _git( repo, "checkout", "-q", "feat" )
    _git( repo, "merge", "-q", "--no-commit", "--no-ff", "side" )


def test_a_tree_mid_merge_exits_three_names_the_merge_and_prints_no_summary( repo, env ):
    _commit_doc( repo, GOOD )
    _start_merge( repo )
    code, text = _run( repo, env )
    assert code == 3 and "uncommitted merge" in text and "Nothing was checked" in text and "Total Tests:" not in text


def test_the_same_tree_passes_again_once_the_merge_is_aborted( repo, env ):
    _commit_doc( repo, GOOD )
    _start_merge( repo )
    _git( repo, "merge", "--abort" )
    code, text = _run( repo, env )
    assert code == 0 and "Passed: 2" in text


def test_a_linked_worktree_mid_merge_is_refused_too( repo, env, tmp_path ):
    _commit_doc( repo, GOOD )
    _git( repo, "checkout", "-q", "-b", "side", "main" )
    ( repo / "side.txt" ).write_text( "side\n", encoding="utf-8" )
    _git( repo, "add", "side.txt" )
    _git( repo, "commit", "-qm", "side" )
    _git( repo, "checkout", "-q", "feat" )
    linked = tmp_path / "linked"
    _git( repo, "worktree", "add", "-q", "-b", "lane", str( linked ), "feat" )
    shutil.copytree( repo / "src", linked / "src", symlinks=True, dirs_exist_ok=True )
    if os.path.isdir( VENV ): os.symlink( VENV, linked / ".venv" )
    _git( linked, "merge", "-q", "--no-commit", "--no-ff", "side" )
    code, text = _run( linked, env )
    assert code == 3 and "uncommitted merge" in text


def test_a_git_dir_left_in_the_environment_never_reaches_the_enclosing_repo( tmp_path, monkeypatch ):
    """A GIT_DIR in the environment never reaches the enclosing repo."""
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    _git( decoy, "init", "-q", "-b", "main" )
    _git( decoy, "commit", "-q", "--allow-empty", "-m", "real" )
    _git( decoy, "worktree", "add", "-q", "--detach", str( tmp_path / "decoy-wt" ), "HEAD" )
    wt_dir = subprocess.run( [ "git", "-C", str( tmp_path / "decoy-wt" ), "rev-parse", "--absolute-git-dir" ], capture_output=True, text=True, check=True, env=_scratch_env() ).stdout.strip()
    head   = lambda where: subprocess.run( [ "git", "-C", str( where ), "log", "--format=%H %s" ], capture_output=True, text=True, check=True, env=_scratch_env() ).stdout
    bare   = lambda: subprocess.run( [ "git", "-C", str( decoy ), "config", "core.bare" ], capture_output=True, text=True, env=_scratch_env() ).stdout.strip()
    before = ( head( tmp_path / "decoy-wt" ), bare() )
    assert before[ 1 ] == "false" and before[ 0 ].count( "\n" ) == 1
    monkeypatch.setenv( "GIT_DIR", wt_dir )
    other = tmp_path / "other"
    other.mkdir()
    _git( other, "init", "-q", "-b", "main" )
    ( other / "README.md" ).write_text( "# tree\n", encoding="utf-8" )
    _git( other, "add", "README.md" )
    _git( other, "commit", "-qm", "base" )
    assert ( head( tmp_path / "decoy-wt" ), bare() ) == before, "the scratch commands reached the decoy repo"
    assert ( other / ".git" ).is_dir() and "base" in head( other )
    assert "GIT_DIR" not in _scratch_env() and _scratch_env()[ "GIT_CEILING_DIRECTORIES" ] == tempfile.gettempdir()
