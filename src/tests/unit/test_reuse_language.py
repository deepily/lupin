"""
The language argument of the reuse search: required, checked, applied, and in the receipt.
"""
import ast
import asyncio
import copy
import json
import pathlib
import subprocess

import pytest

from cosa.repo.symindex.spec import git_toplevel
from lupin_mcp import cosa_voice_mcp as cvm
from lupin_mcp import reuse_e2e_run as e2e
from lupin_mcp import reuse_flip as flip
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt
from tests.unit.test_reuse_candidate_route import FEEDS_ID, MANIFEST, MATH_ID
from tests.unit.test_reuse_candidate_widening import NEAR, BAND, RankedStage
from tests.unit.test_reuse_pack_route import PackedFake, env, no_jev_key, receipt_of      # noqa: F401  (env and no_jev_key are fixtures)
from tests.unit.test_reuse_page_first import HIT
from tests.unit.test_reuse_tools import FEEDS_TEXT, NEED, Recorder, ctx_for, resp

REPO_ROOT = git_toplevel( pathlib.Path( __file__ ).resolve().parent )
BOX_TS    = 'export class Box {\n    /** Public one. */\n    open(): void {}\n    /** Hidden helper. */\n    private hid(): void {}\n}\n'
TS_OPEN   = "src.lupin_app.static.js.box.Box.open"


class AllReuse:
    """Answer reuse for every candidate, so each entry asked lands in the shortlist."""

    def __init__( self ): self.seen = []

    def post( self, body ):
        self.seen.append( body ); return resp( 0.95, 0.03, 0.02 )


def two_languages( env ):
    """Add a TypeScript file to the lupin fixture tree, so the index holds python and ts entries."""
    js = env[ 0 ] / "src" / "lupin_app" / "static" / "js"; js.mkdir( parents=True )
    ( js / "box.ts" ).write_text( BOX_TS, encoding="utf-8" )
    return env


def ids_of( r ): return sorted( { s[ "id" ] for s in r[ "shortlist" ] } | { s[ "id" ] for s in r[ "nearest" ] } )


def is_ts( i ): return i.startswith( "src.lupin_app" )


def old_form( rec ):
    """Return the receipt as it was before the language field was added."""
    old = { k: v for k, v in rec.items() if k != "language" }
    old[ "id" ] = rt.receipt_id( rec[ "tool" ], rec[ "query" ], rec[ "index_sha" ], rec[ "model" ], rec[ "policy" ], rec[ "prompt_template_hash" ], rec[ "causes" ],
                                 rec[ "tool_version" ], rec[ "request_shape" ] if "request_shape" in rec else None )
    return old


# --- the argument itself -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize( "bad, error", [ ( None, "LANGUAGE_REQUIRED" ), ( "python", "LANGUAGE_INVALID" ), ( "", "LANGUAGE_INVALID" ), ( "ALL", "LANGUAGE_INVALID" ) ] )
def test_a_missing_or_unknown_language_is_refused_before_any_request_by_the_impl( env, bad, error ):
    # red when: the check moves after prepare() or the sweep, or a language is guessed from the entry
    fake = Recorder()
    for call in ( lambda: rt.check_exists_impl( NEED, ctx_for( env, fake ), language=bad ), lambda: rt.fetch_similar_impl( "cosa.feeds.parse_feed", ctx_for( env, fake ), language=bad ) ):
        r = call()
        assert ( r[ "status" ], r[ "error" ] ) == ( "error", error ) and r[ "choices" ] == [ "py", "ts", "dart", "all" ]
    assert fake.seen == [] and not ( env[ 1 ] / "receipts" ).exists()                                  # no request, and no receipt


