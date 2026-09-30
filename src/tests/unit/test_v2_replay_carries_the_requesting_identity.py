"""
The v2 executors must address a replayed snapshot to the user who ASKED — row
`0e7c9214`, the half my earlier fix did NOT close.

That row reports two user-visible symptoms from one repeat ask: the completion frame
never arrives, and the answer is never spoken. `0b57602f` closed the first on the v1
tail (`TodoFifoQueue._queue_best_snapshot`). This closes the v2 door, which is the one
the live traffic actually goes through, and it is where the SPOKEN answer was lost.

WHAT THE SERVER DID, in its own words — the two lines are adjacent in the dev log and
they are two different failures, not one:

    [NOTIFY] Warning: No user_email and no LUPIN_DEV_EMAIL — notification skipped
    [WS] emit_to_user: user ricardo_felipe_ruiz_6bdc not in user_sessions — delivery skipped

MECHANISM. `Work` carries `user_id` AND `user_email`, and on the queued path
`QueuedExecutor.submit` pushes `work.job` VERBATIM — it scopes the id_hash and stamps
neither field. A snapshot loaded from storage therefore keeps whoever asked FIRST: an
old-format `user_id` nobody holds a session under, and an EMPTY `user_email`, which is
what makes `FifoQueue._notify` skip before TTS is ever reached
(`if not resolved_email and job and job.user_email`).

The tell that this was an omission rather than a decision: `Work.user_email` was
declared on the dataclass and READ NOWHERE in the module. Carried the whole way and
dropped at the last step.

`InlineExecutor._replay` has the same shape one level down — `for_current_user` copies
`user_id` and `session_id` and not `user_email`.

⚠️ FIXTURE DISCIPLINE, and it is why these tests can see anything: the STORED identity
and the REQUESTING identity are deliberately different values, with a guard asserting
they stay that way. Two equal values cannot reveal a swap between them (row `9ad838d6`),
and I have already been bitten by exactly that on this row's sibling — an `acked` equal
to `recipients` made an operand swap print the identical sentence and survive.
"""
import pytest

from cosa.rest.v2.executor import InlineExecutor, QueuedExecutor, Work
from cosa.rest.v2.trace import StageTrace


STORED_USER_ID     = "ricardo_felipe_ruiz_6bdc"          # what the log showed, old format
STORED_USER_EMAIL  = ""                                   # storage carries no email
ASKER_USER_ID      = "0cf47e2d-d5a1-4cd4-addf-79810fd32b15"
ASKER_USER_EMAIL   = "ricardo.felipe.ruiz@gmail.com"
ASKER_SESSION      = "slow zebra"


class _StoredSnapshot:
    """A snapshot as loaded from storage: it carries its ORIGINAL creator only."""

    def __init__( self ):
        self.id_hash    = "4b0b5204"
        self.user_id    = STORED_USER_ID
        self.user_email = STORED_USER_EMAIL
        self.session_id = "some-old-session"
        self.answer     = "391"
        self.is_cache_hit = False

    # for_current_user is exercised through the real SolutionSnapshot elsewhere; the
    # inline test below uses the real class so this stub is only for the queued path.


class _Tracker:
    def register_scoped_job( self, id_hash, user_id, session_id ):
        return f"{id_hash}::{user_id}"


class _Queue:
    def __init__( self ):
        self.user_job_tracker = _Tracker()
        self.pushed           = []

    def push( self, job ):
        self.pushed.append( job )


def _work( job, kind="replay" ):
    return Work( kind=kind, job=job, user_id=ASKER_USER_ID, user_email=ASKER_USER_EMAIL,
                 session_id=ASKER_SESSION, snapshotable=False )


def test_the_fixture_keeps_the_two_identities_distinct():
    """If these ever collapse, every assertion below passes for free."""
    assert STORED_USER_ID    != ASKER_USER_ID
    assert STORED_USER_EMAIL != ASKER_USER_EMAIL


def test_the_queued_job_is_addressed_to_the_user_who_asked():
    """The completion frame is emitted with `job.user_id`; a stale one reaches nobody."""
    queue = _Queue()
    snap  = _StoredSnapshot()

    QueuedExecutor( queue ).submit( _work( snap ), StageTrace() )

    assert queue.pushed[ 0 ].user_id == ASKER_USER_ID


def test_the_queued_job_carries_the_asker_email_so_the_answer_can_be_SPOKEN():
    """
    This is the symptom Rick reported: job announced, answer never spoken. `_notify`
    resolves `job.user_email` and returns early when it is empty, so an unstamped
    email silences the answer without failing anything.
    """
    queue = _Queue()
    snap  = _StoredSnapshot()

    QueuedExecutor( queue ).submit( _work( snap ), StageTrace() )

    assert queue.pushed[ 0 ].user_email == ASKER_USER_EMAIL


