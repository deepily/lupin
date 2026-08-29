"""Guard: run-unit-tests.sh must FAIL LOUD when no venv pytest is found (row c98bce3f).

WHY THIS IS A COMMITTED GATE, not a one-off check. The runner used to silently fall back
to a bare `python3 -m pytest` when its expected venv pytest was absent. On 2026-08-16 that
silent interpreter switch ran the container's under-provisioned /opt/venv, aborted collection
of ~3000 tests, and the runner reported the REDUCED count as a pass — a false green on the
:8000 merge gate. The fix removed the fallback; this test pins that the fallback stays gone,
because an ungated fix to a runner can silently regress into the exact defect it removed.

⚠️ REWRITTEN 2026-08-24 (row fc74c1d4) — IT USED TO ASSERT WHERE THE CODE LIVED. The old
version string-replaced the literals `"$PROJECT_ROOT/.venv/bin/pytest"` and
`"/opt/venv/bin/pytest"` inside run-unit-tests.sh, because that is where they happened to
sit. Row fc74c1d4 moved the resolution into src/scripts/lib/resolve-venv-pytest.sh so that
eight other runners could share it, and this test went red — its replacements no longer
matched anything.

It went red the RIGHT way: the assert added as "guard the guard" fired, rather than the test
silently exercising an unpatched script that would then have found the real .venv and
reported a false pass. That is the behaviour worth keeping, and the reason this rewrite makes
the test independent of location rather than merely re-pointing it at the new file. The
proposition is "the runner refuses when no venv pytest exists" — which file implements the
looking is not part of it, and the next reorganisation should not break this again.

HOW IT IS INDEPENDENT NOW. The sandbox mirrors the repo layout under tmp_path: the runner is
copied to src/tests/, and every file it `source`s from $PROJECT_ROOT is copied to the same
relative place. The runner derives PROJECT_ROOT from its own location, so the copy resolves
its sources inside the sandbox with no path rewriting. The venv candidates are then patched
wherever they turn out to live, and the sandbox is asserted to contain no real venv path at
all — so a literal that moves somewhere unexpected fails loudly instead of leaving the test
pointed at the real interpreter.
"""

import os
import re
import shutil
import subprocess

import pytest


_PROJECT_ROOT = os.environ[ "LUPIN_ROOT" ]
_SCRIPT_REL   = "src/tests/run-unit-tests.sh"
_SCRIPT       = os.path.join( _PROJECT_ROOT, _SCRIPT_REL )

# Every real venv pytest path any layer may name. The sandbox must contain NONE of these
# afterwards — that is what makes "we actually staged a no-venv box" checkable rather than
# assumed.
_REAL_VENV_PATHS = ( ".venv/bin/pytest", "/opt/venv/bin/pytest" )

# `source "$PROJECT_ROOT/<rel>"` — the files a runner pulls in at run time.
_SOURCED_RE = re.compile( r'source\s+"\$(?:PROJECT_ROOT|LUPIN_ROOT)/([^"]+)"' )


