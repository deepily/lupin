"""
The reap must REFUSE, not merely narrate. Row ee3d3c82.

`self_respin` fails loud when it cannot prove a memento. The reap did not: it computed
a per-seat verdict BEFORE the kill (row 0a36d83d) and then killed unconditionally,
composing `memento_alarm` afterwards — so the seat was already dead by the time anyone
could read the sentence naming what it lost. María 🌸 lost a worker's whole hour to
that shape on 2026-09-03.

🔴 THE SECOND LOOK NOW RUNS BEFORE THE KILL, AND THE KILL CONSULTS IT. The re-check
was moved ahead of the kill rather than a new one being built: a re-check AFTER the
kill measures a seat that can no longer write, so it cannot tell "never wrote" from
"killed before it could" — the kill destroys the evidence the check needs.

WHY NOT THE ASK-TIME VERDICT: it is a SNAPSHOT, not a settled finding. Row f94ab580
measured two of four alarmed seats holding complete, self-named mementos SECONDS after
their 45s window expired — one DM'd "ready for re-spin" after it had been killed and
logged unproven. Gating on that verdict withholds seats that were about to succeed.

AND IT MUST DISCRIMINATE. A gate that withheld on anything short of "verified" would
block safe reaps and get switched off within a day. `unproven_present` — THIS seat's
own file with a failed freshness gate — is the case that proves the rule has an edge.
"""

import pytest

from lupin_mcp.reap_memento import (
    seats_to_withhold, withhold_notice, WITHHOLD_KILL, PROCEED_KILL,
)


# ── The pure predicate ───────────────────────────────────────────────────────

@pytest.mark.parametrize( "status", WITHHOLD_KILL )
def test_a_seat_whose_work_is_not_provably_on_disk_is_withheld( status ):
    assert seats_to_withhold( { "worker": { "status": status } } ) == { "worker": status }


@pytest.mark.parametrize( "status", PROCEED_KILL )
def test_a_seat_that_is_safe_to_reap_is_never_withheld( status ):
    assert seats_to_withhold( { "worker": { "status": status } } ) == {}


def test_unproven_present_is_a_warning_and_not_a_refusal():
    # The edge the row names explicitly: this is THIS seat's OWN file with a gate
    # failure, so the work exists and is recoverable. Withholding here would block a
    # legitimate reap, and a gate that blocks legitimate work gets switched off.
    assert "unproven_present" in PROCEED_KILL
    assert seats_to_withhold( { "w": { "status": "unproven_present" } } ) == {}


def test_prior_holder_present_and_unproven_present_do_not_share_a_fate():
    # If someone collapses the four-way split back into "not verified", this reddens
    # while every single-status test above stays green.
    withheld = seats_to_withhold( {
        "other_seats_file" : { "status": "prior_holder_present" },
        "own_file_stale"   : { "status": "unproven_present"     },
    } )
    assert set( withheld ) == { "other_seats_file" }


def test_a_coordination_error_is_not_mistaken_for_a_seat():
    assert seats_to_withhold( { "_error": "coordination raised", "_recheck_error": "x" } ) == {}


def test_an_unknown_status_does_not_withhold():
    # The vocabulary has demonstrably drifted before. A predicate that withheld on
    # anything unrecognised would turn the next vocabulary addition into a fleet-wide
    # reap outage.
    assert seats_to_withhold( { "w": { "status": "some_future_verdict" } } ) == {}


@pytest.mark.parametrize( "outcomes", [ {}, None, { "w": None }, { "w": {} } ] )
def test_a_degenerate_outcome_map_withholds_nothing( outcomes ):
    assert seats_to_withhold( outcomes ) == {}


# ── The notice ───────────────────────────────────────────────────────────────

def test_the_quiet_case_stays_quiet_so_the_notice_means_something():
    assert withhold_notice( {} ) is None


def test_the_notice_names_every_seat_and_the_way_out():
    text = withhold_notice( { "b": "timeout_no_memento", "a": "prior_holder_present" } )
    assert "a (prior_holder_present)" in text
    assert "b (timeout_no_memento)"   in text
    assert text.index( "a (" ) < text.index( "b (" )   # sorted: same reap reads the same twice
    assert "accept the loss" in text                   # the way out is stated, not implied


# ── 🔴 THE REAL REAP. The incident was a reap, so these enter there ──────────
#
# A receipt that calls `seats_to_withhold` with a hand-picked dict proves the
# predicate computes. It says NOTHING about whether `dismiss_sessions` REACHES it —
# and for the whole life of this defect the verdict WAS computed and never reached.
# These arms drive the real function; only tmux is stood down.

