"""
The reap must REFUSE, not merely narrate. Row ee3d3c82.

`self_respin` fails loud when it cannot prove a memento. The reap did not: it computed
a per-seat verdict BEFORE the kill (row 0a36d83d) and then killed unconditionally,
composing `memento_alarm` afterwards — so the seat was already dead by the time anyone
could read the sentence naming what it lost. María 🌸 lost a worker's whole hour to
that shape on 2026-09-03.

🔴 SCOPE — READ THIS BEFORE TRUSTING THE FILE. These tests cover the PURE PREDICATE
ONLY. The predicate is NOT WIRED into `dismiss_sessions`, deliberately, and the row's
done-means item 4 (drive the real reap) is therefore NOT satisfied.

WHY: wiring it on the ASK-TIME verdict breaks row f94ab580's post-kill re-check, and
that is measured, not feared — the wired version reddened
`test_with_the_recheck_the_reap_alarms_only_on_the_two_real_losses` and
`test_a_raising_recheck_never_breaks_the_reap_and_is_surfaced`, taking that suite's
alarm from 2 seats to 4, against a baseline of 0 failures. The reason is the whole
problem: `prior_holder_present` at ASK TIME is frequently a RACE, not a loss — the
slot legitimately holds the prior holder's file while the seat writes — and THE KILL
IS WHAT STOPS THE SEAT WRITING, which is why the re-check runs after it. Withholding
the kill on an ask-time verdict removes the very event the upgrade depends on.

⇒ ALL THREE WITHHOLD VERDICTS ARE ASK-TIME VERDICTS THE RE-CHECK EXISTS TO UPGRADE.
  So the gate cannot be built at that point in the sequence at all. It needs a
  second look BEFORE the kill for withhold candidates — a design change to a measured
  row that is not mine to make unilaterally.

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
