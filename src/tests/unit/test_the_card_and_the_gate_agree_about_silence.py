"""
THE CARD AND THE GATE AGREE ABOUT SILENCE — row 73d41df0, driven under P0 row d2b1b59a.

The abstract Rick reads ended "Defaults to YES if you are away." while
`approval_from_the_ask` REFUSED on exactly that case. The card and `response_default`
agreed with each other; both disagreed with the outcome. 675a1415 changed the outcome on
his 2026-09-07 order and moved neither the sentence nor the default beneath it.

⚠️ PORTED FROM JOHN'S 2333a752 (unmerged branch `john-202-is-not-a-success`), minus the
two arms that exercise his approver-only `move=` parameter, which does not exist on this
line. When his branch merges, his copy of this file supersedes this one.

🔴 SO THIS FILE DOES NOT PIN A STRING. A test asserting the new wording would go stale
in precisely the way the old sentence did — silently, while still passing, because
nothing connects it to what the gate does. The arms below tie the card's CLAIM to the
gate's BEHAVIOUR, so the two cannot drift apart without a named test going red.

⚠️ AND THE FIX HAD TO BE SCOPED, NOT GLOBAL. A fixed-string sweep for the old sentence
finds it in TWO production modules, and in `lupin_mcp/self_respin_core.py` it is TRUE —
`gate_proceed` really does proceed on the default-used marker. A repo-wide replace would
have broken the honest one. The last arm is the guard on that.
"""

from cosa.rest import task_promotion_gate as gate


ACTOR   = "mr radio d54262de"
TASK_ID = "a1b2c3d4-0000-0000-0000-000000000000"
TITLE   = "a row waiting on Rick"

# The sentence that was wrong. Named once so the arms that forbid it cannot disagree
# with each other about what they are forbidding.
THE_OLD_LIE = "Defaults to YES if you are away."


def _outcome( answer, default_used ):
    return gate.AskOutcome( answer=answer, default_used=default_used )


def _ask_returning( outcome ):
    return lambda **kwargs: outcome


def _approval( answer, default_used ):
    return gate.approval_from_the_ask(
        session_id = "deadbeef", actor = ACTOR, task_id = TASK_ID, title = TITLE,
        ask_fn     = _ask_returning( _outcome( answer, default_used ) ),
    )


# ---------------------------------------------------------------------------
# THE TIE — the card's claim is checked against the gate, not against a literal
# ---------------------------------------------------------------------------

def test_the_card_says_refused_exactly_when_the_gate_refuses_an_unanswered_ask():
    """
    🔴 THE ARM THIS FILE EXISTS FOR. Both sides are read at run time: whether the CARD
    claims silence refuses, and whether the GATE actually refuses it. They must agree.

    ⚠️ THE TWO SIDES REACH THE ANSWER BY DIFFERENT ROUTES ON PURPOSE — one is a
    sentence, the other is a code path — so this is an agreement rather than a
    coincidence. Change the outcome without the sentence, or the sentence without the
    outcome, and this reddens.
    """
    card_says_refused = "REFUSED" in gate.UNANSWERED_MEANS
    gate_refuses      = not _approval( "yes", default_used=True ).allowed

    assert card_says_refused == gate_refuses, (
        f"the card and the gate disagree about what an unanswered ask means. "
        f"card claims refused={card_says_refused}; gate refused={gate_refuses}. "
        f"card text: {gate.UNANSWERED_MEANS!r}"
    )


def test_the_gate_really_does_refuse_a_timed_out_ask():
    """
    The control under the arm above. If the gate ALLOWED on `default_used`, the equality
    test would pass by both sides being False and would prove nothing. This pins one side
    to Rick's actual ruling.
    """
    assert _approval( "yes", default_used=True ).allowed is False, (
        "an unanswered promotion ask was ALLOWED. Rick's ruling of 2026-09-07: "
        "'it must default to NO. That way you can NEVER do it without my approval.'"
    )


def test_a_real_keypress_still_allows():
    """
    🔴 THE POSITIVE ARM. Without it every assertion here is satisfied by a gate that
    refuses everything, which would be a P0 of its own rather than a fix.
    """
    approval_obj = _approval( "yes", default_used=False )
    assert approval_obj.allowed is True
    assert approval_obj.approval_source == gate.APPROVAL_KEYPRESS


# ---------------------------------------------------------------------------
# THE OLD SENTENCE IS GONE FROM THE CARD, AND THE NEW ONE IS ON IT
# ---------------------------------------------------------------------------

def test_the_card_no_longer_promises_that_walking_away_approves():
    abstract = gate.promotion_ask_text( ACTOR, TASK_ID, TITLE )[ 1 ]
    assert THE_OLD_LIE not in abstract, (
        "the promotion card still tells Rick his silence approves, which the gate has "
        "not honoured since 2026-09-07"
    )
    assert gate.UNANSWERED_MEANS in abstract, (
        "the promotion card carries no statement of what silence means at all — the "
        "sentence was removed rather than corrected, which leaves him guessing"
    )


def test_the_card_rick_is_actually_sent_carries_the_new_sentence():
    """
    `promotion_ask_kwargs` is what the live boundary fires. Checking only
    `promotion_ask_text` would stay green if the kwargs builder ever stopped using it.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK_ID, TITLE )
    assert gate.UNANSWERED_MEANS in kwargs[ "abstract" ]
    assert THE_OLD_LIE not in kwargs[ "abstract" ]


# ---------------------------------------------------------------------------
# THE FIX IS SCOPED — the one place the old sentence is TRUE still says it
# ---------------------------------------------------------------------------

def test_the_self_respin_card_still_says_defaults_to_yes_because_there_it_is_true():
    """
    🔴 THE ANTI-OVERREACH ARM. `self_respin_core.gate_proceed` PROCEEDS on the
    default-used marker, so its copy of this sentence is honest and must survive.
    A repo-wide replace would make the self-respin card lie in order to stop the
    promotion card lying.
    """
    from lupin_mcp import self_respin_core

    proceed, _ = self_respin_core.gate_proceed(
        self_respin_core.DEFAULT_USED_MARKER + "yes"
    )
    assert proceed is True, (
        "self_respin no longer proceeds on a default — if that is deliberate, its card's "
        "'Defaults to YES' has become the same defect as the promotion card's, and this "
        "arm should be replaced rather than deleted"
    )

    source = open( self_respin_core.__file__, encoding="utf-8" ).read()
    assert THE_OLD_LIE in source, (
        "the self-respin copy of the sentence is gone. It was TRUE there — check whether "
        "a repo-wide replace took an honest sentence out with the dishonest one"
    )
