"""
A plan-only run leaves the spend ledger exactly as it found it.

These tests build the real reuse context against a temp ledger file, with a Jev key set, and let the real prepare run.
A live run, which needs the Jev transport, is the control: it begins a run, so the test could see a plan that did.
"""
import types

import pytest

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import expansion_run as xr
from lupin_mcp.reuse_needset import stage_parts, yield_trace as yt
from tests.unit import test_reuse_needset_expansion_run as xt
from tests.unit import test_reuse_needset_yield_trace as yut
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_needset_expansion_run import old_run          # a fixture: the earlier run folder
from tests.unit.test_reuse_needset_yield_trace import quiet              # a fixture: the earlier run folder for the yield plan

RUN_NAME = "plan-ledger-test"


@pytest.fixture
def real_ctx( tmp_path, monkeypatch ):
    """Return ( builder, ledger path ).

    The builder makes the real context from the environment over a temp tree. A Jev key is set and the ledger is a temp file.
    """
    root = make_lupin_repo( tmp_path )
    ( tmp_path / "data" ).mkdir()
    led = rl.AccountLedger.create( tmp_path / "ledger.jsonl", limit_tokens=100_000_000, by="t", why="fixture" )
    monkeypatch.setenv( jt.KEY_VARIABLE, "fake-key" )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path / "data" ) ); monkeypatch.setenv( "LUPIN_REUSE_OUT_DIR", str( tmp_path / "out" ) )
    monkeypatch.setenv( "LUPIN_REUSE_LEDGER_PATH", str( led.path ) )
    monkeypatch.setattr( rt, "_refuse_drifted_ledger", lambda path: None )              # this test is about the plan ledger, not the INI key
    for name, value in ( ( rt.PACK_SIZE_VARIABLE, "50" ), ( rt.CEILING_VARIABLE, "60000000" ), ( rt.RUN_NAME_VARIABLE, RUN_NAME ) ): monkeypatch.setenv( name, value )
    return lambda _root: rt.context_from_environment( root ), led.path


def prepares( ctx_holder ):
    """A build_parts stand-in that runs the real prepare, as the real one does."""
    def build( env, built, lists, models, drafter, second, ledgers, partners ):
        rt.prepare( env.ctx )
        async def make_need( seed_id ): return None
        return { "make_need": make_need, "trace_fn": None, "tally": stage_parts.Tally() }
    return build


def test_the_real_prepare_begins_a_spend_run_unless_the_transport_is_held( real_ctx ):
    build, path = real_ctx
    before = path.read_bytes()
    held = build( None ); yt.hold_transport( held ); rt.prepare( held )
    assert path.read_bytes() == before
    rt.prepare( build( None ) )
    assert path.read_bytes() != before and RUN_NAME.encode() in path.read_bytes()


def test_the_yield_plan_leaves_the_real_ledger_unchanged( tmp_path, quiet, real_ctx ):
    build, path = real_ctx
    before = path.read_bytes()
    out = yt.main( yut.argv( tmp_path, "--cli-path", quiet[ 1 ] ), yut.deps_for( tmp_path, prepares( None ), context=build ) )
    assert out[ "live" ] is False and path.read_bytes() == before


def test_the_expansion_plan_leaves_the_real_ledger_unchanged_and_so_does_its_live_run( tmp_path, old_run, real_ctx ):
    build, path = real_ctx
    before = path.read_bytes()
    def rows( args, root, ctx ): rt.prepare( ctx ); return xt.rows3(), [ ], [ ]                  # the real collect_rows prepares the context through its index lookup
    deps = xt.deps_for( tmp_path, context=build, rows=rows, ask=xt.counted_ask(), stage=lambda ctx: ( xt.FakeStage(), xt.search_fn ), close_run=rt.close_run )
    out = xr.main( xt.argv( tmp_path, "--cli-path", old_run ), deps )
    assert out[ "live" ] is False and path.read_bytes() == before
    out = xr.main( xt.argv( tmp_path, "--cli-path", old_run, "--live" ), deps )
    assert out[ "report" ][ "status" ] == xr.DONE and out[ "closed_run" ] is None and path.read_bytes() == before
