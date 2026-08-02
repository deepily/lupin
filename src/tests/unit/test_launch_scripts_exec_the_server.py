"""
Every FastAPI launch script must `exec` the server, so uvicorn becomes the
container's PID 1 (bug AC6, 2026-08-02).

WHAT THIS PINS, AND WHAT IT DELIBERATELY DOES NOT
This is a TEXT check, not a behaviour check. It asserts each launch script's
server line reads `exec python3 -m lupin_app.main`, never a bare
`python3 -m lupin_app.main`. It does NOT — and cannot, here — prove the container
actually shuts down gracefully.

THE CONTAINER SEMANTICS IT STANDS IN FOR
The image starts the server as `/bin/bash <launch-script>`, so PID 1 is bash.
On `docker stop`, SIGTERM goes to PID 1. The kernel applies NO default action to
an un-handled signal for PID 1, and a non-interactive bash installs no SIGTERM
trap AND does not forward the signal to its child — so a non-exec'd server is
never signalled, rides the full ~10s grace, and is SIGKILLed (exit 137) with ZERO
shutdown lines. The lifespan shutdown — and the R4 managed-bounce warning inside
it — never runs. `exec` makes the server replace bash and receive SIGTERM itself,
so uvicorn.run's graceful shutdown fires.

WHY IT IS NOT UNIT-REACHABLE
Proving the shutdown path needs a real container (or a privileged PID namespace to
reproduce PID-1 signal semantics) plus a `docker stop` — neither available to the
unit suite, and we do not stop the live :7999/:8000 to force it. So this pins the
one thing a unit test CAN own: that the fix stays in the scripts. If it ever reads
"stronger than a text check", that is a misread — treat it as a tripwire on the
launch scripts, not a shutdown-behaviour guarantee.

GLOBS, does not NAME. The twin (:8000's run-fastapi-lupin-test.sh) carried the
same defect and was missed once already; a new launch script matching the glob is
covered automatically, and a dropped `exec` on any of them goes red.

⚠️ UNVERIFIED follow-up: with LUPIN_RELOAD=1 uvicorn spawns a reloader subprocess;
whether SIGTERM reaches the worker's lifespan on that path is not yet tested.
Reload is off by default, so `exec` fixes the default path.
"""

import re
from pathlib import Path


REPO_ROOT      = Path( __file__ ).resolve().parents[ 3 ]
SCRIPTS_DIR    = REPO_ROOT / "src" / "scripts"
LAUNCH_GLOB    = "run-fastapi-lupin*.sh"

# The server-launch invocation, with and without the required exec.
_EXECED = re.compile( r"^\s*exec\s+python3\s+-m\s+lupin_app\.main\b", re.MULTILINE )
_BARE   = re.compile( r"^\s*python3\s+-m\s+lupin_app\.main\b",        re.MULTILINE )

# Names we KNOW must exist. Pins the glob against silently matching nothing — a
# harness control: rename the scripts and this fails rather than passing vacuously.
_KNOWN = { "run-fastapi-lupin.sh", "run-fastapi-lupin-test.sh" }


def _launch_scripts():
    return sorted( SCRIPTS_DIR.glob( LAUNCH_GLOB ) )


def test_the_glob_finds_the_known_launch_scripts():
    """
    🔴 Harness control. Every assertion below is vacuously true if the glob returns
    nothing (a rename, a moved dir). Pin that the known scripts are actually found,
    so 'all scripts exec the server' cannot pass by finding zero scripts.
    """
    found = { p.name for p in _launch_scripts() }
    missing = _KNOWN - found
    assert not missing, (
        f"launch-script glob {LAUNCH_GLOB!r} did not find {sorted( missing )} under {SCRIPTS_DIR} — "
        "the exec check below would pass vacuously. Fix the glob/paths, do not delete this test."
    )


def test_every_launch_script_execs_the_server():
    """
    Each launch script that starts the server must do so as
    `exec python3 -m lupin_app.main`, so uvicorn becomes PID 1 and receives SIGTERM
    (see module docstring). A bare, un-exec'd invocation is the defect and fails
    here — for EVERY matched launcher, not a named one.

    A matched script that does NOT launch the server (a future helper sharing the
    glob prefix) is skipped rather than flagged — it has no server line to exec.
    The control below guarantees the real launchers are still exercised.
    """
    checked   = [ ]
    offenders = [ ]
    for script in _launch_scripts():
        text = script.read_text()
        if not ( _EXECED.search( text ) or _BARE.search( text ) ):
            continue                                              # not a server launcher
        checked.append( script.name )
        if _BARE.search( text ) or not _EXECED.search( text ):
            offenders.append( script.name )

    assert not offenders, (
        "these launch scripts start the server without `exec`, so bash stays PID 1 and "
        "SIGTERM never reaches uvicorn on `docker stop` — no graceful shutdown, no R4 "
        f"warning (bug AC6): {offenders}. Prefix the server line with `exec`."
    )
    # 🔴 Control: the known launchers must be among those actually checked, or an
    # offender could hide by simply not matching either pattern (a renamed module,
    # a reformatted line) and read as "0 offenders".
    unchecked = _KNOWN - set( checked )
    assert not unchecked, (
        f"known launcher(s) {sorted( unchecked )} were not recognised as starting the server — "
        "the exec/bare patterns no longer match their server line, so this test is not "
        "watching them. Fix the pattern, do not delete the test."
    )
