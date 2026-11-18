"""
A failed lookup or audit must still end its spend-ledger run.

Failed audits left 64 runs open, each holding its ceiling, until the account had no headroom.
Every ledger here is a temporary file; the live one is never touched.
"""
import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_shadow as rsh
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_pack_route import env, no_jev_key       # noqa: F401  fixtures


def make_ctx( env, tmp_path, monkeypatch, run_name="audit-run" ):
    """Ensures: returns ( ctx, ledger ): a single-use packed context on a temporary 100M ledger."""
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    led = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    ctx = rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], sweeper=rp.packed_sweeper( 10 ), request_shape=rp.SHAPE, pack_size=10,
                           token_ceiling=5_000_000, run_name=run_name, ledger=led, single_use=True )
    return ctx, led


def test_an_audit_naming_an_unknown_entry_closes_its_run( monkeypatch, env, tmp_path ):
    ctx, led = make_ctx( env, tmp_path, monkeypatch )
    r = rt.unstored_need_impl( "read an RSS feed", "no/such.py::ghost", ctx, language="all" )
    assert r[ "error" ] == "UNKNOWN_ENTRY"
    assert not led.is_open( "audit-run" ) and led.total() == 0


def test_an_audit_that_raises_after_the_run_began_closes_it_and_the_error_still_propagates( monkeypatch, env, tmp_path ):
    ctx, led = make_ctx( env, tmp_path, monkeypatch )
    def boom( *a, **k ): raise RuntimeError( "disk gone" )
    monkeypatch.setattr( rt, "save_snapshot", boom )
    with pytest.raises( RuntimeError, match="disk gone" ):
        rt.unstored_need_impl( "read an RSS feed", None, ctx, language="all" )
    assert not led.is_open( "audit-run" ) and led.total() == 0


def test_a_failed_drain_sweep_closes_its_run_so_no_ceiling_stays_held( monkeypatch, env, tmp_path ):
    ctx, led = make_ctx( env, tmp_path, monkeypatch, run_name="x" )
    monkeypatch.setattr( rt, "save_snapshot", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    sweep = rsh.sweep_of( lambda run: ctx, rt.unstored_need_impl )
    with pytest.raises( RuntimeError ): sweep( "read an RSS feed", "all" )
    assert led.total() == 0 and not any( led.is_open( r ) for r in ( "x", ctx.run_name ) )


def test_fetch_similar_closes_its_run_on_an_early_error_return_and_on_an_exception( monkeypatch, env, tmp_path ):
    ctx, led = make_ctx( env, tmp_path, monkeypatch )
    assert rt.fetch_similar_impl( "no/such.py::ghost", ctx, language="all" )[ "error" ] == "UNKNOWN_ENTRY"
    assert not led.is_open( "audit-run" ) and led.total() == 0
    ( tmp_path / "b" ).mkdir()
    ctx2, led2 = make_ctx( env, tmp_path / "b", monkeypatch, run_name="again" )
    monkeypatch.setattr( rt, "save_snapshot", lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    with pytest.raises( RuntimeError ): rt.fetch_similar_impl( "x", ctx2, language="all" )
    assert not led2.is_open( "again" )


def test_a_context_that_is_not_single_use_is_left_for_its_driver_to_close( monkeypatch, env, tmp_path ):
    ctx, led = make_ctx( env, tmp_path, monkeypatch )
    ctx.single_use = False
    rt.unstored_need_impl( "read an RSS feed", "no/such.py::ghost", ctx, language="all" )
    assert led.is_open( "audit-run" )
