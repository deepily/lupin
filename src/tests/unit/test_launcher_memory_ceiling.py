"""
The per-session memory ceiling the LAUNCHER actually enforces — row `df5c3696`.

WHY THIS FILE EXISTS, and it is the whole point: on 2026-08-25 Rick ruled the
ceiling down to 8G, and three days later the fleet was still launching every
session at 24G. Nothing was broken and nobody ignored him. There were simply TWO
implementations of the same idea — `src/cosa/utils/memory_cap.py` on the
unmerged branch `wip-oom-containment-df5c3696`, and this launcher's own block at
`start-cc-with-tmux.sh` — and the ruling was applied to the one that does not
run. The live scopes were read directly to find it: `MemoryMax=25769803776`
(24 GiB) on a running session while the row said 8G.

⇒ NO TEST PINNED THE LAUNCHER'S DEFAULT. That is why the gap survived a direct
ruling: the number lived in exactly one place, and that place was not covered.
This file covers it.

WHAT IS PINNED HERE, and why each is here rather than trusted:

· THE CEILING IS 8G. Pinned as a literal, with the ruling, so a silent drift
  back upward goes red instead of reading as reasonable.

· THE CEILING x CONCURRENCY PROPERTY. A per-session cap bounds one SESSION at
  any value; it bounds the MACHINE only if ceiling x concurrency stays under
  RAM. At the ~24 sessions live on the OOM day, 16G is 384 GB and 24G is 576 GB
  against a 251 GiB box — neither protects the box at all. This test asserts the
  PROPERTY, not the number, so a future "just a bit higher" fails on arithmetic
  rather than on taste. It is the guard that discriminates: 4G passes it while
  failing the literal pin.

· MemorySwapMax=0 IS PRESENT. Measured 2026-08-22: MemoryMax=64M against a
  512 MB allocator RAN TO COMPLETION, because with memory.swap.max unset the
  cgroup reclaims by swapping instead of killing. The swap bound is not a
  refinement of the cap, it is the half that makes it bind — so dropping it
  leaves a cap that looks configured and enforces nothing.

· 🔴 MemoryHigh IS ABSENT. A soft limit throttles and reclaims instead of
  killing, manufacturing the sustained reclaim pressure systemd-oomd's PSI
  criterion picks victims on — so it can help CAUSE the kill it was meant to
  soften, and oomd chooses by pressure rather than by fault. The capped JS-test
  lane reached this independently and pins the same thing
  (`test_jstest_lane.py`); this launcher carried `MemoryHigh=18G` until
  2026-08-25. A future edit helpfully adding it back must go red.

· THE ESCAPE HATCH STILL WORKS. `CC_MEM_LIMIT=off` disables the cap, and an
  operator override reaches the pane. A ceiling nobody can lift in an emergency
  gets removed wholesale rather than adjusted.

Venue: :7999 bucket — `--dry-run` exits before any tmux call, so no session is
created and no persistent state is touched. Under 2s.

See: row df5c3696 · src/rnd/v0.2.0/2026.08.22-oom-incident-what-we-know.md
"""

import os
import re
import subprocess

import pytest


LUPIN_ROOT  = os.environ[ "LUPIN_ROOT" ]
SCRIPT_PATH = os.path.join( LUPIN_ROOT, "src", "scripts", "start-cc-with-tmux.sh" )

# Rick's ruling, 2026-08-25: "shrink into 8".
RULED_CEILING_GB = 8

# The box this fleet runs on, and the concurrency the OOM day actually carried.
# 251 GiB total; ~24 Claude Code sessions live when the kernel started killing.
BOX_RAM_GB        = 251
OOM_DAY_SESSIONS  = 24


def _base_env( home ):
    """Minimal hermetic env — a throwaway HOME so no fleet roster or ambient
    CC_MEM_* value from the operator's shell can reach the script.

    ⚠️ XDG_RUNTIME_DIR IS LOAD-BEARING HERE, not incidental. The launcher's cap
    block is guarded on `command -v systemd-run` AND a non-empty
    XDG_RUNTIME_DIR, so omitting it skips the whole block — and then EVERY
    assertion about the composed scope passes or fails for the wrong reason.
    The `CC_MEM_LIMIT=off` check in particular passes vacuously without it:
    no systemd-run appears, but not because `off` was honoured. Caught by
    watching three assertions go red on a launcher that was in fact correct.
    """
    return {
        "PATH"             : os.environ[ "PATH" ],
        "LUPIN_ROOT"       : LUPIN_ROOT,
        "HOME"             : str( home ),
        "XDG_RUNTIME_DIR"  : os.environ.get( "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}" ),
    }


def _dry_run( env, session_name="mem-ceiling-test-session" ):
    """Run the launcher in --dry-run and return stdout, which carries the fully
    expanded INNER command string on the `tmux new-session ...` line."""
    argv = [ "bash", SCRIPT_PATH, "--dry-run", "--headless", session_name ]
    result = subprocess.run( argv, env=env, capture_output=True, text=True, timeout=30 )
    return result.stdout + result.stderr


