"""
`verify-running-code.sh` — row ce89669e.

THE FALSE GREEN IT KILLS
------------------------
`:8000` bind-mounts `./src` but runs `reload=False`. So a source edit changes the
file inside the container immediately while the imported module stays exactly as
it was at process start.

    ⇒ The file is new. The process is old. And the obvious check reads the FILE.

Measured 2026-07-26 while verifying `69295c25`: `grep -c` inside the container
returned **3 hits, zero of them running** — the container had started 2h45m before
the fix was committed.

⚠️ AND `git` INSIDE THE CONTAINER LIES IDENTICALLY. Measured the same day:
`docker exec lupin-rest-test git rev-parse --short HEAD` → `95f357e6`, a commit
authored 17:20 EDT against a container started 12:57 EDT. The repo is bind-mounted
too, so HEAD tracks the HOST working tree, not the loaded code. **Asking git in the
container is the grep with extra steps** — which matters because "just check the
sha" is the obvious improvement over grepping, and it is not one.

⇒ The only honest question compares two clocks: process start vs commit time.

WHY THESE TESTS INJECT THE CLOCK
--------------------------------
The comparison IS the decision, so it has to be exercisable without a live
container — otherwise the only suite that could test this script would need `:8000`
up, which is the venue the script exists to be careful about. The script reads
`VERIFY_RUNNING_CODE_STARTED_AT` when set, the same injectable-seam shape the
arbiter uses for `hold_roots_fn` / `scan_fn`.

⚠️ Scope: these prove the DECISION and the exit contract. They do not prove
`docker inspect` returns what we think — that arm was exercised live against
`lupin-rest-test` on 2026-07-26 and is recorded on the row.

Venue: :7999-eligible. Runs bash + git in a subprocess; no docker, no network.
"""
import os
import pathlib
import subprocess

import pytest


SCRIPT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/verify-running-code.sh"

# Distinct by design: "does not have it" and "cannot tell" have different remedies,
# and collapsing them is the same defect class the script exists to prevent.
EXIT_HAS     = 0
EXIT_MISSING = 1
EXIT_UNKNOWN = 2


def _run( *args, started_at=None, running=None ):
    """
    Invoke the script with an optionally-injected process-start clock and
    running-state.

    Ensures:
        - returns ( returncode, combined_output )
        - never raises; a timeout is a failure, not a hang
        - when `started_at` is injected and `running` is not, the script treats the
          container as RUNNING — an injected clock stands in for a live container
    """
    env = dict( os.environ )
    if started_at is not None:
        env[ "VERIFY_RUNNING_CODE_STARTED_AT" ] = started_at
    if running is not None:
        env[ "VERIFY_RUNNING_CODE_RUNNING" ] = running
    p = subprocess.run( [ "bash", str( SCRIPT ), *args ], env=env, timeout=60,
                        capture_output=True, text=True )
    return p.returncode, ( p.stdout + p.stderr )


@pytest.fixture( scope="module" )
def a_real_commit():
    """The repo's HEAD sha — a ref git genuinely knows, so ref-resolution is never
    the reason a test below passes or fails."""
    out = subprocess.run( [ "git", "-C", str( SCRIPT.parent.parent.parent ), "log", "-1", "--format=%h" ],
                          capture_output=True, text=True, timeout=30 )
    sha = out.stdout.strip()
    assert sha, "could not resolve HEAD — the fixture, not the script, is broken"
    return sha


# ── the decision ──────────────────────────────────────────────────────────

def test_a_process_started_AFTER_the_commit_HAS_it( a_real_commit ):
    """The safe case: the container was recreated after the fix landed."""
    rc, out = _run( "any-container", a_real_commit, started_at="2099-01-01T00:00:00Z" )
    assert rc == EXIT_HAS, out
    assert "HAS IT" in out


def test_a_process_started_BEFORE_the_commit_is_MISSING_it( a_real_commit ):
    """
    THE ROW ITSELF. The file on disk has the fix; the running process does not.
    This is the case every grep-based check reports as success.
    """
    rc, out = _run( "any-container", a_real_commit, started_at="2000-01-01T00:00:00Z" )
    assert rc == EXIT_MISSING, out
    assert "MISSING" in out


def test_the_MISSING_verdict_names_recreate_and_warns_that_restart_will_not_do( a_real_commit ):
    """
    A verdict without an executable remedy sends the reader to guess, and the
    obvious guess (`docker restart`) does not re-import a loaded module.
    """
    _rc, out = _run( "lupin-rest-test", a_real_commit, started_at="2000-01-01T00:00:00Z" )
    assert "docker rm -f" in out
    assert "RESTART will NOT" in out
    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS" in out, (
        "the remedy omits the env-var export — `docker rm -f` succeeds and then "
        "`compose up` fails to interpolate, leaving the container DOWN"
    )


