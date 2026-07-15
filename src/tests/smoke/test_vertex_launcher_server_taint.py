"""
F-A11 — THE LAUNCHER MUST NOT BIRTH A TAINTED TMUX SERVER. Proven by EXECUTION, not by reading.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

WHY THIS FILE EXISTS, AND WHY IT RUNS THE REAL SHELL

The guard this file protects was, until 2026-07-14, INERT — and it was inert in the one way
that nothing catches: it produced the right answer for a reason that had nothing to do with
the guard. The launcher scrubbed `tmux start-server`. Measured on tmux 3.2a:

    TAINT=1                tmux start-server   -> a later pane reads <unset>
    TAINT=1 env -u TAINT   tmux start-server   -> a later pane reads <unset>
    TAINT=1                tmux new-session    -> a later pane reads TAINT=1

THE SCRUBBED AND UNSCRUBBED CASES ARE IDENTICAL. `start-server` never propagates the caller's
env, so scrubbing it CHANGED NOTHING AND COULD NOT HAVE. Every green it ever produced was
free. `new-session` is the only invocation that freezes the caller's env into the server.

A unit test cannot see any of this: the defect lives in what tmux does with a process's
environment, and tmux is not mocked here — it is RUN. So this test drives the REAL launcher,
on an ISOLATED tmux socket (TMUX_TMPDIR), from a DELIBERATELY TAINTED shell, with a FAKE
`claude` on PATH, and then asks the server what it froze.

AND IT CARRIES ITS OWN NEGATIVE CONTROL. `test_the_probe_can_actually_detect_a_tainted_server`
runs a launcher copy with the scrub REMOVED and proves the probe goes RED. Without it, a clean
reading would be worth nothing: a probe that cannot detect taint reports "clean" forever, and
that is precisely the bug this file was written in response to.

VENUE: :7999-eligible / AI-discretionary — no persistent state, no network, no GCP, no spend,
no server monopoly. It creates a private tmux server on a temp socket and kills it.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.utils.vertex_env import MAX_PANE_UNSET_KEYS, VERTEX_SESSION_KEYS
from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS


LAUNCHER = Path( cu.get_project_root() ) / "src" / "scripts" / "start-cc-with-tmux.sh"

# The vars a Vertex-poisoned shell would be carrying when Rick runs the launcher on the MAX
# path. CLAUDE_CODE_USE_VERTEX is the one that costs money: it is what puts a session on
# metered billing, and a MAX session that inherits it never asked to be billed at all.
TAINT = {
    "CLAUDE_CODE_USE_VERTEX"      : "1",
    "CLOUD_ML_REGION"             : "global",
    "ANTHROPIC_VERTEX_PROJECT_ID" : "someone-elses-project",
}


def _tmux( socket_dir, *args ):
    """Run tmux against an ISOLATED server (never the fleet's), from a clean env."""
    env = { key: value for key, value in os.environ.items() if key not in TAINT }
    for key in TMUX_ISOLATION_STRIP_KEYS:
        env.pop( key, None )    # do NOT inherit the pane's server socket — $TMUX beats TMUX_TMPDIR (plan §2.5)
    env[ "TMUX_TMPDIR" ] = str( socket_dir )
    return subprocess.run( [ "tmux", *args ], capture_output=True, text=True, env=env, timeout=30 )


def _launch( launcher, socket_dir, fake_bin, tainted, session_name, vertex=False ):
    """
    Run the REAL launcher, headless, on an isolated socket, from a shell we control.

    Requires:
        - launcher is an executable start-cc-with-tmux.sh (real or mutated copy)
        - tainted decides whether the CALLING shell carries the Vertex vars

    Ensures:
        - returns the CompletedProcess; the tmux server (if born) lives on socket_dir
    """
    env = dict( os.environ )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        env.pop( key, None )    # do NOT inherit the pane's server socket — $TMUX beats TMUX_TMPDIR (plan §2.5)
    env[ "TMUX_TMPDIR" ] = str( socket_dir )
    env[ "PATH" ]        = f"{fake_bin}:{env['PATH']}"
    env[ "LUPIN_ROOT" ]  = cu.get_project_root()
    env.update( TAINT if tainted else {} )
    for key in ( [] if tainted else TAINT ):
        env.pop( key, None )

    args = [ "bash", str( launcher ), "--headless" ] + ( [ "--vertex" ] if vertex else [] ) + [ session_name ]
    return subprocess.run( args, capture_output=True, text=True, env=env, timeout=120 )


def _server_env( socket_dir, key ):
    """What the tmux SERVER froze — i.e. what every LATER session on this socket inherits."""
    result = _tmux( socket_dir, "show-environment", "-g", key )
    return result.stdout.strip()


@pytest.fixture
def rig( tmp_path ):
    """An isolated tmux socket + a fake `claude` that parks, so no real CC ever spawns."""
    socket_dir = tmp_path / "tmux"
    fake_bin   = tmp_path / "bin"
    socket_dir.mkdir()
    fake_bin.mkdir()

    fake_claude = fake_bin / "claude"
    fake_claude.write_text( "#!/usr/bin/env bash\nsleep 20\n" )
    fake_claude.chmod( 0o755 )

    yield socket_dir, fake_bin

    _tmux( socket_dir, "kill-server" )


@pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )
def test_the_max_path_does_not_freeze_a_tainted_shell_into_the_server( rig ):
    """
    🔴 THE ONE THAT MATTERS. Rick launches a MAX session from a shell that still has
    CLAUDE_CODE_USE_VERTEX=1 exported. The pane protects itself (the INNER unset) — but if
    this invocation BIRTHS the server, the taint is frozen into it, and the NEXT session on
    that socket inherits metered billing it never asked for. That next session is the victim,
    and nothing in it is doing anything wrong.
    """
    socket_dir, fake_bin = rig

    result = _launch( LAUNCHER, socket_dir, fake_bin, tainted=True, session_name="max-sess" )
    assert result.returncode == 0, f"launcher failed: {result.stderr}"
    time.sleep( 1.0 )

    for key in VERTEX_SESSION_KEYS:
        frozen = _server_env( socket_dir, key )
        assert "-" + key == frozen or frozen == "", (
            f"THE LAUNCHER FROZE {key} INTO THE TMUX SERVER ({frozen!r}). Every later session "
            f"on this socket now inherits it — including MAX sessions, which are then billed "
            f"for a toggle they never asked for. The launcher is the polluter F-A11 exists to "
            f"prevent."
        )


@pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )
def test_the_probe_can_actually_detect_a_tainted_server( rig, tmp_path ):
    """
    🔴 THE NEGATIVE CONTROL, AND THE REASON THE TEST ABOVE IS ADMISSIBLE AT ALL.

    Strip the scrub back out of a COPY of the launcher — reintroducing the exact defect — and
    the probe must go RED. Without this, a clean reading proves nothing: the old guard's green
    was free (it scrubbed an invocation that propagates nothing), and a probe that cannot see
    taint would have reported that same clean forever.

    An observation is evidence only if it could have come out otherwise.
    """
    socket_dir, fake_bin = rig

    mutant = tmp_path / "mutant-launcher.sh"
    source = LAUNCHER.read_text()
    assert '"${SERVER_SCRUB[@]}" tmux new-session' in source, (
        "The launcher no longer scrub-prefixes `tmux new-session` — either the fix was reverted "
        "or it moved. This control cannot mutate what it cannot find."
    )
    mutant.write_text( source.replace( '"${SERVER_SCRUB[@]}" tmux new-session', "tmux new-session" ) )

    result = _launch( mutant, socket_dir, fake_bin, tainted=True, session_name="mutant-sess" )
    assert result.returncode == 0, f"mutant launcher failed: {result.stderr}"
    time.sleep( 1.0 )

    frozen = _server_env( socket_dir, "CLAUDE_CODE_USE_VERTEX" )
    assert frozen == "CLAUDE_CODE_USE_VERTEX=1", (
        f"The PROBE IS BLIND: an unscrubbed launcher, run from a tainted shell, should have "
        f"frozen CLAUDE_CODE_USE_VERTEX=1 into the server — but the probe read {frozen!r}. "
        f"Until this control passes, the clean reading in the test above is worth NOTHING."
    )


@pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )
def test_the_vertex_path_still_reaches_the_pane_despite_the_server_scrub( rig ):
    """
    THE P0, GUARDED FROM THE OTHER SIDE. We now scrub the toggle keys from the SERVER-BIRTH
    env even under --vertex. That must NOT kill the feature: `-e` sets the SESSION environment,
    which outranks the frozen server env, so the session still carries the toggle.

    If this ever goes red, --vertex has become a lie again — a metered-billing banner over a
    session running on Max. It failed safe last time. The banner did not.
    """
    socket_dir, fake_bin = rig

    result = _launch(
        LAUNCHER, socket_dir, fake_bin, tainted=False, session_name="vertex-sess", vertex=True
    )
    if result.returncode != 0:
        pytest.skip( f"--vertex refused to compose in this environment: {result.stderr.strip()[:200]}" )

    time.sleep( 1.0 )
    session_env = _tmux( socket_dir, "show-environment", "-t", "vertex-sess" ).stdout

    assert "CLAUDE_CODE_USE_VERTEX=1" in session_env, (
        "--vertex did not put the toggle on the SESSION. The server scrub has eaten the feature "
        "it protects — the P0, reintroduced from the other end."
    )


def test_the_scrub_is_derived_from_the_module_never_restated():
    """
    FLAG D. The launcher must IMPORT the key list, never spell it out — a restated list falls
    silently behind its source while the suite stays green testing the source.
    """
    code = "\n".join(
        line.split( "#", 1 )[ 0 ] for line in LAUNCHER.read_text().splitlines()
    )

    assert "MAX_PANE_UNSET_KEYS" in code, "the launcher must derive its scrub set from vertex_env"
    for key in MAX_PANE_UNSET_KEYS:
        assert f'"{key}"' not in code, (
            f"{key} is RESTATED as a literal in the launcher. Derive it from vertex_env — a "
            f"hardcoded copy drifts behind its source in silence."
        )


def test_the_inert_start_server_scrub_is_gone():
    """
    THE DEAD GUARD MUST STAY DEAD. `tmux start-server` propagates NOTHING (measured: scrubbed
    and unscrubbed give byte-identical clean panes), so a scrub on it is decoration — and a
    decoration that looks like a guard is worse than no guard, because the next reader trusts it.
    """
    code = "\n".join(
        line.split( "#", 1 )[ 0 ] for line in LAUNCHER.read_text().splitlines()
    )
    assert "tmux start-server" not in code, (
        "The launcher scrubs `tmux start-server` again. That invocation does not carry the "
        "caller's env — the guard cannot come out otherwise, and it never could. The scrub "
        "belongs on `tmux new-session`, which is the only invocation that freezes the server env."
    )
