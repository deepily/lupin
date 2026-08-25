"""
`lupin-vm.sh push-bundle` argument handling and `--dry-run` honesty — row c41ec7e6 follow-up.

TWO DEFECTS, BOTH MEASURED BEFORE THIS FILE EXISTED
---------------------------------------------------
Written up in `src/rnd/v0.2.0/2026.08.24-lupin-vm-push-bundle-arg-and-dryrun-defects.md`.

1. THE MODE IS A FLAG, AND THE POSITIONAL FORM FAILS SILENTLY.
   `push-bundle <branch> checkout` puts the branch in BRANCH, then sends `checkout`
   through the same `*)` arm, which tests `[ -z "$BRANCH" ]`, finds it set, and DROPS
   the argument. Exit 0. The tree never moves.

   The asymmetry is the sharp part: a mistyped `--flag` dies loudly via `die`, while a
   plausible bare word runs and does nothing. The two ways to get it wrong have
   OPPOSITE outcomes, and the silent one is what a person reaches for — the usage text
   and the script's own `case` labels both spell the mode as `checkout`.

   Its only tell is a missing tail on the dry-run's plan line, which makes it INVISIBLE
   on the live run where it costs something: the operator believes new code is on the
   box, `.deployed-ref` never moves, and they have been handed the exact wrong answer
   row c41ec7e6 exists to remove. It caught the author on 2026-08-24.

2. `--dry-run` CONTACTS THE VM.
   `do_push_bundle` honours the flag and returns before opening a connection, but the
   POST-checkout preflight arm sits OUTSIDE that function at subcommand level, guarded
   only on `DO_CHECKOUT`. So `--dry-run … --checkout` opened an IAP tunnel and ran 59
   assertions against the live VM, under a log line claiming the tree had moved when
   nothing had. Sibling `deploy` guards the structurally identical remote call.

   Read-only, so nothing was damaged. A dry run that misstates its own contract is
   still worth a guard: it is the cheap thing you reach for when you are unsure.

HOW THESE ARE PROVEN WITHOUT A VM
---------------------------------
A STUB `gcloud` goes first on PATH. It appends its argv to a file and exits 0. That
turns "did this verb contact the VM?" into a local, deterministic file question — no
network, no IAP tunnel, no VM window, no gate to wait for.

⚠️ WHY A STUB RATHER THAN `LUPIN_SKIP_PREFLIGHT=1`. That env var also stops the arm
running, and a test using it would pass on the UNFIXED script — it would assert that
the escape hatch works, not that the dry run is honest. The stub leaves the code path
exactly as an operator meets it.

Venue: :7999-eligible. Subprocesses only, fake project id, no network, no state.
"""
import os
import pathlib
import subprocess

import pytest


SCRIPT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] ) / "src/scripts/lupin-vm.sh"

GCLOUD_STUB = """#!/bin/bash
# Records that the VM was contacted, then succeeds. Never reaches a network.
echo "$@" >> "$GCLOUD_CALL_LOG"
exit 0
"""


