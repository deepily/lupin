"""
Unit tests for model_transport.complete_sync, the one synchronous door to complete.

The model is a stand-in for complete, so no model is contacted.
"""
import asyncio
import threading

import pytest

from cosa.repo.doc_lint import model_transport


def test_complete_sync_returns_complete_s_reply_and_forwards_every_option( monkeypatch ):
    seen = []
    async def fake_complete( model, system, user, **options ): seen.append( ( model, system, user, options ) ); return "the reply"
    monkeypatch.setattr( model_transport, "complete", fake_complete )
    assert model_transport.complete_sync( "m", "sys", "usr", query_fn="q", timeout_seconds=7 ) == "the reply"
    assert seen == [ ( "m", "sys", "usr", { "query_fn": "q", "timeout_seconds": 7 } ) ]


def test_complete_sync_runs_on_a_thread_of_its_own_inside_a_running_loop( monkeypatch ):
    threads = []
    async def fake_complete( model, system, user, **options ): threads.append( threading.current_thread() ); return "ok"
    monkeypatch.setattr( model_transport, "complete", fake_complete )
    async def inside_a_loop(): return model_transport.complete_sync( "m", "s", "u" )
    assert asyncio.run( inside_a_loop() ) == "ok"
    assert threads and threads[ 0 ] is not threading.main_thread()


def test_complete_sync_raises_what_complete_raises( monkeypatch ):
    async def fake_complete( model, system, user, **options ): raise model_transport.ModelCallError( "boom" )
    monkeypatch.setattr( model_transport, "complete", fake_complete )
    with pytest.raises( model_transport.ModelCallError, match="boom" ):
        model_transport.complete_sync( "m", "s", "u" )
