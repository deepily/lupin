"""
END-TO-END guard: a hook's stdout must be nothing but its JSON answer.

WHY THIS EXISTS AND THE UNIT TESTS ARE NOT ENOUGH (row 298af249). I fixed two
sites that leaked a ConfigurationManager banner onto the hook's return channel,
and the second was found by Mr Radio rather than by me — my own fix was
ORDER-DEPENDENT and silent about it, working only because the first site happened
to build the config and cache it. Nothing stopped a third site appearing, and the
failure mode is invisible: the hook still "works", the harness still gets an
answer, and the reader simply loses their preview to our noise.

`test_hook_stdout_is_the_return_channel.py` pins the two known call sites. THIS
file pins the PROPERTY, by running the real hook binary in a subprocess and
reading what actually lands on fd 1. It does not care which function printed, or
whether the print came from our code, a library, or an import — it fails on any
byte that is not the JSON.

Measured before it existed: the banner filled the harness's entire ~2 KB preview
by itself in 391 of 505 saved payloads, and the leak was 2,206 bytes.

⚠️ WHAT THIS GUARD ACTUALLY COVERS TODAY, measured rather than implied. All three
hooks emit clean JSON and none of the parametrized cases skips — but under the
negative control (both call sites unwrapped) ONLY `user_prompt_submit` reddens.
The other two answer on stdout without building the config on this payload, so
they are pinning their CHANNEL, not exercising the leak. That is still worth
having — a leak introduced on their path would fail here — but it would be wrong
to read three green rows as three independent proofs of the fix.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import cosa.utils.util as cu


HOOKS = Path( cu.get_project_root() ) / "src" / "lupin_cli" / "claude_code" / "hooks"

# Hooks that answer on stdout. UserPromptSubmit is the one measured; the others
# share `emit_json` and the same import graph, so a leak introduced in shared code
# surfaces in all of them.
STDOUT_HOOKS = [ "user_prompt_submit.py", "pre_tool_use.py", "post_tool_use.py" ]

PAYLOAD = { "session_id": "deadbeef-0000-0000-0000-000000000000", "prompt": "probe" }


def _run_hook( name, sessions_dir ):
    """
    Run one hook as a real subprocess and return its raw stdout.

    A SUBPROCESS is the point, not an implementation detail: an in-process call
    cannot see a print that happens at import time, and `capsys` would not catch
    anything written straight to file descriptor 1. This reads what the harness
    would actually read.
    """
    env = dict( os.environ )
    env[ "LUPIN_ROOT" ]              = str( cu.get_project_root() )
    env[ "LUPIN_HOOK_SESSIONS_DIR" ] = str( sessions_dir )
    proc = subprocess.run(
        [ sys.executable, str( HOOKS / name ) ],
        input          = json.dumps( PAYLOAD ),
        text           = True,
        capture_output = True,
        env            = env,
        timeout        = 60,
    )
    return proc.stdout


@pytest.mark.parametrize( "hook_name", STDOUT_HOOKS )
def test_the_hook_writes_nothing_but_its_json_answer( hook_name, tmp_path ):
    """
    The whole property in one pair of assertions: stdout parses, and nothing
    precedes it. A banner, a config table, a debug print or a stray library line
    all fail this the same way — which is the point, since the next leak will not
    be one of the two already known.
    """
    if not ( HOOKS / hook_name ).exists():
        pytest.skip( f"{hook_name} not present in this tree" )

    out = _run_hook( hook_name, tmp_path )
    if not out.strip():
        pytest.skip( f"{hook_name} emitted nothing for this payload — no channel to check" )

    leading = len( out ) - len( out.lstrip() )
    assert out.lstrip()[ 0 ] == "{", (
        f"{hook_name} wrote {leading} byte(s) before its JSON.\n"
        f"stdout is this hook's RETURN CHANNEL — the harness keeps a leading ~2 KB "
        f"preview, so anything ahead of the payload is kept INSTEAD of the payload.\n"
        f"Wrap the offending call in hook_common.quiet_stdout(). First 200 bytes:\n"
        f"{out[ :200 ]!r}"
    )
    json.loads( out )   # rejects trailing noise too, not only leading


@pytest.mark.parametrize( "hook_name", STDOUT_HOOKS )
def test_the_hook_emits_exactly_one_json_document( hook_name, tmp_path ):
    """
    Trailing noise is as fatal as leading noise and less obvious. Asserted as a
    shape a reader can rely on rather than trusting that the parse above happened
    to be strict.
    """
    if not ( HOOKS / hook_name ).exists():
        pytest.skip( f"{hook_name} not present in this tree" )

    out = _run_hook( hook_name, tmp_path )
    if not out.strip():
        pytest.skip( f"{hook_name} emitted nothing for this payload" )

    assert len( [ ln for ln in out.splitlines() if ln.strip() ] ) == 1, (
        f"{hook_name} wrote more than one line to its return channel:\n{out[ :300 ]!r}"
    )


def test_this_guard_can_actually_FAIL():
    """
    The control on the control. A guard that cannot redden is decoration, and this
    file exists precisely because a silent leak looked like success — so prove the
    assertions discriminate by handing them the exact shape they must catch.
    """
    polluted = (
        "Using environment variables to instantiate configuration manager\n"
        + json.dumps( { "ok": 1 } )
    )
    assert polluted.lstrip()[ 0 ] != "{"
    with pytest.raises( json.JSONDecodeError ):
        json.loads( polluted )
    assert len( [ ln for ln in polluted.splitlines() if ln.strip() ] ) == 2