# ── cannot-determine must be its own outcome ──────────────────────────────

def test_an_unknown_commit_is_CANNOT_DETERMINE_not_missing():
    """
    A ref git cannot resolve is not evidence the process lacks the code — it is
    evidence the question was malformed. Reporting it as MISSING would send someone
    to recreate a container for no reason.
    """
    rc, out = _run( "any-container", "deadbeefdeadbeef", started_at="2099-01-01T00:00:00Z" )
    assert rc == EXIT_UNKNOWN, out
    assert "CANNOT DETERMINE" in out


def test_a_down_container_is_CANNOT_DETERMINE( a_real_commit ):
    """
    ⚠️ THIS TEST USED TO PASS WHILE THE CASE IT NAMES WAS BROKEN. Measured
    2026-07-27 (Rio ⚡).

    The original body passed a container name that does not EXIST — and non-existence
    is the one down-ish state the script handled. A container that EXISTS and is
    STOPPED was uncovered, and it was the dangerous one: `docker inspect` returns the
    LAST start time for a stopped container, so the emptiness guard never fired and
    the clock comparison happily returned **HAS IT / exit 0 for a container with no
    running process at all.**

    The test NAME asserted the broad claim; the predicate covered a narrow corner of
    it. A receipt narrower than its claim reads true anyway — which is the same
    defect this whole row is about, sitting in the row's own test file.

    ⇒ The name is right and stays. The predicate now covers what the name says:
      ALL THREE down states, each a distinct verdict.
    """
    # 1. exists, was running, has stopped — the false green.
    rc, out = _run( "any-container", a_real_commit,
                    started_at="2000-01-01T00:00:00Z", running="false" )
    assert rc == EXIT_UNKNOWN, out
    assert "CANNOT DETERMINE" in out
    assert "NOT RUNNING" in out

    # 2. exists, never started — the zero sentinel is not a clock.
    rc, out = _run( "any-container", a_real_commit,
                    started_at="0001-01-01T00:00:00Z", running="false" )
    assert rc == EXIT_UNKNOWN, out
    assert "NEVER STARTED" in out

    # 3. does not exist at all — the case the original body actually tested.
    rc, out = _run( "definitely-not-a-real-container-ce89669e" )
    assert rc == EXIT_UNKNOWN, out
    assert "CANNOT DETERMINE" in out


def test_a_STOPPED_container_never_reports_HAS_IT_however_old_the_commit( a_real_commit ):
    """
    THE REGRESSION GUARD, stated as the defect rather than as the fix.

    Before 2026-07-27 this exact call returned `HAS IT` / 0. A stopped container's
    last start time is a real, recent, perfectly parseable timestamp, so every
    commit older than it certified clean — against a process that had already exited.

    The question is "does a RUNNING process have this commit". A start-clock alone
    answers "did a process ever start after this commit" — a different question with
    the same shape, which is this row's thesis wearing the fix's clothes.
    """
    rc, out = _run( "any-container", a_real_commit,
                    started_at="2099-01-01T00:00:00Z", running="false" )
    assert rc != EXIT_HAS, (
        "a STOPPED container certified a commit — the start-clock is being read "
        "without the running flag, which is the defect this row exists for"
    )
    assert rc == EXIT_UNKNOWN, out


def test_the_DOWN_remedy_says_start_it_and_does_NOT_say_recreate( a_real_commit ):
    """
    A remedy that prescribes more than the defect needs is its own defect.

    `docker rm -f` + `compose up` is the remedy for outcome 1 (stale code in a live
    process). A container that is merely DOWN needs `docker start` — recreating it
    would destroy and rebuild a container whose only problem was that nobody had
    started it.
    """
    _rc, out = _run( "lupin-rest-test", a_real_commit,
                     started_at="2000-01-01T00:00:00Z", running="false" )
    assert "docker start lupin-rest-test" in out
    assert "docker rm -f" not in out, (
        "the DOWN verdict prescribes a RECREATE — that is outcome 1's remedy, and "
        "handing it to outcome 2 collapses two situations the exit codes keep apart"
    )


def test_an_unparseable_start_time_is_CANNOT_DETERMINE_not_a_crash( a_real_commit ):
    """
    Garbage from `docker inspect` must not surface as a traceback or, worse, as a
    confident verdict.
    """
    rc, out = _run( "any-container", a_real_commit, started_at="not-a-timestamp" )
    assert rc == EXIT_UNKNOWN, out
    assert "CANNOT DETERMINE" in out


