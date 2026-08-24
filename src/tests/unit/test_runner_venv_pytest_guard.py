"""
Row fc74c1d4 — no sanctioned runner may silently fall back to a bare `python3 -m pytest`.

THE DEFECT. A runner that cannot find a venv pytest can refuse, or it can quietly run
whatever `python3` resolves to on PATH. Row c98bce3f measured what the second option costs:
an under-provisioned interpreter hits a collection error, a chunk of the suite never runs,
and the runner reports the REDUCED count as the whole suite — ~3000 tests silently
uncollected. On :8000, the final merge gate, that manufactures a false GREEN as readily as a
false red. c98bce3f fixed run-unit-tests.sh to refuse.

WHY THIS FILE EXISTS RATHER THAN JUST THE FIX. That guard was written inline, in one script,
and never propagated. Row fc74c1d4 found run-cosa-tests.sh still falling back on 2026-08-22 —
from a fresh worktree with no .venv, run-unit-tests.sh exited 3 with its warning while
run-cosa-tests.sh started `python3 -m pytest src/cosa/tests/ -q`. And cosa had joined the PR
merge requirements on 2026-08-13 (row d83d025b), so it carried full gate weight with none of
the protection.

Widening the search while fixing that row found the fallback in FOUR runners, not one, and
one of them (run-serial-bridge-guard.sh) is a named step in CLAUDE.md § PR MERGE
REQUIREMENTS. Fixing them by hand-copying the block into four more files would have re-armed
the exact mechanism that produced the drift, so the resolution moved into
src/scripts/lib/resolve-venv-pytest.sh and this file pins the property over the WHOLE set.

⚠️ WHAT IS ASSERTED IS A PROPERTY OF EVERY RUNNER, NOT OF A LIST OF KNOWN-BAD ONES. A test
that named the four scripts already fixed would be green forever and would not have caught
any of them before the fact. This walks the runner directories, so a runner added next month
with a copy-pasted fallback fails here on the day it lands.

Venue: :7999-eligible. Pure file reads plus a few subprocesses that run the resolver against
a tmp_path with no venv in it; no server, no state mutation, no network.
"""

import os
import re
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
RESOLVER     = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "resolve-venv-pytest.sh" )

# Where sanctioned runners live. Both directories, so a runner added to either is covered.
RUNNER_DIRS  = [
    os.path.join( PROJECT_ROOT, "src", "tests" ),
    os.path.join( PROJECT_ROOT, "src", "scripts" ),
]

# A runner is a *.sh that actually INVOKES pytest as a command — `-m pytest`, a resolved
# `$PYTEST`, or a path ending in /pytest. Merely containing the word does not count, and the
# distinction is load-bearing rather than pedantic: build-local-venv.sh names pytest inside
# an import check (`python -c "import ... pytest ..."`) and references .venv/bin/python
# because BUILDING that venv is its job. Requiring it to resolve a venv it has not created
# yet would be this guard failing a script for doing the right thing.
PYTEST_INVOCATION_RE = re.compile( r"-m\s+pytest|\$\{?PYTEST\b|/pytest\b" )

# The shape being outlawed: pytest run through a bare `python3`/`python`, with no venv path
# in front of it. `"$PYTEST"` filled by the resolver is exactly what should replace it, so
# the pattern is about the literal interpreter, not about the word pytest.
#
# ⚠️ THE LOOKBEHIND EXCLUDES A PATH, NOT A QUOTE. An earlier version of this pattern was
# `(?<![\w/.\"'])` — it also refused to match after a quote character, which silently
# exempted the single commonest spelling of the defect:
#     PYTEST="python3 -m pytest"
# That is an assignment, not a path, and it is what five of the nine runners actually had.
# The bug was caught by mutating a fixed script back to the broken form and finding this
# file still green — which is the only reason it is not still here.
BARE_PYTHON_PYTEST_RE = re.compile( r"(?<![\w/.])python3?\s+-m\s+pytest" )

# ⚠️ THE SPELLING THAT GREP MISSED, and the reason this file walks scripts instead of
# trusting a search. Three runners never write `python3 -m pytest` anywhere. They assign an
# interpreter to a variable, degrade THAT to a bare python3, and then run
# `"$VENV_PYTHON" -m pytest`:
#
#     VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python3"
#     if ! "$VENV_PYTHON" --version > /dev/null 2>&1; then VENV_PYTHON="python3"; fi
#
# Identical defect, invisible to a search for the literal invocation — and one of the three
# was run-integration-tests.sh, THE FINAL MERGE GATE. So the outlawed shape is also "any
# assignment that falls back to a bare interpreter name", wherever the value is used.
BARE_INTERPRETER_FALLBACK_RE = re.compile( r"""=\s*["']?python3?["']?\s*(;|$)""" )


