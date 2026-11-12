#!/usr/bin/env python3
"""
AgenticJobBase._set_chain_identity: the interface globals and the dispatch context.

The concurrent-jobs tests watch the per-task context. These pin each module global on its own.
"""

import types

from cosa.agents.podcast_generator.job import PodcastGeneratorJob
from cosa.agents.utils import agent_notification_dispatcher as dispatcher_mod


def _interface():
    return types.SimpleNamespace( SENDER_ID="old-sender", TARGET_USER="old-user", _get_sender_id=lambda suffix: f"sender#{suffix}" )


def test_the_interface_globals_and_the_dispatch_context_name_this_job():
    job       = PodcastGeneratorJob( research_path="/io/dr/x.md", user_id="id-x", user_email="x@test.com", session_id="s-x", dry_run=True )
    interface = _interface()
    tokens    = dispatcher_mod.set_dispatch_context( sender_id="before", target_user="before" )
    try:
        job._set_chain_identity( interface )
        assert interface.SENDER_ID == f"sender#{job.base_id}"
        assert interface.TARGET_USER == "x@test.com"
        assert dispatcher_mod.ctx_sender_id.get() == f"sender#{job.base_id}"
        assert dispatcher_mod.ctx_target_user.get() == "x@test.com"
    finally:
        dispatcher_mod.reset_dispatch_context( tokens )