def test_no_arguments_is_CANNOT_DETERMINE():
    rc, out = _run()
    assert rc == EXIT_UNKNOWN
    assert "usage" in out.lower()


# ── the three outcomes must actually be three ─────────────────────────────

def test_the_three_exit_codes_are_pairwise_DISTINCT( a_real_commit ):
    """
    The discriminator. If MISSING and CANNOT-DETERMINE ever collapsed to one code,
    a caller could not tell "recreate the container" from "your question was wrong"
    — which is precisely the conflation this row is about, reproduced in the fix.
    """
    has,     _ = _run( "any-container", a_real_commit, started_at="2099-01-01T00:00:00Z" )
    missing, _ = _run( "any-container", a_real_commit, started_at="2000-01-01T00:00:00Z" )
    unknown, _ = _run( "any-container", "deadbeefdeadbeef", started_at="2099-01-01T00:00:00Z" )

    assert { has, missing, unknown } == { EXIT_HAS, EXIT_MISSING, EXIT_UNKNOWN }, (
        f"exit codes collapsed: has={has} missing={missing} unknown={unknown}"
    )


# ── instrument controls ───────────────────────────────────────────────────

def test_the_injected_clock_ACTUALLY_drives_the_verdict( a_real_commit ):
    """
    NEGATIVE CONTROL. Every test above rides on the injection working. If the env
    var were ignored, they would all fall through to `docker inspect` and either
    pass or fail for reasons unrelated to what they claim to test.

    One variable changed, opposite verdicts — proving the seam is live.
    """
    early, _ = _run( "any-container", a_real_commit, started_at="2000-01-01T00:00:00Z" )
    late,  _ = _run( "any-container", a_real_commit, started_at="2099-01-01T00:00:00Z" )
    assert early != late, "the injected clock changed nothing ⇒ the seam is dead and every test above is vacuous"


def test_the_injected_RUNNING_flag_ACTUALLY_drives_the_verdict( a_real_commit ):
    """
    NEGATIVE CONTROL for the second seam. The three tests above all ride on
    `VERIFY_RUNNING_CODE_RUNNING` being read; if the script ignored it they would
    still pass — the container name is fake, so `docker inspect` returns nothing and
    every one of them would land on CANNOT-DETERMINE for the WRONG reason and assert
    green anyway.

    ⇒ The control has to make the flag the ONLY difference, and it has to be a case
      where ignoring the flag gives a DIFFERENT answer. Same clock, same commit, an
      injected clock so the docker path is never reached: running=true must reach a
      real verdict, running=false must refuse to answer.
    """
    live, live_out = _run( "any-container", a_real_commit,
                           started_at="2099-01-01T00:00:00Z", running="true" )
    down, _        = _run( "any-container", a_real_commit,
                           started_at="2099-01-01T00:00:00Z", running="false" )
    assert live == EXIT_HAS, live_out
    assert down == EXIT_UNKNOWN
    assert live != down, "the running flag changed nothing ⇒ the seam is dead"


def test_an_injected_clock_alone_still_means_RUNNING( a_real_commit ):
    """
    Pins the default the pre-existing tests depend on. An injected clock stands in
    for a live container; if the default flipped to not-running, every decision test
    in this file would silently become a CANNOT-DETERMINE test and stop measuring
    the comparison they were written for — passing the whole time.
    """
    rc, out = _run( "any-container", a_real_commit, started_at="2099-01-01T00:00:00Z" )
    assert rc == EXIT_HAS, out
    assert "NOT RUNNING" not in out


def test_the_script_is_executable_and_syntactically_valid():
    """`bash -n` catches what a passing test run never reaches."""
    assert os.access( SCRIPT, os.X_OK ), f"{SCRIPT} is not executable"
    p = subprocess.run( [ "bash", "-n", str( SCRIPT ) ], capture_output=True, text=True, timeout=30 )
    assert p.returncode == 0, p.stderr


def test_the_docstring_warns_that_git_in_the_container_lies_too():
    """
    Pins the non-obvious half. "Just check the sha instead of grepping" is the
    natural improvement, and it is not one — the repo is bind-mounted, so HEAD
    tracks the host working tree. A reader who misses this replaces one false
    green with another.
    """
    text = SCRIPT.read_text()
    assert "git` INSIDE THE CONTAINER LIES" in text or "git INSIDE THE CONTAINER LIES" in text
    assert "bind-mounted" in text
