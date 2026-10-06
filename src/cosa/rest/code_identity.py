"""
The running process's code identity, captured once at import.

The question this answers: "Does the process serving me right now have commit X?"

Every cheap way of asking reads the filesystem, and on `:8000` the filesystem is not the
process. `:8000` (lupin-rest-test) bind-mounts ./src and runs `reload=False`, so a
scheduled run cannot shift underneath itself. Editing a source file on the host changes the
file inside the container at once, while the module stays as imported at process start.
The file is new and the process is old, so a grep for a symbol can hit while none of it runs.

Git inside the container gives the same wrong answer. The repo is bind-mounted too, so
`git rev-parse HEAD` tracks the host working tree, not the loaded code. Checking the sha
instead of grepping is the grep with extra steps.

So this module captures at import time and never re-reads. A `/health` field that computed
the sha per request would reproduce the same wrong answer in a new place. The capture
happens once, when the process loads its code, and the value is frozen from then on.
`_FROZEN_IDENTITY` below is the whole mechanism; `test_code_identity.py` pins it.

``imported_at`` is the authority and ``git_sha`` is a convenience. A caller decides whether
this process has commit X by comparing X's author date against ``imported_at``. That is the
comparison `src/scripts/verify-running-code.sh` makes against `docker inspect .State.StartedAt`,
but available over HTTP to any seat, with no docker socket and no shell. ``git_sha`` is the
sha the tree carried when this process loaded, but it cannot prove that every other module
was loaded from that revision. Only the clock gives certainty; the sha makes the common case
one glance.

If git cannot be reached, the field says `unavailable` in words, with the reason, and never
falls back to a plausible-looking constant. A version string that identifies nothing is
what `/health` once served (a hardcoded "0.1.0"): confident, well-formed, and empty.
"""

import os
import subprocess
from datetime import datetime, timezone

import cosa.utils.util as cu


# The value every field takes when it could not be determined. A NAMED sentinel, so a
# consumer that forgets to check reads the word "unavailable" rather than mistaking a
# blank or a stale default for a measurement.
UNAVAILABLE = "unavailable"

# git is invoked with an inline safe.directory: on the VM (and in the container) the
# repo is owned by uid 1001 while the process may run as someone else, and git refuses
# a "dubious ownership" repo by default. lupin-vm.sh passes the same flag inline for
# the same reason. Without it the sha would read UNAVAILABLE on exactly the deployment
# this module matters most on.
_GIT_TIMEOUT_SECONDS = 5


def _run_git( args, project_root, runner ):
    """
    Run a git command against the project root, returning its stdout or None.

    Requires:
        - args is a list of git arguments (no leading "git")
        - project_root is a path string
        - runner is a subprocess.run-compatible callable

    Ensures:
        - returns the stripped stdout string on success
        - returns None on any failure (git absent, non-zero exit, timeout, no repo)
        - never raises, never blocks longer than _GIT_TIMEOUT_SECONDS

    Raises:
        - None. An import-time probe that can abort startup is a worse defect than
          an unknown sha.
    """
    try:
        completed = runner(
            [ "git", "-c", f"safe.directory={project_root}", "-C", project_root ] + args,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS
        )
    except Exception:
        # FileNotFoundError (no git), TimeoutExpired, OSError — all mean the same
        # thing to the caller: this surface cannot answer. Distinguishing them here
        # would put a taxonomy in front of a fact nobody can act on differently.
        return None
    if completed.returncode != 0:
        return None
    out = ( completed.stdout or "" ).strip()
    return out or None


def capture_code_identity( project_root=None, runner=None, now=None ):
    """
    Build the code-identity record for this process, reading the tree once.

    Requires:
        - project_root resolves to a path (defaults to cu.get_project_root())
        - runner is a subprocess.run-compatible callable (defaults to subprocess.run)
        - now is a timezone-aware datetime (defaults to datetime.now(timezone.utc))

    Ensures:
        - returns a new dict with keys: git_sha, git_branch, git_sha_source,
          imported_at, pid
        - git_sha / git_branch are `UNAVAILABLE` when git cannot answer; never a
          fabricated or defaulted value
        - git_sha_source states how the value was obtained, so a reader can tell a
          measurement from a miss without inspecting the value
        - never raises

    Returns:
        dict: the identity record
    """
    root    = project_root if project_root is not None else cu.get_project_root()
    run     = runner       if runner       is not None else subprocess.run
    stamp   = now          if now          is not None else datetime.now( timezone.utc )

    sha    = _run_git( [ "rev-parse", "--short", "HEAD" ], root, run )
    branch = _run_git( [ "rev-parse", "--abbrev-ref", "HEAD" ], root, run )

    if sha is None:
        source = f"{UNAVAILABLE}: git could not read a HEAD sha at {root}"
    else:
        source = "git rev-parse at module import"

    return {
        "git_sha"        : sha    if sha    is not None else UNAVAILABLE,
        "git_branch"     : branch if branch is not None else UNAVAILABLE,
        "git_sha_source" : source,
        "imported_at"    : stamp.isoformat(),
        "pid"            : os.getpid(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# THE CAPTURE. This line is the entire remedy.
#
# It runs exactly once, when Python first imports this module — i.e. when the
# process loads its code. Everything served afterwards is this frozen record, no
# matter how many times the tree changes underneath the running process.
#
# ⚠️ DO NOT move this call into get_code_identity(). A per-request read would return
# the CURRENT working tree, which on a bind-mounted `reload=False` container is not
# the code that is running — reintroducing the exact false green this module exists
# to remove, in the place readers trust most. Pinned by
# test_the_identity_is_frozen_at_import_not_recomputed_per_call.
# ══════════════════════════════════════════════════════════════════════════════
_FROZEN_IDENTITY = capture_code_identity()


def get_code_identity():
    """
    The identity captured at import, returned as a fresh copy on every call.

    Requires:
        - the module has been imported (guaranteed by calling this)

    Ensures:
        - returns a dict equal to the import-time capture
        - returns a copy, so a caller mutating the response cannot corrupt the
          record every later caller reads. A frozen fact that one handler can edit
          is not frozen
        - never re-reads the filesystem, the repo, or the clock

    Returns:
        dict: the frozen identity record
    """
    return dict( _FROZEN_IDENTITY )


def quick_smoke_test():
    """Print this process's captured identity and prove it does not move."""
    cu.print_banner( "code_identity smoke test", prepend_nl=True )
    first  = get_code_identity()
    second = get_code_identity()
    for key, value in first.items():
        print( f"  {key:16} = {value}" )
    ok = first == second and first is not second
    print( f"\n  {'✓' if ok else '✗'} two calls agree and are distinct objects" )


if __name__ == "__main__":
    quick_smoke_test()
