"""
`cosa.rest.code_identity` — row ce89669e remedy 1.

WHAT THIS MODULE IS FOR
-----------------------
Answering "does the process serving me right now have commit X?" as a REQUEST rather
than an inference from `docker inspect` plus a shell.

WHY THE CAPTURE POINT IS THE WHOLE DESIGN
-----------------------------------------
`:8000` bind-mounts `./src` and runs `reload=False`. So the file inside the container
is the HOST's current file while the imported module is whatever was loaded at process
start. The obvious checks read the filesystem:

    docker exec lupin-rest-test grep -c <symbol> .../job.py   -> 3 hits, 0 running
    docker exec lupin-rest-test git rev-parse --short HEAD    -> the HOST's HEAD

Both answer confidently and both answer the wrong question. Re-measured 2026-07-27:
the container reported `7f41db3d`, a commit made on the host minutes earlier, against
a process that had started nearly an hour before it.

⇒ A `/health` field computing the sha PER REQUEST would reproduce that lie in the
  place readers trust most. `code_identity` captures at IMPORT and never re-reads.

THE LOAD-BEARING TEST IN THIS FILE
----------------------------------
`test_the_identity_is_frozen_at_import_not_recomputed_per_call`, and its control
`test_the_patched_runner_WOULD_have_changed_the_answer`. Neither is worth anything
alone:

  - "two calls agree" passes trivially if git is simply deterministic — which it is.
    That test cannot fail for the reason it claims to test.
  - so the control patches the runner to return a DIFFERENT sha every call, then
    drives BOTH paths with that same patched runner. `capture_code_identity()` must
    move; `get_code_identity()` must not. One patch, two call paths, opposite
    outcomes — that is what makes the freeze a measured property instead of an
    assumption.

Venue: :7999-eligible. Pure in-process, no docker, no network, no live git needed
(every git interaction is injected).
"""
import subprocess

import pytest

from cosa.rest import code_identity as ci


# ── a runner that changes its answer, so "frozen" can be distinguished from
#    "deterministic" ─────────────────────────────────────────────────────────

class _CountingRunner:
    """
    A subprocess.run stand-in returning a DIFFERENT sha on every invocation.

    This is the instrument the freeze test depends on, so it is asserted on
    directly (test_the_counting_runner_actually_counts) rather than trusted.
    """
    def __init__( self ):
        self.calls = 0

    def __call__( self, args, capture_output=None, text=None, timeout=None ):
        self.calls += 1
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout=f"sha-{self.calls}\n", stderr=""
        )


class _FailingRunner:
    """A runner whose git always exits non-zero — 'git ran and could not answer'."""
    def __call__( self, args, capture_output=None, text=None, timeout=None ):
        return subprocess.CompletedProcess( args=args, returncode=128,
                                            stdout="", stderr="fatal: not a git repository" )


class _EmptyRunner:
    """A runner whose git succeeds but prints nothing — success is not an answer."""
    def __call__( self, args, capture_output=None, text=None, timeout=None ):
        return subprocess.CompletedProcess( args=args, returncode=0, stdout="  \n", stderr="" )


def _raising_runner( exc ):
    def run( args, capture_output=None, text=None, timeout=None ):
        raise exc
    return run


# ── the capture works at all ──────────────────────────────────────────────

def test_a_successful_capture_reports_the_sha_and_says_it_MEASURED_it():
    got = ci.capture_code_identity( project_root="/some/root", runner=_CountingRunner() )
    assert got[ "git_sha" ]        == "sha-1"
    assert got[ "git_branch" ]     == "sha-2"
    assert got[ "git_sha_source" ] == "git rev-parse at module import"
    assert ci.UNAVAILABLE not in got[ "git_sha_source" ]


def test_the_capture_stamps_an_import_time_and_a_pid():
    got = ci.capture_code_identity( project_root="/some/root", runner=_CountingRunner() )
    assert got[ "imported_at" ]
    assert isinstance( got[ "pid" ], int ) and got[ "pid" ] > 0


def test_the_capture_passes_safe_directory_INLINE():
    """
    On the VM and in the container the repo is uid-1001-owned while the process may
    run as someone else, and git refuses a "dubious ownership" repo by default.
    Without the inline flag the sha would read UNAVAILABLE on exactly the deployment
    this module matters most on — a field that goes blank precisely where it is
    needed, which is the alarm-gated-on-the-healthy-value shape.
    """
    seen = []

    def recording_runner( args, capture_output=None, text=None, timeout=None ):
        seen.append( args )
        return subprocess.CompletedProcess( args=args, returncode=0, stdout="abc123\n", stderr="" )

    ci.capture_code_identity( project_root="/mnt/lupin-data/lupin", runner=recording_runner )
    assert seen, "the runner was never invoked"
    assert "-c" in seen[ 0 ]
    assert "safe.directory=/mnt/lupin-data/lupin" in seen[ 0 ]