from lupin_mcp import session_spawner


class _Ok:
    returncode = 0
    stdout     = ""
    stderr     = ""


def _drive_reap( tmp_path, coordinator_returns, **kw ):
    killed = []

    def runner( argv, **kwargs ):
        killed.append( argv[ -1 ] )
        return _Ok()

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    # A REAL manifest record. An empty manifest makes everything downstream of
    # `reaped_names` unobservable — which is exactly how mutation M3 (counting a
    # withheld seat as reaped) survived a suite that otherwise looked thorough.
    session_spawner._write_manifest(
        session_spawner._manifest_path( "mgr-session", session_dir ),
        [ { "session_name": "worker-1", "session_id": "sid-worker-1" } ] )

    result = session_spawner.dismiss_sessions(
        "mgr-session",
        session_names    = [ "worker-1" ],
        runner           = runner,
        session_dir      = session_dir,
        memento_coord_fn = lambda identities: coordinator_returns,
        **kw
    )
    return result, killed


def test_the_real_reap_withholds_when_the_slot_holds_another_seats_file( tmp_path ):
    result, killed = _drive_reap( tmp_path, { "worker-1": { "status": "prior_holder_present" } } )

    assert killed == [], "tmux kill-session ran on a seat whose work is not on disk"
    assert result[ "dismissed" ][ 0 ][ "status" ]  == "withheld_no_memento"
    assert result[ "dismissed" ][ 0 ][ "verdict" ] == "prior_holder_present"
    assert "KILL WITHHELD" in ( result[ "withhold_notice" ] or "" )


def test_the_real_reap_still_kills_a_verified_seat( tmp_path ):
    # THE CONTROL. Without it, a gate that withheld EVERY seat satisfies the arm above
    # and takes the whole fleet's reaps down.
    result, killed = _drive_reap( tmp_path, { "worker-1": { "status": "verified" } } )

    assert killed == [ "worker-1" ]
    assert result[ "dismissed" ][ 0 ][ "status" ] == "killed"
    assert result[ "withhold_notice" ] is None


def test_the_real_reap_still_kills_on_unproven_present( tmp_path ):
    # The DISCRIMINATING control: the seat's OWN file is at the slot with a failed
    # gate. Loud, recoverable, and explicitly not a refusal.
    _, killed = _drive_reap( tmp_path, { "worker-1": { "status": "unproven_present" } } )
    assert killed == [ "worker-1" ]


def test_force_kill_keeps_an_unresponsive_seat_reapable( tmp_path ):
    # Without this escape the gate manufactures a class of immortal seat, and
    # CLAUDE.md is explicit that a non-responsive worker is reaped and replaced.
    _, killed = _drive_reap(
        tmp_path, { "worker-1": { "status": "prior_holder_present" } }, force_kill=True
    )
    assert killed == [ "worker-1" ]


def test_a_raising_recheck_does_not_withhold_the_whole_fleet( tmp_path ):
    # FAIL-SAFE. A crashed instrument leaves only ask-time verdicts, which row
    # f94ab580 measured are a snapshot and not a settled finding. Withholding on that
    # is the wrong direction — proceed, loudly.
    def boom( outcomes, identities ):
        raise RuntimeError( "recheck exploded" )

    result, killed = _drive_reap(
        tmp_path, { "worker-1": { "status": "prior_holder_present" } }, memento_recheck_fn=boom
    )
    assert killed == [ "worker-1" ]
    assert "recheck exploded" in result[ "memento_outcomes" ][ "_recheck_error" ]


def test_a_withheld_seat_is_never_counted_as_reaped( tmp_path ):
    # A withheld seat is STILL ALIVE. Leaking it into `reaped_names` drops it from the
    # manifest and unlinks its bridge WHILE IT IS STILL RUNNING — worse than the bug
    # this row is about, and silent.
    #
    # 🔴 ASSERT THE MANIFEST, NOT JUST THE RETURN VALUE. The `dismissed` list alone
    # cannot see this: mutation M3 removed the withheld-exclusion from `reaped_names`
    # and the whole 254-test suite stayed GREEN, because nothing looked at what the
    # reap left behind.
    result, _ = _drive_reap( tmp_path, { "worker-1": { "status": "prior_holder_present" } } )
    assert [ d for d in result[ "dismissed" ] if d[ "status" ] == "killed" ] == []
    assert result[ "remaining" ] == [ "worker-1" ], (
        "a withheld seat must stay in the manifest — it was never killed" )


def test_a_killed_seat_does_leave_the_manifest( tmp_path ):
    # THE CONTROL for the assertion above. Without it, a `remaining` that always
    # listed every seat would satisfy it.
    result, _ = _drive_reap( tmp_path, { "worker-1": { "status": "verified" } } )
    assert result[ "remaining" ] == []


