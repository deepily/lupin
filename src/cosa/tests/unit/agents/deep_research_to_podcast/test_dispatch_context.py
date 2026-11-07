#!/usr/bin/env python3
"""
What the DeepResearch-to-podcast chain's notifications carry.

The tests use the real voice_io, the real cosa_interface and the real dispatcher.
Only the final send (`_notify_user_async`) is replaced by a recorder, so each test sees
the sender_id and target_user that would have gone on the wire.
Two jobs run concurrently on one event loop, as in the agentic pool.
One job alone cannot tell a per-task identity from a module-global one.
"""

import asyncio
from unittest.mock import patch

import pytest

from cosa.agents.deep_research import cosa_interface, voice_io
from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
from cosa.agents.deep_research_to_podcast.state import ChainedResult, PipelineState
from cosa.agents.utils import agent_notification_dispatcher as dispatcher_mod


@pytest.fixture( autouse=True )
def _publishing_off( monkeypatch ):
    """The shipped INI has Drive publishing on; these tests do not publish."""
    from cosa.agents.podcast_generator import drive_hook
    from cosa.agents.podcast_generator.config import PodcastConfig
    monkeypatch.setattr( drive_hook, "_load_config", lambda: PodcastConfig( publish_to_google_drive=False ) )


@pytest.fixture( autouse=True )
def _restore_module_identity():
    """Put the module globals back after the job writes them."""
    saved = ( cosa_interface.SENDER_ID, cosa_interface.TARGET_USER )
    yield
    cosa_interface.SENDER_ID, cosa_interface.TARGET_USER = saved


class _FakeAgent:
    """Stands in for the chained agent; notifies via the real voice_io."""

    def __init__( self, tag ):
        self.tag = tag

    async def run_async( self ):
        voice_io.reconfigure()   # the real chain re-binds voice_io to the DR interface before its research phase
        for step in range( 3 ):
            await voice_io.notify( f"{self.tag} step {step}", priority="low" )
            await asyncio.sleep( 0 )
        return ChainedResult(
            research_path = "/io/dr/r.md", research_abstract = "abs",
            audio_path = "/io/pod/a.mp3", script_path = "/io/pod/s.md",
            dr_cost = 0.0, pg_cost = 0.0, total_cost = 0.0, state = PipelineState.COMPLETED,
        )


def _job( tag, **kw ):
    job = DeepResearchToPodcastJob( query=f"q-{tag}", user_id=f"id-{tag}", user_email=f"{tag}@test.com", session_id=f"s-{tag}", **kw )
    job._make_agent = lambda: _FakeAgent( tag )
    return job


def _run_two( **kw ):
    """Run jobs A and B concurrently; return the ( sender_id, target_user, message ) sent."""
    sent = []
    with patch.object( dispatcher_mod, "_notify_user_async", lambda request: sent.append( ( request.sender_id, request.target_user, request.message ) ) ):
        async def both():
            return await asyncio.gather( _job( "a", **kw )._execute(), _job( "b", **kw )._execute() )
        asyncio.run( both() )
    return sent


def _step_rows( sent, tag ):
    return [ row for row in sent if row[ 2 ].startswith( f"{tag} step" ) ]


def _assert_every_notification_is_the_jobs_own( sent ):
    for tag in ( "a", "b" ):
        rows = _step_rows( sent, tag )
        assert len( rows ) == 3
        for sender_id, target_user, message in rows:
            assert target_user == f"{tag}@test.com", f"{message!r} went to {target_user}"
            assert sender_id.endswith( f"#{_base_id_of( tag )}" ), f"{message!r} carried sender {sender_id}"


_BASE_IDS = { }


def _base_id_of( tag ):
    """The base id the job under test built its sender suffix from."""
    return _BASE_IDS[ tag ]


@pytest.fixture( autouse=True )
def _record_base_ids( monkeypatch ):
    """Capture each job's base_id so the sender_id suffix can be pinned to a literal per job."""
    original = DeepResearchToPodcastJob.__init__

    def recording_init( self, *args, **kw ):
        original( self, *args, **kw )
        _BASE_IDS[ kw[ "session_id" ].split( "-" )[ -1 ] ] = self.base_id

    monkeypatch.setattr( DeepResearchToPodcastJob, "__init__", recording_init )


def test_concurrent_real_path_notifications_keep_their_own_identity():
    """Real path: each job's notifications carry that job's sender_id suffix and its user."""
    _assert_every_notification_is_the_jobs_own( _run_two() )


def test_concurrent_dry_run_notifications_keep_their_own_identity():
    """Dry-run path: same contract. The breadcrumb sleeps are shortened so the run is quick."""
    sent = []
    with patch.object( dispatcher_mod, "_notify_user_async", lambda request: sent.append( ( request.sender_id, request.target_user, request.message ) ) ), \
         patch( "asyncio.sleep", new=_instant_sleep ):
        async def both():
            return await asyncio.gather( _job( "a", dry_run=True )._execute(), _job( "b", dry_run=True )._execute() )
        asyncio.run( both() )
    for tag in ( "a", "b" ):
        rows = [ row for row in sent if "Dry run" in row[ 2 ] and row[ 1 ] == f"{tag}@test.com" ]
        assert len( rows ) >= 10
        assert all( row[ 0 ].endswith( f"#{_base_id_of( tag )}" ) for row in rows )
    assert not [ row for row in sent if row[ 1 ] is None ]


async def _instant_sleep( delay, *args, **kw ):
    """Yield to the loop without waiting, so two dry runs still interleave."""
    await _REAL_SLEEP( 0 )


_REAL_SLEEP = asyncio.sleep
