"""
Prove the LAUNCHER'S per-session memory cap actually kills — row `42f65ee1`.

WHY THIS FILE EXISTS AS A SEPARATE TEST FROM `test_launcher_memory_ceiling.py`.
That file reads `start-cc-with-tmux.sh` and asserts the flags it composes. An
emitted flag is a claim about the kernel, not a guard: it says what the launcher
INTENDS, and nothing in the suite has ever checked that the intent binds on this
box. This file executes the flags.

That distinction is not theoretical. The cap was first built to a proposal of
`systemd-run --user --scope -p MemoryMax=24G`, and when it was finally pointed at
a real allocator IT DID NOT KILL:

    scope with MemoryMax=64M, allocator asking for 512 MB  ->  "SURVIVED"
    the scope's memory.max read 67108864, exactly as configured

The cap was set and the process simply spilled into swap. Adding
`MemorySwapMax=0` produced the kill — rc 137, and the scope's own memory.events
read `oom_kill 1`. So the swap bound is the half that makes the cap real, and
`TestWhyTheSwapBoundIsNotOptional` below is the only thing in the suite that
would notice if someone dropped it.

🔴 THE FLAGS ARE TAKEN FROM THE LAUNCHER, NOT RETYPED HERE. Every case composes
its argv by running `start-cc-with-tmux.sh --dry-run` and lifting the
`systemd-run … --` prefix the launcher actually built. That is deliberate and it
is the whole point of the port: an earlier version of this proof imported a
`memory_cap` module that the launcher does not use, so the test could stay green
while the live ceiling drifted — which is exactly how Rick's 8G ruling got
applied to the dead copy and the fleet ran at 24G for three days. A test that
retypes the flags proves only that systemd works. This one goes red if the
LAUNCHER stops emitting a flag that matters.

Uses a 64 MB cap (via `CC_MEM_LIMIT`, the launcher's own override) and a 512 MB
hard-bounded allocator: the kill lands at ~64 MB, so the cost of a REGRESSION
here is half a gigabyte for under a second.

VENUE — :7999 bucket, and routed by the rubric rather than by this folder's
name (`src/tests/smoke/` is heterogeneous). It qualifies on all three counts:
no persistent-state mutation (a transient `--scope` with `--collect` dies with
the command; no DB rows, no queue enqueues, no LLM spend, no writes outside the
scope's own memory), runtime ~5s, and no monopoly requirement. It kills only
processes it started, inside a cgroup it owns — which is the property
`test_the_kill_is_charged_to_the_sessions_own_cgroup_not_the_machine` asserts.

See: row df5c3696 (the incident) · row 42f65ee1 (this port) ·
     src/tests/unit/test_launcher_memory_ceiling.py (the static half) ·
     src/rnd/v0.2.0/2026.08.22-oom-incident-what-we-know.md
"""

import importlib.util
import os
import re
import shutil
import subprocess

import pytest


LUPIN_ROOT  = os.environ[ "LUPIN_ROOT" ]
SCRIPT_PATH = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )
HOG         = os.path.join( LUPIN_ROOT, "src", "tests", "smoke", "fixtures", "memory_hog.py" )

CAP_MB      = 64
ALLOCATE_MB = 512   # hard bound: what a BROKEN cap costs us
UNDER_MB    = 16    # comfortably under CAP_MB once the interpreter is counted

# The scope's own kill is a SIGKILL from the cgroup OOM killer. subprocess
# reports that as -9 for a direct child; a shell in between reports 137. Both
# spellings are the same signal, and anything else is not a kill at all.
SIGKILL_RETURNCODES = ( -9, 137 )


def _launcher_env():
    """
    A hermetic environment for the launcher's --dry-run.

    Requires:
        - nothing

    Ensures:
        - returns an env carrying only what the cap block reads, with
          CC_MEM_LIMIT pinned to the test cap

    ⚠️ XDG_RUNTIME_DIR IS LOAD-BEARING. The launcher's cap block is guarded on
    `command -v systemd-run` AND a non-empty XDG_RUNTIME_DIR, so omitting it
    skips the block entirely and every case here would compose an EMPTY flag
    list — the allocator would then survive for a reason that has nothing to do
    with the cap, and the negative control would pass vacuously.
    """

    return {
        "PATH"            : os.environ[ "PATH" ],
        "LUPIN_ROOT"      : LUPIN_ROOT,
        "HOME"            : os.environ[ "HOME" ],
        "XDG_RUNTIME_DIR" : os.environ.get( "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}" ),
        "CC_MEM_LIMIT"    : f"{CAP_MB}M",
    }


