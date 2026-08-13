"""
Every authenticated fetch in a served page must go through a refresh-aware wrapper.

WHY THIS GUARD EXISTS — the defect class, not the defect (row 38943485, Sam 🎙️
2026-08-04, fixed 2026-08-13). `audio-player.html` is a STANDALONE page: it was
written separately from the notifications app, so it never inherited that app's
`authedFetch` → `ensureValidToken` path. It read the JWT straight out of
localStorage, fired raw fetches with it, and turned a 401 into "Could not load
audio" with no retry and no way forward but a manual reload.

Nothing caught that, because nothing was looking. The row said it plainly:

    "The defect class is 'one page written separately from the others', and it
     will recur."

A test pinned to audio-player.html alone would not have caught audio-player.html
before it existed, and will not catch the next page either. So this guard is
written against the PATTERN: any served page that reads an access token must not
also call bare `fetch(` with it.

⚠️ THIS IS A STATIC READ, and its limits are stated rather than implied. It greps
served HTML; it cannot prove a page's runtime behaviour, and a page that obtains a
token by some route this does not recognise is invisible to it. It catches the
recurrence of the exact shape that bit us, which is what the row asked for — not
every conceivable auth mistake.
"""

import os
import re
import unittest

import cosa.utils.util as cu


# Pages are served from here; the guard walks whatever is present rather than a
# hardcoded list, so a NEW page is covered the moment it lands.
_HTML_DIR = os.path.join( cu.get_project_root(), "src/lupin_app/static/html" )

# Reading either token key is what makes a page "authenticated" for this guard's
# purposes — it is the act that gives the page a credential to misuse.
_TOKEN_READ = re.compile( r"localStorage\.getItem\(\s*['\"]lupin_(?:access|refresh)_token['\"]\s*\)" )

# A bare `fetch(` — the thing that must not carry a token without a retry path.
_BARE_FETCH = re.compile( r"(?<![\w.])fetch\s*\(" )

# Calls that are legitimately bare, because they ARE the refresh machinery or are
# unauthenticated by nature. Matched on the URL literal in the same call.
_ALLOWED_BARE = (
    "/auth/refresh",   # the refresh call itself cannot require a fresh token
    "/auth/login",     # unauthenticated by definition
)


def _served_pages():
    """Every .html file actually served, as ( filename, text ) pairs."""
    if not os.path.isdir( _HTML_DIR ): return []
    out = []
    for name in sorted( os.listdir( _HTML_DIR ) ):
        if not name.endswith( ".html" ): continue
        with open( os.path.join( _HTML_DIR, name ), encoding="utf-8" ) as f:
            out.append( ( name, f.read() ) )
    return out


def _bare_fetch_lines( text ):
    """Line numbers of bare `fetch(` calls that are not on the allow-list."""
    hits = []
    for n, line in enumerate( text.splitlines(), start=1 ):
        if not _BARE_FETCH.search( line ):        continue
        if any( a in line for a in _ALLOWED_BARE ): continue
        # A wrapper's OWN body necessarily calls bare fetch — that is what a wrapper
        # is. Recognise it by the header-building helper it passes, not by line
        # number: `withAuth(...)` only exists inside the wrapper.
        if "withAuth(" in line: continue
        hits.append( ( n, line.strip() ) )
    return hits


# ── KNOWN PRE-EXISTING OFFENDERS ─────────────────────────────────────────────
# Dated, named, and NOT silently skipped. Recording them here rather than widening
# the pattern keeps the guard sharp: a NEW page joining this list fails the build,
# while these stay visible as debt rather than disappearing into a green run.
#
# Found 2026-08-13 by this guard on its first run — which is the point. Row 38943485
# predicted "the defect class is 'one page written separately from the others', and
# it will recur"; it had already recurred twice before anyone looked.
#
# ⚠️ An entry here is a promise to fix, not an exemption. Removing a page from this
# list without fixing it re-hides the defect.
_KNOWN_UNWRAPPED = {
    # EMPTY, and that is the finding. The guard's first run named two candidates;
    # document-viewer.html was a REAL recurrence of the same defect and was fixed in
    # the same pass rather than listed, because doc-viewer links are what every
    # session emits and they are clicked long after they are sent — precisely when a
    # token has aged out. parity-harness.html turned out not to match at all (its
    # fetches live in compiled JS, not the served HTML); listing it would have been an
    # exemption protecting nothing.
    #
    # Keep this dict EMPTY unless a page is genuinely known-broken and scheduled. An
    # entry is a promise to fix, never a way to make the guard quiet.
}


