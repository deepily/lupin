"""
The caller picks the retry policy; packed and first-trial paths retry transient failures.

The default check_exists path keeps its old send counts. A 429 or 529 gets the sweep's three tries
of four sends, and a 500 or a timeout gets three single sends. The packed path and the first-trial
driver set `transient`, which allows one cap of four sends in all. Doors and sleeps are scripted.
"""
import pytest

from cosa.repo.doc_lint import jev_transport
from lupin_mcp import reuse_stage1 as st
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_422_breaker import Door, ctx_over, entries, env, no_jev_key       # noqa: F401  fixtures
from lupin_mcp import reuse_ledger
from tests.unit.test_reuse_tools import N
from tests.unit.test_reuse_transport_telemetry import ENV


def sweep_posts( env_, status, transient ):
    """Ensures: returns ( posts, failed ) for a six-entry sweep over a door answering `status`."""
    door = Door( [ status ] )
    ctx  = ctx_over( env_, door )
    ctx.transport.transient = transient
    sw   = rt.sweep( ctx, N( "q" ), entries( 6 ) )
    return door.posts, len( sw[ "failed" ] )


@pytest.mark.parametrize( "status, posts", [ ( 500, 6 * ( rt.RETRIES + 1 ) ), ( 429, 6 * ( rt.RETRIES + 1 ) * jev_transport.MAX_ATTEMPTS ) ] )
def test_the_default_policy_keeps_the_old_send_counts( env, status, posts ):      # noqa: F811
    assert sweep_posts( env, status, False ) == ( posts, 6 )


@pytest.mark.parametrize( "status", [ 500, 429 ] )
def test_the_transient_policy_sends_four_in_all_and_the_sweep_does_not_ask_again( env, status ):      # noqa: F811
    assert sweep_posts( env, status, True ) == ( 6 * jev_transport.MAX_ATTEMPTS, 6 )


def test_the_default_policy_does_not_retry_a_timeout_or_a_reset():
    for error in ( TimeoutError( "t" ), ConnectionResetError( "r" ) ):
        calls = []
        def post( url, headers, body, timeout, error=error ):
            calls.append( 1 )
            raise error
        with pytest.raises( jev_transport.JevCallError, match="call to Jev failed" ):
            jev_transport.send_with_meta( b"{}", post_fn=post, sleep_fn=lambda s: None, environ=ENV )
        assert len( calls ) == 1


def test_the_stage_1_driver_builds_a_transient_transport( tmp_path ):
    default = st.Stage1Env( tmp_path, tmp_path / "data", None )
    assert default.transport_factory( None ).transient is True


def test_prepare_sets_the_policy_from_the_path_in_use( env, monkeypatch, tmp_path ):      # noqa: F811
    root, data, out = env
    monkeypatch.setenv( jev_transport.KEY_VARIABLE, "k" )
    plain = rt.ReuseContext( root, data, out_dir=out )
    rt.prepare( plain )
    assert plain.transport.transient is False
    packed = rt.ReuseContext( root, data, out_dir=out, pack_size=2, sweeper=lambda *a, **k: None, token_ceiling=1000, run_name="r",
                              ledger=reuse_ledger.AccountLedger.create( tmp_path / "ledger.jsonl", 1_000_000, "test", "scratch" ), single_use=True )
    rt.prepare( packed )
    assert packed.transport.transient is True
