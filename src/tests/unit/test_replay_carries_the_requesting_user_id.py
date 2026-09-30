"""
A replayed snapshot must be addressed to the user who ASKED, not the user who
first asked (row `0e7c9214`).

Measured live on `:7999` 2026-08-30: Rick asked "what is 17 times 23", confirmed
the answer, then asked again. The repeat ran — `Executing SolutionSnapshot code
… Done! in 122 ms` — and the completion frame never reached his browser. The
server said why:

    [WS] Scheduled emission of job_state_transition to user ricardo_felipe_ruiz_6bdc
    [WS] emit_to_user: user ricardo_felipe_ruiz_6bdc not in user_sessions — delivery skipped

His browser session is registered under his UUID `0cf47e2d-…` (the `users` row
id). `ricardo_felipe_ruiz_6bdc` is the OLD system-id format, persisted inside
the stored snapshot from an earlier era.

The mechanism is one line. `TodoFifoQueue._queue_best_snapshot` builds the running
job with `best_snapshot.get_copy( user_email=user_email )`, and `get_copy` injects
the requester's EMAIL but not their USER ID — so the copy carries the original
creator's id into `_transition_to_done`, which emits with `user_id = job.user_id`.
`get_copy`'s own docstring states the principle it half-implements: "snapshots are
loaded from storage without user context. The requesting user's email is injected
at copy time."

⚠️ THE FIXTURE IS THE TEST HERE. The stored id and the requesting id must actually
DIFFER, or a swap between them changes nothing observable and the test passes on a
broken build — the failure mode banked at row `9ad838d6`. Every case below keeps
the two values distinct and asserts the identity, never a count.
"""
import copy

import pytest

from cosa.memory.solution_snapshot import SolutionSnapshot


# The two identities, deliberately unequal. STORED is the old system-id format that
# was actually in the log; REQUESTER is the UUID shape the users row carries.
STORED_USER_ID    = "ricardo_felipe_ruiz_6bdc"
REQUESTER_USER_ID = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"
REQUESTER_EMAIL   = "ricardo.felipe.ruiz@gmail.com"


def _stored_snapshot():
    """
    A snapshot as loaded from storage: it carries its ORIGINAL creator, no requester.

    Built WITHOUT the constructor on purpose. `SolutionSnapshot( question=... )`
    computes an embedding, which needs a model-server key a worktree does not have —
    and `get_copy` is a `copy.copy` plus two attribute writes, so a bare instance
    exercises every line of it. Reaching for the constructor here would add a network
    dependency to a unit test and measure nothing extra.
    """
    snap            = object.__new__( SolutionSnapshot )
    snap.question   = "what is 17 times 23"
    snap.user_id    = STORED_USER_ID
    snap.user_email = ""
    return snap


def test_the_fixture_itself_can_tell_the_two_identities_apart():
    """
    Guard on the guard. If these ever collapse to one value, every assertion below
    passes for free and this file stops measuring anything.
    """
    assert STORED_USER_ID != REQUESTER_USER_ID


def test_a_replayed_snapshot_is_addressed_to_the_user_who_asked():
    """The defect, stated directly: the copy must not keep the original creator's id."""
    snap = _stored_snapshot()

    job = snap.get_copy( user_email=REQUESTER_EMAIL, user_id=REQUESTER_USER_ID )

    assert job.user_id == REQUESTER_USER_ID, (
        "the replayed job is addressed to the snapshot's original creator; "
        "emit_to_user will find no session under that key and drop the answer"
    )


def test_the_stored_snapshot_is_left_alone():
    """
    A copy must not rewrite the record it came from — the stored snapshot is shared
    and gets saved back.
    """
    snap = _stored_snapshot()

    snap.get_copy( user_email=REQUESTER_EMAIL, user_id=REQUESTER_USER_ID )

    assert snap.user_id == STORED_USER_ID


def test_the_email_injection_still_works():
    """The behaviour that was already right must survive the change."""
    snap = _stored_snapshot()

    job = snap.get_copy( user_email=REQUESTER_EMAIL, user_id=REQUESTER_USER_ID )

    assert job.user_email == REQUESTER_EMAIL


def test_omitting_the_requester_leaves_the_stored_id_in_place():
    """
    Back-compatible by construction: callers that pass no user_id get exactly the
    old behaviour, so this change cannot break a caller it did not touch.
    """
    snap = _stored_snapshot()

    job = snap.get_copy()

    assert job.user_id    == STORED_USER_ID
    assert job.user_email == ""


@pytest.mark.parametrize( "blank", [ "", None ] )
def test_a_blank_requester_does_not_erase_the_stored_id( blank ):
    """
    Same shape as the existing `if user_email` guard: a falsy value means "no
    requester context", not "blank it out". An erased id is as undeliverable as a
    stale one.
    """
    snap = _stored_snapshot()

    job = snap.get_copy( user_email=REQUESTER_EMAIL, user_id=blank )

    assert job.user_id == STORED_USER_ID


# ── The call site, which the tests above cannot reach ────────────────────────────
#
# Fixing `get_copy` is inert unless the queue actually HANDS it the requester. Those
# are two edits in two files, and a test of the first says nothing about the second:
# dropping `user_id=user_id` from the call leaves every assertion above green while
# the delivered behaviour is exactly as broken as before the fix. So this reaches
# `_queue_best_snapshot` itself.

class _RecordingSnapshot:
    """Records what the queue asked for, and returns something job-shaped."""

    def __init__( self ):
        self.question            = "what is 17 times 23"
        self.last_question_asked = "what is 17 times 23"
        self.id_hash             = "4b0b5204"
        self.user_id             = STORED_USER_ID
        self.user_email          = ""
        self.seen                = None

    def get_copy( self, user_email="", user_id="" ):
        self.seen = { "user_email": user_email, "user_id": user_id }
        copied = copy.copy( self )
        if user_email: copied.user_email = user_email
        if user_id:    copied.user_id    = user_id
        return copied

    def add_synonymous_question( self, *a, **kw ):
        pass


class _Stop( Exception ):
    """Everything past the copy is another test's business; stop the method there."""


def test_the_queue_hands_the_requesting_identity_to_the_copy():
    """
    The call site, asserted on the REQUEST the queue issues rather than on a verdict
    downstream of it — a test watching only the final answer could not tell a wrong
    id from a delivery that failed for some other reason.
    """
    from cosa.rest.todo_fifo_queue import TodoFifoQueue

    class _Tracker:
        def register_scoped_job( self, *a, **kw ):
            raise _Stop

    queue                  = object.__new__( TodoFifoQueue )
    queue.debug            = False
    queue.verbose          = False
    queue.push_counter     = 0
    queue.user_job_tracker = _Tracker()

    snap = _RecordingSnapshot()

    with pytest.raises( _Stop ):
        queue._queue_best_snapshot( snap, 100.0, REQUESTER_USER_ID, REQUESTER_EMAIL )

    assert snap.seen == {
        "user_email" : REQUESTER_EMAIL,
        "user_id"    : REQUESTER_USER_ID,
    }, "the queue did not hand the requesting user's id to the snapshot copy"
