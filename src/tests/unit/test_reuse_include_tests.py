"""
The include_tests argument of the reuse search: off by default, sweep-only when on.
"""
import asyncio
import json

import pytest

from cosa.repo.symindex import build as bd
from lupin_mcp import cosa_voice_mcp as cvm
from lupin_mcp import reuse_tools as rt
from tests.unit.include_tests_helpers import AllReuse, HELPER_ID, ctx_of, tests_env      # noqa: F401  (tests_env is a fixture)
from tests.unit.test_reuse_pack_route import no_jev_key, receipt_of                              # noqa: F401
from tests.unit.test_reuse_tools import NEED, Recorder, ctx_for


def ids_of( r ): return sorted( { s[ "id" ] for s in r[ "shortlist" ] } | { s[ "id" ] for s in r[ "nearest" ] } )


def test_a_default_call_neither_reads_nor_sends_a_test_record( tests_env ):
    # red when: prepare() adds the test records without being asked
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, ctx_of( tests_env, fake ), language="py" )
    assert HELPER_ID not in ids_of( r ) and not any( HELPER_ID in json.dumps( b ) for b in fake.seen )
    assert not ( tests_env[ 2 ] / "tests" ).exists()                                  # the tests generation is not even built
    rec = receipt_of( tests_env, r )
    assert "include_tests" not in rec and "sweep_only" not in rec                    # a default receipt keeps the shape it had


def test_include_tests_asks_the_test_record_on_the_sweep_only_route_and_the_receipt_says_so( tests_env ):
    # red when: the stage can propose a test record (it holds no vectors for them), or the receipt drops either key
    fake = AllReuse()
    plain = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py" )
    r     = rt.check_exists_impl( NEED, ctx_of( tests_env, fake ), language="py", include_tests=True )
    assert HELPER_ID in ids_of( r ) and r[ "receipt_id" ] != plain[ "receipt_id" ]
    rec = receipt_of( tests_env, r )
    assert rec[ "include_tests" ] is True and rec[ "sweep_only" ] is True and rec[ "route" ] == "full"
    assert len( ids_of( r ) ) > len( ids_of( plain ) ) and len( fake.seen ) == 1 and HELPER_ID in json.dumps( fake.seen[ 0 ] )     # the other three answers were cached by the first call


def test_the_index_sha_of_an_include_tests_call_follows_the_tests_and_a_default_call_does_not( tests_env ):
    # red when: tests_sha is left out of index_sha, which would hand a call that read tests the receipt of one that did not
    root, data, out, helper = tests_env
    one   = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py", include_tests=True )
    plain = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py" )
    assert one[ "index_sha" ] != plain[ "index_sha" ]
    helper.write_text( helper.read_text( encoding="utf-8" ).replace( "Help a test read", "Help another test read" ), encoding="utf-8" )
    two   = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py", include_tests=True )
    again = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py" )
    assert two[ "index_sha" ] != one[ "index_sha" ] and again[ "index_sha" ] == plain[ "index_sha" ]
    tsha = bd.read_header( bd.current_generation( out / "tests" ) )[ "search_sha" ]
    assert rt.index_sha( "s", [] ) == rt.index_sha( "s", [], "", None ) != rt.index_sha( "s", [], "", tsha )


def test_fetch_similar_accepts_a_test_definition_only_when_asked( tests_env ):
    fake = AllReuse()
    no   = rt.fetch_similar_impl( HELPER_ID, ctx_of( tests_env, fake ), language="py" )
    assert ( no[ "status" ], no[ "error" ] ) == ( "error", "UNKNOWN_ENTRY" ) and fake.seen == []
    yes  = rt.fetch_similar_impl( HELPER_ID, ctx_of( tests_env, fake ), language="py", include_tests=True )
    assert yes[ "status" ] == "ok" and HELPER_ID not in ids_of( yes ) and ids_of( yes )
    assert receipt_of( tests_env, yes )[ "include_tests" ] is True


def test_sendable_screens_a_test_record_like_any_other( tests_env ):
    # red when: the test records bypass sendable(): the helper's docstring holds an address
    root, data, out, helper = tests_env
    helper.write_text( 'def helper_for_tests( x ):\n    """Mail ops@example.com."""\n    return x\n', encoding="utf-8" )
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, ctx_of( tests_env, fake ), language="py", include_tests=True )
    assert HELPER_ID not in ids_of( r ) and not any( "ops@example.com" in json.dumps( b ) for b in fake.seen )
    one  = rt.fetch_similar_impl( HELPER_ID, ctx_of( tests_env, fake ), language="py", include_tests=True )
    assert one[ "error" ] == "EXCLUDED_SENSITIVE_CONTENT"


