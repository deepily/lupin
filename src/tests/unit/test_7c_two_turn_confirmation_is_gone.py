"""
Step 7c — the two-turn confirmation dialogue is gone, and something still asks.

WHAT WAS DELETED. `TodoFifoQueue.push_job` used to open with an `is_accepting_jobs()`
gate. Behind it sat a `ConfirmationDialogue` LLM call that read the user's NEXT spoken
question as a yes/no answer about the PREVIOUS one, and on "yes" replayed a snapshot
stashed by `push_blocking_object()` at a hard-coded score of 100.0. The three FifoQueue
methods that carried that state — `push_blocking_object`, `pop_blocking_object`,
`is_accepting_jobs` — went with the branch, along with the two attributes behind them.

WHY A TEST AND NOT JUST A DELETE. The deletion rested on a runtime window in which the
gate and the branch never once tripped. A window proves what happened while somebody was
watching; it says nothing about tomorrow. This file makes the absence a property.

WHY THE POSITIVE HALF IS NOT OPTIONAL. "The confirmation is gone" is also true of a build
that confirms NOTHING and replays every near match in silence — which is the failure 7b
found and removed one step earlier. So the second test pins that a near match is still
confirmed before it is replayed, in AskFlow, where confirmation lives now.

RED ON REVERT: restore any of the three methods or either attribute and the first test
names it; drop AskFlow's near-match ask, or stop it declining an unattended caller, and
the third one does.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import inspect
import os
import sys

from cosa.rest.fifo_queue import FifoQueue
import cosa.rest.todo_fifo_queue as tfq

# The near-match ask's behavioural harness lives with the branch it pins, in
# test_v2_flow.py. Importing it keeps ONE set of fakes instead of a second copy that can
# drift out of resemblance with the real classes — and this file needs the real thing,
# because what it has to show is what the flow DOES, not what its source says.
# Aliased away from a `Test*` name on purpose: pytest collects by the name bound here, so
# the alias stops the imported class's own tests being collected and run twice.
sys.path.insert( 0, os.path.dirname( __file__ ) )
from test_v2_flow import TestTheFlowAsksAboutANearMatch as _NearMatchHarness
from test_v2_flow import _FakeConfirmer, _CTX, notifier   # noqa: F401 — `notifier` is a fixture


# The blocking-object API, by name. Anything that reintroduces one of these reintroduces
# the state the two-turn dialogue needed to exist.
_DELETED_METHODS    = ( "push_blocking_object", "pop_blocking_object", "is_accepting_jobs" )
_DELETED_ATTRIBUTES = ( "_blocking_object", "_accepting_jobs" )


def test_the_blocking_object_api_is_gone_from_the_queue_base_class():
    """
    The three methods and the two attributes are not on FifoQueue any more — not on the
    class, and not set by `__init__` on an instance.

    RED ON REVERT: put any one of them back and it is named here.
    """
    revived_methods = [ name for name in _DELETED_METHODS if hasattr( FifoQueue, name ) ]
    assert not revived_methods, (
        f"FifoQueue has the blocking-object API again: {revived_methods}. It existed for one "
        f"caller — the two-turn confirmation in push_job — and step 7c deleted both together."
    )

    queue = FifoQueue()
    revived_attributes = [ name for name in _DELETED_ATTRIBUTES if hasattr( queue, name ) ]
    assert not revived_attributes, (
        f"FifoQueue.__init__ sets the blocking-object state again: {revived_attributes}. "
        f"Nothing reads it; a queue that can stop accepting jobs and never be restarted is "
        f"the shape 7c removed."
    )


def test_push_job_no_longer_runs_a_confirmation_dialogue():
    """
    `push_job`'s body does not reach `ConfirmationDialogue`, and the module no longer
    imports it.

    Read off the SOURCE rather than by calling the method: the branch is unreachable by
    construction now, so there is no input that would distinguish a build that kept it.
    That is exactly why a behavioural test cannot cover this and a structural one must.

    RED ON REVERT: restore the branch and the second assertion names it. A revived
    MODULE-LEVEL import reddens the first — a function-local one inside push_job does
    not, which is fine: a revived branch has to CALL the class, and that is what the
    second assertion reads. (Pocholo, on 290f6831.)
    """
    assert not hasattr( tfq, "ConfirmationDialogue" ), (
        "todo_fifo_queue imports ConfirmationDialogue again — the class still exists and is "
        "still tested, but the queue is not where it belongs any more"
    )

    body = _code_lines( inspect.getsource( tfq.TodoFifoQueue.push_job ) )
    revived = [ call for call in ( "ConfirmationDialogue(", "is_accepting_jobs()", "pop_blocking_object()" )
                if call in body ]
    assert not revived, f"push_job calls the deleted two-turn machinery again: {revived}"


def _code_lines( source ):
    """The source with whole-line comments dropped — the tombstone QUOTES what it removed,
    so a raw text search would accuse the very comment that explains the deletion."""
    return "\n".join( line for line in source.splitlines() if not line.strip().startswith( "#" ) )


def test_a_near_match_is_still_confirmed_before_it_is_replayed( tmp_path, notifier, monkeypatch ):
    """
    THE POSITIVE HALF, and it has to be behavioural. Confirmation moved to AskFlow's
    near-match ask (step 6b); it did not evaporate. An earlier draft of this test asserted
    that the string `if not interactive` appears in the source — Pocholo kept the string,
    gutted the body under it, and the test stayed green while the real guard went red. A
    grep proves grep works.

    So this drives the flow twice, and BOTH halves are load-bearing:

      * with a human listening, a 95% match is put to them and replayed only on the yes —
        without this, a build that has no near-match branch at all satisfies the other half
        trivially, since a branch that does not exist also never asks anybody;
      * with `interactive=False`, the confirmer is never called AND the answer comes from
        the agent — asserted positively, not as "not a replay", because a receptionist
        answer or a broken command would satisfy a negative while the match was declined
        for a reason nobody wanted.

    RED ON REVERT: delete the near-match branch and the first half fails; accept a near
    match without asking, or ask a caller with nobody on it, and the second does.
    """
    asked   = _FakeConfirmer( response_value="yes" )
    flow    = _NearMatchHarness()._flow( tmp_path, notifier, monkeypatch, asked )
    replay  = flow.ask( "what\'s on my todo list", **_CTX )

    assert asked.requests, "a near match was served with nobody asked — the ask is gone"
    assert replay[ "path" ] == "replay", "the user said yes and the cached answer was not served"

    unattended = _FakeConfirmer( response_value="yes" )
    flow       = _NearMatchHarness()._flow( tmp_path, notifier, monkeypatch, unattended )
    declined   = flow.ask( "what\'s on my todo list", **_CTX, interactive=False )

    assert unattended.requests == [], "a caller with no human on it was put to the user"
    assert declined[ "path" ] == "agent", "the near match was accepted without consent"
