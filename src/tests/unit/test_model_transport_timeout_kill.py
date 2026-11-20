"""
A timed-out bounded call ends its Claude Code child process.

The stand-in for the SDK starts a real child that sleeps and then hangs, the way the CLI does. The call
is cut at its time limit, and the child must be gone.
"""

import asyncio
import os
import subprocess
import sys

import pytest

from cosa.repo.doc_lint import model_transport as mt

SLEEPER = [ sys.executable, "-c", "import time; time.sleep( 300 )" ]


def _hanging_query( children ):
    """Stand in for the SDK: start a sleeping child, then never answer."""
    async def query( prompt, options ):
        children.append( subprocess.Popen( SLEEPER, env=dict( os.environ, **options.env ) ) )
        await asyncio.sleep( 60 )
        yield None
    return query


def test_a_timeout_kills_the_child_the_call_started():
    children = []
    with pytest.raises( mt.ModelCallTimeout, match="timed out after 0.3s" ):
        asyncio.run( mt.complete( "m", "sys", "user", query_fn=_hanging_query( children ), timeout_seconds=0.3 ) )
    assert len( children ) == 1
    assert children[ 0 ].wait( timeout=5 ) == -9, "the child ended by SIGKILL, not by its own sleep"


def test_a_timeout_is_a_model_call_error_so_callers_that_catch_one_catch_both():
    assert issubclass( mt.ModelCallTimeout, mt.ModelCallError )


def test_a_failed_call_kills_its_child_too():
    children = []

    async def failing( prompt, options ):
        children.append( subprocess.Popen( SLEEPER, env=dict( os.environ, **options.env ) ) )
        raise RuntimeError( "the stream broke" )
        yield None

    with pytest.raises( mt.ModelCallError, match="failed: the stream broke" ):
        asyncio.run( mt.complete( "m", "sys", "user", query_fn=failing ) )
    assert children[ 0 ].wait( timeout=5 ) == -9


def test_only_the_process_carrying_the_tag_is_killed():
    mine  = subprocess.Popen( SLEEPER, env=dict( os.environ, **{ mt.CALL_TAG_ENV: "tag-one" } ) )
    other = subprocess.Popen( SLEEPER, env=dict( os.environ, **{ mt.CALL_TAG_ENV: "tag-two" } ) )
    try:
        assert mt.kill_tagged_processes( "tag-one" ) == [ mine.pid ]
        assert mine.wait( timeout=5 ) == -9
        assert other.poll() is None, "a peer call's child is left alone"
        assert mt.kill_tagged_processes( "no-such-tag" ) == []
    finally:
        other.kill()
        other.wait()


def test_a_tag_that_is_only_a_prefix_of_another_is_not_matched():
    longer = subprocess.Popen( SLEEPER, env=dict( os.environ, **{ mt.CALL_TAG_ENV: "abcdef" } ) )
    try:
        assert mt.kill_tagged_processes( "abc" ) == []
        assert longer.poll() is None
    finally:
        longer.kill()
        longer.wait()


def test_the_scan_skips_what_it_cannot_read_and_what_has_gone( monkeypatch ):
    real_open = open

    def refusing( path, *args, **kwargs ):
        if str( path ).endswith( "/environ" ) and not str( path ).startswith( f"/proc/{os.getpid()}/" ): raise PermissionError( path )
        return real_open( path, *args, **kwargs )

    monkeypatch.setattr( "builtins.open", refusing )
    assert mt.kill_tagged_processes( "nothing-carries-this" ) == []


def test_every_call_carries_a_fresh_random_tag():
    seen = []

    async def noting( prompt, options ):
        seen.append( options.env[ mt.CALL_TAG_ENV ] )
        raise RuntimeError( "stop" )
        yield None

    for _ in range( 2 ):
        with pytest.raises( mt.ModelCallError ): asyncio.run( mt.complete( "m", "s", "u", query_fn=noting ) )
    assert len( set( seen ) ) == 2 and all( len( tag ) == 16 for tag in seen )
