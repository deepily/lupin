"""
The stylelint merge gate (row d3d4a18c, Rick's ruling 2026-09-18 21:06) — both directions.

A gate that has only ever been seen to pass proves nothing, so the revert arm is a test
here rather than a one-off measurement: each case copies `run-stylelint-gate.sh` into a
throwaway git repo (the script derives its root from its own location), gives it the
real `.stylelintrc.json` and a borrowed `node_modules`, and drives one state.

Requires: node_modules with stylelint at the project root (the unit tier already needs it
for the TypeScript tooling); the cases skip, naming why, when it is absent.
"""

import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
GATE         = os.path.join( PROJECT_ROOT, "src", "tests", "run-stylelint-gate.sh" )
CONFIG       = os.path.join( PROJECT_ROOT, ".stylelintrc.json" )
NODE_MODULES = os.path.join( PROJECT_ROOT, "node_modules" )

pytestmark = pytest.mark.skipif(
    not os.access( os.path.join( NODE_MODULES, ".bin", "stylelint" ), os.X_OK ),
    reason="no node_modules/.bin/stylelint at the project root — the gate cannot be driven",
)

CLEAN_CSS = ".pane {\n    color: #fff;\n}\n"


def _git( repo, *args ):
    subprocess.run( [ "git", *args ], cwd=repo, check=True, timeout=60,
                    capture_output=True, text=True )


@pytest.fixture
def repo( tmp_path ):
    """
    A git repo shaped like the project root: the gate at src/tests/, the real config,
    node_modules borrowed by symlink, and one tracked clean .css file.

    Ensures:
        - returns the repo path; `css/a.css` is tracked and clean
    """
    os.makedirs( tmp_path / "src" / "tests" )
    shutil.copy2( GATE, tmp_path / "src" / "tests" / "run-stylelint-gate.sh" )
    shutil.copy2( CONFIG, tmp_path / ".stylelintrc.json" )
    os.symlink( NODE_MODULES, tmp_path / "node_modules" )
    os.makedirs( tmp_path / "css" )
    ( tmp_path / "css" / "a.css" ).write_text( CLEAN_CSS )
    _git( tmp_path, "init", "-q" )
    _git( tmp_path, "add", "css/a.css" )
    return tmp_path


def _run( repo ):
    done = subprocess.run( [ "bash", str( repo / "src" / "tests" / "run-stylelint-gate.sh" ) ],
                           cwd=repo, capture_output=True, text=True, timeout=120 )
    return done.returncode, done.stdout


def test_a_clean_tree_passes_and_counts_files( repo ):
    rc, out = _run( repo )
    assert rc == 0, out
    assert "Total Tests: 1\nPassed: 1\nFailed: 0\nErrors: 0" in out


def test_one_planted_error_fails_the_gate_and_names_its_line( repo ):
    ( repo / "css" / "a.css" ).write_text( CLEAN_CSS + ".planted {\n    color: #ffffff;\n}\n" )
    rc, out = _run( repo )
    assert rc == 1, out
    assert "css/a.css:5:12" in out and "color-hex-length" in out
    assert "Failed: 1\nErrors: 1" in out


def test_a_waiver_without_a_reason_fails_the_gate( repo ):
    ( repo / "css" / "a.css" ).write_text(
        CLEAN_CSS + "/* stylelint-disable-next-line color-hex-length */\n.planted {\n    color: #ffffff;\n}\n" )
    rc, out = _run( repo )
    assert rc == 1, out
    assert "is missing a description" in out


def test_a_waiver_with_a_reason_passes( repo ):
    ( repo / "css" / "a.css" ).write_text(
        CLEAN_CSS + ".planted {\n    /* stylelint-disable-next-line color-hex-length -- a test fixture */\n    color: #ffffff;\n}\n" )
    rc, out = _run( repo )
    assert rc == 0, out


def test_the_population_is_git_tracked_files_only( repo ):
    # An UNTRACKED bad file is outside the tree under review, so it must not fail the
    # gate — and the tracked count must not move.
    ( repo / "css" / "untracked.css" ).write_text( ".x {\n    color: #ffffff;\n}\n" )
    rc, out = _run( repo )
    assert rc == 0, out
    assert "Total Tests: 1\n" in out


def test_no_tracked_css_refuses_rather_than_passing( repo ):
    _git( repo, "rm", "-q", "--cached", "css/a.css" )
    rc, out = _run( repo )
    assert rc == 2, out
    assert out.startswith( "REFUSING:" ) and "Total Tests" not in out


def test_a_missing_config_refuses_rather_than_passing( repo ):
    os.remove( repo / ".stylelintrc.json" )
    rc, out = _run( repo )
    assert rc == 2, out
    assert "Total Tests" not in out


def test_a_missing_stylelint_refuses_rather_than_passing( repo ):
    os.remove( repo / "node_modules" )
    rc, out = _run( repo )
    assert rc == 2, out
    assert "no stylelint" in out and "Total Tests" not in out
