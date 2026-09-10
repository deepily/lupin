"""
THE RATIO REFUSAL MUST NOT OFFER A PETITIONER THE EXEMPTION IT JUST DENIED — row d2b1b59a,
Finding 4.

Measured live 2026-09-10 21:31Z: a manager's P0 petition, filed on Rick's order, was judged
at the P1 it is minted at (deliberate — see `create_task`) and refused 422 with a message
ending "(A P0 is exempt if this genuinely cannot wait.)". The rule stays. The sentence a
petitioner reads now says what the gate actually did.

Every branch of `ratio_gate_advisory` that refuses is driven here, because the hint is
appended in three separate places and a fix that reached two of them would still lie in
the third.
"""

import pytest

from cosa.rest import task_store_rules as rules


# ( created, closed, allow_below ) — one per refusing branch.
REFUSING_BRANCHES = [
    pytest.param( 14, 3, 1.0, id="ratio-over-threshold" ),
    pytest.param( 5,  0, 1.0, id="nothing-closed" ),
    pytest.param( 14, 3, 0.0, id="zero-threshold-hard-stop" ),
]

OLD_SENTENCE   = "(A P0 is exempt if this genuinely cannot wait.)"
PETITION_WORDS = "judged it at P1"


@pytest.mark.parametrize( "created, closed, allow_below", REFUSING_BRANCHES )
def test_a_refused_petition_is_not_told_a_P0_is_exempt( created, closed, allow_below ):
    message = rules.ratio_gate_advisory( created, closed, priority="P1",
                                         allow_below=allow_below, petition=True )
    assert message is not None, "the branch under test did not refuse — the arm measures nothing"
    assert "A P0 is exempt" not in message
    assert PETITION_WORDS in message


@pytest.mark.parametrize( "created, closed, allow_below", REFUSING_BRANCHES )
def test_CONTROL_an_ordinary_refusal_still_offers_the_P0_exemption_word_for_word(
    created, closed, allow_below
):
    """Without this, the arm above is equally consistent with the hint being deleted for everyone."""
    message = rules.ratio_gate_advisory( created, closed, priority="P1", allow_below=allow_below )
    assert message is not None
    assert OLD_SENTENCE in message
    assert PETITION_WORDS not in message


@pytest.mark.parametrize( "created, closed, allow_below", REFUSING_BRANCHES )
def test_only_the_closing_hint_differs_between_the_two_refusals( created, closed, allow_below ):
    """The counts, the remedy and the fleet-wide warning reach a petitioner unchanged."""
    ordinary = rules.ratio_gate_advisory( created, closed, allow_below=allow_below )
    petition = rules.ratio_gate_advisory( created, closed, allow_below=allow_below, petition=True )
    assert ordinary.replace( OLD_SENTENCE, "" ) == petition.replace( rules.RATIO_GATE_PETITION_HINT, "" )


def test_petition_changes_the_sentence_never_the_verdict():
    """A petition flag must not buy an allow, nor turn an allow into a refusal."""
    assert rules.ratio_gate_advisory( 1, 10, allow_below=1.0, petition=True ) is None
    assert rules.ratio_gate_advisory( 14, 3, allow_below=1.0, petition=True ) is not None
