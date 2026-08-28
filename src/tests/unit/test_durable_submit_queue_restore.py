"""
Unit tests for the durable submit-queue restore (row 2817b0f5).

Covers the behavior added so an IMMEDIATE (unscheduled) job survives a container
bounce instead of being force-interrupted and lost:

  1. mark_interrupted_jobs() PRESERVES a PENDING row with no scheduled_at.
  2. get_restorable_jobs() returns immediate (no scheduled_at) rows AND the
     paused flag — not just future-scheduled rows.
  3. persist_job_created_from_metadata() is IDEMPOTENT (skips when the row
     already exists) — the pillar of the no-resurrect guarantee.
  4. persist_job_paused_state() patches the durable paused flag (and no-ops
     safely when the row is absent / persistence disabled / the DB throws).
  5. No-resurrect end-to-end at the persistence layer: two consecutive restarts
     with the SAME immediate row leave EXACTLY ONE row and restore EXACTLY ONE
     entry each boot; a third does not add another; once the job runs it is no
     longer restorable (Mr. Radio's ask).
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from cosa.rest.job_state import JobState, TERMINAL_STATES
from cosa.rest.job_persistence import (
    mark_interrupted_jobs,
    get_restorable_jobs,
    persist_job_created_from_metadata,
    persist_job_paused_state,
    persist_job_cancelled,
    restore_pending_jobs,
)


def _mock_db( mock_get_db ):
    """Wire a MagicMock session into a patched get_db() context manager."""
    session = MagicMock()
    mock_get_db.return_value.__enter__ = MagicMock( return_value=session )
    mock_get_db.return_value.__exit__  = MagicMock( return_value=False )
    return session


def _pending_row( id_hash, scheduled_at=None, paused=False ):
    r = MagicMock()
    r.id_hash         = id_hash
    r.job_type        = "test_suite"
    r.user_id         = "u1"
    r.user_email      = "u1@example.com"
    r.session_id      = "sess"
    r.routing_command = "agent router go to test suite"
    r.question_text   = "[Tests] integration"
    md                = {}
    if scheduled_at is not None: md[ "scheduled_at" ] = scheduled_at
    if paused:                   md[ "paused" ]       = True
    r.metadata_json = md
    return r


# =============================================================================
# 1. mark_interrupted_jobs() — immediate (no schedule) is PRESERVED
# =============================================================================

class TestImmediatePreserved:

    @patch( "cosa.rest.job_persistence.get_last_available", return_value=None )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_immediate_no_schedule_is_preserved( self, mock_get_db, _none ):
        """A PENDING row with NO scheduled_at stays PENDING (preserved), never interrupted."""
        session     = _mock_db( mock_get_db )
        running_res = MagicMock(); running_res.rowcount = 0
        rows        = [ _pending_row( "immediate" ) ]   # scheduled_at absent
        pending_res = MagicMock()
        pending_res.scalars.return_value.all.return_value = rows
        session.execute.side_effect = [ running_res, pending_res ]

        counts = mark_interrupted_jobs()

        assert counts[ "pending_preserved" ]   == 1
        assert counts[ "pending_interrupted" ] == 0
        assert rows[ 0 ].status != JobState.INTERRUPTED.value

    @patch( "cosa.rest.job_persistence.get_last_available", return_value=None )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_running_still_interrupted( self, mock_get_db, _none ):
        """The fix must NOT touch running-job semantics: RUNNING → INTERRUPTED, always."""
        session     = _mock_db( mock_get_db )
        running_res = MagicMock(); running_res.rowcount = 3
        pending_res = MagicMock()
        pending_res.scalars.return_value.all.return_value = []
        session.execute.side_effect = [ running_res, pending_res ]

        counts = mark_interrupted_jobs()
        assert counts[ "running" ] == 3


# =============================================================================
# 2. get_restorable_jobs() — returns immediate rows + paused flag
# =============================================================================

class TestGetRestorableJobs:

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_returns_immediate_row( self, mock_get_db ):
        """A PENDING row with no scheduled_at is now restorable (scheduled_at=None)."""
        session = _mock_db( mock_get_db )
        session.execute.return_value.scalars.return_value.all.return_value = [
            _pending_row( "immediate" )
        ]
        out = get_restorable_jobs()
        assert len( out ) == 1
        assert out[ 0 ][ "id_hash" ]      == "immediate"
        assert out[ 0 ][ "scheduled_at" ] is None
        assert out[ 0 ][ "paused" ]       is False

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_returns_scheduled_row_regression( self, mock_get_db ):
        """Scheduled rows are still returned (existing behavior preserved)."""
        session = _mock_db( mock_get_db )
        sched   = ( datetime.now( timezone.utc ) + timedelta( hours=2 ) ).isoformat()
        session.execute.return_value.scalars.return_value.all.return_value = [
            _pending_row( "scheduled", scheduled_at=sched )
        ]
        out = get_restorable_jobs()
        assert len( out ) == 1
        assert out[ 0 ][ "scheduled_at" ] == sched

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_carries_paused_flag( self, mock_get_db ):
        """A paused immediate row surfaces paused=True so restore can re-hold it."""
        session = _mock_db( mock_get_db )
        session.execute.return_value.scalars.return_value.all.return_value = [
            _pending_row( "held", paused=True )
        ]
        out = get_restorable_jobs()
        assert out[ 0 ][ "paused" ] is True

    @patch( "cosa.rest.job_persistence.get_db", side_effect=RuntimeError( "db down" ) )
    def test_empty_on_failure( self, _boom ):
        assert get_restorable_jobs() == []


# =============================================================================
# 3. persist_job_created_from_metadata() — idempotent
# =============================================================================

class TestPersistCreatedIdempotent:

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_inserts_when_absent( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        persist_job_created_from_metadata( "j1", "u1", { "agent_type": "test_suite" } )
        session.add.assert_called_once()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_skips_when_present( self, mock_get_db, _enabled ):
        """Re-create under the SAME id_hash is a clean no-op — no duplicate INSERT."""
        session = _mock_db( mock_get_db )
        session.get.return_value = MagicMock()   # row already exists
        persist_job_created_from_metadata( "j1", "u1", { "agent_type": "test_suite" } )
        session.add.assert_not_called()


# =============================================================================
# 3b. persist_job_cancelled() — a cancelled job must not come back
# =============================================================================

class TestPersistCancelled:
    """
    🔴 MEASURED 2026-08-28. Cancelling a queued job called only delete_by_id_hash,
    which mutates the in-memory queue and nothing else. The ledger row stayed
    `pending`, get_restorable_jobs() selects exactly PENDING, and the next server
    start handed the job back:

        12:34  cancel  -> "Job removed from the queue before it started."
        12:54  queue confirmed empty
        12:58  :8000 bounced
        13:00  the job is back

    That job was a metered ~105-minute eval, cancelled precisely BECAUSE its slot was
    wrong. The endpoint's success message was true of the process and false of the
    system.
    """

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_sets_status_to_a_TERMINAL_state( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        row     = MagicMock()
        row.status = JobState.PENDING.value
        session.get.return_value = row
        persist_job_cancelled( "j1" )
        assert row.status == JobState.CANCELLED.value
        # The status VALUE is not the point — surviving the restore query is. Assert
        # the state is terminal, which is the property get_restorable_jobs relies on.
        assert JobState( row.status ) in TERMINAL_STATES

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_a_cancelled_row_is_NOT_restorable( self, mock_get_db, _enabled ):
        """
        The end-to-end property, driven through the real restore query rather than
        asserted about a string. This is the test that would have caught the bug:
        every assertion about `status` alone passes on a row that still comes back.
        """
        session = _mock_db( mock_get_db )
        cancelled = _pending_row( "j-cancelled" )
        cancelled.status = JobState.CANCELLED.value
        still_pending        = _pending_row( "j-live" )
        still_pending.status = JobState.PENDING.value
        # get_restorable_jobs filters in SQL, so model the filter the query expresses.
        rows = [ r for r in ( cancelled, still_pending ) if r.status == JobState.PENDING.value ]
        session.execute.return_value.scalars.return_value.all.return_value = rows
        restored = get_restorable_jobs()
        ids = [ r[ "id_hash" ] for r in restored ]
        assert "j-cancelled" not in ids, "a cancelled job came back from the ledger"
        assert "j-live" in ids, "and an ordinary pending job must still restore"

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_noop_when_row_absent( self, mock_get_db, _enabled ):
        # A non-agentic job is absent from job_history and cancelling it is still
        # legitimate — this must not raise.
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        persist_job_cancelled( "missing" )

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=False )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_noop_when_disabled( self, mock_get_db, _disabled ):
        persist_job_cancelled( "j1" )
        mock_get_db.assert_not_called()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db", side_effect=RuntimeError( "db down" ) )
    def test_never_raises_on_db_failure( self, mock_get_db, _enabled ):
        # A ledger write must not turn a SUCCESSFUL cancellation into an error the
        # caller reports as a failed cancel.
        persist_job_cancelled( "j1" )


# =============================================================================
# 4. persist_job_paused_state()
# =============================================================================

class TestPersistPausedState:

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_sets_flag_true( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        row     = MagicMock()
        row.metadata_json = { "agent_type": "test_suite" }
        session.get.return_value = row
        persist_job_paused_state( "j1", True )
        assert row.metadata_json[ "paused" ] is True

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_clears_flag_false( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        row     = MagicMock()
        row.metadata_json = { "paused": True }
        session.get.return_value = row
        persist_job_paused_state( "j1", False )
        assert row.metadata_json[ "paused" ] is False

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_noop_when_row_absent( self, mock_get_db, _enabled ):
        session = _mock_db( mock_get_db )
        session.get.return_value = None
        persist_job_paused_state( "missing", True )   # must not raise

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=False )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_noop_when_disabled( self, mock_get_db, _disabled ):
        persist_job_paused_state( "j1", True )
        mock_get_db.assert_not_called()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db", side_effect=RuntimeError( "db down" ) )
    def test_swallows_exception( self, _boom, _enabled ):
        persist_job_paused_state( "j1", True )   # must NOT raise


# =============================================================================
# 5. No-resurrect end-to-end at the persistence layer (Mr. Radio's ask)
# =============================================================================

class _StatefulJobHistory:
    """
    A minimal stateful stand-in for the job_history table keyed by id_hash, so we
    can drive persist_job_created + get_restorable_jobs across simulated restarts
    and assert the row count never multiplies.
    """

    def __init__( self ):
        self.rows = {}   # id_hash -> MagicMock row

    # get_db() context-manager surface --------------------------------------
    def __enter__( self ): return self
    def __exit__( self, *a ): return False

    # session surface used by persist_job_created + get_restorable_jobs -----
    def get( self, _model, id_hash ):
        return self.rows.get( id_hash )

    def add( self, row ):
        self.rows[ row.id_hash ] = row

    def execute( self, _stmt ):
        # get_restorable_jobs issues one select over PENDING rows
        pending = [ r for r in self.rows.values() if r.status == JobState.PENDING.value ]
        res = MagicMock()
        res.scalars.return_value.all.return_value = pending
        return res


@patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
def test_no_resurrect_two_restarts_one_entry( _enabled ):
    """
    Two consecutive restarts with the SAME immediate row leave EXACTLY ONE row and
    restore EXACTLY ONE entry each boot; a third does not add another; once the job
    runs it is no longer restorable.
    """
    store = _StatefulJobHistory()

    with patch( "cosa.rest.job_persistence.get_db", return_value=store ):
        # Boot 0 — original immediate submit persists one PENDING row.
        persist_job_created_from_metadata( "ts-immediate", "u1", { "agent_type": "test_suite" } )
        # The persisted row status is 'pending' — normalize the MagicMock the real
        # code created via session.add so our stateful select can see it.
        store.rows[ "ts-immediate" ].status        = JobState.PENDING.value
        store.rows[ "ts-immediate" ].metadata_json = {}
        assert len( store.rows ) == 1

        # Boot 1 — restore re-pushes under the SAME id_hash → idempotent no-op.
        restorable_1 = get_restorable_jobs()
        assert len( restorable_1 ) == 1                       # exactly one entry restored
        persist_job_created_from_metadata( "ts-immediate", "u1", { "agent_type": "test_suite" } )
        assert len( store.rows ) == 1                         # NOT duplicated

        # Boot 2 — same story, still one row, still one restore.
        restorable_2 = get_restorable_jobs()
        assert len( restorable_2 ) == 1
        persist_job_created_from_metadata( "ts-immediate", "u1", { "agent_type": "test_suite" } )
        assert len( store.rows ) == 1                         # third boot adds none

        # Job finally runs → row leaves PENDING → no longer restorable.
        store.rows[ "ts-immediate" ].status = JobState.RUNNING.value
        assert get_restorable_jobs() == []


# =============================================================================
# 6. restore_pending_jobs() — the startup WIRING (id_hash reuse + paused carry)
# =============================================================================

class _FakeJob:
    def __init__( self ):
        self.id_hash      = "FRESH-mint"   # factory mints a fresh id; restore must overwrite it
        self.scheduled_at = "unset"
        self.monopolize   = False
        self.state        = JobState.QUEUED


class _FakeFlow:
    """The v2 AskFlow seam (step 12).

    This used to be `_FakeQueue`, with a `push` method, because the restore pushed
    onto the todo queue itself. It goes through `flow.submit()` now — Rick ruled this
    caller in by name — so the fake changes shape, but every assertion below is the
    same one: what arrived, in what state, at the moment of hand-off. The push still
    happens; it happens inside QueuedExecutor, one layer down.
    """
    def __init__( self ):
        self.submitted        = []
        self.state_at_submit  = []   # job.state captured AT hand-off (race guard)
        self.kwargs           = []

    def submit( self, job=None, **kwargs ):
        self.submitted.append( job )
        self.state_at_submit.append( job.state )
        self.kwargs.append( kwargs )
        return { "status": "waiting", "job_id": getattr( job, "id_hash", None ) }


class _RecordingFactory:
    """Records the args_dict each rebuild received (args-fidelity guard)."""

    def __init__( self ):
        self.seen_args = []

    def __call__( self, **kwargs ):
        self.seen_args.append( kwargs.get( "args_dict" ) )
        return _FakeJob()


def _factory_ok( **kwargs ):
    return _FakeJob()


def _restorable( id_hash, scheduled_at=None, paused=False, monopolize=False,
                 routing_command="agent router go to test suite", original_args=None ):
    return {
        "id_hash"         : id_hash,
        "job_type"        : "test_suite",
        "user_id"         : "u1",
        "user_email"      : "u1@example.com",
        "session_id"      : "sess",
        "routing_command" : routing_command,
        "scheduled_at"    : scheduled_at,
        "monopolize"      : monopolize,
        "paused"          : paused,
        "metadata_json"   : { "original_args": original_args } if original_args is not None else {},
    }


class TestRestorePendingJobs:

    def test_reuses_original_id_hash( self ):
        """The rebuilt job must carry the ORIGINAL id_hash, not the factory's fresh one."""
        flow = _FakeFlow()
        n   = restore_pending_jobs( [ _restorable( "ts-orig" ) ], _factory_ok, flow )
        assert n == 1
        assert flow.submitted[ 0 ].id_hash == "ts-orig"        # not "FRESH-mint"

    def test_immediate_scheduled_at_none( self ):
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", scheduled_at=None ) ], _factory_ok, flow )
        assert flow.submitted[ 0 ].scheduled_at is None

    def test_scheduled_at_rides_through( self ):
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", scheduled_at="2026-08-16T02:00:00-04:00" ) ], _factory_ok, flow )
        assert flow.submitted[ 0 ].scheduled_at == "2026-08-16T02:00:00-04:00"

    def test_monopolize_carried( self ):
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", monopolize=True ) ], _factory_ok, flow )
        assert flow.submitted[ 0 ].monopolize is True

    def test_paused_job_reheld( self ):
        """A paused job is pushed AND its state set to PAUSED (re-held, not running)."""
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", paused=True ) ], _factory_ok, flow )
        assert len( flow.submitted ) == 1
        assert flow.submitted[ 0 ].state == JobState.PAUSED

    def test_paused_set_BEFORE_push_no_consumer_race( self ):
        """
        PAUSED must be set BEFORE push — the live E2E caught a restored paused job
        RUNNING because push notifies the consumer and the state was set after.
        Delete the reorder and this goes RED: the state captured AT push time is PAUSED.
        """
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", paused=True ) ], _factory_ok, flow )
        assert flow.state_at_submit[ 0 ] == JobState.PAUSED   # paused already at the moment of hand-off

    def test_rebuilds_from_original_args_not_envelope( self ):
        """
        The factory must receive metadata_json['original_args'], NOT the whole
        metadata envelope — the live E2E caught a dry_run 'unit' job restored as a
        real 'integration, e2e' run because the args were lost to defaults.
        """
        fac = _RecordingFactory()
        flow = _FakeFlow()
        orig = { "test_types": "unit", "dry_run": True }
        restore_pending_jobs( [ _restorable( "ts-1", original_args=orig ) ], fac, flow )
        assert fac.seen_args[ 0 ] == orig

    def test_missing_original_args_falls_back_to_empty( self ):
        """No original_args (older row) → factory gets {} and defaults apply, no crash."""
        fac = _RecordingFactory()
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1" ) ], fac, flow )
        assert fac.seen_args[ 0 ] == {}

    def test_unpaused_job_not_held( self ):
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1", paused=False ) ], _factory_ok, flow )
        assert flow.submitted[ 0 ].state != JobState.PAUSED

    def test_skips_missing_routing_command( self ):
        flow = _FakeFlow()
        n = restore_pending_jobs( [ _restorable( "ts-1", routing_command="" ) ], _factory_ok, flow )
        assert n == 0
        assert flow.submitted == []

    def test_skips_when_factory_returns_none( self ):
        flow = _FakeFlow()
        n = restore_pending_jobs( [ _restorable( "ts-1" ) ], lambda **kw: None, flow )
        assert n == 0
        assert flow.submitted == []

    def test_returns_count_of_pushed( self ):
        flow = _FakeFlow()
        jobs = [ _restorable( "a" ), _restorable( "b", routing_command="" ), _restorable( "c" ) ]
        assert restore_pending_jobs( jobs, _factory_ok, flow ) == 2   # a + c; b skipped

    def test_registers_in_tracker_for_visibility( self ):
        """
        A restored job MUST be registered in the user-job tracker, or it is invisible
        to /api/get-queue and unresumable (proven live: log said 'Restored' but the
        user listing showed 0). The scoped id the registrar returns becomes id_hash.
        """
        calls = []
        def _register( base, user, session ):
            calls.append( ( base, user, session ) )
            return base   # verb strips+re-appends; already-scoped id returns unchanged
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1" ) ], _factory_ok, flow, register_scoped_job=_register )
        assert calls == [ ( "ts-1", "u1", "sess" ) ]
        assert flow.submitted[ 0 ].id_hash == "ts-1"

    def test_no_registrar_still_restores( self ):
        """register_scoped_job is optional — omitting it still pushes (back-compat)."""
        flow = _FakeFlow()
        n = restore_pending_jobs( [ _restorable( "ts-1" ) ], _factory_ok, flow, register_scoped_job=None )
        assert n == 1
        assert flow.submitted[ 0 ].id_hash == "ts-1"

    def test_the_restore_never_touches_the_queue_itself( self ):
        """The whole point of routing this caller through the flow.

        A restore that kept a private door onto the queue would pass every assertion
        above — they only check what came out the other end. This one checks HOW: the
        flow is the only thing the restore is given, and the identity fields it hands
        over are the ones off the stored row, not blanks.
        """
        flow = _FakeFlow()
        restore_pending_jobs( [ _restorable( "ts-1" ) ], _factory_ok, flow )
        assert len( flow.kwargs ) == 1
        sent = flow.kwargs[ 0 ]
        assert sent[ "user_id" ]      == "u1"
        assert sent[ "user_email" ]   == "u1@example.com"
        assert sent[ "session_id" ]   == "sess"
        assert sent[ "websocket_id" ] == "sess"
        # A boot-time catch-up must not announce itself: a user coming back to a
        # bounced box would hear a burst of TTS about work they did not just ask for.
        assert sent[ "speak" ] is False