def test_the_capture_bounds_its_own_runtime():
    """An import-time probe with no timeout can hang application startup forever."""
    seen = {}

    def recording_runner( args, capture_output=None, text=None, timeout=None ):
        seen[ "timeout" ] = timeout
        return subprocess.CompletedProcess( args=args, returncode=0, stdout="abc123\n", stderr="" )

    ci.capture_code_identity( project_root="/r", runner=recording_runner )
    assert seen[ "timeout" ] is not None and seen[ "timeout" ] > 0


# ── every way of not knowing says UNAVAILABLE, in words ───────────────────

@pytest.mark.parametrize( "runner, why", [
    ( _FailingRunner(),                                   "git exited non-zero" ),
    ( _EmptyRunner(),                                     "git printed nothing" ),
    ( _raising_runner( FileNotFoundError( "git" ) ),      "git is not installed" ),
    ( _raising_runner( subprocess.TimeoutExpired( "git", 5 ) ), "git hung" ),
    ( _raising_runner( OSError( "boom" ) ),               "the OS refused the exec" ),
] )
def test_a_sha_that_cannot_be_read_is_UNAVAILABLE_and_never_a_plausible_default( runner, why ):
    """
    THE POINT OF THE NAMED SENTINEL. `/health` already served a hardcoded
    `"version": "0.1.0"` — confident, well-formed, and identifying nothing. A field
    that quietly falls back to a constant is the same defect with a fresh coat.

    Every failure mode lands on the same honest word, and the SOURCE field says the
    value is a miss, so a consumer that only reads one of the two still cannot be
    misled.
    """
    got = ci.capture_code_identity( project_root="/r", runner=runner )
    assert got[ "git_sha" ]    == ci.UNAVAILABLE, why
    assert got[ "git_branch" ] == ci.UNAVAILABLE, why
    assert got[ "git_sha_source" ].startswith( ci.UNAVAILABLE ), why
    assert "/r" in got[ "git_sha_source" ], "the miss does not name where it looked"


def test_a_failed_capture_still_stamps_the_clock():
    """
    `imported_at` is the LOAD-BEARING field — the sha is a convenience. If a git
    failure took the clock down with it, the module would lose the very thing that
    makes it useful in the case where you most need it.
    """
    got = ci.capture_code_identity( project_root="/r", runner=_FailingRunner() )
    assert got[ "git_sha" ] == ci.UNAVAILABLE
    assert got[ "imported_at" ]


# ── the freeze, and the control that makes the freeze measurable ──────────

def test_the_counting_runner_actually_counts():
    """
    INSTRUMENT CHECK, before anything is concluded from it. The freeze test's whole
    force comes from this runner returning a different answer each call. If it
    returned a constant, "the value did not change" would prove nothing at all.
    """
    runner = _CountingRunner()
    first  = ci.capture_code_identity( project_root="/r", runner=runner )
    second = ci.capture_code_identity( project_root="/r", runner=runner )
    assert first[ "git_sha" ] != second[ "git_sha" ], "the instrument is a constant"


def test_the_patched_runner_WOULD_have_changed_the_answer( monkeypatch ):
    """
    THE CONTROL. Patch the module's default runner to one that changes its answer,
    then drive the CAPTURE path. It must move.

    Without this, the freeze test below could pass because the patch never took
    effect — a green that measures the patch's failure rather than the code's
    behaviour.
    """
    monkeypatch.setattr( ci.subprocess, "run", _CountingRunner() )
    first  = ci.capture_code_identity( project_root="/r" )
    second = ci.capture_code_identity( project_root="/r" )
    assert first[ "git_sha" ] != second[ "git_sha" ], (
        "the patched runner did not reach capture_code_identity — the freeze test "
        "that follows would be vacuous"
    )