class TestTheGuardCanFail( unittest.TestCase ):
    """
    CONTROL. A pattern guard that matches nothing passes silently forever, and a
    green wall is exactly how the original defect survived. These prove both
    detectors actually fire.
    """

    def test_the_token_pattern_matches_a_real_token_read( self ):
        self.assertTrue( _TOKEN_READ.search( "const t = localStorage.getItem( 'lupin_access_token' );" ) )

    def test_the_token_pattern_ignores_unrelated_storage( self ):
        self.assertFalse( _TOKEN_READ.search( "localStorage.getItem( 'lupin_session_name' )" ) )

    def test_the_bare_fetch_pattern_matches_a_bare_call( self ):
        self.assertEqual( len( _bare_fetch_lines( "const r = await fetch( url, init );" ) ), 1 )

    def test_the_bare_fetch_pattern_ignores_a_wrapped_call( self ):
        self.assertEqual( _bare_fetch_lines( "const r = await authedFetch( url, {} );" ), [] )

    def test_the_allow_list_exempts_the_refresh_call_itself( self ):
        self.assertEqual( _bare_fetch_lines( "await fetch( '/auth/refresh', opts );" ), [] )

    def test_it_would_catch_the_original_defect( self ):
        """
        The exact shape of audio-player.html BEFORE the fix. If this stops failing,
        the guard has stopped guarding.
        """
        before = (
            "const token = localStorage.getItem( 'lupin_access_token' );\n"
            "const resp  = await fetch( audioApiUrl, authInit );\n"
        )
        self.assertTrue( _TOKEN_READ.search( before ) )
        self.assertEqual( len( _bare_fetch_lines( before ) ), 1 )


class TestServedPagesUseTheWrapper( unittest.TestCase ):
    """The guard itself, run against every served page."""

    def test_no_NEW_page_reads_a_token_and_calls_bare_fetch( self ):
        offenders = []
        for name, text in _served_pages():
            if name in _KNOWN_UNWRAPPED:       continue
            if not _TOKEN_READ.search( text ): continue
            for lineno, line in _bare_fetch_lines( text ):
                offenders.append( f"{name}:{lineno}  {line[ :90 ]}" )

        self.assertEqual(
            offenders, [],
            "a served page reads an auth token AND calls bare fetch() — a 401 there is a "
            "dead end with no refresh and no retry, which is bug 38943485 recurring:\n  "
            + "\n  ".join( offenders )
        )

    def test_every_known_offender_is_STILL_an_offender( self ):
        """
        STALE-EXEMPTION GUARD. If a page on the known list gets fixed and stays listed,
        the list quietly becomes a place where a future defect could hide — the entry
        would pre-authorise the very shape it was recording. Fixing a page must
        therefore also remove it from the list, and this makes that mandatory.
        """
        pages = dict( _served_pages() )
        stale = []
        for name in _KNOWN_UNWRAPPED:
            text = pages.get( name )
            if text is None:                          continue   # page deleted — covered below
            if not _TOKEN_READ.search( text ) or not _bare_fetch_lines( text ):
                stale.append( name )
        self.assertEqual(
            stale, [],
            "these pages no longer match the defect and must be REMOVED from "
            f"_KNOWN_UNWRAPPED: {stale}"
        )

    def test_the_known_list_names_only_pages_that_exist( self ):
        """A listed page that was deleted or renamed leaves an entry protecting nothing."""
        names = { n for n, _ in _served_pages() }
        missing = sorted( set( _KNOWN_UNWRAPPED ) - names )
        self.assertEqual( missing, [], f"_KNOWN_UNWRAPPED names non-existent pages: {missing}" )

    def test_the_sweep_actually_examined_pages( self ):
        """
        Guards against the emptiest failure: a directory rename makes _served_pages()
        return nothing, every assertion above passes vacuously, and the suite reports
        health while checking zero files.
        """
        pages = _served_pages()
        self.assertGreater( len( pages ), 0, f"no served pages found under {_HTML_DIR}" )

    def test_at_least_one_page_actually_reads_a_token( self ):
        """
        The second vacuity guard. If no page matches the token pattern, the sweep is
        green because it examined nothing relevant — not because the pages are clean.
        """
        with_token = [ n for n, t in _served_pages() if _TOKEN_READ.search( t ) ]
        self.assertGreater( len( with_token ), 0,
                            "no served page reads an auth token — the guard is inspecting nothing" )


if __name__ == "__main__":
    unittest.main()
