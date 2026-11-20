"""
A finished principle-extractor job must not break the done-queue listing.

Before the fix, GET /api/get-queue/done answered 500 while an extractor job sat in the done queue.
The route reads job.cost_summary on every agentic job, and the extractor never set it.
These tests drive the real endpoint function over a real PrincipleExtractorJob.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import cosa.rest.routers.queues as queues_mod
from cosa.agents.principle_learner.extractor_job import PrincipleExtractorJob

ADMIN = { "uid": "admin1", "email": "a@x.com", "roles": [ "admin" ] }


def _extractor_job():
    """
    Build a real extractor job, as the queue holds it after a run.

    Ensures:
        - returns a PrincipleExtractorJob, not a double
    """
    return PrincipleExtractorJob( notification_id="11111111-1111-1111-1111-111111111111", user_id="admin1", user_email="a@x.com" )


def _list_queue( queue_name, job ):
    """
    Call the real get_queue endpoint over one queue that holds job.

    Ensures:
        - returns the endpoint's response dict
    """
    held = MagicMock()
    held.get_jobs_for_user.return_value = [ job ]
    queues = { "todo": MagicMock(), "run": MagicMock(), "done": MagicMock(), "dead": MagicMock() }
    queues[ queue_name ] = held
    with patch.object( queues_mod, "_count_interactions_for_jobs", return_value={} ):
        return asyncio.run( queues_mod.get_queue(
            queue_name    = queue_name,
            current_user  = ADMIN,
            user_filter   = ADMIN[ "uid" ],
            todo_queue    = queues[ "todo" ],
            running_queue = queues[ "run" ],
            done_queue    = queues[ "done" ],
            dead_queue    = queues[ "dead" ],
        ) )


def test_new_extractor_job_has_an_explicit_empty_cost_summary():
    """The attribute exists and is None, because the extractor reports no cost."""
    job = _extractor_job()

    assert "cost_summary" in vars( job ), "cost_summary must be set in __init__, not found by fallback"
    assert job.cost_summary is None


def test_done_listing_carries_an_extractor_job_with_no_cost():
    """Without the assignment in __init__ the endpoint raises AttributeError."""
    job = _extractor_job()

    out   = _list_queue( "done", job )
    cards = out[ "done_jobs_metadata" ]

    assert len( cards ) == 1, f"expected one done card, got {cards}"
    assert cards[ 0 ][ "job_id" ]       == job.id_hash
    assert cards[ 0 ][ "agent_type" ]   == "principle_extractor"
    assert cards[ 0 ][ "cost_summary" ] is None


def test_dead_listing_carries_an_extractor_job_with_no_cost():
    """The dead branch reads the same field, so a failed extraction must list too."""
    job = _extractor_job()

    out   = _list_queue( "dead", job )
    cards = out[ "dead_jobs_metadata" ]

    assert len( cards ) == 1, f"expected one dead card, got {cards}"
    assert cards[ 0 ][ "cost_summary" ] is None