def _runner_scripts():
    """
    Every *.sh under the runner directories that mentions pytest at all.

    Ensures:
        - returns [ ( repo_rel_path, text ), ... ]
        - raises rather than returning empty: an empty walk would make every assertion
          below pass vacuously, which is this directory's recurring failure mode
    """
    out = []
    for d in RUNNER_DIRS:
        for name in sorted( os.listdir( d ) ):
            if not name.endswith( ".sh" ):
                continue
            path = os.path.join( d, name )
            if not os.path.isfile( path ):
                continue
            text = open( path, encoding="utf-8", errors="replace" ).read()
            if PYTEST_INVOCATION_RE.search( text ):
                out.append( ( os.path.relpath( path, PROJECT_ROOT ), text ) )
    assert out, "walked ZERO pytest-invoking runner scripts — every assertion here would pass vacuously"
    return out


RUNNERS = _runner_scripts()


def test_the_walk_FOUND_the_runners_it_is_supposed_to_guard():
    """
    The instrument before the reading. The five scripts row fc74c1d4 actually touched must be
    in the walked set; if a directory move or a rename dropped them, the parametrized cases
    below would quietly stop covering the very scripts this row is about.
    """
    found = { p for p, _t in RUNNERS }
    for required in (
        "src/tests/run-unit-tests.sh",
        "src/tests/run-cosa-tests.sh",
        "src/tests/run-smoke-tests.sh",
        "src/tests/run-pytest-direct.sh",
        "src/scripts/run-serial-bridge-guard.sh",
        "src/tests/run-lupin-smoke-tests.sh",
        "src/tests/run-integration-tests.sh",
        "src/scripts/run-e2e-ui-tests.sh",
        "src/tests/run-presentation-regression.sh",
    ):
        assert required in found, f"{required} is not in the walked set — the guard is not reaching it"


@pytest.mark.parametrize( "repo_rel,text", RUNNERS, ids=[ p for p, _t in RUNNERS ] )
def test_no_runner_invokes_pytest_through_a_bare_python( repo_rel, text ):
    """
    No sanctioned runner may run pytest through a bare `python3 -m pytest`.

    A bare python3 is whatever is on PATH. When it is under-provisioned the suite
    under-collects and the reduced count is reported as the whole suite (row c98bce3f) —
    the false green this whole family of rows is about.
    """
    hits = [ line.strip() for line in text.splitlines()
             if BARE_PYTHON_PYTEST_RE.search( line ) and not line.strip().startswith( "#" ) ]
    assert not hits, (
        f"{repo_rel} invokes pytest through a bare python3:\n"
        + "\n".join( f"    {h}" for h in hits )
        + "\nSource src/scripts/lib/resolve-venv-pytest.sh and call resolve_venv_pytest instead;"
          "\nit refuses with exit 3 and names what it looked for (rows c98bce3f, fc74c1d4)."
    )


@pytest.mark.parametrize( "repo_rel,text", RUNNERS, ids=[ p for p, _t in RUNNERS ] )
def test_no_runner_degrades_its_interpreter_variable_to_a_bare_python( repo_rel, text ):
    """
    The same refusal, for the runners that resolve an INTERPRETER rather than a pytest.

    This is the case a grep for `python3 -m pytest` cannot see, and it is why the fix for
    row fc74c1d4 kept growing: run-integration-tests.sh (the FINAL merge gate),
    run-e2e-ui-tests.sh and run-presentation-regression.sh each set VENV_PYTHON to a venv
    path and then quietly reassigned it to a bare `python3` when that path was missing. The
    suite then runs on whatever is on PATH, which is the whole defect.
    """
    hits = [ line.strip() for line in text.splitlines()
             if BARE_INTERPRETER_FALLBACK_RE.search( line )
             and not line.strip().startswith( "#" )
             and "PYTHON" in line.upper() ]
    assert not hits, (
        f"{repo_rel} degrades its interpreter variable to a bare python:\n"
        + "\n".join( f"    {h}" for h in hits )
        + "\nSource src/scripts/lib/resolve-venv-pytest.sh and call resolve_venv_python instead;"
          "\nit refuses with exit 3 rather than running the suite on whatever is on PATH."
    )


@pytest.mark.parametrize( "repo_rel,text", RUNNERS, ids=[ p for p, _t in RUNNERS ] )
def test_every_runner_that_resolves_a_pytest_uses_the_shared_resolver( repo_rel, text ):
    """
    Choosing an interpreter must go through the one shared resolver.

    Naming a venv path inline is how the guard drifted the first time: run-unit-tests.sh had
    it, three siblings did not, and nothing said so for nine days. A script that hardcodes
    `.venv/bin/pytest` for itself is re-opening that gap even if its own logic is correct
    today.
    """
    if "resolve-venv-pytest.sh" in text:
        return   # routes through the shared resolver; correct by construction

    mentions_venv_interpreter = any(
        marker in text for marker in (
            ".venv/bin/pytest", "/opt/venv/bin/pytest",
            ".venv/bin/python", "/opt/venv/bin/python",
        )
    )
    if not mentions_venv_interpreter:
        pytest.skip( f"{repo_rel} does not resolve a pytest interpreter — nothing to route" )

    pytest.fail(
        f"{repo_rel} picks a pytest interpreter by hand instead of sourcing "
        f"src/scripts/lib/resolve-venv-pytest.sh — that is how row c98bce3f's guard failed "
        f"to reach three other runners (row fc74c1d4)."
    )