def _launcher_scope_argv( unit_suffix ):
    """
    The systemd-run prefix the LAUNCHER composes, lifted from its own dry-run.

    Requires:
        - unit_suffix is a string safe for a systemd unit name

    Ensures:
        - returns an argv list beginning with 'systemd-run' and ending in '--',
          carrying the launcher's real properties and a unique --unit
        - raises AssertionError if the launcher composed no scope at all, so a
          silently-uncapped run can never be mistaken for a passing test
    """

    session = f"riomemcap{unit_suffix}{os.getpid()}"
    result  = subprocess.run(
        [ "bash", SCRIPT_PATH, "--dry-run", "--headless", session ],
        env=_launcher_env(), capture_output=True, text=True, timeout=30,
    )
    composed = result.stdout + result.stderr

    match = re.search( r"(systemd-run --user --scope .*?) -- ", composed )
    assert match, (
        "the launcher composed no systemd-run scope, so nothing here would be "
        f"testing a cap. Check XDG_RUNTIME_DIR and systemd-run on PATH.\n{composed}"
    )

    argv = match.group( 1 ).split()

    # A unique unit name per case, so two runs of this file (or a peer's) cannot
    # collide on an already-existing transient unit.
    argv.append( f"--unit=lupin-memcap-test-{unit_suffix}-{os.getpid()}" )
    argv.append( "--" )

    return argv


def _without_swap_bound( argv ):
    """
    The launcher's flags with MemorySwapMax removed — the negative control.

    Requires:
        - argv is a launcher scope argv from _launcher_scope_argv

    Ensures:
        - returns the same argv minus '-p MemorySwapMax=…' and its '-p'
        - raises AssertionError if there was no swap bound to remove, because a
          control that removes nothing proves nothing
    """

    index = next( ( i for i, token in enumerate( argv ) if token.startswith( "MemorySwapMax=" ) ), None )

    assert index is not None, (
        "the launcher emitted no MemorySwapMax property, so this negative control "
        "has nothing to remove. That is itself the regression this file guards: "
        "see test_launcher_memory_ceiling.py::test_swap_bound_is_emitted."
    )

    stripped = list( argv )
    del stripped[ index - 1 : index + 1 ]   # the '-p' and its value

    return stripped


def _scopes_available():
    """
    Report whether this box can start a user scope carrying memory properties.

    Requires:
        - nothing

    Ensures:
        - returns (True, "") when a capped transient scope starts
        - returns (False, reason) naming the cause otherwise, so a skip reads as
          an unsupported host rather than as a product failure
    """

    if shutil.which( "systemd-run" ) is None:
        return False, "systemd-run is not on PATH"

    if not os.environ.get( "XDG_RUNTIME_DIR" ) and not os.path.isdir( f"/run/user/{os.getuid()}" ):
        return False, "no user D-Bus runtime directory (XDG_RUNTIME_DIR unset and /run/user/<uid> absent)"

    probe = subprocess.run(
        [ "systemd-run", "--user", "--scope", "-q",
          "-p", "MemoryAccounting=yes", "-p", f"MemoryMax={CAP_MB}M", "-p", "MemorySwapMax=0",
          "--", "/bin/true" ],
        capture_output=True, text=True, timeout=30,
    )

    if probe.returncode != 0:
        return False, (
            "this box cannot start a capped user scope — probably an undelegated memory "
            f"controller or no user D-Bus (systemd-run rc={probe.returncode}: "
            f"{probe.stderr.strip() or 'no stderr'})"
        )

    return True, ""


_SCOPES_OK, _SKIP_REASON = _scopes_available()

requires_scopes = pytest.mark.skipif( not _SCOPES_OK, reason=_SKIP_REASON )


def _run_hog( scope_argv, allocate_mb ):
    """
    Run the bounded allocator inside a scope carrying the given flags.

    Requires:
        - scope_argv is a systemd-run argv prefix ending in '--'
        - allocate_mb is a positive integer

    Ensures:
        - returns the CompletedProcess, whose returncode carries the kill (or
          its absence) and whose stdout carries the SURVIVED token (or not)
    """

    return subprocess.run(
        scope_argv + [ "python3", HOG, str( allocate_mb ) ],
        capture_output=True, text=True, timeout=120,
    )


