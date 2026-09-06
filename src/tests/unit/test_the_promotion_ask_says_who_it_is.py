"""
THE PROMOTION ASK NAMES ITS SENDER — row `b48e231f`.

🔴 THE DEFECT. `NotificationRequest` carries a `sender_id` field and this ask never set it.
Server-side `resolve_sender_id` (`routers/notifications.py`) tries three things in order:
an explicit sender, a `[PREFIX]` regex on the message text, then the literal fallback
`claude.code@unknown.deepily.ai`. The promotion ask supplied neither of the first two, so it
fell to the fallback UNCONDITIONALLY — from every tree, registered or not.

MEASURED 2026-09-04, and this is why it is a hole rather than a blemish: grouping EVERY
promotion ask ever recorded by sender gives ONE group — `claude.code@unknown.deepily.ai`,
29 rows spanning 09-03 22:31 to 09-04 19:48. In the same table in the same minute, ordinary
seats stamp real senders (`claude.code@lupin.deepily.ai#b7114f78`, `#e5288886`, `#a7f5a72a`).
So the column discriminates; this path simply never filled it.

⚠️ WHAT IT COST. During the 2026-09-04 incident (row `e625e608`) five unit tiers were live
and the one field that would have named the source read `unknown` for every candidate at
once. A stamp identical across all suspects is not a weak clue — it is no clue.

⚠️ IT WAS MIS-DIAGNOSED FIRST, AND THE MIS-DIAGNOSIS IS WORTH KEEPING. The original reading
was that an unregistered `/tmp` root caused it. It did not: the root is not an input to
`resolve_sender_id`, and an ask at 19:48:56 carried `unknown` a full hour after the
`/tmp`-rooted process died at 18:49:25. Do NOT "fix" this by widening project detection.

WHAT THESE TESTS PIN, and each is a separate claim:
  · the kwargs the ask is fired with CARRY a sender (the wiring, at the layer the value is
    built) — without this, a correct builder can sit unused;
  · a resolved session becomes the sender's suffix, so two different sessions are
    DISTINGUISHABLE — that is the whole point, and a test asserting merely "a sender exists"
    would pass under the defect's replacement too;
  · no session yields a suffix that NAMES THE PATH rather than degrading to `unknown`;
  · a blank session cannot produce a sender ending in a bare `#`.
"""
import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.rest import task_promotion_gate as gate


# The literal the server falls back to. Named here so a test can assert we are NOT it.
UNKNOWN_SENDER = "claude.code@unknown.deepily.ai"


def test_the_kwargs_the_ask_is_fired_with_actually_carry_a_sender():
    """
    🔴 THE WIRING, AND IT IS A SEPARATE CLAIM FROM THE BUILDER BEING CORRECT.

    `promotion_ask_kwargs` is the pure, pinnable record of EVERY argument the ask is fired
    with — its own docstring says so. A sender built by a perfect function and never placed
    in these kwargs reaches nobody, and every builder test below would still pass.
    """
    kwargs = gate.promotion_ask_kwargs( "operator foolish goat", "task-1", "a title", "bee97090" )

    assert "sender_id" in kwargs, (
        "the promotion ask's kwargs carry no sender_id — the builder may be correct and the "
        "ask will still reach the server with nothing to resolve, which is the defect"
    )
    assert kwargs[ "sender_id" ] != UNKNOWN_SENDER
    assert "bee97090" in kwargs[ "sender_id" ]


def test_two_different_sessions_produce_two_different_senders():
    """
    🔴 THE ONE THAT MATTERS — DISTINGUISHABILITY, not mere presence.

    The incident was not "the sender field was empty". It was that the field read the SAME
    value for every candidate, so it could not separate them. A test asserting only that a
    sender exists would pass against a version that stamped one constant for everybody —
    which is the defect wearing a different string.
    """
    a = gate.promotion_ask_sender_id( "bee97090" )
    b = gate.promotion_ask_sender_id( "54250c10" )

    assert a != b, "two sessions produced the same sender — the field still names nobody"
    assert a.endswith( "#bee97090" )
    assert b.endswith( "#54250c10" )


def test_no_session_names_the_path_rather_than_degrading_to_unknown():
    """
    A browser actor resolves NO session (row 9d3a975e) — a real case, not a defensive one.

    ⚠️ The requirement here is NOT "produce something non-empty". It is that the absent-session
    case stays DISTINGUISHABLE from the server's own fallback, so a reader can tell "a
    promotion gate fired this and the requester had no session" apart from "nothing supplied
    a sender at all". Those want different investigations.
    """
    sender = gate.promotion_ask_sender_id( None )

    assert sender != UNKNOWN_SENDER
    assert sender.endswith( f"#{gate.NO_SESSION_SUFFIX}" )
    assert gate.NO_SESSION_SUFFIX == "promotion-gate"


@pytest.mark.parametrize( "blank", [ "", "   ", "\t\n" ] )
def test_a_blank_session_is_treated_as_absent_not_as_a_suffix( blank ):
    """
    A falsy-but-present value must not produce a sender ending in a bare `#`.

    Without this, `session_id=""` yields `claude.code@lupin.deepily.ai#` — parseable, wrong,
    and indistinguishable at a glance from a real one.
    """
    sender = gate.promotion_ask_sender_id( blank )

    assert not sender.endswith( "#" )
    assert sender.endswith( f"#{gate.NO_SESSION_SUFFIX}" )


def test_a_non_string_session_does_not_raise():
    """
    The contract says it never raises. The session arrives from
    `rules.session_id_from_created_by( payload.actor )`, which is free to return None — and a
    sender builder that throws would turn an attribution gap into a 500 on the promotion path.
    """
    for odd in ( None, 12345, object() ):
        sender = gate.promotion_ask_sender_id( odd )
        assert sender.endswith( f"#{gate.NO_SESSION_SUFFIX}" )
