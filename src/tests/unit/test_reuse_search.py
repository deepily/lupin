"""
Unit tests for the recorded search: terms, grep, spans, ranking, the record, its errors.
"""
import pathlib
import shutil
import subprocess

import pytest

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.spec import git_toplevel, spec_for
from lupin_mcp import reuse_search as rs
from lupin_mcp import reuse_tools as rt
from tests.unit.symindex_helpers import make_lupin_repo
from tests.unit.test_reuse_tools import resp

REPO_ROOT = git_toplevel( pathlib.Path( __file__ ).resolve().parent )
NEED      = "parse an RSS feed into Article objects"
TS_FEED   = "/** Parse an RSS feed into Article objects. */\nexport function parseFeed( url: string ) { return url; }\n"
GIT       = [ "git", "-c", "user.email=t@example.com", "-c", "user.name=t", "-c", "commit.gpgsign=false" ]


@pytest.fixture( autouse=True )
def _toolchain( monkeypatch ):
    monkeypatch.setenv( "LUPIN_ROOT", str( REPO_ROOT ) )                                    # the fixture trees have no node_modules of their own
    monkeypatch.delenv( "JEV_API_TOASTER", raising=False )


class AnyJev:
    """Answer every candidate as a clear reuse, so a receipt can be made without a model."""

    def post( self, body ): return resp( 0.95, 0.03, 0.02 )


def git_commit( root ):
    for args in ( [ "init", "-q" ], [ "add", "-A" ], [ "commit", "-q", "-m", "fixture" ] ):
        subprocess.run( [ *( GIT if args[ 0 ] == "commit" else [ "git" ] ), *args ], cwd=root, check=True, capture_output=True )


@pytest.fixture
def tree( tmp_path ):
    root = make_lupin_repo( tmp_path )
    git_commit( root )
    return root, tmp_path / "data", tmp_path / "out"


def ctx_of( tree ):
    return rt.ReuseContext( tree[ 0 ], tree[ 1 ], out_dir=tree[ 2 ], transport=AnyJev() )


def add_ts( tree ):
    js = tree[ 0 ] / "src" / "lupin_app" / "static" / "js"; js.mkdir( parents=True )
    ( js / "feeds.ts" ).write_text( TS_FEED, encoding="utf-8" )


def receipt_for( tree, need=NEED, language="all" ):
    return rt.check_exists_impl( need, ctx_of( tree ), language=language )[ "receipt_id" ]


def search( tree, receipt_id=None, entry=None, extra_terms=None, language=None ):
    return rs.record_search_impl( receipt_id, entry, extra_terms, language, ctx_of( tree ) )


def ids( result ): return [ c[ "id" ] for c in result[ "candidates" ] ]


# --- the terms -------------------------------------------------------------------------------------------------------------------------------

def test_derived_terms_split_like_the_candidate_stage_and_keep_the_longest():
    assert rs.derive_terms( "getUserProfile and parse_feed" ) == [ "profile", "parse", "feed", "user" ]           # camel case and snake case split; "get" and "and" are too short
    assert rs.derive_terms( "alpha alpha beta gamma delta epsilon zeta theta" ) == [ "epsilon", "alpha", "delta", "gamma", "theta", "beta" ]       # the 6 longest, ties alphabetical, repeats once
    assert rs.derive_terms( "this that with from" ) == []                                                           # stop words only
    assert rs.derive_terms( "alpha beta gamma delta", room=2 ) == [ "alpha", "delta" ]
    assert rs.derive_terms( "alpha beta gamma", skip={ "alpha" } ) == [ "gamma", "beta" ]
    assert rs.derive_terms( "alpha beta gamma" ) == rs.derive_terms( "alpha beta gamma" )                           # no model: the same text gives the same terms


def test_terms_need_three_in_all_and_added_terms_fill_the_gap():
    with pytest.raises( rs.SearchError ) as e: rs.search_terms( "do it", [] )
    assert e.value.name == "NO_TERMS"
    with pytest.raises( rs.SearchError ) as e: rs.search_terms( "parse feed", [] )                                   # two derived terms are not enough
    assert e.value.name == "NO_TERMS"
    assert rs.search_terms( "parse feed", [ "rss" ] ) == [ "parse", "feed", "rss" ]                                 # one added term makes three
    with pytest.raises( rs.SearchError ) as e: rs.search_terms( "do it", [ "x", "x", " X " ] )                       # three spellings of one term make one
    assert e.value.name == "NO_TERMS"