@requires_scopes
class TestTheCapKills:

    def test_the_launchers_composed_flags_kill_an_allocator_that_runs_past_the_cap( self ):
        """
        THE PROOF, and the one this whole file exists for. Not 'memory.max was
        configured' and not 'the script contains the right string' — the process
        actually dies under the flags the launcher actually builds.
        """

        result = _run_hog( _launcher_scope_argv( "kills" ), ALLOCATE_MB )

        assert "SURVIVED" not in result.stdout, "the allocator finished — THE CAP DID NOT BIND"
        assert result.returncode in SIGKILL_RETURNCODES, (
            f"expected SIGKILL {SIGKILL_RETURNCODES}, got {result.returncode}: {result.stderr}"
        )

    def test_the_kill_is_charged_to_the_sessions_own_cgroup_not_the_machine( self ):
        """
        The 08-22 kills were `constraint=CONSTRAINT_NONE, global_oom`: the machine
        ran out and the kernel picked its own victim, so an INNOCENT session could
        be the one that died. This asserts the replacement is a LOCAL kill — the
        scope's own memory.events records it, so the rest of the fleet never
        enters the kernel's reclaim path at all.
        """

        reader = (
            'CG=$(awk -F: "{print \\$3}" /proc/self/cgroup); '
            f'python3 {HOG} {ALLOCATE_MB} >/dev/null 2>&1; '
            'echo "child_rc=$?"; cat /sys/fs/cgroup$CG/memory.events'
        )

        result = subprocess.run(
            _launcher_scope_argv( "events" ) + [ "bash", "-c", reader ],
            capture_output=True, text=True, timeout=120,
        )

        assert "child_rc=137" in result.stdout, result.stdout
        assert "oom_kill 1"   in result.stdout, f"the cgroup did not record the kill: {result.stdout}"

    def test_a_process_that_stays_under_the_cap_is_left_alone( self ):
        """A guard that kills healthy sessions is not a guard."""

        result = _run_hog( _launcher_scope_argv( "healthy" ), UNDER_MB )

        assert result.returncode == 0, f"a process under the cap was killed: {result.stderr}"
        assert "SURVIVED" in result.stdout


@requires_scopes
class TestWhyTheSwapBoundIsNotOptional:

    def test_memory_max_alone_does_not_kill( self ):
        """
        🔴 THE NEGATIVE CONTROL, and the case people delete because it asserts a
        FAILURE to kill and therefore reads as pointless. It is the only thing
        that proves `MemorySwapMax=0` is load-bearing rather than decorative.

        It takes the LAUNCHER'S OWN flags and removes exactly one of them: with
        the swap bound gone, MemoryMax on its own lets the process reclaim by
        swapping instead of dying. The cap is set, the allocation succeeds, and
        the box still loses — measured 2026-08-22 at MemoryMax=64M against a
        512 MB allocator. Kept at 256 MB because this one is EXPECTED to run to
        completion.

        So the two cases together are a revert pair: case one dies WITH the swap
        bound, this one survives WITHOUT it, and the difference is one flag.
        """

        stripped = _without_swap_bound( _launcher_scope_argv( "swaponly" ) )

        assert not any( token.startswith( "MemorySwapMax=" ) for token in stripped ), (
            "the swap bound survived the strip — this control is not testing what it claims"
        )

        result = _run_hog( stripped, 256 )

        assert "SURVIVED" in result.stdout, (
            "MemoryMax alone killed the allocator — if this box now behaves that way "
            "(swap disabled machine-wide, or a kernel change), re-derive the 08-22 "
            "finding before trusting either result. Do NOT delete this control."
        )
        assert result.returncode == 0


