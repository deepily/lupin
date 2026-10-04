"""
Row 1b3ec88f: a near match between two OPPOSITE unit conversions is replayed as the answer.

MEASURED, :8000 job ts-8278f1c5, 2026-10-03 21:02:20 EDT (io/v2-flow/trace-2026-10-04.jsonl, the
trace for the eval's request 55). The user asked "Convert 10 miles to kilometers"; the flow answered
"10 kilometers is about 6.21 miles" by replaying the snapshot of "How many miles is 10 kilometers?".
The trace says why, field by field: cache_tier "ann", similarity/best_score 93.40580443635491 (above
the 90.0 near-match threshold), interactive false, route_reason "near_match_auto_accepted"
(`similarity confirmation enabled = false` in [Lupin: Testing]), and the snapshot had been stamped
`answer_is_correct = True` by the suite-lineage skip 16 s earlier.

WHAT IS REAL HERE AND WHAT IS NOT. Real: `AskFlow._near_match_replay`, `_may_serve`, and the
executor hand-off, through `AskFlow.ask`. NOT real: the embedding similarity, which comes from the
model server and is not reachable in this tier; its value is the one MEASURED in that trace, not
invented. So this file tests the DECISION on the measured score. It cannot tell whether the embedder
should have scored the pair lower, and it does not claim to.

THE DEFECT, AS A TEST: the first test below asserts the pair is NOT replayed. It fails today and is
marked `xfail(strict=True)`, so the unit tier stays green while the gap is open and goes RED the day
the gap closes (strict) so the marker gets removed with the fix instead of lingering. The control
shows the same pair is declined on a flow that has confirmation on, which is what production
(Development) runs, so the hole is the test server's auto-accept setting plus a stamped row, not
the matcher everywhere.

Venue: :7999-eligible; no network, no DB.
"""

import os
import sys

import pytest

sys.path.insert( 0, os.path.dirname( __file__ ) )
import test_v2_flow as v2                       # noqa: E402
from test_v2_flow import notifier               # noqa: F401,E402 — a fixture, used by name
from test_9b_the_read_guard import _flow, _RecordingExecutor   # noqa: E402

ASKED               = "Convert 10 miles to kilometers"
STORED_QUESTION     = "How many miles is 10 kilometers?"
MEASURED_SCORE      = 93.40580443635491     # trace-2026-10-04.jsonl, seq 179's flow trace
NEAR_MATCH_FLOOR    = 90.0                  # `similarity threshold confirmation`


def _candidate():
    # the snapshot as the suite-lineage skip left it: stamped correct, never verified by a person
    return v2._snapshot( question=STORED_QUESTION, id_hash="0b574ed9", answer_is_correct=True,
                         routing_command="agent router go to calculator" )


def _lookup():
    return v2._lookup( is_replay_hit=False, best_candidate=_candidate(), best_score=MEASURED_SCORE,
                       similarity=MEASURED_SCORE, tier="ann" )


@pytest.mark.xfail( strict=True, reason="row 1b3ec88f: ANN near match at 93.4 between opposite conversions is "
                                        "auto-accepted and replayed on a flow with confirmation off (the :8000 setting)" )
def test_opposite_conversions_are_not_replayed_when_confirmation_is_off( tmp_path, notifier, monkeypatch ):
    executor = _RecordingExecutor( v2._outcome() )
    flow     = _flow( tmp_path, notifier, monkeypatch, _lookup(), executor, threshold=NEAR_MATCH_FLOOR )
    assert flow.confirmation_enabled is False, "this arm models [Lupin: Testing], confirmation off"

    result = flow.ask( ASKED, interactive=False, **v2._CTX )

    assert executor.kinds == [ "agent" ], (
        f"{ASKED!r} was answered by replaying the snapshot of {STORED_QUESTION!r}: {executor.kinds}"
    )
    assert result[ "path" ] == "agent"


def test_control_the_same_pair_is_declined_unasked_when_confirmation_is_on_and_nobody_is_there( tmp_path, notifier, monkeypatch ):
    """
    Passes today. Same candidate, same measured score; only the flow's confirmation setting
    differs. With it on and `interactive=False`, the near match is declined without asking and
    the question is routed, which is what stops the wrong answer on a flow configured like
    Development. It also proves the xfail above is about the auto-accept branch and not about
    some fixture that always replays.
    """
    confirmer = v2._FakeConfirmer( response_value="yes" )
    executor  = _RecordingExecutor( v2._outcome() )
    flow      = _flow( tmp_path, notifier, monkeypatch, _lookup(), executor,
                       confirmer=confirmer, threshold=NEAR_MATCH_FLOOR )
    assert flow.confirmation_enabled is True

    result = flow.ask( ASKED, interactive=False, **v2._CTX )

    assert confirmer.requests == [], "nobody is there to ask; the prompt must not be sent"
    assert executor.kinds == [ "agent" ], f"declined near match was served anyway: {executor.kinds}"
    assert result[ "path" ] == "agent"


def test_control_the_xfail_is_the_decision_not_the_fixture( tmp_path, notifier, monkeypatch ):
    """
    Passes today. With confirmation OFF the measured pair DOES replay: this states the defect
    as an observation (the executor is handed a replay), so the xfail above cannot be passing
    for the wrong reason, and a fix is seen as this test changing, not as silence.
    """
    executor = _RecordingExecutor( v2._outcome() )
    flow     = _flow( tmp_path, notifier, monkeypatch, _lookup(), executor, threshold=NEAR_MATCH_FLOOR )

    result = flow.ask( ASKED, interactive=False, **v2._CTX )

    assert executor.kinds == [ "replay" ], f"expected the measured defect, got {executor.kinds}"
    assert result[ "path" ] == "replay"