@pytest.mark.parametrize( "args, error", [ ( {}, "LANGUAGE_REQUIRED" ), ( { "language": "python" }, "LANGUAGE_INVALID" ) ] )
def test_a_missing_or_unknown_language_is_refused_before_any_request_by_the_mcp_wrapper( env, monkeypatch, args, error ):
    fake = Recorder()
    monkeypatch.setattr( rt, "context_from_environment", lambda r=None: ctx_for( env, fake ) )
    for name, own in ( ( "check_exists", { "need": NEED } ), ( "fetch_similar", { "entry": "cosa.feeds.parse_feed" } ) ):
        tool = asyncio.run( cvm.mcp.get_tool( name ) )
        out  = asyncio.run( tool.run( { **own, **args } ) ).structured_content
        assert out[ "error" ] == error, name
    assert fake.seen == []


def test_the_wrappers_say_in_their_docstrings_that_the_language_is_mandatory():
    for name in ( "check_exists", "fetch_similar" ):
        tool = asyncio.run( cvm.mcp.get_tool( name ) )
        assert "mandatory" in tool.description and "required; there is no default" in tool.description, name


def test_the_helpers_name_the_choices_and_filter_by_the_lang_key():
    assert rt.LANGUAGES == ( "py", "ts", "dart", "all" )
    assert rt.language_error( "dart" ) is None and rt.language_error( None )[ "error" ] == "LANGUAGE_REQUIRED"
    entries = [ { "id": "a", "lang": "py" }, { "id": "b", "lang": "ts" }, { "id": "c", "lang": "py" } ]
    assert [ e[ "id" ] for e in rt.in_language( entries, "py" ) ] == [ "a", "c" ] and rt.in_language( entries, "dart" ) == []
    assert rt.in_language( entries, "all" ) == entries and rt.in_language( entries, "all" ) is not entries


def test_run_question_refuses_a_language_the_impls_would_have_refused( env ):
    with pytest.raises( rt.ReuseError ) as e: rt.run_question( ctx_for( env, Recorder() ), "check_exists", NEED, NEED, language="python" )
    assert e.value.name == "BAD_LANGUAGE"
    with pytest.raises( TypeError ): rt.run_question( ctx_for( env, Recorder() ), "check_exists", NEED, NEED )                 # keyword-only and required: no default of its own


# --- the search ----------------------------------------------------------------------------------------------------------------------------

def test_a_search_covers_the_language_asked_and_all_opts_into_every_language( env ):
    # red when: prepare() or _run_question stops filtering by `lang`, or `all` stops being the only way to widen
    two_languages( env )
    got = { lang: rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=AllReuse() ), language=lang ) for lang in ( "py", "ts", "all" ) }
    py, ts, every = ( ids_of( got[ k ] ) for k in ( "py", "ts", "all" ) )
    assert py and ts and not any( is_ts( i ) for i in py ) and all( is_ts( i ) for i in ts )
    assert sorted( py + ts ) == every and len( {  r[ "receipt_id" ] for r in got.values() } ) == 3
    assert [ receipt_of( env, got[ k ] )[ "language" ] for k in ( "py", "ts", "all" ) ] == [ "py", "ts", "all" ]
    assert got[ "py" ][ "stats" ][ "entries" ] < got[ "all" ][ "stats" ][ "entries" ]


def test_fetch_similar_takes_its_language_from_the_caller_and_a_cross_language_look_is_allowed( env ):
    two_languages( env )
    own   = rt.fetch_similar_impl( "cosa.feeds.parse_feed", rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=AllReuse() ), language="py" )
    other = rt.fetch_similar_impl( "cosa.feeds.parse_feed", rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=AllReuse() ), language="ts" )
    assert ids_of( own ) and not any( is_ts( i ) for i in ids_of( own ) ) and "cosa.feeds.parse_feed" not in ids_of( own )
    assert ids_of( other ) and all( is_ts( i ) for i in ids_of( other ) )
    assert own[ "receipt_id" ] != other[ "receipt_id" ]