def test_added_terms_are_stripped_kept_once_and_make_room_in_the_cut():
    assert rs.search_terms( "alpha beta gamma delta epsilon zeta", [ " Mine " ] ) == [ "epsilon", "alpha", "delta", "gamma", "beta", "Mine" ]      # derived cut to 5 to leave room
    assert rs.search_terms( "alpha beta gamma", [ "alpha", "delta" ] ) == [ "gamma", "beta", "alpha", "delta" ]        # an added term is not also derived
    with pytest.raises( rs.SearchError ) as e: rs.search_terms( "alpha", [ f"t{i}" for i in range( 7 ) ] )
    assert e.value.name == "TOO_MANY_TERMS"
    assert len( rs.search_terms( "alpha", [ f"t{i}" for i in range( 6 ) ] ) ) == 6                                  # six added terms are allowed


# --- hits to definitions, and ranking ------------------------------------------------------------------------------------------------------------

def rec( id_, file="a.py", line=1, end_line=5, sig="()" ): return { "id": id_, "file": file, "line": line, "end_line": end_line, "sig": sig }


def test_a_hit_goes_to_the_innermost_definition_and_a_hit_in_none_is_dropped_and_counted():
    outer, inner, other = rec( "a.Outer", line=2, end_line=20 ), rec( "a.Outer.inner", line=5, end_line=8 ), rec( "b.f", file="b.py", line=10, end_line=12 )
    no_span = { "id": "c.f", "file": "c.py", "line": 1, "sig": "()" }                                          # a Dart-like record: no end_line
    hits = [ ( "a.py", 6, "x" ), ( "a.py", 6, "y" ), ( "a.py", 15, "x" ), ( "a.py", 1, "x" ), ( "a.py", 1, "y" ), ( "b.py", 11, "x" ), ( "c.py", 1, "x" ), ( "z.py", 3, "x" ) ]
    found, dropped = rs.map_hits( hits, [ outer, inner, other, no_span ] )
    assert sorted( found ) == [ "a.Outer", "a.Outer.inner", "b.f" ]
    assert found[ "a.Outer.inner" ][ "terms" ] == { "x", "y" } and found[ "a.Outer.inner" ][ "lines" ] == { 6 }       # line 6 is inside both spans: the inner one takes it
    assert found[ "a.Outer" ][ "lines" ] == { 15 }
    assert dropped == 3                                                                                     # a.py:1 (for two terms, one line), c.py:1 with no span, and z.py:3 in no indexed file
    assert ( "a.py", 1 ) not in { ( f[ "rec" ][ "file" ], l ) for f in found.values() for l in f[ "lines" ] }       # a hit before the first definition is given to no neighbour


def test_spans_that_start_on_one_line_go_to_the_shorter():
    wide, narrow = rec( "a.wide", line=3, end_line=30 ), rec( "a.narrow", line=3, end_line=4 )
    found, _ = rs.map_hits( [ ( "a.py", 3, "x" ) ], [ wide, narrow ] )
    assert sorted( found ) == [ "a.narrow" ]


def found_of( **rows ): return { k: { "rec": rec( k, line=i + 1 ), "terms": set( v[ 0 ] ), "lines": set( v[ 1 ] ) } for i, ( k, v ) in enumerate( rows.items() ) }


def test_ranking_orders_by_terms_then_lines_then_id_leaves_out_the_entry_and_keeps_five():
    found = found_of( z=( "ab", [ 1, 2, 3 ] ), a=( "ab", [ 1, 2 ] ), m=( "abc", [ 1 ] ), b=( "ab", [ 1, 2 ] ), e=( "a", [ 1 ] ), f=( "a", [ 1, 2 ] ), g=( "a", [ 9 ] ), t=( "abc", [ 1 ] ) )
    got = rs.rank_candidates( found, "m" )
    assert [ c[ "id" ] for c in got ] == [ "t", "z", "a", "b", "f" ]                                         # t has the most terms and the fewest lines, so terms outrank lines; then more lines, then id; m is the entry itself
    assert got[ 1 ] == { "id": "z", "file": "a.py", "line": 1, "sig": "()", "terms_matched": [ "a", "b" ] }
    assert [ c[ "id" ] for c in rs.rank_candidates( { k: v for k, v in found.items() if k not in ( "t", "z" ) }, "m" ) ] == [ "a", "b", "f", "e", "g" ]       # one-term rows: more lines first, then id
    assert [ c[ "id" ] for c in rs.rank_candidates( found_of( a=( "x", [ 1 ] ) ), None ) ] == [ "a" ]         # fewer than five is allowed
    assert rs.rank_candidates( {}, None ) == []