def test_a_reap_with_no_coordinator_is_unchanged( tmp_path ):
    # The default path must behave exactly as before — the gate must not alter reaps
    # that never asked for a memento.
    killed = []

    def runner( argv, **kwargs ):
        killed.append( argv[ -1 ] )
        return _Ok()

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    ( session_dir / "manifest.json" ).write_text( "[]" )

    result = session_spawner.dismiss_sessions(
        "mgr-session", session_names=[ "worker-1" ], runner=runner, session_dir=session_dir )
    assert killed == [ "worker-1" ]
    assert result[ "withhold_notice" ] is None


# ── 🔴 F4: A WITHHELD SEAT MAKES A CORRECT RESPIN NAME REPORT AS UNMATCHED ───
#
# Tiffany's finding. `retained_unmatched` is computed over the seats actually REAPED,
# so a seat whose kill was withheld drops out of the population and its persona — a
# name the caller got exactly right — lands in a list whose own contract explains it
# as "a stale/typo'd name". Two causes, one field, and the two want OPPOSITE responses:
# re-ask the live seat for a memento, versus go and fix a typo.
#
# `respin_personas` and `retained_unmatched` appeared ZERO times in this file before
# this arm, against 5 and 4 in the module — the interaction was simply never driven.

import json


def _drive_reap_with_a_persona( tmp_path, status, respin_personas ):
    """Same reap, but with a real bridge so a persona name actually resolves."""
    killed = []

    def runner( argv, **kwargs ):
        killed.append( argv[ -1 ] )
        return _Ok()

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    session_spawner._write_manifest(
        session_spawner._manifest_path( "mgr-session", session_dir ),
        [ { "session_name": "worker-1", "session_id": "sid-worker-1" } ] )
    # WITHOUT this bridge the persona resolves to None, retention is unreachable, and
    # both arms below would pass against a module that had no retention code at all.
    ( session_dir / "cc-sid-worker-1.json" ).write_text( json.dumps( {
        "tmux_session"      : "worker-1",
        "stable_session_id" : "sid-worker-1",
        "voice_persona"     : { "name": "Zephyr" },
    } ) )

    result = session_spawner.dismiss_sessions(
        "mgr-session",
        session_names    = [ "worker-1" ],
        runner           = runner,
        session_dir      = session_dir,
        memento_coord_fn = lambda identities: { "worker-1": { "status": status } },
        respin_personas  = respin_personas,
        emit_reap_fn     = lambda ident, reason: None,
        emit_reaped_fn   = lambda *a, **k: None,
        clear_hold_fn    = lambda *a, **k: None,
    )
    return result, killed


def test_a_withheld_seat_reports_a_correct_respin_name_as_unmatched( tmp_path ):
    # THE FINDING, pinned as TODAY'S BEHAVIOUR rather than asserted to be right. The
    # name is correct, the seat is alive, and its rows were never at risk — so the
    # outcome is fail-safe. What is NOT safe is the READING the field invites, which
    # is why 1d38876e's contract now names this cause explicitly.
    result, killed = _drive_reap_with_a_persona(
        tmp_path, "prior_holder_present", [ "Zephyr" ] )

    assert killed == []
    assert result[ "dismissed" ][ 0 ][ "status" ]  == "withheld_no_memento"
    assert result[ "retained_unmatched" ]      == [ "zephyr" ]
    assert result[ "retained_owner_personas" ] == []


def test_a_killed_seat_with_the_same_name_is_retained_not_unmatched( tmp_path ):
    # 🔴 THE CONTROL, and it is what makes the arm above a finding rather than a
    # fixture artifact. One variable — the memento verdict. If `retained_unmatched`
    # simply always listed every requested name, this arm reddens and the one above
    # proves nothing.
    result, killed = _drive_reap_with_a_persona( tmp_path, "verified", [ "Zephyr" ] )

    assert killed == [ "worker-1" ]
    assert result[ "retained_owner_personas" ] == [ "zephyr" ]
    assert result[ "retained_unmatched" ]      == []


def test_the_contract_names_the_withheld_cause_so_a_reader_can_separate_them( tmp_path ):
    # The field cannot separate the two causes on its own, so the docstring must say
    # how — read the slug against `dismissed`. Delete that sentence and this reddens,
    # which is the only thing standing between a correct name and a typo hunt.
    doc = session_spawner.dismiss_sessions.__doc__
    assert "HAS TWO CAUSES AND ONLY NAMES ONE" in doc
    assert "withheld_no_memento" in doc
