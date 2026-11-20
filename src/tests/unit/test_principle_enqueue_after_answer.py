"""
The answer door queues the silent extractor, then the sweep, once per owner answer.

The queue is a recording double, so a count of pushes is a count of jobs. The sweep thread is started inline by the test.
The ini switches are real keys read through a patched config object that answers by key, so a swapped key reddens a test.
"""

import uuid

import pytest

import cosa.agents.principle_learner.enqueue_after_answer as eaa
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob
from cosa.agents.principle_learner.review_card_sweep import ReviewCardSweepJob
from cosa.rest.job_state import JobState

OWNER = str( uuid.UUID( "00000000-0000-4000-8000-0000000000aa" ) )
NID   = str( uuid.UUID( "00000000-0000-4000-8000-0000000000bb" ) )
CARD  = { "review_card": True, "questions": [] }
ASK   = { "questions": [ { "header": "h" } ] }


class Tracker:
    """Records each registration and returns a scoped id the way the real tracker does."""

    def __init__( self ): self.calls = []

    def register_scoped_job( self, base, user_id, session_id=None ):
        self.calls.append( ( base, user_id, session_id ) )
        return f"{base}::{user_id}"


class Queue:
    """A todo-queue double: keeps the pushed jobs in order."""

    def __init__( self ):
        self.user_job_tracker = Tracker()
        self.pushed           = []

    def push( self, job ): self.pushed.append( job )


@pytest.fixture
def keys( monkeypatch ):
    """Answer _flag from a dict, and fail on an unknown key."""
    values = { eaa.ENABLE_KEY: True, eaa.SHOW_KEY: True }
    def _flag( key ): return values[ key ]
    monkeypatch.setattr( eaa, "_flag", _flag )
    return values


def run( queue, options=ASK, **kwargs ):
    """Enqueue one answer, starting the sweep thread inline; return ( report, threads )."""
    threads = []
    report  = eaa.enqueue_after_answer( queue, NID, OWNER, "o@example.com", options, start=threads.append, sleep=lambda s: None, **kwargs )
    return report, threads


class TestOneAnswerOneExtractorAndOneSweep:

    def test_the_extractor_is_pushed_now_and_the_sweep_only_after_it_ends( self, keys ):
        queue          = Queue()
        report, threads = run( queue )
        assert report[ "queued" ] and report[ "reason" ] == "queued"
        assert [ type( job ) for job in queue.pushed ] == [ PrincipleExtractorJob ]
        extractor = queue.pushed[ 0 ]
        assert extractor.notification_id == NID and str( extractor.user_id ) == OWNER and extractor.user_email == "o@example.com"
        assert len( threads ) == 1
        extractor.state = JobState.COMPLETED
        threads[ 0 ].run()
        assert [ type( job ) for job in queue.pushed ] == [ PrincipleExtractorJob, ReviewCardSweepJob ]
        assert str( queue.pushed[ 1 ].user_id ) == OWNER

    def test_the_sweep_waits_by_polling_and_still_runs_after_a_failed_extractor( self, keys ):
        queue          = Queue()
        slept          = []
        threads        = []
        eaa.enqueue_after_answer( queue, NID, OWNER, "o@example.com", ASK, poll_seconds=5, start=threads.append,
                                  sleep=lambda s: ( slept.append( s ), setattr( queue.pushed[ 0 ], "state", JobState.FAILED ) ) )
        threads[ 0 ].run()
        assert slept == [ 5 ]
        assert len( queue.pushed ) == 2 and isinstance( queue.pushed[ 1 ], ReviewCardSweepJob )

    def test_a_stuck_extractor_does_not_hold_the_sweep_past_the_give_up_time( self, keys ):
        queue   = Queue()
        threads = []
        eaa.enqueue_after_answer( queue, NID, OWNER, "o@example.com", ASK, poll_seconds=10, give_up_after=30, start=threads.append, sleep=lambda s: None )
        threads[ 0 ].run()
        assert [ type( job ) for job in queue.pushed ] == [ PrincipleExtractorJob, ReviewCardSweepJob ]

    def test_a_review_card_answer_queues_neither_job( self, keys ):
        queue          = Queue()
        report, threads = run( queue, CARD )
        assert report == { "queued": False, "reason": "review_card", "job_id": None }
        assert queue.pushed == [] and threads == []

    def test_the_real_thread_start_path_runs_and_pushes_the_sweep( self, keys ):
        queue  = Queue()
        report = eaa.enqueue_after_answer( queue, NID, OWNER, "o@example.com", ASK, poll_seconds=0.01 )
        queue.pushed[ 0 ].state = JobState.COMPLETED
        import time
        for _ in range( 200 ):
            if len( queue.pushed ) == 2: break
            time.sleep( 0.01 )
        assert report[ "queued" ] and len( queue.pushed ) == 2