# --- git grep, for real ------------------------------------------------------------------------------------------------------------------------

def test_git_grep_reads_working_tree_edits_and_untracked_files_case_insensitively_and_as_fixed_strings( tree ):
    root = tree[ 0 ]
    assert sorted( rs.git_grep( root, "RSS FEED", [ "src/cosa/feeds.py" ] ) ) == [ ( "src/cosa/feeds.py", 2 ) ]
    ( root / "src" / "cosa" / "feeds.py" ).write_text( "x = 1\n# Rss feed here\n", encoding="utf-8" )         # an uncommitted edit
    ( root / "src" / "cosa" / "fresh.py" ).write_text( "a.b\naxb\n-x\n", encoding="utf-8" )                  # not added to git
    assert rs.git_grep( root, "rss feed", [ "src/cosa/feeds.py" ] ) == [ ( "src/cosa/feeds.py", 2 ) ]
    assert rs.git_grep( root, "a.b", [ "src/cosa/fresh.py" ] ) == [ ( "src/cosa/fresh.py", 1 ) ]               # the dot is not a pattern
    assert rs.git_grep( root, "-x", [ "src/cosa/fresh.py" ] ) == [ ( "src/cosa/fresh.py", 3 ) ]               # a term that looks like an option
    assert rs.git_grep( root, "nowhere", [ "src/cosa/fresh.py" ] ) == []


def test_git_grep_asks_for_the_paths_in_batches_and_never_for_an_empty_list( tree, monkeypatch ):
    root, calls = tree[ 0 ], []
    real = subprocess.run
    monkeypatch.setattr( rs.subprocess, "run", lambda *a, **kw: ( calls.append( a[ 0 ] ), real( *a, **kw ) )[ 1 ] )
    assert rs.git_grep( root, "def", [] ) == [] and calls == []                                                 # an empty pathspec would search the whole tree
    monkeypatch.setattr( rs, "BATCH", 1 )
    hits = rs.git_grep( root, "def", [ "src/cosa/feeds.py", "src/cosa/mathx.py", "src/lupin_mcp/tool.py" ] )
    assert len( calls ) == 3 and sorted( hits ) == [ ( "src/cosa/feeds.py", 1 ), ( "src/cosa/mathx.py", 1 ), ( "src/lupin_mcp/tool.py", 1 ) ]
    assert all( c[ 0 ] == "git" and "--" in c for c in calls ) and all( isinstance( c, list ) for c in calls )          # a list, never a shell string


def test_git_grep_outside_a_git_tree_is_a_named_error(tmp_path):
    with pytest.raises( rs.SearchError ) as e: rs.git_grep( tmp_path, "x", [ "a.py" ] )
    assert e.value.name == "GREP_FAILED"


def test_the_parser_agrees_with_a_plain_scan_on_a_copy_of_the_real_lupin_mcp_tree( tmp_path ):
    # the real producer: git grep over the real files, compared with a second route that does not use git
    dest = tmp_path / "copy"
    shutil.copytree( REPO_ROOT / "src" / "lupin_mcp", dest / "src" / "lupin_mcp", ignore=shutil.ignore_patterns( "__pycache__", "*.pyc" ) )
    git_commit( dest )
    paths = sorted( p.relative_to( dest ).as_posix() for p in ( dest / "src" / "lupin_mcp" ).rglob( "*.py" ) )
    term  = "Check_Exists"
    plain = sorted( ( p, n + 1 ) for p in paths for n, line in enumerate( ( dest / p ).read_text( encoding="utf-8", errors="replace" ).split( "\n" ) ) if term.lower() in line.lower() )
    assert len( plain ) > 20                                                                                   # the instrument finds something
    assert sorted( rs.git_grep( dest, term, paths ) ) == plain