def test_a_work_with_no_email_leaves_the_stored_value_alone():
    """
    Falsy means "no requester context", never "blank it out" — the same guard shape the
    v1 fix uses. An erased email is as silent as a stale one.
    """
    queue = _Queue()
    snap  = _StoredSnapshot()
    snap.user_email = "someone@else.example"
    w = Work( kind="replay", job=snap, user_id=ASKER_USER_ID, user_email="",
              session_id=ASKER_SESSION, snapshotable=False )

    QueuedExecutor( queue ).submit( w, StageTrace() )

    assert queue.pushed[ 0 ].user_email == "someone@else.example"


def test_an_agent_job_is_stamped_too_not_only_a_replay():
    """
    The queued path takes "every kind, no exceptions" by its own docstring, so the
    stamping must not be special-cased to replay — an agent job queued for a user is
    addressed the same way.
    """
    queue = _Queue()
    job   = _StoredSnapshot()

    QueuedExecutor( queue ).submit( _work( job, kind="agent" ), StageTrace() )

    assert queue.pushed[ 0 ].user_id    == ASKER_USER_ID
    assert queue.pushed[ 0 ].user_email == ASKER_USER_EMAIL


def test_the_id_hash_scoping_still_happens():
    """The behaviour that was already right must survive the change."""
    queue = _Queue()
    snap  = _StoredSnapshot()

    QueuedExecutor( queue ).submit( _work( snap ), StageTrace() )

    assert queue.pushed[ 0 ].id_hash == f"4b0b5204::{ASKER_USER_ID}"


def test_the_inline_replay_copy_carries_the_asker_email( monkeypatch ):
    """
    `InlineExecutor._replay` builds its per-user copy with `for_current_user`, which
    copied user_id and session_id and not the email — the same omission one level down.
    """
    from cosa.memory.solution_snapshot import SolutionSnapshot

    snap            = object.__new__( SolutionSnapshot )
    snap.user_id    = STORED_USER_ID
    snap.user_email = STORED_USER_EMAIL
    snap.session_id = "old"
    snap.answer     = "391"

    copy_ = snap.for_current_user( ASKER_USER_ID, ASKER_SESSION, user_email=ASKER_USER_EMAIL )

    assert copy_.user_id    == ASKER_USER_ID
    assert copy_.user_email == ASKER_USER_EMAIL
    assert snap.user_email  == STORED_USER_EMAIL, "the stored snapshot was mutated"


# ── the PRODUCTION callers, added after Rachel 🕊️ caught a parameter with none ───
#
# The first cut added `user_email` to `for_current_user` and then never passed it from
# production code — a parameter only my own test exercised. A defaulted parameter with
# no caller is not a fix; it is a fix-shaped thing that leaves the defect running, and
# the suite reads green either way. Both live callers are now wired and asserted.

def test_the_inline_executor_passes_the_asker_email_to_the_copy( monkeypatch ):
    """
    `InlineExecutor._replay` — executor.py:115. Asserted on the ARGUMENTS the executor
    hands `for_current_user`, not on a downstream verdict: a test watching only the
    answer cannot tell a wrong address from a delivery that failed for another reason.
    """
    from cosa.rest.v2.executor import InlineExecutor
    from cosa.rest.v2.trace import StageTrace

    seen = {}

    class _Snap:
        def for_current_user( self, user_id, session_id, user_email="" ):
            seen.update( user_id=user_id, session_id=session_id, user_email=user_email )
            return self
        id_hash = "4b0b5204"
        answer  = "391"
        def run_code( self ): pass
        def run_formatter( self ): return "391"

    InlineExecutor()._replay( _work( _Snap() ), StageTrace() )

    assert seen[ "user_email" ] == ASKER_USER_EMAIL
    assert seen[ "user_id" ]    == ASKER_USER_ID


def test_the_v1_cache_hit_path_passes_the_current_asker_email():
    """
    `RunningFifoQueue` cache hit — running_fifo_queue.py:1957, the THIRD site of the same
    omission. Its own comment has always read "use current user, not original creator";
    it carried the id and the session and stopped short of the email, so a cache hit was
    announced to the original asker's (empty) address.

    Asserted by reading the call the source makes, because standing up a RunningFifoQueue
    here would test the harness rather than the line.
    """
    import inspect

    from cosa.rest import running_fifo_queue

    src = inspect.getsource( running_fifo_queue )
    call = src.split( "done_queue_entry = cached_snapshot.for_current_user(" )[ 1 ].split( ")" )[ 0 ]

    assert "user_email=current_user_email" in call, (
        "the cache-hit copy does not carry the current asker's email; the answer is "
        "announced to whoever asked first"
    )
    assert "current_user_email = original_job.user_email" in src