class TestTheShowSwitch:

    def test_show_registers_both_jobs_under_the_owner( self, keys ):
        queue           = Queue()
        report, threads = run( queue )
        queue.pushed[ 0 ].state = JobState.COMPLETED
        threads[ 0 ].run()
        assert [ call[ 1 ] for call in queue.user_job_tracker.calls ] == [ OWNER, OWNER ]
        assert [ job.id_hash for job in queue.pushed ] == [ f"{call[ 0 ]}::{OWNER}" for call in queue.user_job_tracker.calls ]
        assert report[ "job_id" ] == queue.pushed[ 0 ].id_hash

    def test_hide_registers_neither_job_but_still_pushes_both( self, keys ):
        keys[ eaa.SHOW_KEY ] = False
        queue                = Queue()
        _, threads           = run( queue )
        queue.pushed[ 0 ].state = JobState.COMPLETED
        threads[ 0 ].run()
        assert queue.user_job_tracker.calls == [] and len( queue.pushed ) == 2
        assert "::" not in queue.pushed[ 0 ].id_hash


class TestTheSwitchesAreRealIniKeys:

    def test_is_enabled_reads_the_enable_key_through_the_config( self, monkeypatch ):
        seen = []
        class Config:
            def __init__( self, env_var_name ): pass
            def get_required( self, key, return_type="string" ): seen.append( ( key, return_type ) ); return True
        monkeypatch.setattr( eaa, "ConfigurationManager", Config )
        assert eaa.is_enabled() is True and seen == [ ( "prediction learner enqueue extractor on answer", "boolean" ) ]

    def test_the_committed_ini_defaults_are_off_for_the_enqueue_and_on_for_show( self ):
        from cosa.config.configuration_manager import ConfigurationManager
        config = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        assert config.get_required( eaa.ENABLE_KEY, return_type="boolean" ) is False
        assert config.get_required( eaa.SHOW_KEY, return_type="boolean" ) is True


class TestTheHookInTheRouter:

    def test_a_disabled_switch_touches_neither_database_nor_queue( self, monkeypatch ):
        import cosa.rest.routers.notifications as notif
        monkeypatch.setattr( eaa, "is_enabled", lambda: False )
        assert notif._enqueue_extractor_sync( NID, { "recipient_id": OWNER, "response_options": ASK } ) == { "queued": False, "reason": "disabled", "job_id": None }

    def _wire( self, monkeypatch, owner ):
        import cosa.rest.routers.notifications as notif
        import contextlib
        import sys
        import types
        monkeypatch.setattr( eaa, "is_enabled", lambda: True )
        queue = Queue()
        main  = types.ModuleType( "lupin_app.main" )
        main.jobs_todo_queue = queue
        monkeypatch.setitem( sys.modules, "lupin_app.main", main )
        class Session:
            def get( self, model, key ): return owner
        @contextlib.contextmanager
        def get_db(): yield Session()
        monkeypatch.setattr( notif, "get_db", get_db )
        return notif, queue

    def test_an_enabled_switch_queues_the_extractor_for_the_owner_with_their_email( self, monkeypatch, keys ):
        notif, queue = self._wire( monkeypatch, type( "U", (), { "email": "o@example.com" } )() )
        report       = notif._enqueue_extractor_sync( NID, { "recipient_id": uuid.UUID( OWNER ), "response_options": ASK } )
        assert report[ "queued" ] and len( queue.pushed ) == 1
        assert queue.pushed[ 0 ].user_email == "o@example.com" and str( queue.pushed[ 0 ].user_id ) == OWNER

    def test_a_recipient_with_no_user_row_fails_loud( self, monkeypatch, keys ):
        notif, queue = self._wire( monkeypatch, None )
        with pytest.raises( LookupError, match="no user row" ):
            notif._enqueue_extractor_sync( NID, { "recipient_id": OWNER, "response_options": ASK } )
        assert queue.pushed == []