def test_a_file_that_changes_during_the_search_makes_it_stale_with_no_candidates( tree ):
    ctx, grep_calls = ctx_of( tree ), []
    sx_build.ensure( ctx.root, ctx.out_dir )
    def editing_grep( root, term, paths ):
        grep_calls.append( term )
        ( root / "src" / "cosa" / "mathx.py" ).write_text( "def add( a, b ):\n    return a - b\n", encoding="utf-8" )         # the tree moves inside the call
        return []
    with pytest.raises( rs.SearchError ) as e: rs.run_search( ctx, [ "add" ], [ "src/cosa/mathx.py" ], grep=editing_grep )
    assert e.value.name == "INDEX_STALE" and grep_calls == [ "add" ]
    quiet = rs.run_search( ctx_of( tree ), [ "add" ], [], grep=lambda *a: pytest.fail( "an empty path list is never searched" ), fresh=lambda spec, out: True )
    assert quiet == []
    assert rs.run_search( ctx, [ "a", "b" ], [ "p" ], grep=lambda r, t, p: [ ( "p", 1 ) ], fresh=lambda spec, out: True ) == [ ( "p", 1, "a" ), ( "p", 1, "b" ) ]


# --- the tool --------------------------------------------------------------------------------------------------------------------------------------

def test_a_receipt_search_finds_the_nearest_definition_and_records_it_once( tree ):
    rid = receipt_for( tree )
    one = search( tree, rid )
    assert one[ "status" ] == "ok" and one[ "receipt_id" ] == rid and rs.SEARCH_ID.fullmatch( one[ "search_id" ] )
    assert ids( one ) == [ "cosa.feeds.parse_feed" ] and one[ "candidates" ][ 0 ][ "terms_matched" ] == [ "article", "feed", "objects", "parse" ]
    assert one[ "terms" ] == [ "article", "objects", "parse", "feed" ] and one[ "dropped_hits" ] == 0
    path = tree[ 1 ] / rs.SEARCH_DIR / f"{one[ 'search_id' ]}.json"
    stored = rt.json.loads( path.read_text( encoding="utf-8" ) )
    assert stored[ "id" ] == one[ "search_id" ] and stored[ "receipt_id" ] == rid and stored[ "entry" ] is None and stored[ "language" ] == "all"
    assert stored[ "scope" ] == [ "public", "private" ] and stored[ "index_sha" ] == rt.load_receipt( ctx_of( tree ), rid )[ "index_sha" ]
    assert stored[ "candidates" ] == one[ "candidates" ] and stored[ "generation" ].startswith( "gen-" )
    before = path.stat().st_mtime_ns
    two = search( tree, rid )
    assert two == one and path.stat().st_mtime_ns == before and len( list( ( tree[ 1 ] / rs.SEARCH_DIR ).glob( "*.json" ) ) ) == 1       # the same search is a no-op


def test_the_search_covers_the_language_of_its_receipt( tree ):
    add_ts( tree )
    by = { lang: search( tree, receipt_for( tree, language=lang ) ) for lang in ( "py", "ts", "all" ) }
    assert ids( by[ "py" ] ) == [ "cosa.feeds.parse_feed" ]
    assert ids( by[ "ts" ] ) == [ "src.lupin_app.static.js.feeds.parseFeed" ]
    assert sorted( ids( by[ "all" ] ) ) == sorted( ids( by[ "py" ] ) + ids( by[ "ts" ] ) )
    assert len( { r[ "search_id" ] for r in by.values() } ) == 3
    assert rt.json.loads( ( tree[ 1 ] / rs.SEARCH_DIR / f"{by[ 'ts' ][ 'search_id' ]}.json" ).read_text( encoding="utf-8" ) )[ "language" ] == "ts"