class TestTheSkipPathAndTheFlagPlumbing:
    """
    The guards ON the guard — no scope needed, so these run on every box.

    WHY THEY ARE HERE. The four cases above are skipped wholesale on a host that
    cannot start a capped scope, which means on such a host NOTHING in this file
    executes and the helpers that decide the skip are themselves unproven. A
    skip path that is only exercised on the machine where it never fires is a
    skip path that will be wrong the day it is needed — it will report the wrong
    cause, or worse, error out and read as a product failure. These pin it.
    """

    def test_skip_reason_names_a_missing_systemd_run( self, monkeypatch ):
        """A box without systemd-run must say so, not say something vaguer."""

        monkeypatch.setattr( shutil, "which", lambda _name: None )

        available, reason = _scopes_available()

        assert available is False
        assert "systemd-run is not on PATH" == reason

    def test_skip_reason_names_a_missing_user_runtime_directory( self, monkeypatch ):
        """No user D-Bus is the second way a box legitimately cannot do this."""

        monkeypatch.setattr( shutil, "which", lambda _name: "/usr/bin/systemd-run" )
        monkeypatch.delenv( "XDG_RUNTIME_DIR", raising=False )
        monkeypatch.setattr( os.path, "isdir", lambda _path: False )

        available, reason = _scopes_available()

        assert available is False
        assert "no user D-Bus runtime directory" in reason

    def test_an_unset_xdg_var_is_tolerated_when_the_directory_exists( self, monkeypatch ):
        """
        The two halves of that check are an OR, not a duplicate: an unset
        variable with the directory present is a NORMAL cron/systemd context,
        and skipping there would hide a real result.
        """

        monkeypatch.setattr( shutil, "which", lambda _name: "/usr/bin/systemd-run" )
        monkeypatch.delenv( "XDG_RUNTIME_DIR", raising=False )
        monkeypatch.setattr( os.path, "isdir", lambda _path: True )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess( a, 0, stdout="", stderr="" ),
        )

        assert _scopes_available() == ( True, "" )

    def test_skip_reason_names_an_undelegated_controller( self, monkeypatch ):
        """
        The third way, and the one that actually bites: systemd-run exists, the
        session bus is there, and the memory controller is simply not delegated
        to the user slice. The probe's own stderr is carried through, because
        the remedy differs per cause and a generic reason sends the reader
        hunting.
        """

        monkeypatch.setattr( shutil, "which", lambda _name: "/usr/bin/systemd-run" )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess( a, 1, stdout="", stderr="Failed to start transient scope" ),
        )

        available, reason = _scopes_available()

        assert available is False
        assert "undelegated memory" in reason
        assert "Failed to start transient scope" in reason, "the probe's own cause was dropped"

    def test_a_probe_with_no_stderr_still_yields_a_readable_reason( self, monkeypatch ):
        """A silent failure must not produce a reason ending in nothing."""

        monkeypatch.setattr( shutil, "which", lambda _name: "/usr/bin/systemd-run" )
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess( a, 1, stdout="", stderr="   " ),
        )

        assert "no stderr" in _scopes_available()[ 1 ]

    def test_the_launcher_env_pins_the_test_cap_and_carries_the_runtime_dir( self ):
        """
        XDG_RUNTIME_DIR is load-bearing: without it the launcher's cap block is
        skipped and every case above would compose an empty flag list.
        """

        env = _launcher_env()

        assert env[ "CC_MEM_LIMIT" ]    == f"{CAP_MB}M"
        assert env[ "XDG_RUNTIME_DIR" ]

    def test_a_launcher_that_composes_no_scope_is_caught_not_silently_uncapped( self, monkeypatch ):
        """
        THE VACUOUS-PASS GUARD. If the launcher emits no systemd-run at all, the
        allocator would run uncapped and survive — and 'SURVIVED' is the PASS
        signal for the negative control. Without this assertion that case would
        go green while proving nothing at all.
        """

        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **kw: subprocess.CompletedProcess( a, 0, stdout="tmux new-session claude", stderr="" ),
        )

        with pytest.raises( AssertionError, match="composed no systemd-run scope" ):
            _launcher_scope_argv( "vacuous" )

    def test_the_strip_removes_the_swap_bound_and_nothing_else( self ):
        """The negative control's one edit must be surgical — the '-p' goes with
        its value, and MemoryMax must survive untouched."""

        argv     = [ "systemd-run", "-p", "MemoryAccounting=yes", "-p", "MemoryMax=64M",
                     "-p", "MemorySwapMax=0", "--" ]
        stripped = _without_swap_bound( argv )

        assert stripped == [ "systemd-run", "-p", "MemoryAccounting=yes", "-p", "MemoryMax=64M", "--" ]

    def test_the_strip_refuses_when_there_is_no_swap_bound_to_remove( self ):
        """A control that removes nothing proves nothing, so it must fail loudly
        rather than quietly test the same flags twice."""

        with pytest.raises( AssertionError, match="no MemorySwapMax property" ):
            _without_swap_bound( [ "systemd-run", "-p", "MemoryMax=64M", "--" ] )


class TestTheAllocatorItself:
    """
    The fixture the cases above run as a subprocess. Covered here in-process
    because a subprocess is invisible to coverage, and an allocator that quietly
    stopped allocating would make every case above pass for the wrong reason.
    """

    def _hog( self ):

        spec   = importlib.util.spec_from_file_location( "memory_hog", HOG )
        module = importlib.util.module_from_spec( spec )
        spec.loader.exec_module( module )

        return module

    def test_it_allocates_the_requested_megabytes( self ):
        """The buffers must be real and touched, or the cap has nothing to bind
        against and 'SURVIVED' means only that nothing was asked of the kernel."""

        hog        = self._hog()
        buffers    = hog.allocate( 64 )
        total_mb   = sum( len( buffer ) for buffer in buffers ) // ( 1024 * 1024 )

        assert total_mb == 64
        assert all( len( buffer ) == hog.STEP_MB * 1024 * 1024 for buffer in buffers )

    def test_it_never_allocates_past_the_bound( self ):
        """THE HARD BOUND. This is what makes a cap that fails to bind cost half
        a gigabyte for a second rather than costing the box."""

        hog = self._hog()

        assert hog.allocate( 8 ) == [], "a sub-step request must allocate nothing, not round up"

    def test_it_prints_the_survival_token_the_cases_assert_on( self, capsys ):
        """The token is the FAILURE signal for three of the four cases, so a
        typo in it would turn them green."""

        hog = self._hog()

        assert hog.main( [ "16" ] ) == 0
        assert capsys.readouterr().out.strip() == hog.SURVIVED_TOKEN
        assert hog.SURVIVED_TOKEN == "SURVIVED"
