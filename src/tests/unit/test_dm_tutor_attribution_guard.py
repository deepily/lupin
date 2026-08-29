"""
The DM tutor must not invent who holds a position.

Row 897a8db1, 2026-08-15. A DM body reading "My proposal, which matches Rick's
instinct: follow the /clear with a SECOND delayed send-keys" was condensed to
"María proposes sending a second keystroke…" and delivered to María. She opened
her reply with "Check your source before building on it — I did not propose
that," correctly rejecting a proposal she had never made and the sender had
never attributed to her.

The existing `literal_violations` guard cannot catch it, and the reason is the
whole point: "María" WAS in the original — as the addressee. The condenser did
not invent a token, it invented a RELATIONSHIP, moving a name from
who-is-being-written-to into who-holds-the-position.

Why that outranks an ordinary summarisation slip: it manufactures provenance. A
position laundered into a peer's name reads to that peer as something to own or
disown, and to everyone downstream as their settled view.
"""
import pytest

from cosa.agents.dm_tutor.tutor import (
    attribution_bindings,
    attribution_violations,
    gate,
)

# The actual strings from the incident.
ORIGINAL = (
    "María — Rick asked me to coordinate with you on the re-spins. "
    "My proposal, which matches Rick's instinct: follow the /clear with a "
    "SECOND delayed send-keys carrying a short prompt that names the memento path."
)
CONDENSED_BAD = (
    "The issue is that after a /clear the session does not read a memento. "
    "María proposes sending a second keystroke with a prompt to address this issue."
)
CONDENSED_OK = (
    "The issue is that after a /clear the session does not read a memento. "
    "The proposed fix is a second keystroke carrying a prompt."
)


def test_the_actual_incident_is_caught( ):
    """
    CONTROL FOR THE REAL DEFECT. If this ever returns [], the condenser is free
    to put a proposal in a peer's name again.
    """
    assert attribution_violations( ORIGINAL, CONDENSED_BAD ) == [ "maría" ]


def test_the_gate_blocks_the_actual_incident( ):
    ok, reason = gate( ORIGINAL, CONDENSED_BAD )
    assert ok is False
    assert "attributed a position" in reason
    assert "maría" in reason


def test_a_clean_rewrite_of_the_same_body_passes( ):
    """
    The guard has to let the CORRECT condensation through. A guard that fires
    on good text gets switched off, which is worse than not having one.
    """
    assert attribution_violations( ORIGINAL, CONDENSED_OK ) == []
    assert gate( ORIGINAL, CONDENSED_OK )[0] is True


def test_literal_violations_alone_would_have_missed_it( ):
    """
    Proves this guard earns its place rather than duplicating the existing one:
    the name is present in BOTH texts, so a presence/count check sees nothing.
    """
    from cosa.agents.dm_tutor.tutor import literal_violations
    assert literal_violations( ORIGINAL, CONDENSED_BAD ) == [], \
        "if literal_violations already caught this, the new guard is redundant"
    assert attribution_violations( ORIGINAL, CONDENSED_BAD ), \
        "the new guard must catch what the old one cannot"


# ---------------------------------------------------------------------------
# Scope — narrow on purpose
# ---------------------------------------------------------------------------
def test_reporting_an_action_is_not_attributing_a_position( ):
    """"María ran the suite" reports what she did; it invents no stance."""
    assert attribution_violations( ORIGINAL, "María ran the suite and it was green." ) == []


def test_a_binding_present_in_the_original_is_legal( ):
    """Condensing a real attribution is the job, not a violation."""
    original = "Mr Radio says hold the merge until the cosa tier is green."
    assert attribution_violations( original, "Mr Radio says hold the merge." ) == []


def test_dropping_an_attribution_is_legal( ):
    """Absence is legal; invention is not — same rule as literal_violations."""
    original = "María proposes the boot path read the memento itself."
    assert attribution_violations( original, "The boot path should read the memento." ) == []


@pytest.mark.parametrize( "lead", [
    "The proposed fix is a keystroke.",
    "This suggests the boot path is wrong.",
    "They said the run was green.",
    "It says the tier is red.",
    "Nobody proposed that.",
    "Someone suggested a second keystroke.",
] )
def test_capitalised_non_names_never_register( lead ):
    """
    Without the stop-list these read as people called "The"/"This"/"They"
    holding positions, and the guard would block clean rewrites.
    """
    assert attribution_bindings( lead ) == set()


@pytest.mark.parametrize( "text", [ "", None ] )
def test_empty_input_attributes_nothing( text ):
    assert attribution_bindings( text ) == set()
    assert attribution_violations( text or "", text or "" ) == []


def test_a_two_word_phrase_led_by_a_stop_word_is_not_a_name( ):
    """
    "The Manager says…" survives the whole-phrase stop-list (the phrase itself
    is not in it) and must still be rejected on its leading word. Otherwise a
    role reference reads as a person named "The Manager".
    """
    assert attribution_bindings( "The Manager says the tier is red." ) == set()
    assert attribution_bindings( "Our Reviewer proposed a rewrite." )  == set()


def test_two_word_names_are_recognised( ):
    """Half this fleet has a two-word name; missing them would gut the guard."""
    assert "mr radio" in attribution_bindings( "Mr Radio proposes holding the merge." )


def test_multiple_invented_attributions_are_all_reported( ):
    invented = attribution_violations(
        "The merge is held pending the cosa tier.",
        "María proposes holding it and Rick says the tier is red."
    )
    assert invented == [ "maría", "rick" ]