def test_an_entry_search_needs_a_language_and_never_returns_the_entry_itself( tree ):
    add_ts( tree )
    assert search( tree, entry="cosa.feeds.parse_feed" )[ "error" ] == "LANGUAGE_REQUIRED"
    assert search( tree, entry="cosa.feeds.parse_feed", language="python" )[ "error" ] == "LANGUAGE_INVALID"
    own = search( tree, entry="cosa.feeds.parse_feed", language="py" )
    assert own[ "status" ] == "ok" and own[ "receipt_id" ] is None and own[ "candidates" ] == []                    # the only match in python is the entry
    cross = search( tree, entry="cosa.feeds.parse_feed", language="all" )
    assert ids( cross ) == [ "src.lupin_app.static.js.feeds.parseFeed" ]
    record = rt.json.loads( ( tree[ 1 ] / rs.SEARCH_DIR / f"{cross[ 'search_id' ]}.json" ).read_text( encoding="utf-8" ) )
    assert record[ "entry" ] == "cosa.feeds.parse_feed" and record[ "receipt_id" ] is None and record[ "language" ] == "all"
    assert search( tree, entry="cosa.nowhere", language="py" ) == { "status": "error", "error": "UNKNOWN_ENTRY", "detail": "cosa.nowhere" }


@pytest.mark.parametrize( "kwargs", [ {}, { "receipt_id": "0123456789abcdef", "entry": "a.b" }, { "receipt_id": "0123456789abcdef", "language": "py" },
                                      { "entry": "a.b", "language": "py", "extra_terms": "abc" }, { "entry": "a.b", "language": "py", "extra_terms": [ 1 ] } ] )
def test_a_bad_key_is_named_before_anything_is_read( tree, kwargs ):
    out = search( tree, **kwargs )
    assert out[ "status" ] == "error" and out[ "error" ] == "BAD_SEARCH_KEY" and not ( tree[ 1 ] / rs.SEARCH_DIR ).exists()


def test_each_other_error_is_named_and_none_is_an_empty_candidate_list( tree, tmp_path ):
    assert search( tree, "0123456789abcdef" )[ "error" ] == "RECEIPT_MISSING"
    cap = rt.read_capability_impl( [ "none" ], ctx_of( tree ) )
    assert search( tree, cap[ "receipt_id" ] )[ "error" ] == "BAD_SEARCH_KEY"                                    # only a check_exists or fetch_similar receipt can be backed
    short = receipt_for( tree, need="do it" )
    assert search( tree, short )[ "error" ] == "NO_TERMS"
    assert search( tree, short, extra_terms=[ "alpha", "beta", "gamma" ] )[ "status" ] == "ok"                       # added terms reach three
    assert search( tree, short, extra_terms=[ f"t{i}" for i in range( 7 ) ] )[ "error" ] == "TOO_MANY_TERMS"
    plain = tmp_path / "plain"; plain.mkdir()
    out = rs.record_search_impl( None, "a.b", None, "py", rt.ReuseContext( plain, tree[ 1 ], out_dir=tree[ 2 ], transport=AnyJev() ) )
    assert out[ "error" ] == "NOT_LUPIN_TREE"


def test_a_tracked_edit_and_an_untracked_file_are_both_found( tree ):
    # red when: the search skips build.ensure (the spans are the old ones) or git grep loses --untracked (the newest code is invisible)
    rid = receipt_for( tree )
    feeds = tree[ 0 ] / "src" / "cosa" / "feeds.py"
    feeds.write_text( feeds.read_text( encoding="utf-8" ) + '\ndef parse_feed_again( url ):\n    """Parse an RSS feed into Article objects again."""\n    return url\n', encoding="utf-8" )
    ( tree[ 0 ] / "src" / "cosa" / "fresh.py" ).write_text( 'def fresh_one( x ):\n    """Parse an RSS feed into Article objects, freshly."""\n    return x\n', encoding="utf-8" )
    out = search( tree, rid )
    by = { c[ "id" ]: c for c in out[ "candidates" ] }
    assert sorted( by ) == [ "cosa.feeds.parse_feed", "cosa.feeds.parse_feed_again", "cosa.fresh.fresh_one" ]
    assert by[ "cosa.feeds.parse_feed_again" ][ "line" ] == 5 and by[ "cosa.fresh.fresh_one" ][ "line" ] == 1


