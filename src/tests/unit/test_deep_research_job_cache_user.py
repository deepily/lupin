#!/usr/bin/env python3
"""
A deep-research job names its user to run_research, so the search cache is per user.

Store id 20827e36-1209-4d81-9690-af609da5163c. `run_research` takes `user_email` and hands
it to the search cache, whose folder is `io/deep-research/<user_email>/cache/<date>`. The job
left it out, so every job's cache landed in `io/deep-research//cache/<date>`.

Seams driven for real: the job's `_execute` and the cache's `get_cache_dir`. Faked: `run_research`
itself, the gister and outbound notifications.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _run_job_for( user_email, tmp_path ):
    """
    Run one real DeepResearchJob._execute against a fake run_research.

    Requires:
        - user_email is a non-empty string
        - tmp_path is an existing directory

    Ensures:
        - returns the keyword arguments the job passed to run_research
    """
    from cosa.agents.deep_research.job import DeepResearchJob

    job = DeepResearchJob(
        query      = "what changed",
        user_id    = "uid-" + user_email,
        user_email = user_email,
        session_id = "sess-1",
    )
    fake_run = AsyncMock( return_value=None )
    gister   = MagicMock()
    gister.return_value.get_gist.return_value = "what changed"

    with patch( "cosa.agents.deep_research.cli.run_research", fake_run ), \
         patch( "cosa.memory.gister.Gister", gister ), \
         patch( "cosa.agents.deep_research.voice_io.notify", AsyncMock() ):
        await job._execute()

    return fake_run.call_args.kwargs


@pytest.mark.asyncio
async def test_the_REAL_job_passes_its_users_email_to_run_research( tmp_path ):
    kwargs = await _run_job_for( "alice@lupin", tmp_path )
    assert kwargs.get( "user_email" ) == "alice@lupin", "the job must name its user, or the cache folder is shared"


@pytest.mark.asyncio
async def test_two_jobs_for_two_users_reach_run_research_with_two_different_emails( tmp_path ):
    first  = await _run_job_for( "alice@lupin", tmp_path )
    second = await _run_job_for( "bob@lupin",   tmp_path )
    assert first.get( "user_email" ) is not None
    assert first.get( "user_email" ) != second.get( "user_email" )


def test_POSITIVE_CONTROL_the_cache_folder_follows_the_email_and_an_empty_email_is_shared():
    from cosa.agents.deep_research import search_cache

    alice = search_cache.get_cache_dir( "alice@lupin" )
    bob   = search_cache.get_cache_dir( "bob@lupin" )
    blank = search_cache.get_cache_dir( "" )
    assert alice != bob
    assert "/alice@lupin/" in alice
    assert "deep-research//cache" in blank, "an empty email is the shared folder the job was landing in"
