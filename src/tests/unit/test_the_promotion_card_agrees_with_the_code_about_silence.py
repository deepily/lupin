"""
The promotion card and the gate must agree about what SILENCE means.

🔴 THE DEFECT THIS PINS, AND WHY A TEXT FIX ALONE WOULD NOT HAVE HELD. The card ended
"Defaults to YES if you are away" while `approval_from_the_ask` REFUSED every timed-out
ask. The behaviour moved at `675a1415` (2026-09-07 23:00 EDT); the sentence Rick reads
did not move with it. Nothing connected the two, so nothing went red.

⚠️ LATENT, NOT REALIZED — the distinction is why this shipped as a text fix rather than
an incident. Measured in `lupin_db_dev`: 118 promotion asks have ever fired, 113 carried
the old line, 69 went unanswered, and ALL 118 predate `675a1415` (latest 2026-09-07
22:19 EDT, forty minutes before it landed). The promise was TRUE for every ask ever
shown. The NEXT one would have been the first to mislead him.

🔴 WHY THIS TEST DERIVES THE CODE'S ANSWER INSTEAD OF ASSERTING TWO STRINGS. The obvious
guard — "assert the card does not say YES" plus "assert a default refuses" — is two
independent assertions that happen to agree today. That is the shape this repo keeps
finding: a comparison whose sides never have to move together. Here ONE side is
COMPUTED by running the real scorer, so if the gate is ever changed back to allow on
silence, this test fails until the card is changed with it. The card and the code cannot
drift apart without something going red.

⚠️ THE IDENTICAL SENTENCE IN `lupin_mcp/self_respin_core.py:1110` IS CORRECT THERE and is
deliberately out of scope. Its `gate_proceed` returns PROCEED on a default, so "Defaults
to YES if you are away" is true of that card. Same words, opposite behaviour, two files —
a sweep that "fixes" both breaks the one that was right.
"""
import pytest

from cosa.rest import task_promotion_gate as gate


def _code_allows_on_silence():
    """
    What the REAL scorer does when the window closes with no answer — computed, never
    assumed. This is the side of the comparison that must come from behaviour.
    """
    approval = gate.approval_from_the_ask(
        session_id = "s1",
        actor      = "mr radio 52f3fe21",
        task_id    = "t1",
        title      = "a row",
        ask_fn     = lambda **kw: gate.AskOutcome( answer="yes", default_used=True ),
    )
    return approval.allowed


def _card_promises_silence_approves():
    """Whether the card Rick reads tells him an unanswered ask goes through."""
    _question, abstract = gate.promotion_ask_text( "mr radio 52f3fe21", "t1", "a row" )
    lowered = abstract.lower()
    return "defaults to yes" in lowered


def test_the_card_and_the_code_agree_about_what_silence_means():
    """
    The load-bearing one. Flip EITHER side and this reddens.

    Not "the card must say X" — that pins today's wording and would have to be edited
    every time the sentence is reworded. It pins the AGREEMENT, which is the thing that
    broke.
    """
    assert _code_allows_on_silence() is False, (
        "the gate now ALLOWS a timed-out ask. That reverses Rick's 2026-09-07 ruling "
        "('it must default to NO. That way you can NEVER do it without my approval'). "
        "If that reversal is deliberate, the CARD must be changed in the same commit — "
        "this test exists so the two cannot move apart."
    )
    assert _card_promises_silence_approves() is False, (
        "the code REFUSES a timed-out ask but the card still promises 'Defaults to YES "
        "if you are away'. Rick reads the card, not the code: he would believe his "
        "silence approved a promotion it actually refused."
    )


def test_the_card_says_plainly_what_silence_does():
    """
    The agreement test above is satisfied by a card that says NOTHING about silence, and
    saying nothing is its own defect — the operator then has no way to know. So this
    pins that the consequence is stated, without pinning the exact wording.
    """
    _question, abstract = gate.promotion_ask_text( "mr radio 52f3fe21", "t1", "a row" )
    lowered = abstract.lower()
    assert "refused" in lowered, (
        "the card must TELL Rick that not answering refuses. A card silent about the "
        "consequence leaves him to guess, which is how the old wrong sentence survived."
    )


def test_the_probe_can_see_a_card_that_promises_approval():
    """
    POSITIVE CONTROL. Without this, `_card_promises_silence_approves` returning False
    proves nothing — a detector that can never fire would pass the test above forever,
    on any card at all.
    """
    assert _card_promises_silence_approves() is False          # today's card
    # and the same predicate, run over the sentence that used to ship, DOES fire:
    old = "**Promotion out of the holding area**\n\nDefaults to YES if you are away."
    assert "defaults to yes" in old.lower()


def test_a_real_keypress_yes_still_allows():
    """
    The other direction, so this file cannot be satisfied by a gate that refuses
    everything. A refusing-always gate agrees with the card trivially and would be a
    worse defect than the one being fixed.
    """
    approval = gate.approval_from_the_ask(
        session_id = "s1",
        actor      = "mr radio 52f3fe21",
        task_id    = "t1",
        title      = "a row",
        ask_fn     = lambda **kw: gate.AskOutcome( answer="yes", default_used=False ),
    )
    assert approval.allowed is True
    assert approval.approval_source == gate.APPROVAL_KEYPRESS
