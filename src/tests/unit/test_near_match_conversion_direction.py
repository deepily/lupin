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

THE DEFECT, AS A TEST: the first test below asserts the pair is NOT replayed. It was `xfail(strict=True)`
and failed until `near_match_guard` was wired in; the marker is gone because the fix landed (strict
mode made that removal compulsory). Controls: the same pair is declined on a flow with confirmation on
(what Development runs), and a near match naming the SAME quantity is still served.

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


def _trace_texts( tmp_path ):
    texts = []
    for name in os.listdir( tmp_path ):
        path = os.path.join( tmp_path, name )
        if os.path.isfile( path ):
            with open( path, errors="ignore" ) as fh: texts.append( fh.read() )
    return texts


def _candidate():
    # the snapshot as the suite-lineage skip left it: stamped correct, never verified by a person
    return v2._snapshot( question=STORED_QUESTION, id_hash="0b574ed9", answer_is_correct=True,
                         routing_command="agent router go to calculator" )


def _lookup():
    return v2._lookup( is_replay_hit=False, best_candidate=_candidate(), best_score=MEASURED_SCORE,
                       similarity=MEASURED_SCORE, tier="ann" )


def test_opposite_conversions_are_not_replayed_when_confirmation_is_off( tmp_path, notifier, monkeypatch ):
    """
    THE DEFECT, FIXED (row 1b3ec88f). This was `xfail(strict=True)` and failed with
    `['replay'] == ['agent']` until `near_match_guard.quantities_differ` was wired into
    `_near_match_replay`. RED ON REVERT: remove that call and the executor is handed a replay.
    """
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


def test_control_a_near_match_with_the_same_quantity_is_still_replayed_when_confirmation_is_off( tmp_path, notifier, monkeypatch ):
    """
    THE NEGATIVE CONTROL, and the reason the guard is not "refuse every near match". The stored
    question names the same quantity (10 miles) as the one asked, at the same measured score, so
    the auto-accept still serves it. Without this a build that refused ALL near matches would pass
    the test above.

    RED ON REVERT: make `quantities_differ` return True unconditionally.
    """
    executor = _RecordingExecutor( v2._outcome() )
    same     = v2._snapshot( question="What is 10 miles in kilometers?", id_hash="same-quantity",
                             answer_is_correct=True, routing_command="agent router go to calculator" )
    lookup   = v2._lookup( is_replay_hit=False, best_candidate=same, best_score=MEASURED_SCORE,
                           similarity=MEASURED_SCORE, tier="ann" )
    flow     = _flow( tmp_path, notifier, monkeypatch, lookup, executor, threshold=NEAR_MATCH_FLOOR )

    result = flow.ask( ASKED, interactive=False, **v2._CTX )

    assert executor.kinds == [ "replay" ], f"a same-quantity near match was refused: {executor.kinds}"
    assert result[ "path" ] == "replay"


def test_the_refusal_is_recorded_in_the_trace( tmp_path, notifier, monkeypatch ):
    """
    A refusal and a broken cache look alike from outside, so the guard writes down which it was.

    RED ON REVERT: drop the `trace.set( "near_match_refused_quantity" ... )` line.
    """
    executor = _RecordingExecutor( v2._outcome() )
    flow     = _flow( tmp_path, notifier, monkeypatch, _lookup(), executor, threshold=NEAR_MATCH_FLOOR )

    flow.ask( ASKED, interactive=False, **v2._CTX )

    assert any( "near_match_refused_quantity" in text for text in _trace_texts( tmp_path ) )
