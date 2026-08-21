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
names it; drop AskFlow's near-match ask and the second one does.

⚠️ Run scoped — `pytest src/tests/unit/...` — an unscoped run collects `src/tmp/`, which
exits at import time.
"""

import inspect

from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.v2.flow import AskFlow
import cosa.rest.todo_fifo_queue as tfq


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

    RED ON REVERT: restore the branch — or just the import — and this names it.
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


def test_a_near_match_is_still_confirmed_before_it_is_replayed():
    """
    THE POSITIVE HALF. Confirmation moved to AskFlow's near-match ask (step 6b); it did
    not evaporate. `_near_match_replay` takes `interactive` and must not replay when
    nobody is there to answer.

    RED ON REVERT: delete the near-match ask, or stop threading `interactive` into it,
    and this fails — which is what stops the first two tests from being satisfied by a
    build that simply replays everything without asking.
    """
    assert hasattr( AskFlow, "_near_match_replay" ), (
        "AskFlow has no near-match ask — with push_job's two-turn dialogue deleted, nothing "
        "in the system confirms a near match before serving it"
    )

    parameters = inspect.signature( AskFlow._near_match_replay ).parameters
    assert "interactive" in parameters, (
        "the near-match ask no longer takes `interactive` — it cannot tell whether anybody is "
        "listening, and asking a question nobody can answer is how the old dialogue went wrong"
    )

    source = inspect.getsource( AskFlow._near_match_replay )
    assert "if not interactive" in source, (
        "the near-match ask no longer declines when nobody is listening"
    )