def test_the_identity_is_frozen_at_import_not_recomputed_per_call( monkeypatch ):
    """
    ⚠️ THE LOAD-BEARING TEST OF THIS ROW.

    Same patch as the control above — a runner that returns a DIFFERENT sha every
    time. The control proved that patch moves `capture_code_identity`. So if
    `get_code_identity` ALSO moved, the identity would be per-request, and a
    bind-mounted container would report the host's current tree instead of the code
    it is running: this row's defect, reintroduced inside the row's remedy.

    It must not move.
    """
    monkeypatch.setattr( ci.subprocess, "run", _CountingRunner() )
    first  = ci.get_code_identity()
    second = ci.get_code_identity()
    assert first == second, (
        "get_code_identity() re-read the tree — the capture has escaped module import "
        "and now answers 'what is on disk NOW', which is the wrong question"
    )
    assert first[ "git_sha" ] == ci._FROZEN_IDENTITY[ "git_sha" ]


def test_get_code_identity_returns_a_COPY_so_a_caller_cannot_corrupt_the_record():
    """
    A frozen fact that any handler can edit in place is not frozen. `/health` hands
    this dict straight into a JSON response; one middleware mutating it would change
    what every later caller reads, permanently and invisibly.
    """
    first = ci.get_code_identity()
    first[ "git_sha" ] = "tampered"
    assert ci.get_code_identity()[ "git_sha" ] != "tampered"


def test_imported_at_does_not_move_between_calls():
    """
    The field a caller compares against a commit's author date. If it tracked "now"
    it would always be newer than every commit and would certify EVERYTHING — the
    quietest possible failure, since the answer would always be the reassuring one.
    """
    assert ci.get_code_identity()[ "imported_at" ] == ci.get_code_identity()[ "imported_at" ]


# ── the endpoints actually serve it ───────────────────────────────────────

def test_both_health_endpoints_serve_the_frozen_identity():
    """
    Wiring check — the module can be perfect and still be unreachable; a remedy
    nobody can call is a remedy in name only.

    ⚠️ This test's first draft asserted only that the router had IMPORTED the
    function. That is a claim about a name binding, not about a response body — an
    endpoint could import it and never call it and the test would still be green.
    A receipt narrower than its claim reads true anyway, which is this row's own
    lesson. It now INVOKES both handlers and reads what they return.
    """
    import asyncio
    from cosa.rest.routers import system

    root = asyncio.run( system.health_check() )
    assert root[ "code_identity" ] == ci.get_code_identity(), "/ serves a different record"

    dedicated = asyncio.run( system.code_identity() )
    assert dedicated == ci.get_code_identity(), "/api/code-identity serves a different record"
    assert dedicated[ "imported_at" ], "the dedicated endpoint has no import clock"


def test_the_MINIMAL_health_endpoint_stays_minimal():
    """
    ⚠️ A REVERT, PINNED. `code_identity` was added to `/health` first and taken back
    out. That endpoint's stated contract is "minimal response for high-frequency
    health checks", it backs a docker healthcheck firing every 30s, and
    `test_system_router.py::test_health_endpoint` asserts the field count — an
    assertion that CAUGHT the growth.

    The assertion was right and the change was wrong, so the change moved rather than
    the assertion. This test states the reason next to the constraint, so the next
    person tempted to enrich `/health` finds out here instead of from a failing
    unittest with no context.
    """
    import asyncio
    from cosa.rest.routers import system

    body = asyncio.run( system.health() )
    assert set( body ) == { "status", "timestamp" }, (
        "/health grew a field — it backs a 30s docker healthcheck and its contract "
        "is minimal; put the payload on /api/code-identity instead"
    )


def test_the_endpoint_serves_an_identity_that_does_NOT_move_between_requests():
    """
    The behaviour a caller depends on, asserted at the SURFACE rather than inferred
    from the module. `/`'s own `timestamp` must move (it says when you asked);
    `imported_at` must not (it says when the code was loaded). If they moved
    together, every commit would look older than the process and the field would
    certify EVERYTHING — the quietest possible failure, since the answer would
    always be the reassuring one.
    """
    import asyncio
    from cosa.rest.routers import system

    first  = asyncio.run( system.code_identity() )
    second = asyncio.run( system.code_identity() )
    assert first[ "imported_at" ] == second[ "imported_at" ]
    assert first[ "git_sha" ]     == second[ "git_sha" ]


def test_the_module_docstring_warns_that_a_PER_REQUEST_read_reproduces_the_bug():
    """
    Pins the non-obvious constraint in prose next to the code, because the natural
    "improvement" — compute it fresh so it's always current — is precisely the
    defect. A future reader who moves the capture into the getter must trip over
    this sentence, and over the test above it.
    """
    text = ci.__doc__
    assert "IMPORT" in text
    assert "PER REQUEST" in text