def test_the_same_need_under_two_languages_is_two_receipts_and_an_old_receipt_still_loads_and_replays( env ):
    # red when: language is left out of the id (write_once would hand the second call the first receipt), or an old receipt stops loading
    two_languages( env )
    fake = AllReuse()
    a = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ), language="py" )
    b = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ), language="ts" )
    assert a[ "receipt_id" ] != b[ "receipt_id" ] and len( list( ( env[ 1 ] / "receipts" ).glob( "*.json" ) ) ) == 2
    c = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ), language="all" )
    old = old_form( receipt_of( env, c ) )
    ( env[ 1 ] / "receipts" / f"{old[ 'id' ]}.json" ).write_text( rt.canonical( old ) + "\n", encoding="utf-8" )
    assert old[ "id" ] != c[ "receipt_id" ] and "language" not in rt.load_receipt( ctx_for( env, fake ), old[ "id" ] )         # it loads: its id recomputes without the key
    rep = rt.replay_impl( old[ "id" ], rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ) )
    ids = lambda rows: [ s[ "id" ] for s in rows ]
    assert rep[ "status" ] == "ok" and rep[ "differences" ][ "frozen" ] == [] and ids( rep[ "frozen" ][ "shortlist" ] ) == ids( rep[ "stored" ][ "shortlist" ] )        # no key replays as `all`
    assert len( rep[ "stored" ][ "shortlist" ] ) == len( c[ "shortlist" ] ) > len( a[ "shortlist" ] )


def test_a_receipt_replays_in_the_language_it_stored( env ):
    two_languages( env )
    fake = AllReuse()
    r    = rt.check_exists_impl( NEED, rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ), language="ts" )
    rep  = rt.replay_impl( r[ "receipt_id" ], rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake ) )
    assert rep[ "status" ] == "ok" and rep[ "differences" ] == { "frozen": [], "head": [] }
    assert rep[ "frozen" ][ "shortlist" ] and all( is_ts( s[ "id" ] ) for s in rep[ "frozen" ][ "shortlist" ] )


def test_the_receipt_id_holds_language_and_include_tests_only_when_present():
    base = ( "check_exists", "q", "i" * 40, "m", { "p": 1 }, "t" )
    bare = rt.receipt_id( *base )
    assert rt.receipt_id( *base, language=None, include_tests=None ) == bare                       # an old receipt keeps its id
    assert len( { bare, rt.receipt_id( *base, language="py" ), rt.receipt_id( *base, language="ts" ), rt.receipt_id( *base, language="py", include_tests=True ),
                  rt.receipt_id( *base, language="py", include_tests=False ) } ) == 5


# --- the candidate stage holds every language ----------------------------------------------------------------------------------------------

class MixedStage:
    """A stand-in stage whose answer holds ids of both languages, as the real vector set does."""

    arm, K = "B1", 128

    def manifest( self ): return { "manifest_hash": MANIFEST }

    def shortlist( self, ranking_text, entries, index_sha, pages, exclude_id=None, cache_only=False, wiki_ids=None, index_manifest=None ):
        ids = sorted( [ FEEDS_ID, MATH_ID, TS_OPEN ] )
        return { "ids": ids, "ranking": ids, "lists": { "code": { "size": 3, "head": ids } }, "manifest_hash": MANIFEST, "embed_models": { "code": "c", "prose": "p" },
                 "arm": self.arm, "K": self.K, "widened": False, "stage_key": "k" * 32, "wiki": 0, "wiki_ids": [], "ranking_hash": "r" * 64 }


def packed_with( env, fake, stage, policy=None ):
    return rt.ReuseContext( env[ 0 ], env[ 1 ], out_dir=env[ 2 ], transport=fake, sweeper=rp.packed_sweeper( 10, shape=rp.SHAPE_WHOLE ), request_shape=rp.SHAPE_WHOLE,
                            pack_size=10, candidate_stage=stage, policy=policy )


