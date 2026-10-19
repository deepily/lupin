"""
Unit tests for the shared worktree_scope helper.

Both expediter orchestrators delegate their worktree_scope methods to it.
"""

import asyncio
from unittest.mock import patch

import pytest

from cosa.agents.shared import worktree_context as wc


class _FakeContext:
    """Stands in for WorktreeContext: records its arguments, reports enabled or not."""

    def __init__( self, enabled, path="/tmp/wt-1" ):
        self.enabled = enabled
        self.path    = path
        self.args    = None

    def __call__( self, job_id, debug ):
        self.args = ( job_id, debug )
        return self

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *exc ):
        return False


class _Orch:
    def __init__( self, debug=False ):
        self.job_id        = "job-7"
        self.debug         = debug
        self._worktree_cwd = "stale"
        self.warned        = 0

    async def _warn_on_uncommitted_changes_if_any( self ):
        self.warned += 1


def _run( coro ):
    return asyncio.run( coro )


def test_enabled_sets_cwd_inside_the_block_and_clears_it_after( capsys ):
    fake, orch = _FakeContext( enabled=True ), _Orch( debug=True )
    seen       = []
    async def go():
        async with wc.worktree_scope( orch, "XOrchestrator" ) as wt:
            seen.append( ( wt, orch._worktree_cwd ) )
    with patch.object( wc, "WorktreeContext", fake ):
        _run( go() )
    assert seen == [ ( fake, "/tmp/wt-1" ) ]
    assert orch._worktree_cwd is None and orch.warned == 0
    assert fake.args == ( "job-7", True )
    assert "[XOrchestrator] Worktree isolation active: /tmp/wt-1" in capsys.readouterr().out


def test_enabled_without_debug_prints_nothing( capsys ):
    fake, orch = _FakeContext( enabled=True ), _Orch( debug=False )
    async def go():
        async with wc.worktree_scope( orch, "XOrchestrator" ):
            pass
    with patch.object( wc, "WorktreeContext", fake ):
        _run( go() )
    assert capsys.readouterr().out == ""


def test_disabled_clears_cwd_and_runs_the_uncommitted_changes_warning():
    fake, orch = _FakeContext( enabled=False ), _Orch()
    seen       = []
    async def go():
        async with wc.worktree_scope( orch, "XOrchestrator" ):
            seen.append( orch._worktree_cwd )
    with patch.object( wc, "WorktreeContext", fake ):
        _run( go() )
    assert seen == [ None ] and orch.warned == 1 and orch._worktree_cwd is None


def test_cwd_is_cleared_when_the_block_raises():
    fake, orch = _FakeContext( enabled=True ), _Orch()
    async def go():
        async with wc.worktree_scope( orch, "XOrchestrator" ):
            raise RuntimeError( "boom" )
    with patch.object( wc, "WorktreeContext", fake ), pytest.raises( RuntimeError ):
        _run( go() )
    assert orch._worktree_cwd is None
