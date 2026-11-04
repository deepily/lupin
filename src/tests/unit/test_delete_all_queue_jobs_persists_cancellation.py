"""
Unit tests for DELETE /api/queue/{queue_name}/all and the durable cancel it must record.

Only an integration test reached this endpoint before.
A cancelled todo job not marked cancelled in the database comes back at the next start.
So each case reads which ids were persisted as cancelled, not just the response.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.auth as auth
from cosa.rest.routers import queues

ADMIN = { "uid": "admin-1", "email": "a@x.test", "roles": [ "admin", "user" ] }
USER  = { "uid": "user-1",  "email": "u@x.test", "roles": [ "user" ] }


class _Job:
    def __init__( self, id_hash, owner ): self.id_hash, self.owner = id_hash, owner


class _Queue:
    """An in-memory queue with the five calls the endpoint makes; clear() really empties it."""

    def __init__( self, jobs=(), undeletable=() ):
        self.jobs        = list( jobs )
        self.undeletable = set( undeletable )

    def get_all_jobs( self ):             return list( self.jobs )
    def size( self ):                     return len( self.jobs )
    def clear( self ):                    self.jobs.clear()
    def get_jobs_for_user( self, uid ):   return [ j for j in self.jobs if j.owner == uid ]

    def delete_by_id_hash( self, id_hash ):
        if id_hash in self.undeletable: return False
        self.jobs[ : ] = [ j for j in self.jobs if j.id_hash != id_hash ]
        return True


@pytest.fixture
def persisted( monkeypatch ):
    """The ids the endpoint marked cancelled, in order."""
    calls = []
    monkeypatch.setattr( queues, "persist_job_cancelled", calls.append )
    return calls


def _delete( identity, queue_name, queue ):
    app = FastAPI()
    app.include_router( queues.router )
    empty = _Queue()
    for dep in ( queues.get_todo_queue, queues.get_running_queue, queues.get_done_queue, queues.get_dead_queue ):
        app.dependency_overrides[ dep ] = lambda: empty
    real = { "todo": queues.get_todo_queue, "run": queues.get_running_queue,
             "done": queues.get_done_queue, "dead": queues.get_dead_queue }[ queue_name ]
    app.dependency_overrides[ real ] = lambda: queue

    async def _who(): return identity
    app.dependency_overrides[ auth.get_current_user ] = _who
    return TestClient( app ).delete( f"/api/queue/{queue_name}/all" )


def test_admin_clearing_todo_persists_every_id_it_read_before_the_clear( persisted ):
    queue = _Queue( [ _Job( "a", "u1" ), _Job( "b", "u2" ) ] )

    response = _delete( ADMIN, "todo", queue )

    assert response.status_code == 200 and response.json()[ "items_deleted" ] == 2
    assert queue.jobs == []
    assert persisted == [ "a", "b" ], "ids must be read before clear(), when there is still something to name"


def test_admin_clearing_a_queue_that_is_not_cancellable_persists_nothing( persisted ):
    queue = _Queue( [ _Job( "a", "u1" ) ] )

    response = _delete( ADMIN, "done", queue )

    assert response.status_code == 200 and response.json()[ "items_deleted" ] == 1
    assert persisted == []


def test_a_user_clearing_todo_persists_only_the_jobs_actually_deleted( persisted ):
    queue = _Queue( [ _Job( "mine-1", "user-1" ), _Job( "mine-2", "user-1" ), _Job( "theirs", "u2" ) ],
                    undeletable=[ "mine-2" ] )

    response = _delete( USER, "todo", queue )

    assert response.json()[ "items_deleted" ] == 1, "a job the queue refused to delete was counted"
    assert persisted == [ "mine-1" ]
    assert [ j.id_hash for j in queue.jobs ] == [ "mine-2", "theirs" ]


def test_a_user_clearing_a_queue_that_is_not_cancellable_persists_nothing( persisted ):
    queue = _Queue( [ _Job( "mine", "user-1" ) ] )

    response = _delete( USER, "dead", queue )

    assert response.json()[ "items_deleted" ] == 1
    assert persisted == []
