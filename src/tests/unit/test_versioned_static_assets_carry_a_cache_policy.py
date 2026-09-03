"""
A `?v=`-tokened asset URL must be served with an explicit freshness directive.

THE DEFECT, measured 2026-09-02 against the live :7999. The SPA shell is served
`Cache-Control: no-cache` (pages.py:71) so a reload revalidates it — that half works. The
static mount underneath it (`main.py`, `app.mount( "/static", StaticFiles(...) )`) sets NO
cache-control at all, only `last-modified` and an ETag.

⇒ SO THE WHOLE CACHE-BUSTING SCHEME RESTS ON THE HTML BEING REVALIDATED FIRST. Bump a
`?v=` token and the new URL is a new cache key, which is the point — but the OLD url is
also a cache key, and with no freshness directive on it a browser may serve it from
heuristic cache indefinitely without ever asking. A tab that was already open when the
token moved therefore keeps running the old asset, and "nothing happens and nothing
throws" is what the operator sees. Every `?v=` bump this repo has made carries the hole.

⚠️ WHAT THIS FILE ASSERTS, AND WHY IT IS NOT "THE HEADER IS PRESENT". A guard that pins
one header on one known file is the easy half and would not have caught this: the hole was
never about a file anyone was looking at, it was about a POLICY that was absent
everywhere. So the load-bearing test DISCOVERS the corpus from the page — every asset the
shell links with a `?v=` — and requires a directive on each. Add a tenth asset tomorrow
and it is covered on the day it is linked, without anyone remembering to extend a list.

⚠️ AND THE CORPUS IS PROVEN NON-EMPTY BEFORE IT IS TRUSTED. A discovery that silently
finds nothing passes every per-item assertion in the loop, and an empty search and a clean
result print the same thing.

🔴 THE LAST CLASS HERE DRIVES THE APP `main.py` ACTUALLY BUILDS, AND IT IS NOT OPTIONAL.
Everything above mounts `VersionedStaticFiles` itself, so all of it stays green if the
server goes on mounting plain `StaticFiles` — a policy that is implemented and not
installed is exactly the defect this closes, one level up. The same trap this repo already
names: a test that enters below the layer the incident entered at cannot speak to the
incident.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lupin_app.versioned_static import VersionedStaticFiles


STATIC_DIR = Path( __file__ ).resolve().parents[ 2 ] / "lupin_app" / "static"
SHELL      = STATIC_DIR / "html" / "notifications.html"


def _linked_versioned_assets():
    """
    Every `/static/...?v=...` URL the shell links — the corpus, read from the page.

    Ensures:
        - returns a sorted list of (path, query) pairs, deduplicated
        - discovers from the HTML rather than from a list kept in this file
    """
    html  = SHELL.read_text( encoding="utf-8" )
    found = re.findall( r'(?:src|href)="(/static/[^"?]+)\?(v=[^"]+)"', html )
    return sorted( set( found ) )


@pytest.fixture
def client():
    app = FastAPI()
    app.mount( "/static", VersionedStaticFiles( directory=str( STATIC_DIR ) ), name="static" )
    return TestClient( app )


def test_the_shell_actually_links_versioned_assets():
    """
    THE POSITIVE CONTROL, and it is not ceremony. Every assertion below runs inside a loop
    over this corpus, so a discovery that quietly returned nothing would make the whole
    file pass while measuring not one byte.
    """
    assets = _linked_versioned_assets()
    assert len( assets ) >= 5, f"only {len( assets )} versioned assets discovered - the regex has stopped matching the page"


def test_every_versioned_asset_the_page_links_is_served_with_a_freshness_directive( client ):
    """
    THE GUARD THIS FILE EXISTS FOR. Not "the header is set on notifications.js" — that
    would have gone green on nine other assets carrying the same hole.
    """
    missing = []
    for path, query in _linked_versioned_assets():
        r = client.get( f"{path}?{query}" )
        assert r.status_code == 200, f"{path} is linked by the shell and does not serve"
        if not r.headers.get( "cache-control" ): missing.append( path )
    assert missing == [], f"linked with ?v= and served with no cache-control: {missing}"


def test_a_versioned_url_is_cacheable_because_the_token_makes_it_immutable( client ):
    """
    A `?v=` URL names one exact revision: bumping the token yields a DIFFERENT url, so the
    old one can never need to change. That is what earns a long max-age, and it is the
    property that makes the token scheme work rather than merely look like it works.
    """
    path, query = _linked_versioned_assets()[ 0 ]
    cc = client.get( f"{path}?{query}" ).headers[ "cache-control" ]
    assert "max-age=" in cc
    assert int( re.search( r"max-age=(\d+)", cc ).group( 1 ) ) >= 86400, f"a token-pinned url got a short max-age: {cc}"


def test_the_same_file_without_a_token_must_revalidate( client ):
    """
    THE OTHER HALF, and the one that makes this a policy rather than a blanket max-age.
    An UN-tokened url has no revision in it, so caching it hard is exactly the stale-asset
    trap one level down — the file changes underneath a url that never changes.
    """
    path, _ = _linked_versioned_assets()[ 0 ]
    cc = client.get( path ).headers.get( "cache-control", "" )
    assert "no-cache" in cc, f"an un-tokened asset url may go stale silently: {cc!r}"


def test_the_two_policies_actually_differ_for_one_file( client ):
    """
    DISCRIMINATING, and it is the case a single-policy implementation passes everything
    else on. Same file, same server, one variable — the presence of the token. If both
    answers are equal, the code is not reading the query at all and one of the two rules
    above is being satisfied by accident.
    """
    path, query = _linked_versioned_assets()[ 0 ]
    with_token    = client.get( f"{path}?{query}" ).headers.get( "cache-control", "" )
    without_token = client.get( path ).headers.get( "cache-control", "" )
    assert with_token != without_token, f"the token changes nothing: both {with_token!r}"


class TestTheServerActuallyMountsIt:
    """
    THROUGH-PATH. The mount under test is the one `main.py` assembles — not one this file
    built. Precedent and fixture shape: test_retired_doors_through_the_real_app.py.
    """

    @pytest.fixture( scope="class" )
    def real_app( self ):
        import os, sys
        root = os.environ.get( "LUPIN_ROOT" )
        assert root, "LUPIN_ROOT must be set — see CLAUDE.md § PATH MANAGEMENT"
        os.environ.setdefault( "JWT_SECRET_KEY", "test-only-never-signs-anything" )
        src = os.path.join( root, "src" )
        if src not in sys.path: sys.path.insert( 0, src )
        import lupin_app.main as main_module
        return main_module.app

    def test_the_static_mount_the_server_builds_carries_the_policy( self, real_app ):
        """
        Asked of the assembled route table, not of the source text. A source-level check
        would hold against the import sitting unused, which is how three assertions in the
        neighbouring JS suite went green against strings that never ran.
        """
        mounts = [ r for r in real_app.routes if getattr( r, "path", None ) == "/static" ]
        assert mounts, "the server mounts nothing at /static"
        assert any( isinstance( getattr( m, "app", None ), VersionedStaticFiles ) for m in mounts ), \
            "/static is mounted with plain StaticFiles - the policy is implemented but not installed"

    def test_a_versioned_asset_is_cacheable_through_the_real_app( self, real_app ):
        """
        The end-to-end claim, one request through the server the operator talks to. Without
        this, every assertion above is about a class nobody reaches.
        """
        from fastapi.testclient import TestClient
        client      = TestClient( real_app, raise_server_exceptions=False )
        path, query = _linked_versioned_assets()[ 0 ]
        assert "immutable" in client.get( f"{path}?{query}" ).headers.get( "cache-control", "" )
        assert "no-cache"  in client.get( path ).headers.get( "cache-control", "" )
