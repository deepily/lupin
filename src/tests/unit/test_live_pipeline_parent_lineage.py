#!/usr/bin/env python3
"""
Unit tests for the lineage tag a live-pipeline smoke sends when it runs inside a tier.

A test-suite job that monopolizes the server exports its own id to every pytest it starts.
The variable is LUPIN_TEST_MONOPOLIZE_PARENT_ID.
The queue consumer defers any job the monopolizer did not spawn.
A smoke that sends no tag therefore waits out its whole timeout in the todo queue.

The base class applies the tag where it submits, after get_submit_payload returns, so an override cannot miss it.
There are two layers: the body the base class posts, and the consumer's admission of the job it becomes.
The second layer runs the real executor stamp and the real consumer thread with a real monopolizing parent.
It fails when the tag is dropped anywhere on the way.
"""

import os
import threading
from unittest.mock import patch

import pytest

from cosa.rest.routers import v2_ask
from cosa.rest.v2.executor import QueuedExecutor, Work
from cosa.rest.v2.trace import StageTrace
from cosa.tests.unit.rest import test_monopolize_lineage_inprocess as lineage
import tests.smoke.utilities.live_pipeline_base as lpb
from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase

ENV      = "LUPIN_TEST_MONOPOLIZE_PARENT_ID"
SCENARIO = { "id": "CASE_1", "query": "what is 2 plus 2" }


class _Harness( LivePipelineTestBase ):
    """Minimal concrete subclass; it keeps the base class's own get_submit_payload."""
    def __init__( self ):
        pass


class _UntaggedOverride( _Harness ):
    """An override that builds its own payload and knows nothing about lineage."""
    def get_submit_payload( self, scenario, ws_id ):
        return { "question": scenario[ "query" ], "websocket_id": ws_id, "speak": False }


class _SelfTaggedOverride( _Harness ):
    """An override that already tags its payload with its own value."""
    def get_submit_payload( self, scenario, ws_id ):
        return { "question": scenario[ "query" ], "websocket_id": ws_id, "parent_id_hash": "own-value" }


def _posted_body( harness, tier_id ):
    """Run the base class's submit and return the JSON body it posted."""
    env = { k: v for k, v in os.environ.items() if k != ENV }
    if tier_id is not None: env[ ENV ] = tier_id
    seen = {}
    def _post( url, json=None, headers=None, timeout=None ):
        seen[ "json" ] = json
        raise RuntimeError( "stop after the body is captured" )
    with patch.dict( os.environ, env, clear=True ), patch.object( lpb.requests, "post", _post ):
        harness._submit_and_wait( SCENARIO, { "Authorization": "Bearer t" }, "wise penguin" )
    return seen[ "json" ]


def test_the_posted_body_carries_the_tier_id_as_parent_id_hash_when_the_tier_sets_it():
    assert _posted_body( _Harness(), "ts-abc123" ) == { "question": "what is 2 plus 2", "websocket_id": "wise penguin", "parent_id_hash": "ts-abc123" }


@pytest.mark.parametrize( "value", [ None, "" ] )
def test_the_posted_body_is_unchanged_when_no_tier_set_the_id( value ):
    assert _posted_body( _Harness(), value ) == { "question": "what is 2 plus 2", "websocket_id": "wise penguin" }


def test_an_override_that_knows_nothing_about_lineage_is_tagged_too():
    assert _posted_body( _UntaggedOverride(), "ts-abc123" ) == { "question": "what is 2 plus 2", "websocket_id": "wise penguin", "speak": False, "parent_id_hash": "ts-abc123" }


def test_an_override_that_tags_its_own_payload_keeps_its_value():
    assert _posted_body( _SelfTaggedOverride(), "ts-abc123" )[ "parent_id_hash" ] == "own-value"


def test_the_ask_door_accepts_the_body_the_base_class_posts():
    assert v2_ask.AskRequest( **_posted_body( _Harness(), "ts-abc123" ) ).parent_id_hash == "ts-abc123"


class _TodoShim:
    """What QueuedExecutor needs of the todo queue, pushing into the real queue under test."""
    def __init__( self, todo ):
        self._todo         = todo
        self.user_job_tracker = self
    def register_scoped_job( self, base, user_id, session_id=None ): return f"{base}::{user_id}"
    def push( self, job ):
        with self._todo.condition:
            self._todo.push( job )
            self._todo.condition.notify_all()
    def size( self ): return self._todo.size()


class TestHarnessChildAdmission( lineage.TestMonopolizeLineageInProcess ):
    """A tagged smoke job is admitted during the hold; an untagged one is not."""

    test_lineage_child_dispatches_during_hold_foreign_deferred_then_released = None   # the inherited proof is not re-run here

    def _ask_as_the_harness( self, label, do_all, parent_id ):
        """Queue the job the ask door would build for this payload."""
        request = v2_ask.AskRequest( **_posted_body( _Harness(), parent_id ) )
        trace = StageTrace( trace_dir="/tmp/unused" )
        if request.parent_id_hash: trace.set( "parent_id_hash", request.parent_id_hash )
        job = lineage._ProbeJob( label, do_all )
        QueuedExecutor( _TodoShim( self.todo ) ).submit( Work( "agent", job, "u-1", "u@x.com", "s-1", snapshotable=True ), trace )
        return job

    def test_a_job_sent_with_the_tier_tag_is_admitted_during_the_hold_and_an_untagged_one_waits( self ):
        order              = []
        child_dispatched   = threading.Event()
        foreign_dispatched = threading.Event()
        observations       = {}

        def _child( job ):
            order.append( "child" );   child_dispatched.set();   return "ok"

        def _foreign( job ):
            order.append( "foreign" ); foreign_dispatched.set(); return "ok"

        def _parent( job ):
            order.append( "parent" )
            self._ask_as_the_harness( "child",   _child,   parent_id=job.id_hash )
            self._ask_as_the_harness( "foreign", _foreign, parent_id=None )
            observations[ "child_admitted_during_hold" ] = child_dispatched.wait( timeout=8 )
            observations[ "foreign_deferred_during_hold" ] = not foreign_dispatched.is_set()
            return "parent done"

        parent = lineage._ProbeJob( "parent", _parent, monopolize=True )
        with self.todo.condition:
            self.todo.push( parent )
            self.todo.condition.notify_all()
        self._consumer_thread = lineage.qc.start_todo_producer_run_consumer_thread( self.todo, self.running )

        released = foreign_dispatched.wait( timeout=15 )

        assert observations.get( "child_admitted_during_hold" ) is True, "the tagged job was held out by the monopoly hold"
        assert observations.get( "foreign_deferred_during_hold" ) is True, "the untagged job ran during the hold"
        assert released is True, "the untagged job never ran after the hold cleared"
        assert order == [ "parent", "child", "foreign" ], order