def test_the_stage_ids_of_another_language_are_dropped_before_anything_is_asked_and_the_replay_follows( env ):
    # red when: _run_question stops dropping them (the receipt would list a ts id the py sweep never asked) or the replay compares the unfiltered ids
    two_languages( env )
    need = "read an RSS feed [lang-stage]"
    fake = PackedFake( need, { FEEDS_TEXT: HIT } )
    r    = rt.check_exists_impl( need, packed_with( env, fake, MixedStage() ), language="py" )
    rec  = receipt_of( env, r )
    assert sorted( rec[ "candidate_stage" ][ "ids" ] ) == sorted( [ FEEDS_ID, MATH_ID ] ) and sorted( i for q in rec[ "requests" ] for i in q[ "ids" ] ) == sorted( [ FEEDS_ID, MATH_ID ] )
    rep = rt.replay_impl( r[ "receipt_id" ], packed_with( env, fake, MixedStage() ) )
    assert rep[ "status" ] == "ok" and rep[ "differences" ][ "frozen" ] == []
    every = rt.check_exists_impl( need, packed_with( env, PackedFake( need, { FEEDS_TEXT: HIT } ), MixedStage() ), language="all" )
    assert TS_OPEN in receipt_of( env, every )[ "candidate_stage" ][ "ids" ]                                # `all` filters nothing


def test_a_widening_drops_the_wider_sets_ids_of_another_language( env ):
    two_languages( env )
    need  = "read an RSS feed [lang-wide]"
    stage = RankedStage( ranking=[ FEEDS_ID, TS_OPEN, MATH_ID ] )
    fake  = PackedFake( need, { FEEDS_TEXT: NEAR } )
    rt_wide, old = 3, rt.WIDE_K
    rt.WIDE_K = rt_wide
    try:
        r = rt.check_exists_impl( need, packed_with( env, fake, stage, policy=dict( BAND ) ), language="py" )
    finally:
        rt.WIDE_K = old
    cs = receipt_of( env, r )[ "candidate_stage" ]
    assert cs[ "ids" ] == [ FEEDS_ID ] and cs[ "widened_ids" ] == [ MATH_ID ]                           # the ts id sat between them in the wide ranking


# --- the measurement drivers say `all` ---------------------------------------------------------------------------------------------------------

def record_language( monkeypatch, name, target=rt ):
    seen = []
    def spy( *a, **kw ):
        seen.append( kw[ "language" ] if "language" in kw else "<missing>" ); raise rt.ReuseError( "STOP", "recorded" )
    monkeypatch.setattr( target, name, spy )
    return seen


def test_the_two_driver_impls_pass_their_language_on_to_run_question( env, monkeypatch ):
    seen = record_language( monkeypatch, "run_question" )
    rt.sweep_need_impl( NEED, None, ctx_for( env, Recorder() ), language="ts" )
    rt.unstored_need_impl( NEED, None, ctx_for( env, Recorder() ), language="dart" )
    assert seen == [ "ts", "dart" ]
    with pytest.raises( TypeError ): rt.sweep_need_impl( NEED, None, ctx_for( env, Recorder() ) )                    # required: no default
    with pytest.raises( TypeError ): rt.unstored_need_impl( NEED, None, ctx_for( env, Recorder() ) )
    assert rt.sweep_need_impl( NEED, None, ctx_for( env, Recorder() ), language="python" )[ "error" ] == "LANGUAGE_INVALID"


def test_the_e2e_driver_asks_in_every_language( monkeypatch ):
    item, seen = { "need": "n", "member": "m" }, []
    monkeypatch.setattr( rt, "sweep_need_impl", lambda *a, **kw: seen.append( kw[ "language" ] ) )
    monkeypatch.setattr( rt, "unstored_need_impl", lambda *a, **kw: seen.append( kw[ "language" ] ) )
    e2e.ask_old( None, item ); e2e.ask_new( None, item ); e2e.ask_candidates( None, item )
    assert seen == [ "all", "all", "all" ]


def test_the_flip_driver_asks_in_every_language( monkeypatch ):
    seen = []
    monkeypatch.setattr( rt, "unstored_need_impl", lambda *a, **kw: seen.append( kw[ "language" ] ) )
    ctx = copy.copy( rt.ReuseContext( pathlib.Path( "/x" ), pathlib.Path( "/y" ) ) )
    ctx.sweeper, ctx.pack_size = object(), 10
    flip.ask_repeat( ctx, "n", "m", 1 )
    assert seen == [ "all" ]