def test_a_rebuild_between_fetch_similar_and_the_search_does_not_break_it( tree ):
    # the terms come from the receipt's own snapshot, so renaming or removing the entry since then cannot make the search fail
    rid = rt.fetch_similar_impl( "cosa.feeds.parse_feed", ctx_of( tree ), language="all" )[ "receipt_id" ]
    ( tree[ 0 ] / "src" / "cosa" / "feeds.py" ).write_text( "x = 1\n", encoding="utf-8" )
    out = search( tree, rid )
    assert out[ "status" ] == "ok" and "parse" in out[ "terms" ] and out[ "candidates" ] == []
    assert rt.load_receipt( ctx_of( tree ), rid )[ "query" ] == "cosa.feeds.parse_feed"


def test_a_tree_that_moves_during_the_search_gives_a_named_error_and_no_record( tree, monkeypatch ):
    rid, real = receipt_for( tree ), rs.run_search
    def editing( root, term, paths ):
        ( root / "src" / "cosa" / "mathx.py" ).write_text( "def add( a, b ):\n    return a - b\n", encoding="utf-8" )
        return []
    monkeypatch.setattr( rs, "run_search", lambda ctx, terms, paths: real( ctx, terms, paths, grep=editing ) )
    out = search( tree, rid )
    assert out[ "error" ] == "INDEX_STALE" and out.get( "candidates" ) is None and not ( tree[ 1 ] / rs.SEARCH_DIR ).exists()


def test_an_index_that_cannot_be_built_is_a_named_error( tree, monkeypatch ):
    rid = receipt_for( tree )
    monkeypatch.setattr( rs.sx_build, "ensure", lambda *a, **kw: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    out = search( tree, rid )
    assert out[ "error" ] == "INDEX_STALE" and "RuntimeError: boom" in out[ "detail" ]


def test_the_id_hashes_the_record_so_a_different_search_is_a_different_id():
    one = rs.search_record_id( { "terms": [ "a" ] } )
    assert rs.SEARCH_ID.fullmatch( one ) and one == rs.search_record_id( { "terms": [ "a" ] } ) and one != rs.search_record_id( { "terms": [ "b" ] } )
    assert not rs.SEARCH_ID.fullmatch( "rs-0123456789a" ) and not rs.SEARCH_ID.fullmatch( "xs-0123456789" ) and not rs.SEARCH_ID.fullmatch( "rs-0123456789\n" )


def test_the_tool_is_mounted_beside_the_four_others_and_the_middleware_knows_it():
    import asyncio
    from lupin_mcp import cosa_voice_mcp as cvm
    from lupin_mcp import reuse_call_log_middleware as mw
    assert "record_search" in mw.REUSE_TOOLS
    tool = asyncio.run( cvm.mcp.get_tool( "record_search" ) )
    assert "exactly one of receipt_id and entry" in tool.description and "no default" in tool.description


def test_a_receipt_of_a_nested_definition_gives_its_stored_text_to_the_search( tree ):
    # red when: the search reads a need_text receipt from the snapshot (which cannot hold a nested definition) and so answers UNKNOWN_ENTRY
    feeds = tree[ 0 ] / "src" / "cosa" / "feeds.py"
    feeds.write_text( feeds.read_text( encoding="utf-8" ) + '\ndef outer( x ):\n    def _quiet_shredder( y ):\n        """Shred a zebra pelt into mosaic tiles."""\n        return y\n    return _quiet_shredder( x )\n', encoding="utf-8" )
    rid = rt.fetch_similar_impl( "cosa.feeds.outer.<locals>._quiet_shredder", ctx_of( tree ), language="all" )[ "receipt_id" ]
    assert "need_text" in rt.load_receipt( ctx_of( tree ), rid )                                                  # the premise: the receipt carries the nested text
    out = search( tree, rid )
    assert out[ "status" ] == "ok" and { "shredder", "mosaic" } <= set( out[ "terms" ] )     # the six longest words


def test_a_snapshot_that_no_longer_holds_the_entry_is_a_named_error_and_not_an_empty_search( tree, monkeypatch ):
    rid = rt.fetch_similar_impl( "cosa.feeds.parse_feed", ctx_of( tree ), language="all" )[ "receipt_id" ]
    monkeypatch.setattr( rt, "load_snapshot", lambda ctx, sha: ( [], None ) )
    assert search( tree, rid ) == { "status": "error", "error": "UNKNOWN_ENTRY", "detail": "cosa.feeds.parse_feed" }
