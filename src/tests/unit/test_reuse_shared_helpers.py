"""
Unit tests for the two helpers that replaced copied bodies.

They are cosa_voice_mcp._reuse_call (four reuse tool wrappers) and
reuse_flip._sweeper_factory (four sweeper builders).
"""

import asyncio
import sys
from unittest.mock import patch

import pytest

import lupin_mcp.cosa_voice_mcp as cvm
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt


class TestReuseCall:

    def test_it_builds_the_context_for_root_and_calls_the_named_impl_with_args_then_ctx( self ):
        with patch.object( rt, "context_from_environment", return_value="CTX" ) as ctx_fn, \
             patch.object( rt, "replay_impl", return_value={ "ok": 1 } ) as impl:
            assert cvm._reuse_call( "replay_impl", "/some/root", "rid" ) == { "ok": 1 }
        ctx_fn.assert_called_once_with( "/some/root" )
        impl.assert_called_once_with( "rid", "CTX" )

    def test_a_failing_context_answers_with_the_unavailable_dict( self ):
        with patch.object( rt, "context_from_environment", side_effect=RuntimeError( "boom" ) ):
            assert cvm._reuse_call( "check_exists_impl", None, "need" ) == \
                   { "status": "error", "error": "REUSE_TOOLS_UNAVAILABLE", "detail": "RuntimeError: boom" }

    def test_a_failing_import_answers_with_the_unavailable_dict( self, monkeypatch ):
        import lupin_mcp
        monkeypatch.delattr( lupin_mcp, "reuse_tools" )
        monkeypatch.setitem( sys.modules, "lupin_mcp.reuse_tools", None )
        answer = cvm._reuse_call( "check_exists_impl", None, "need" )
        assert answer["error"] == "REUSE_TOOLS_UNAVAILABLE" and answer["detail"].startswith( "ModuleNotFoundError" )

    @pytest.mark.parametrize( "tool, impl, arg_name, arg, extra", [
        ( "check_exists",    "check_exists_impl",    "need",       "a need",     { "language": "py" } ),
        ( "fetch_similar",   "fetch_similar_impl",   "entry",      "some.entry", { "language": "ts" } ),
        ( "read_capability", "read_capability_impl", "names",      [ "page" ],   {} ),
        ( "replay",          "replay_impl",          "receipt_id", "abc123",     {} ),
    ] )
    def test_each_wrapper_sends_its_own_impl_root_and_first_argument( self, tool, impl, arg_name, arg, extra ):
        # the two search wrappers also send the language they were given, as a keyword; the other two take none
        async def run():
            registered = await cvm.mcp.get_tool( tool )
            return await registered.run( { arg_name: arg, "root": "/r", **extra } )
        with patch.object( cvm, "_reuse_call", return_value={ "answer": tool } ) as call:
            result = asyncio.run( run() )
        assert result.structured_content == { "answer": tool }
        call.assert_called_once_with( impl, "/r", arg, **extra )


class TestSweeperFactory:

    @pytest.fixture
    def sent( self ):
        with patch.object( rp, "sweep_packed", return_value="SWEPT" ) as sweep:
            yield sweep

    @pytest.mark.parametrize( "builder, key_mode, kind", [
        ( rf.repeat_sweeper,      "stage1", None ),
        ( rf.repeat_pair_sweeper, "stage1", "pair" ),
        ( rf.replay_sweeper,      "replay", None ),
        ( rf.replay_pair_sweeper, "replay", "pair" ),
    ] )
    def test_each_builder_sweeps_in_its_key_mode_and_kind( self, sent, builder, key_mode, kind ):
        sweeper = builder( 4, 5, 3, breaker="B" )
        assert sweeper( "ctx", "need", [ "e" ], frozen=True, template="t", model="m", gaps="g" ) == "SWEPT"
        kwargs = sent.call_args.kwargs
        assert sent.call_args.args == ( "ctx", "need", [ "e" ], 4 )
        assert ( kwargs["workers"], kwargs["key_mode"], kwargs["run_index"], kwargs["breaker"] ) == ( 5, key_mode, 3, "B" )
        assert ( kwargs["template"], kwargs["model"], kwargs["frozen"], kwargs["gaps"] ) == ( "t", "m", True, "g" )
        if kind is None: assert "kind" not in kwargs
        else:            assert kwargs["kind"] == kind

    @pytest.mark.parametrize( "builder", [ rf.repeat_sweeper, rf.repeat_pair_sweeper, rf.replay_sweeper, rf.replay_pair_sweeper ] )
    def test_each_builder_refuses_a_bad_run_index_before_anything_is_sent( self, sent, builder ):
        with pytest.raises( ValueError, match="run_index of 1 or more" ):
            builder( 4, 5, 0 )
        sent.assert_not_called()

    def test_the_checker_is_given_the_key_mode_and_kind( self ):
        with patch.object( rp, "_check_sweep_args" ) as check:
            rf.replay_pair_sweeper( 4, 5, 1 )
            rf.repeat_sweeper( 4, 5, 1 )
        assert [ c.args for c in check.call_args_list ] == [ ( 4, 5, "replay", 1, "pair" ), ( 4, 5, "stage1", 1 ) ]