def test_the_seeded_miss_driver_and_the_band_fit_driver_ask_in_every_language( monkeypatch ):
    from lupin_mcp import reuse_band_fit_run as bf
    from lupin_mcp import reuse_seeded_miss_e2e as sm
    seen = []
    monkeypatch.setattr( rt, "check_exists_impl", lambda need, c, language: ( seen.append( language ), { "status": "error", "error": "NO" } )[ 1 ] )
    sm.candidate_scenario( None, None, None, None, 5 )
    source = pathlib.Path( bf.__file__ ).read_text( encoding="utf-8" )
    assert seen == [ "all" ] and 'language="all" )' in source.split( "rt._need_impl(" )[ 1 ].split( "\n" )[ 0 ]


# --- every caller says it (a census with a positive control) --------------------------------------------------------------------------------

CALLED = frozenset( { "check_exists_impl", "fetch_similar_impl", "sweep_need_impl", "unstored_need_impl", "_need_impl", "run_question", "_run_question" } )
VIA    = frozenset( { "check_exists_impl", "fetch_similar_impl" } )                       # named by a string in the MCP wrappers' _reuse_call


def callers_without_language( sources ):
    """
    Find the call sites of the search entry points.

    Ensures:
        - returns ( found, missing ): every call site, and those with no `language=` keyword
    """
    found, missing = [], []
    for path, text in sources:
        try: tree = ast.parse( text )
        except SyntaxError:
            if any( name in text for name in CALLED ): missing.append( f"{path}: unparsable and names an entry point" )
            continue
        for n in ast.walk( tree ):
            if not isinstance( n, ast.Call ): continue
            fn   = n.func
            name = fn.attr if isinstance( fn, ast.Attribute ) else ( fn.id if isinstance( fn, ast.Name ) else None )
            via  = name == "_reuse_call" and n.args and isinstance( n.args[ 0 ], ast.Constant ) and n.args[ 0 ].value in VIA
            if name not in CALLED and not via: continue
            found.append( f"{path}:{n.lineno}" )
            if not any( k.arg == "language" for k in n.keywords ): missing.append( f"{path}:{n.lineno}" )
    return found, missing


def tracked_sources():
    names = subprocess.run( [ "git", "ls-files", "src" ], cwd=REPO_ROOT, capture_output=True, text=True, check=True ).stdout.split()
    return [ ( n, ( REPO_ROOT / n ).read_text( encoding="utf-8" ) ) for n in names if n.endswith( ".py" ) and not n.startswith( ( "src/tests/", "src/rnd/" ) ) and "/tests/" not in n ]


def test_every_caller_of_a_search_entry_point_in_src_says_which_language():
    found, missing = callers_without_language( tracked_sources() )
    assert len( found ) == 15, found                                                  # the denominator, counted 24 October: 7 inside reuse_tools, 2 wrappers, 3 + 1 + 1 + 1 in the drivers
    assert missing == []


def test_the_caller_census_goes_red_for_a_stray_caller_and_for_an_unparsable_file():
    stray = [ ( "src/x.py", "def f( ctx ):\n    return rt.check_exists_impl( 'n', ctx )\n" ), ( "src/y.py", "def g(:\n    sweep_need_impl\n" ), ( "src/z.py", "x = _reuse_call( 'fetch_similar_impl', None, 'e' )\n" ) ]
    found, missing = callers_without_language( stray )
    assert found == [ "src/x.py:2", "src/z.py:1" ] and missing == [ "src/x.py:2", "src/y.py: unparsable and names an entry point", "src/z.py:1" ]
    assert callers_without_language( [ ( "src/ok.py", "rt.check_exists_impl( 'n', ctx, language='all' )\n" ) ] ) == ( [ "src/ok.py:1" ], [] )