def _memory_max( text ):
    """Pull the MemoryMax value the launcher composed, or None if it emitted none."""
    match = re.search( r"MemoryMax=(\S+?)(?:\s|'|\"|$)", text )
    return match.group( 1 ) if match else None


@pytest.fixture
def env( tmp_path ):
    return _base_env( tmp_path )


class TestTheRuledCeiling:

    def test_default_ceiling_is_8g( self, env ):
        """THE PIN. Rick ruled 8G on 2026-08-25; the launcher default is the one
        place that number lives, and it went unpinned for three days while the
        fleet ran at 24G."""
        composed = _dry_run( env )
        assert _memory_max( composed ) == "8G", (
            f"launcher composed MemoryMax={_memory_max( composed )!r}, expected '8G' "
            "(Rick's 2026-08-25 ruling). If this was changed deliberately, change "
            "the ruling first — see row df5c3696."
        )

    def test_ceiling_times_oom_day_concurrency_fits_the_box( self ):
        """THE PROPERTY, not the number. A per-session cap bounds the MACHINE
        only if ceiling x concurrency stays under RAM. This is what makes 16G
        and 24G wrong rather than merely generous, and it is deliberately
        satisfiable by values the literal pin above rejects (4G passes here)."""
        total = RULED_CEILING_GB * OOM_DAY_SESSIONS
        assert total < BOX_RAM_GB, (
            f"{RULED_CEILING_GB}G x {OOM_DAY_SESSIONS} sessions = {total} GB, which "
            f"exceeds the {BOX_RAM_GB} GB box. A ceiling that fails this stops ONE "
            "runaway while several at once still take the machine down."
        )

    @pytest.mark.parametrize( "rejected_gb", [ 16, 24 ] )
    def test_the_rejected_ceilings_fail_the_property( self, rejected_gb ):
        """The positive control for the test above: prove the property has teeth
        by showing the two values actually proposed for this cap both fail it.
        Without this, a property that everything passes reads as a guard."""
        total = rejected_gb * OOM_DAY_SESSIONS
        assert total >= BOX_RAM_GB, (
            f"{rejected_gb}G x {OOM_DAY_SESSIONS} = {total} GB was expected to exceed "
            f"the {BOX_RAM_GB} GB box; if the box grew, update BOX_RAM_GB and re-derive "
            "the ceiling rather than deleting this control."
        )


class TestTheHalfThatMakesItBind:

    def test_swap_bound_is_emitted( self, env ):
        """MemoryMax alone does not bind — measured 2026-08-22, a 64M cap let a
        512 MB allocator run to completion by swapping past it. Dropping this
        leaves a cap that looks configured and enforces nothing."""
        composed = _dry_run( env )
        assert "MemorySwapMax=0" in composed, (
            "MemorySwapMax=0 is missing. Without it the cgroup reclaims by swapping "
            "rather than killing, and the ceiling above is decorative."
        )


class TestNoSoftLimit:

    def test_memory_high_is_not_emitted( self, env ):
        """🔴 A soft limit manufactures the reclaim pressure systemd-oomd selects
        victims on, so it can help cause the kill it was meant to soften — and
        oomd picks by pressure, not by fault. This launcher carried
        MemoryHigh=18G until 2026-08-25. Do not add it back."""
        composed = _dry_run( env )
        # Match the systemd property as composed, not the word in a comment.
        assert not re.search( r"-p\s+MemoryHigh=", composed ), (
            "the launcher emitted a MemoryHigh property. A soft limit throttles and "
            "reclaims instead of killing, driving up the slice pressure oomd chooses "
            "victims by — see the same conclusion in test_jstest_lane.py."
        )


class TestTheEscapeHatch:

    def test_off_disables_the_cap_entirely( self, env ):
        """A ceiling nobody can lift in an emergency gets removed wholesale
        rather than adjusted, so the hatch is part of the guard.

        The positive control below is what makes this mean anything: without it
        an environment that cannot compose a scope at all would satisfy this
        assertion for the wrong reason."""
        capped = _dry_run( env )
        assert "systemd-run" in capped, (
            "PRECONDITION FAILED: the default env did not compose a scope at all, so "
            "the `off` assertion below would pass vacuously. Check XDG_RUNTIME_DIR and "
            "that systemd-run is on PATH."
        )

        env[ "CC_MEM_LIMIT" ] = "off"
        composed = _dry_run( env )
        assert "systemd-run" not in composed, (
            "CC_MEM_LIMIT=off must skip the scope entirely; the launcher still "
            "composed a systemd-run invocation."
        )

    def test_operator_override_reaches_the_pane( self, env ):
        """The default is a default, not a hard-code — an operator raising it for
        one heavy session must actually take effect."""
        env[ "CC_MEM_LIMIT" ] = "12G"
        composed = _dry_run( env )
        assert _memory_max( composed ) == "12G", (
            f"override CC_MEM_LIMIT=12G did not reach the pane; composed "
            f"MemoryMax={_memory_max( composed )!r}."
        )
