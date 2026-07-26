"""
`lupin-vm.sh preflight` argument handling — row c8f60c22.

THE DEFECT
----------
The verb took a bare POSITIONAL phase while the script it wraps takes
`--phase <val>`. So the obvious invocation

    lupin-vm.sh preflight --phase pre

forwarded `--phase --phase` to `preflight-vm.sh`, which aborted. It aborted
LOUDLY — that part is the design working — but the error named the INNER
script's argument handling for a mistake made at the OUTER verb, sending the
reader to the wrong file. Two interfaces for one concept with nothing
reconciling them.

⚠️ AND IT WAS AN INJECTION POINT, not only a typo. `PF_PHASE` is interpolated
into the remote `--command` string handed to `gcloud compute ssh`. Unvalidated,
anything the caller types runs on the VM. The whitelist fixes both.

TWO KINDS OF ARM, AND THE SECOND IS THE ONE THAT MATTERS
--------------------------------------------------------
The first half asserts the SHAPE of the guard in the script source — a whitelist
exists, it names exactly the three legal phases, the failure paths call `die`.

Shape alone is not enough: those assertions would all stay green if `die` had
been spelled `echo`. So the second half RUNS the verb. `--dry-run` prints the
gcloud command it would issue and exits without executing it, which makes the
accept-path observable with no SSH, no network and no VM, while the reject-paths
never reach gcloud at all.

⚠️ WHAT A GREEN HERE STILL DOES NOT MEAN: that the phase the guard lets through
is one the VM will accept. That is the inner script's contract, covered by
test_preflight_vm_lib.py, and it was exercised live against the VM on 2026-07-26
(`preflight` → passed=27 warnings=5 blocking=0).

Venue: :7999-eligible. Spawns `bash lupin-vm.sh --dry-run` in a subprocess with a
fake project id; no network, no VM, no state touched.
"""
import os
import pathlib
import re

import pytest


SCRIPT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lupin-vm.sh"

LEGAL_PHASES = ( "pre", "post", "full" )


@pytest.fixture( scope="module" )
def preflight_block():
    """
    The `preflight)` case arm's source text.

    Ensures:
        - returns the text from the `preflight)` label up to its `;;` terminator
        - raises rather than returning empty if the arm cannot be located — an
          empty string would make every assertion below pass vacuously, which is
          the failure mode this file's sibling comparators keep running into
    """
    src = SCRIPT.read_text()
    m   = re.search( r"^\s*preflight\)\s*$(.*?)^\s*;;\s*$", src, re.M | re.S )
    assert m, "could not locate the `preflight)` case arm — the scan would pass vacuously"
    block = m.group( 1 )
    assert block.strip(), "the preflight arm parsed to empty text"
    return block


def test_the_phase_is_validated_against_a_whitelist( preflight_block ):
    """
    The guard must EXIST. Without it, an unknown phase is forwarded verbatim into
    a remote `--command` string.
    """
    assert re.search( r"case\s+\"?\$PF_PHASE\"?\s+in", preflight_block ), (
        "no `case $PF_PHASE in` whitelist in the preflight arm — an unvalidated "
        "phase is interpolated into the remote gcloud --command string"
    )


def test_the_whitelist_names_exactly_the_three_legal_phases( preflight_block ):
    """
    Pins the allowed set. A whitelist that quietly grew a fourth entry would pass
    a mere "is there a case statement" check.
    """
    m = re.search( r"case\s+\"?\$PF_PHASE\"?\s+in(.*?)esac", preflight_block, re.S )
    assert m, "whitelist present but unparseable"
    arms = m.group( 1 )

    accepted = re.search( r"^\s*([a-z|]+)\)\s*;;\s*$", arms, re.M )
    assert accepted, "no accept-arm found in the whitelist"
    assert set( accepted.group( 1 ).split( "|" ) ) == set( LEGAL_PHASES ), (
        f"the accept-arm is {accepted.group( 1 )!r}; expected exactly {'|'.join( LEGAL_PHASES )}"
    )


def test_an_unknown_phase_dies_rather_than_being_forwarded( preflight_block ):
    """
    The catch-all must ABORT. Falling through would send the bad value to the VM,
    which is both the original bug and the injection path.
    """
    m = re.search( r"case\s+\"?\$PF_PHASE\"?\s+in(.*?)esac", preflight_block, re.S )
    arms = m.group( 1 )
    catch_all = re.search( r"^\s*\*\)\s*(.+)$", arms, re.M )
    assert catch_all, "no catch-all `*)` arm — an unknown phase falls through silently"
    assert "die" in catch_all.group( 1 ), f"the catch-all does not die: {catch_all.group( 1 )!r}"


def test_the_inner_scripts_own_flag_spelling_is_accepted( preflight_block ):
    """
    THE ROW ITSELF. `--phase pre` is what the wrapped script takes and what a
    reader will type; the verb must consume it rather than forwarding it as a
    phase value.
    """
    assert re.search( r'\$PF_PHASE"?\s*=\s*"--phase"', preflight_block ), (
        "the verb does not recognise `--phase` — `lupin-vm.sh preflight --phase pre` "
        "will forward `--phase --phase` and abort inside preflight-vm.sh, naming the "
        "wrong file for the caller's mistake"
    )