def _sandbox( tmp_path ):
    """
    A runnable copy of the shipped runner whose venv candidates cannot resolve.

    Requires:
        - the shipped runner exists and derives PROJECT_ROOT from its own location

    Ensures:
        - the repo layout is mirrored under tmp_path, so the copied runner sources the
          COPIED libraries rather than the real ones — no path rewriting needed
        - every venv-pytest candidate is redirected to a nonexistent path, in WHICHEVER
          copied file carries it
        - raises rather than returning a sandbox that still names a real venv path: a
          sandbox that quietly kept one would find the developer's own .venv and report a
          false pass, which is the failure this file exists to prevent
        - returns the path to the copied runner
    """
    copied = {}

    def _copy( rel ):
        src = os.path.join( _PROJECT_ROOT, rel )
        assert os.path.isfile( src ), f"{rel} does not exist — the runner's layout changed"
        dst = tmp_path / rel
        dst.parent.mkdir( parents=True, exist_ok=True )
        shutil.copy2( src, dst )
        copied[ rel ] = dst
        # Follow this file's own `source` lines too, so a library that sources another
        # library is carried into the sandbox as well.
        for nested in _SOURCED_RE.findall( open( src, encoding="utf-8" ).read() ):
            if nested not in copied:
                _copy( nested )

    _copy( _SCRIPT_REL )

    # Redirect the candidates wherever they ended up living.
    patched_files = []
    for rel, dst in copied.items():
        text  = dst.read_text()
        fixed = ( text
                  .replace( ".venv/bin/pytest",     "nonexistent/host/pytest" )
                  .replace( "/opt/venv/bin/pytest", "/nonexistent/container/pytest" ) )
        if fixed != text:
            dst.write_text( fixed )
            patched_files.append( rel )

    assert patched_files, (
        "no copied file contained a venv pytest candidate — the runner no longer resolves an "
        "interpreter the way this test assumes, so it would exercise nothing. Files copied: "
        f"{sorted( copied )}"
    )

    # The sandbox must not be able to reach a REAL venv. Checked over every copied file, so
    # a candidate that moves to a layer this test did not anticipate fails here rather than
    # silently letting the runner find the developer's own .venv.
    for rel, dst in copied.items():
        body = dst.read_text()
        for real in _REAL_VENV_PATHS:
            assert real not in body, (
                f"{rel} in the sandbox still names {real} — the no-venv condition was not "
                f"actually staged and this test would pass by finding a real interpreter"
            )

    return str( copied[ _SCRIPT_REL ] )


def _run( tmp_path ):
    """Drive the sandboxed runner and return its CompletedProcess."""
    script = _sandbox( tmp_path )
    return subprocess.run(
        [ "bash", script ], capture_output=True, text=True, timeout=60,
        env=dict( os.environ, LUPIN_ROOT=str( tmp_path ) ),
    )


def test_the_sandbox_copies_more_than_the_runner_itself( tmp_path ):
    """
    The instrument before the reading. Since row fc74c1d4 the resolution lives in a sourced
    library, so a sandbox that copied only the runner would source the REAL library, find the
    REAL .venv, and this file would be testing nothing. Asserting the runner actually pulls
    something in keeps that failure visible.
    """
    _sandbox( tmp_path )                     # raises if the layout assumption broke
    sourced = _SOURCED_RE.findall( open( _SCRIPT, encoding="utf-8" ).read() )
    assert sourced, (
        "run-unit-tests.sh sources nothing from $PROJECT_ROOT — if the resolution moved back "
        "inline that is fine, but this sandbox's premise changed and should be re-read"
    )


def test_fails_loud_when_no_venv_pytest_is_found( tmp_path ):
    result   = _run( tmp_path )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, f"runner did NOT fail loud (exit {result.returncode}):\n{combined}"
    assert "no runnable venv pytest found" in result.stderr, result.stderr
    # It names BOTH paths it looked for, in the message.
    assert "nonexistent/host/pytest" in result.stderr, result.stderr
    assert "/nonexistent/container/pytest" in result.stderr, result.stderr
    # And it did NOT quietly execute a bare python3 fallback (the removed defect).
    assert "using pytest at" not in combined, "runner selected a pytest despite both candidates being absent"


def test_names_the_merge_gate_risk_in_its_refusal( tmp_path ):
    """The refusal explains WHY the fallback is refused — so the next reader does not re-add
    it as a convenience. Pins the rationale, not just the exit code."""
    result = _run( tmp_path )
    assert "python3 -m pytest" in result.stderr, "refusal should name the fallback it declines"
    assert "false green" in result.stderr.lower(), result.stderr


def test_the_refusal_uses_the_exit_code_callers_and_logs_already_know( tmp_path ):
    """
    Row c98bce3f established exit 3 for this refusal and the scheduled suite job reads it.
    Row fc74c1d4 moved the code that produces it into a shared library; the contract must
    have survived the move, which is a different claim from "it fails".
    """
    result = _run( tmp_path )
    assert result.returncode == 3, f"expected exit 3, got {result.returncode}\n{result.stderr}"