# ---------------------------------------------------------------------------
# The resolver itself: it must actually refuse, with the exit code callers expect
# ---------------------------------------------------------------------------

# The container venv is a real path on this box (docker/lupin/Dockerfile bakes
# UV_PROJECT_ENVIRONMENT=/opt/venv). On a host where it happens to exist, the "no venv
# anywhere" cases below cannot be staged honestly — skip rather than assert a result the
# staging did not actually produce.
_OPT_VENV_PRESENT  = os.access( "/opt/venv/bin/pytest", os.X_OK )
_needs_no_opt_venv = pytest.mark.skipif(
    _OPT_VENV_PRESENT,
    reason="/opt/venv/bin/pytest exists on this host — the no-venv-anywhere case cannot be staged"
)


def _run_resolver( cwd, path_dirs=None ):
    """
    Run resolve_venv_pytest with PROJECT_ROOT pointed at `cwd`.

    Ensures:
        - returns the CompletedProcess; the function's return code is re-raised as the
          script's exit status, which is what every caller does with `|| exit $?`
        - when path_dirs is given, PATH is replaced by it — used to prove the refusal is
          not quietly satisfied by some pytest lying around on PATH
    """
    env = dict( os.environ, PROJECT_ROOT=cwd, LUPIN_ROOT=cwd )
    if path_dirs is not None:
        env[ "PATH" ] = path_dirs
    script = f'source "{RESOLVER}"\nresolve_venv_pytest || exit $?\necho "PYTEST=$PYTEST"\n'
    return subprocess.run(
        [ "bash", "-c", script ], cwd=cwd, env=env, capture_output=True, text=True, timeout=120
    )


@_needs_no_opt_venv
def test_resolver_refuses_with_exit_3_when_no_venv_exists( tmp_path ):
    """
    The worktree shape, which is the crew default: a checkout with no .venv of its own. The
    resolver must refuse rather than degrade, and must use exit code 3 — the code row
    c98bce3f established and that log readers and the suite job already recognise.
    """
    proc = _run_resolver( str( tmp_path ) )

    assert proc.returncode == 3, f"expected the row c98bce3f exit code 3, got {proc.returncode}\n{proc.stderr}"
    assert "Refusing to fall back to a bare 'python3 -m pytest'" in proc.stderr, \
        f"the refusal did not explain itself.\n--- stderr ---\n{proc.stderr}"
    assert "PYTEST=" not in proc.stdout, "the resolver returned non-zero but still set PYTEST"


@_needs_no_opt_venv
def test_resolver_names_every_location_it_looked_in( tmp_path ):
    """
    "Not found" without a search list sends the reader hunting. The refusal must name each
    candidate path so the fix is obvious from the log alone — which for a worktree is usually
    just symlinking the main repo's .venv.
    """
    proc = _run_resolver( str( tmp_path ) )

    assert f"{tmp_path}/.venv/bin/pytest" in proc.stderr, "the host venv candidate was not named"
    assert "/opt/venv/bin/pytest" in proc.stderr, "the container venv candidate was not named"


@_needs_no_opt_venv
def test_resolver_does_not_settle_for_a_pytest_that_is_merely_on_PATH( tmp_path ):
    """
    The precise thing being outlawed. A pytest sitting on PATH must NOT satisfy the
    resolver — that is the bare-python3 fallback wearing different clothes, and it is how an
    under-provisioned interpreter gets in.

    Staged by putting an executable named `pytest` on PATH inside an empty project root.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    decoy = bin_dir / "pytest"
    decoy.write_text( "#!/bin/bash\necho 'pytest 0.0.0-decoy'\n" )
    decoy.chmod( 0o755 )

    proc = _run_resolver( str( tmp_path ), path_dirs=f"{bin_dir}:{os.environ.get( 'PATH', '' )}" )

    assert proc.returncode == 3, (
        f"a pytest merely on PATH satisfied the resolver (exit {proc.returncode}) — that is "
        f"the fallback this guard exists to refuse.\n{proc.stdout}\n{proc.stderr}"
    )


def test_resolver_finds_a_real_venv_pytest_and_reports_its_path():
    """
    The other half, and the one that keeps the refusal honest: against this repo, which HAS a
    .venv, the resolver must succeed and hand back that exact path. A guard that only ever
    refuses would be trivially "passing" while breaking every runner in the tree.
    """
    proc = _run_resolver( PROJECT_ROOT )

    assert proc.returncode == 0, f"resolver failed against the real repo.\n{proc.stderr}"
    expected = os.path.join( PROJECT_ROOT, ".venv", "bin", "pytest" )
    assert f"PYTEST={expected}" in proc.stdout, f"expected PYTEST={expected}, got:\n{proc.stdout}"
