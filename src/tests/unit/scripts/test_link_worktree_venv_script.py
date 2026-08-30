"""
Regression control for the SIGPIPE race in `src/scripts/link-worktree-venv.sh` (row f8f7d54b).

THE DEFECT. The script resolved the main repo with

    MAIN_REPO="$( git -C "$TARGET" worktree list --porcelain | awk '/^worktree /{print $2; exit}' )"

`awk` closes the pipe on its first match while `git` is still writing. git takes SIGPIPE,
and `set -euo pipefail` turns that into a silent exit 141 — before any of the script's own
messages, so a caller sees no output and no `.venv`, which reads exactly like "ran fine,
nothing to do". Measured on a box with 152 lines of worktree list: 17 of 30 runs died.

🔴 WHY THE SHAPE GUARD IS THE REAL CONTROL AND THE LOOP IS ONLY CORROBORATION.
The failure rate is a function of how much git still has to write when awk quits. On a
fresh clone with one worktree, the racing version passes every time — so the loop below
would be GREEN against the exact code this row exists to remove. A test that can only fail
on a crowded box is not a regression test; it is a weather report. The shape guard fails
identically in every tree, which is the property that makes it worth committing.
"""

import os
import re
import subprocess

import pytest

_ROOT   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_SCRIPT = os.path.join( _ROOT, "src", "scripts", "link-worktree-venv.sh" )


@pytest.fixture( scope="module" )
def source():
    assert os.path.exists( _SCRIPT ), f"the script under test is missing: {_SCRIPT}"
    with open( _SCRIPT ) as f:
        return f.read()


def _code_lines( source ):
    """The script minus comments — the fix's own explanation quotes the racing line verbatim."""
    return [ ln for ln in source.splitlines() if not ln.lstrip().startswith( "#" ) ]


class TestNoEarlyClosingPipe:

    def test_git_worktree_list_is_not_piped_into_an_early_closing_reader( self, source ):
        """
        THE CONTROL. Any reader that stops early — `awk ... exit`, `head -n`, `sed Nq` —
        re-opens the race, so the guard names the shape rather than the one spelling that
        was there. Reading git's whole output into a variable first is the shape that
        cannot race: there is no reader to close.
        """
        early_close = re.compile(
            r"git\b[^|\n]*worktree\s+list[^|\n]*\|\s*(?:awk[^|\n]*\bexit\b|head\b|sed\b[^|\n]*\d+q)"
        )
        offenders = [ ln.strip() for ln in _code_lines( source ) if early_close.search( ln ) ]
        assert not offenders, (
            "`git worktree list` is piped into a reader that closes early, which is the "
            "SIGPIPE race of row f8f7d54b:\n" + "\n".join( f"    {o}" for o in offenders )
            + "\nRead the whole output into a variable first, then match against it."
        )

    def test_the_script_still_runs_under_pipefail_so_the_hazard_would_still_bite( self, source ):
        """
        The guard above only matters while `pipefail` is set — without it a dead upstream
        is invisible and the shape is harmless. Pinning this means that if someone ever
        relaxes the shell options, the guard above is re-read rather than silently
        protecting against nothing.
        """
        assert any( ln.startswith( "set -" ) and "pipefail" in ln for ln in _code_lines( source ) )

    def test_the_resolution_reads_the_whole_list_before_matching( self, source ):
        """The positive half: the replacement shape is present, not merely the old one absent."""
        code = "\n".join( _code_lines( source ) )
        assert "WORKTREE_LIST=" in code
        assert '${line#worktree }' in code, (
            "the parameter-expansion spelling is also what preserves worktree paths containing "
            "spaces, which awk '{print $2}' truncated"
        )


class TestExitCodesInPractice:
    """
    Corroboration, not proof — see the module docstring. These runs can only catch the race
    on a tree whose `git worktree list` is long enough to still be writing.
    """

    def test_repeated_check_runs_never_die_of_sigpipe( self ):
        codes = []
        for _ in range( 25 ):
            r = subprocess.run( [ "bash", _SCRIPT, "--check" ], cwd=_ROOT,
                                capture_output=True, text=True )
            codes.append( r.returncode )

        # 141 = 128 + SIGPIPE. 0 (provisioned) and 1 (no .venv here) are both legitimate.
        assert 141 not in codes, f"SIGPIPE death is back: {codes}"
        assert set( codes ) <= { 0, 1 }, f"unexpected exit codes: {sorted( set( codes ) )}"

    def test_a_path_that_is_not_a_directory_is_refused_with_its_own_code( self ):
        """
        A negative control for the loop above: it proves these runs reach the script's own
        logic at all. Without it, a script that had been deleted or renamed would make the
        SIGPIPE assertion pass for the wrong reason.
        """
        r = subprocess.run( [ "bash", _SCRIPT, "/nonexistent/path/for/this/test" ],
                            cwd=_ROOT, capture_output=True, text=True )
        assert r.returncode == 2
        assert "not a directory" in r.stderr