def test_a_flag_with_no_value_dies_with_a_usage_message( preflight_block ):
    """`preflight --phase` (nothing after it) must not resolve to the empty string."""
    m    = re.search( r"case\s+\"?\$PF_PHASE\"?\s+in(.*?)esac", preflight_block, re.S )
    arms = m.group( 1 )
    empty_arm = re.search( r'^\s*""\)\s*(.+)$', arms, re.M )
    assert empty_arm, "no empty-value arm — `preflight --phase` would pass \"\" through"
    assert "die" in empty_arm.group( 1 )


def test_the_default_is_still_full( preflight_block ):
    """A bare `lupin-vm.sh preflight` must keep its documented default."""
    assert re.search( r'PF_PHASE="\$\{1:-full\}"', preflight_block ), \
        "the bare-invocation default changed away from `full`"


# ── instrument controls ───────────────────────────────────────────────────

def test_the_block_extractor_finds_a_real_arm( preflight_block ):
    """
    NEGATIVE CONTROL for the fixture. If the regex silently stopped matching, the
    fixture would raise — but if it matched something EMPTY, every assertion above
    would pass on nothing. Pins that it captured the real code.
    """
    assert "gcloud compute ssh" in preflight_block, "extracted arm does not contain the ssh call"
    assert "preflight-vm.sh" in preflight_block,    "extracted arm does not invoke the inner script"


def test_the_extractor_would_NOT_match_a_different_verb():
    """
    Proves the arm regex is anchored to `preflight)` specifically and is not
    matching the first `;;`-terminated block it finds.
    """
    fake = "\nsomething-else)\n    echo hi\n    ;;\n"
    assert re.search( r"^\s*preflight\)\s*$(.*?)^\s*;;\s*$", fake, re.M | re.S ) is None


# ── BEHAVIORAL ARMS — the guard actually running ──────────────────────────
#
# The text assertions above prove the guard is PRESENT. These prove it FIRES.
# `--dry-run` prints the gcloud command it would run and exits without executing,
# so the accept-path is observable with no SSH, no network, and no VM. The
# reject-paths never reach gcloud at all.
#
# This is the arm the row was missing: shape-only tests would have stayed green
# if `die` had been spelled `echo`.

import subprocess


def _run( *args ):
    """
    Invoke lupin-vm.sh with a fake project id and no side effects.

    Ensures:
        - returns ( returncode, combined_output )
        - LUPIN_GCP_PROJECT_ID is supplied so `require_project` cannot be the thing
          that fails — otherwise every arm below would pass for the wrong reason
        - never raises; a timeout is a failure, not a hang
    """
    env = dict( os.environ, LUPIN_GCP_PROJECT_ID="test-project-not-real" )
    p   = subprocess.run( [ "bash", str( SCRIPT ), *args ], env=env, timeout=60,
                          capture_output=True, text=True )
    return p.returncode, ( p.stdout + p.stderr )


def test_BEHAVIOR_an_unknown_phase_aborts_before_any_gcloud_call():
    rc, out = _run( "preflight", "bogus" )
    assert rc != 0, "an unknown phase exited 0"
    assert "unknown phase 'bogus'" in out
    assert "gcloud compute ssh" not in out, "the bad phase reached the gcloud command line"


def test_BEHAVIOR_a_valueless_flag_aborts_with_usage():
    rc, out = _run( "preflight", "--phase" )
    assert rc != 0
    assert "no value" in out and "pre|post|full" in out
    assert "gcloud compute ssh" not in out


def test_BEHAVIOR_the_flag_form_forwards_ONE_phase_not_two():
    """
    THE ORIGINAL BUG, asserted directly. Before the fix this produced
    `--phase --phase`, which the inner script rejected.
    """
    rc, out = _run( "--dry-run", "preflight", "--phase", "pre" )
    assert rc == 0, out
    assert "preflight-vm.sh --phase pre" in out
    assert "--phase --phase" not in out, "the flag form still double-forwards"


def test_BEHAVIOR_the_positional_form_still_works():
    """The spelling that always worked must keep working."""
    rc, out = _run( "--dry-run", "preflight", "post" )
    assert rc == 0, out
    assert "preflight-vm.sh --phase post" in out


def test_BEHAVIOR_bare_invocation_defaults_to_full():
    rc, out = _run( "--dry-run", "preflight" )
    assert rc == 0, out
    assert "preflight-vm.sh --phase full" in out


def test_BEHAVIOR_both_spellings_produce_the_IDENTICAL_command():
    """
    The two interfaces now converge — which is the point of the fix, not a side
    effect. If they ever diverge again, one of them is the trap.
    """
    _, positional = _run( "--dry-run", "preflight", "pre" )
    _, flagged    = _run( "--dry-run", "preflight", "--phase", "pre" )
    assert "preflight-vm.sh --phase pre" in positional
    assert "preflight-vm.sh --phase pre" in flagged