def test_a_receipt_replays_with_its_own_include_tests( tests_env ):
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, ctx_of( tests_env, fake ), language="py", include_tests=True )
    rep  = rt.replay_impl( r[ "receipt_id" ], ctx_of( tests_env, fake ) )
    assert rep[ "status" ] == "ok" and rep[ "differences" ] == { "frozen": [], "head": [] }
    assert HELPER_ID in [ s[ "id" ] for s in rep[ "frozen" ][ "shortlist" ] ] and HELPER_ID in [ s[ "id" ] for s in rep[ "head" ][ "shortlist" ] ]
    assert rep[ "head" ][ "index_sha" ] == r[ "index_sha" ]                            # head asked with include_tests too, or its sha would be the default one


def test_the_snapshot_of_an_include_tests_call_holds_the_test_record_and_a_default_one_does_not( tests_env ):
    plain = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py" )
    r     = rt.check_exists_impl( NEED, ctx_of( tests_env, AllReuse() ), language="py", include_tests=True )
    held  = lambda res: [ e[ "id" ] for e in rt.load_snapshot( ctx_of( tests_env, AllReuse() ), res[ "index_sha" ] )[ 0 ] ]
    assert HELPER_ID in held( r ) and HELPER_ID not in held( plain )


def test_an_include_tests_call_sizes_the_live_attempt_limit_by_the_searchable_plus_test_count( tests_env, monkeypatch ):
    # red when: the budget ignores the test records, or a default call's budget moves
    sizes, budgets = [], []
    monkeypatch.setattr( rt.jev_transport, "has_key", lambda: True )
    monkeypatch.setattr( rt, "LiveJevTransport", lambda budget, transient: ( budgets.append( budget.limit ), Recorder() )[ 1 ] )
    monkeypatch.setattr( rt, "call_budget_cap_for", lambda n: ( sizes.append( n ), 77777 )[ 1 ] )
    ctx = ctx_of( tests_env, None )
    rt.prepare( ctx )
    assert sizes == [] and budgets == [ ctx.call_budget ]                              # default: the context's own budget, the cap function never asked
    ctx = ctx_of( tests_env, None )
    rt.prepare( ctx, include_tests=True )
    main  = bd.read_header( bd.current_generation( tests_env[ 2 ] ) )[ "counts" ][ "searchable" ]
    tests = bd.read_header( bd.current_generation( tests_env[ 2 ] / "tests" ) )[ "counts" ][ "searchable" ]
    assert tests == 1 and sizes == [ main + tests ] and budgets[ -1 ] == 77777


def test_a_live_budget_takes_the_attempts_it_is_given_on_both_paths( tests_env ):
    ctx = ctx_of( tests_env, None )
    assert rt._live_budget( ctx ).limit == ctx.call_budget and rt._live_budget( ctx, 12 ).limit == 12


def test_a_failed_tests_build_leaves_the_index_stale( tests_env, monkeypatch ):
    real = bd.ensure
    def broken( root, out, spec=None ):
        if spec is not None: raise OSError( "disk full" )
        return real( root, out, spec )
    monkeypatch.setattr( rt.sx_build, "ensure", broken )
    r = rt.check_exists_impl( NEED, ctx_of( tests_env, Recorder() ), language="py", include_tests=True )
    assert "INDEX_STALE" in receipt_of( tests_env, r )[ "flags" ]


@pytest.mark.parametrize( "name, own", [ ( "check_exists", { "need": NEED } ), ( "fetch_similar", { "entry": "cosa.feeds.parse_feed" } ) ] )
def test_the_wrappers_name_include_tests_and_pass_it_to_the_impl( tests_env, monkeypatch, name, own ):
    tool = asyncio.run( cvm.mcp.get_tool( name ) )
    assert "include_tests" in tool.description and tool.parameters[ "properties" ][ "include_tests" ][ "default" ] is False
    seen = {}
    monkeypatch.setattr( rt, "context_from_environment", lambda r=None: ctx_for( tests_env[ :3 ], Recorder() ) )
    monkeypatch.setattr( rt, name + "_impl", lambda arg, ctx, language=None, include_tests=False: seen.update( include_tests=include_tests ) or { "status": "ok" } )
    asyncio.run( tool.run( { **own, "language": "py", "include_tests": True } ) )
    assert seen == { "include_tests": True }