@pytest.fixture
def run_push_bundle( tmp_path ):
    """
    A caller for `lupin-vm.sh push-bundle` with a stubbed `gcloud`.

    Requires:
        - LUPIN_ROOT names a checkout containing src/scripts/lupin-vm.sh

    Ensures:
        - returns a callable ( *args ) -> ( CompletedProcess, gcloud_calls: list[str] )
        - `gcloud` resolves to a stub that records argv and never opens a connection
        - the project id is fake, so a leaked real call would fail rather than act
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gcloud"
    stub.write_text( GCLOUD_STUB )
    stub.chmod( 0o755 )

    call_log = tmp_path / "gcloud-calls.txt"

    def _run( *args ):
        env = dict( os.environ )
        env[ "PATH" ]                 = f"{bin_dir}:{env[ 'PATH' ]}"
        env[ "GCLOUD_CALL_LOG" ]      = str( call_log )
        env[ "LUPIN_GCP_PROJECT_ID" ] = "fake-project-for-tests"
        proc = subprocess.run(
            [ "bash", str( SCRIPT ), *args ],
            capture_output=True, text=True, env=env, timeout=120,
        )
        calls = call_log.read_text().splitlines() if call_log.exists() else []
        return proc, calls

    return _run


# ══════════════════════════════════════════════════════════════════════════════
# DEFECT 1 — a positional mode must be refused, not swallowed
# ══════════════════════════════════════════════════════════════════════════════

def test_a_positional_mode_is_refused_rather_than_dropped( run_push_bundle ):
    """THE ONE THAT COST SOMETHING. `push-bundle <branch> checkout` must not report
    success while doing nothing.

    Falsification, verified rather than claimed: with the `*)` arm written as
    `[ -z "$BRANCH" ] && BRANCH="$a"`, this exits 0 and the run degrades silently to
    fetch-only."""
    proc, _ = run_push_bundle( "--dry-run", "push-bundle", "mybranch", "checkout" )

    assert proc.returncode != 0, (
        "push-bundle accepted a stray positional 'checkout' and exited 0. The mode was "
        "DROPPED, so this run moves nothing — and on a live run no output says so."
    )
    assert "checkout" in proc.stderr, (
        "the rejection does not name the flag. The whole mistake is reaching for a bare "
        f"word the usage text spells `checkout`; stderr was: {proc.stderr!r}"
    )


def test_an_unknown_flag_is_still_refused( run_push_bundle ):
    """The pre-existing loud path, pinned so a fix for the silent one cannot trade it
    away."""
    proc, _ = run_push_bundle( "--dry-run", "push-bundle", "mybranch", "--nonsense" )
    assert proc.returncode != 0
    assert "--nonsense" in proc.stderr


def test_the_flag_form_is_accepted_and_plans_the_move( run_push_bundle ):
    """THE CONTROL THAT MAKES THE REJECTIONS MEAN SOMETHING. A guard that refused
    everything would satisfy both tests above; this pins that the correct invocation
    still reaches the moving plan, naming the checkout and the stamp."""
    proc, _ = run_push_bundle( "--dry-run", "push-bundle", "mybranch", "--checkout" )
    assert proc.returncode == 0, proc.stderr
    plan = proc.stdout + proc.stderr
    assert "checkout -B" in plan, f"the dry-run plan does not describe the checkout: {plan!r}"
    assert ".deployed-ref" in plan, (
        "the dry-run plan does not mention the stamp — the tail whose ABSENCE was the "
        "only tell that the mode had been dropped."
    )


# ══════════════════════════════════════════════════════════════════════════════
# DEFECT 2 — `--dry-run` must not contact the VM
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_with_checkout_does_not_contact_the_vm( run_push_bundle ):
    """The post-checkout preflight arm sits outside `do_push_bundle`'s DRY_RUN return,
    so `--dry-run … --checkout` SSHed and ran 59 assertions against the live VM.

    Falsification: remove the DRY_RUN guard from that arm and this goes red, because
    the stub records the call."""
    proc, calls = run_push_bundle( "--dry-run", "push-bundle", "mybranch", "--checkout" )

    assert calls == [], (
        f"--dry-run contacted the VM {len( calls )} time(s): {calls!r}. A dry run must "
        "describe what it would do, not do part of it."
    )
    assert proc.returncode == 0, proc.stderr


def test_dry_run_still_says_what_the_preflight_would_do( run_push_bundle ):
    """Silence is not the fix. Skipping the arm without saying so would leave the
    operator unaware the real run performs a preflight at all — trading a dishonest dry
    run for an incomplete one."""
    proc, _ = run_push_bundle( "--dry-run", "push-bundle", "mybranch", "--checkout" )
    plan = proc.stdout + proc.stderr
    assert "preflight" in plan.lower(), (
        f"the dry-run plan never mentions the post-checkout preflight: {plan!r}"
    )


def test_fetch_only_dry_run_contacts_nothing_either( run_push_bundle ):
    """The arm is keyed on DO_CHECKOUT, so the fetch-only path was never affected.
    Pinned so a fix cannot regress the case that was already correct."""
    _, calls = run_push_bundle( "--dry-run", "push-bundle", "mybranch" )
    assert calls == []
