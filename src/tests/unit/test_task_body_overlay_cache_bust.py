"""
Cache-bust tokens vouch for their asset's CONTENT — regression guards for bug f7486a9d
(task-body overlay served from a stale cache) and row 80f46993 (the date guard that failed both ways).

THE RULE lives in `lupin_app/asset_tokens.py` and is not restated here: a `?v=` token is the
first 12 hex characters of the SHA-256 of the asset's working-tree bytes. This file asks that
module's `verify()` and asserts on what it returns, so the hashing rule has one home.

WHAT THE OLD GUARD GOT WRONG (row 80f46993, measured twice):
  - BLIND: it compared the token's DAY to the asset's last-commit DAY, so a second edit to an
    asset on the same day stayed green (dda4fafe, 2026-09-27).
  - WHOLESALE RED: PR #22's squash merge (8420e8b0a, 2026-09-30) re-dated every file's last
    commit, so all 12 guarded assets read stale at once with no content change.
Both are impossible now: the check reads bytes, never git, so a re-date cannot move it and a
changed byte always does.

The symptom this family exists to prevent (f7486a9d): `task-list.css` gained the
`.task-body-overlay` modal rule but `notifications.html` kept a stale `?v=` token, the token
being part of the browser cache KEY, so returning browsers kept the OLD CSS and the overlay
dumped as an unstyled block at the page foot.

🔴 WHAT A STALE TOKEN COSTS (measured 2026-08-30, row a0a8ac19, then superseded): `/static`
answers a `?v=` URL `public, max-age=31536000, immutable` (lupin_app/versioned_static.py), so an
unmoved token means a warm browser keeps the OLD file for up to a year. The token is what makes
that window zero.

:7999-eligible — static, pure-Python, no server, no state mutation. The planted-defect proofs
run against a temp COPY of the static tree, never the live one.
"""

import os
import re
import shutil
import subprocess

import pytest

import cosa.utils.util as cu
from lupin_app import asset_tokens as at

ROOT           = cu.get_project_root()
STATIC         = at.project_static_root( ROOT )
LEGACY_CSS     = os.path.join( STATIC, "css", "task-list.css" )
MUX_CSS        = os.path.join( STATIC, "css", "multiplexer", "task-list.css" )
NOTIF_HTML     = os.path.join( STATIC, "html", "notifications.html" )
NOTIF_HTML_REL = "src/lupin_app/static/html/notifications.html"

# The versioned assets EXPECTED on the page — the non-vacuous-discovery anchor. If discovery
# silently matched nothing (markup reshaped, quoting changed) the parametrized tests would
# collect zero cases and pass VACUOUSLY; this set makes that impossible. Update it
# deliberately when the page's versioned-asset set genuinely changes.
EXPECTED_VERSIONED_ASSETS = frozenset( {
    "/static/css/notifications.css",
    "/static/css/broadcast-panel.css",
    "/static/css/task-list.css",
    "/static/css/epic-board.css",
    "/static/js/shared/task-list-query.js",
    "/static/js/shared/task-verbs.js",
    "/static/js/shared/task-lookup.js",
    "/static/js/shared/task-create.js",
    "/static/js/shared/task-request.js",
    "/static/js/shared/agent-select.js",
    "/static/js/shared/arg-interview.js",
    "/static/js/notifications.js",
    "/static/js/broadcast-panel.js",
} )

# Versioned dynamic imports inside authored JS: ( source, imported ).
EXPECTED_JS_IMPORTS = frozenset( {
    ( "src/lupin_app/static/js/notifications.js", "/static/js/ws-channel.js" ),
} )

# Third-party bundles this repo neither authors nor versions. EVERY NAME HERE IS A HOLE IN
# THE CORPUS, so the set is pinned by a test below.
_JS_CORPUS_EXCLUDED_DIRS = frozenset( { "vendor", "canvaskit" } )


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def _overlay_block( css_text ):
    """Return the body of the `.task-body-overlay { ... }` rule (without braces)."""
    return css_text.split( ".task-body-overlay {" )[ 1 ].split( "}" )[ 0 ]


def _shipped_js_sources():
    """
    Every shipped `.js` file under the static tree, repo-relative POSIX, sorted; disk, not index.

    Ensures:
        - walks the WHOLE static tree (not `static/js/` only — eleven files once hid outside it)
        - skips only `_JS_CORPUS_EXCLUDED_DIRS`
    """
    found = []
    for dirpath, dirnames, filenames in os.walk( STATIC ):
        dirnames[ : ] = [ d for d in dirnames if d not in _JS_CORPUS_EXCLUDED_DIRS ]
        for name in filenames:
            if name.endswith( ".js" ):
                found.append( os.path.relpath( os.path.join( dirpath, name ), ROOT ).replace( os.sep, "/" ) )
    return sorted( found )


# ONE discovery, from the module that owns the rule. Page links vs JS imports are split by source.
_REFS              = at.collect_refs( ROOT )
_DISCOVERED_ASSETS = [ ( url, token ) for src, url, token in _REFS if src == NOTIF_HTML_REL ]
_DISCOVERED_JS     = [ ( src, url, token ) for src, url, token in _REFS if src.endswith( ".js" ) ]
_DRIFT             = { ( src, url ): ( found, expected ) for src, url, found, expected in at.verify( ROOT ) }


# ---------------------------------------------------------------------------
# Both client sheets carry the centered-modal overlay rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "css_path", [ LEGACY_CSS, MUX_CSS ] )
def test_overlay_rule_is_fixed_position_modal( css_path ):
    """The 📄 overlay must be a fixed, full-viewport, centered modal in BOTH
    client sheets — not a static block that flows to the page foot (f7486a9d)."""
    block = _overlay_block( _read( css_path ) )
    assert "position: fixed" in block, \
        f"{os.path.basename( css_path )} .task-body-overlay must be position:fixed (not static)"
    assert "inset: 0" in block, \
        f"{os.path.basename( css_path )} .task-body-overlay must cover the viewport (inset:0)"
    assert "align-items: center" in block and "justify-content: center" in block, \
        f"{os.path.basename( css_path )} .task-body-overlay must center its content"


# ---------------------------------------------------------------------------
# notifications.html versions the legacy sheet; every token vouches for current bytes
# ---------------------------------------------------------------------------

def test_notifications_links_versioned_task_list_css():
    """The legacy client must cache-bust task-list.css with a `?v=` token."""
    assert ( "/static/css/task-list.css", ) == tuple(
        u for u, _t in _DISCOVERED_ASSETS if u == "/static/css/task-list.css" ), \
        "notifications.html must link task-list.css with a ?v= cache-bust token"


def test_versioned_asset_discovery_is_nonvacuous():
    """
    Discovery must find EXACTLY the expected versioned-asset set (row 14e2c5c7).

    Ensures:
        - a discovery that matched nothing fails loudly instead of greening the per-asset
          tests below by collecting zero cases
        - a NEW versioned asset joining the page must join this anchor
    """
    found = { url for url, _token in _DISCOVERED_ASSETS }
    assert found == EXPECTED_VERSIONED_ASSETS, (
        f"versioned-asset discovery drifted from the expected set.\n"
        f"  missing (expected, not found): {sorted( EXPECTED_VERSIONED_ASSETS - found )}\n"
        f"  unexpected (found, not listed): {sorted( found - EXPECTED_VERSIONED_ASSETS )}\n"
        f"If the page's versioned assets genuinely changed, update EXPECTED_VERSIONED_ASSETS."
    )


def test_js_import_discovery_is_nonvacuous():
    """The versioned JS imports found must be exactly the expected set (same purpose as above)."""
    found = { ( src, url ) for src, url, _t in _DISCOVERED_JS }
    assert found == EXPECTED_JS_IMPORTS, (
        f"versioned JS-import discovery drifted.\n"
        f"  missing: {sorted( EXPECTED_JS_IMPORTS - found )}\n"
        f"  unexpected: {sorted( found - EXPECTED_JS_IMPORTS )}"
    )


def _remedy( found, expected ):
    return (
        f"carries ?v={found} but the asset's current bytes hash to {expected} "
        f"({at.ALGORITHM}, first {at.TOKEN_HEX_LEN} hex). Run: python -m lupin_app.asset_tokens --stamp"
    )


@pytest.mark.parametrize( "static_url,token", _DISCOVERED_ASSETS, ids=[ u for u, _t in _DISCOVERED_ASSETS ] )
def test_versioned_asset_token_vouches_for_current_content( static_url, token ):
    """
    Each page link's `?v=` token must equal the hash of that asset's CURRENT bytes.

    Ensures:
        - fails by name on a same-day edit (bytes changed, token did not) — the case the
          old date comparison could not see
        - passes after a squash/rebase that re-dates files without changing them
        - asks `asset_tokens.verify()`; the hashing rule is not restated here
    """
    found, expected = _DRIFT.get( ( NOTIF_HTML_REL, static_url ), ( token, token ) )
    assert found == expected, f"notifications.html links {static_url} {_remedy( found, expected )}"


@pytest.mark.parametrize( "source_rel,static_url,token", _DISCOVERED_JS,
                          ids=[ f"{s.rsplit( '/', 1 )[ -1 ]}->{u}" for s, u, _t in _DISCOVERED_JS ] )
def test_js_import_token_vouches_for_current_content( source_rel, static_url, token ):
    """A dynamic import's token must equal the hash of the imported module's current bytes."""
    found, expected = _DRIFT.get( ( source_rel, static_url ), ( token, token ) )
    assert found == expected, f"{source_rel} imports {static_url} {_remedy( found, expected )}"


def test_the_live_tree_has_no_token_drift_at_all():
    """The whole-tree verdict, so a reference `_DRIFT` keys differently from the cases still reddens."""
    assert at.verify( ROOT ) == [], f"token drift: {at.verify( ROOT )}"


# ---------------------------------------------------------------------------
# PLANTED-DEFECT PROOFS, on a temp copy of the static tree (never the live one)
# ---------------------------------------------------------------------------

@pytest.fixture
def tree( tmp_path ):
    """A private copy of the static tree, stamped clean."""
    dest = tmp_path / "src" / "lupin_app"
    dest.mkdir( parents=True )
    shutil.copytree( STATIC, dest / "static",
                     ignore=shutil.ignore_patterns( *at.EXCLUDED_DIRS, "dist", "*.map" ) )
    at.stamp( str( tmp_path ) )
    assert at.verify( str( tmp_path ) ) == [], "fixture must start clean"
    return str( tmp_path )


def _asset( tree, url ):
    return os.path.join( at.project_static_root( tree ), url[ len( "/static/" ) : ] )


def test_a_same_day_edit_reddens_exactly_that_asset( tree ):
    """THE BLIND SPOT: change bytes, leave the token. The old date test stayed green here."""
    with open( _asset( tree, "/static/js/shared/task-verbs.js" ), "a", encoding="utf-8" ) as fh:
        fh.write( "\n// a second edit, same day\n" )
    bad = at.verify( tree )
    assert [ ( s.rsplit( "/", 1 )[ -1 ], u ) for s, u, _f, _e in bad ] == \
        [ ( "notifications.html", "/static/js/shared/task-verbs.js" ) ]


def test_a_redate_with_no_content_change_stays_green( tree ):
    """THE WHOLESALE FAILURE: a squash re-dates every file. Bytes unchanged ⇒ nothing moves."""
    for dirpath, _d, names in os.walk( at.project_static_root( tree ) ):
        for name in names:
            os.utime( os.path.join( dirpath, name ), ( 1, 1 ) )
    assert at.verify( tree ) == []


def test_restamping_after_an_edit_restores_green_and_moves_only_that_token( tree ):
    before = { ( s, u ): t for s, u, t in at.collect_refs( tree ) }
    with open( _asset( tree, "/static/css/epic-board.css" ), "a", encoding="utf-8" ) as fh:
        fh.write( "\n/* edit */\n" )
    assert at.stamp( tree ) == [ NOTIF_HTML_REL ]
    after = { ( s, u ): t for s, u, t in at.collect_refs( tree ) }
    assert at.verify( tree ) == []
    moved = sorted( k for k in before if before[ k ] != after[ k ] )
    assert moved == [ ( NOTIF_HTML_REL, "/static/css/epic-board.css" ) ]


def test_editing_an_imported_module_cascades_to_its_importer_and_the_page( tree ):
    """ws-channel.js ← notifications.js ← notifications.html: one edit moves two tokens."""
    before = { ( s, u ): t for s, u, t in at.collect_refs( tree ) }
    with open( _asset( tree, "/static/js/ws-channel.js" ), "a", encoding="utf-8" ) as fh:
        fh.write( "\n// edit\n" )
    changed = at.stamp( tree )
    after = { ( s, u ): t for s, u, t in at.collect_refs( tree ) }
    assert changed == sorted( [ NOTIF_HTML_REL, "src/lupin_app/static/js/notifications.js" ] )
    moved = sorted( k for k in before if before[ k ] != after[ k ] )
    assert ( "src/lupin_app/static/js/notifications.js", "/static/js/ws-channel.js" ) in moved
    assert ( NOTIF_HTML_REL, "/static/js/notifications.js" ) in moved
    assert at.verify( tree ) == []


def test_an_old_date_token_is_reported_as_drift_not_ignored( tree ):
    page = os.path.join( tree, NOTIF_HTML_REL )
    with open( page, encoding="utf-8" ) as fh:
        text = fh.read()
    url  = "/static/css/task-list.css"
    good = dict( ( u, t ) for _s, u, t in at.collect_refs( tree ) )[ url ]
    with open( page, "w", encoding="utf-8" ) as fh:
        fh.write( text.replace( f"{url}?v={good}", f"{url}?v=20260930a" ) )
    bad = at.verify( tree )
    assert [ ( u, f ) for _s, u, f, _e in bad ] == [ ( url, "20260930a" ) ]


def test_a_reference_to_a_missing_asset_is_reported_and_cannot_be_stamped( tree ):
    page = os.path.join( tree, NOTIF_HTML_REL )
    with open( page, "a", encoding="utf-8" ) as fh:
        fh.write( '\n<script src="/static/js/no-such-file.js?v=abc"></script>\n' )
    assert ( NOTIF_HTML_REL, "/static/js/no-such-file.js", "abc", None ) in at.verify( tree )
    with pytest.raises( ValueError, match="missing asset" ):
        at.stamp( tree )


def test_a_reference_cycle_is_reported_not_looped( tmp_path ):
    js = tmp_path / "src" / "lupin_app" / "static" / "js"
    js.mkdir( parents=True )
    ( js / "a.js" ).write_text( 'import( "/static/js/b.js?v=x" );\n' )
    ( js / "b.js" ).write_text( 'import( "/static/js/a.js?v=x" );\n' )
    with pytest.raises( ValueError, match="cycle" ):
        at.stamp( str( tmp_path ) )


def test_the_token_rule_is_sha256_first_twelve_hex():
    """Pinned to a literal: sha256(b"abc") begins ba7816bf8f01cfea414140de…"""
    assert ( at.ALGORITHM, at.TOKEN_HEX_LEN ) == ( "sha256", 12 )
    assert at.content_token( b"abc" ) == "ba7816bf8f01"
    assert at.TOKEN_RE.fullmatch( at.content_token( b"" ) )


def test_cli_check_and_stamp( tree, capsys ):
    assert at.main( [], tree ) == 0
    with open( _asset( tree, "/static/css/task-list.css" ), "a", encoding="utf-8" ) as fh:
        fh.write( "\n/* x */\n" )
    assert at.main( [], tree ) == 1
    out = capsys.readouterr().out
    assert "DRIFT" in out and "--stamp" in out
    assert at.main( [ "--stamp" ], tree ) == 0
    assert at.main( [], tree ) == 0


def test_cli_stamp_reports_failure_with_exit_2( tmp_path, capsys ):
    js = tmp_path / "src" / "lupin_app" / "static" / "js"
    js.mkdir( parents=True )
    ( js / "a.js" ).write_text( 'import( "/static/js/gone.js?v=x" );\n' )
    assert at.main( [ "--stamp" ], str( tmp_path ) ) == 2
    assert "cannot stamp" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# THE CORPUS ITSELF — enumerated, reported, and asserted
# ---------------------------------------------------------------------------
#
# 🔴 THIS WAS A POPULATION DEFECT, NOT A LOGIC DEFECT (Mr Radio 🦉's framing, and it
# is the sharper one). The page guards above were never WRONG. They were pointed at
# a corpus of one file, and they answered correctly about it for six weeks while
# ws-channel.js rotted just outside the frame.
#
# ⇒ A GUARD THAT SILENTLY SCANS ONE FILE AND A GUARD THAT SCANS FORTY-TWO LOOK
# IDENTICAL WHEN BOTH ARE GREEN. Nothing in a passing run says how much was looked
# at, so a corpus that quietly shrinks — a moved directory, a walk that stops
# matching, an exclusion that grows teeth — becomes a guard that passes forever
# while watching nothing.
#
# 🔴 AND THE FIRST CUT OF THIS BLOCK COULD NOT SEE THE EXCLUSION CASE, because it
# derived BOTH SIDES of its comparison from `_JS_CORPUS_EXCLUDED_DIRS`. Adding
# "shared" to that set shrank the walk AND the expected list together, so they
# agreed perfectly and the guard stayed green while eight files left the frame.
# Measured, not reasoned: the break was run and it passed. ⇒ THE EXPECTED SIDE OF
# A COVERAGE COMPARISON MUST NOT BE DERIVED FROM THE THING BEING CHECKED. The
# exclusion set is PINNED by its own test instead, so widening it is a deliberate
# edit in two places rather than a quiet one in a single line.

def _tracked( pathspec ):
    """
    Repo-relative paths git tracks under `pathspec`, sorted.

    Requires:
        - pathspec is a git pathspec

    Ensures:
        - returns POSIX repo-relative paths

    ⚠️ A git pathspec is NOT shell globstar: `dir/**/*.md` requires an intervening
    directory and silently drops files sitting directly in `dir`. Callers here pass
    a plain directory prefix for that reason.
    """
    out = subprocess.run(
        [ "git", "ls-files", "--", pathspec ],
        cwd=cu.get_project_root(), capture_output=True, text=True, check=True
    ).stdout.split()
    return sorted( out )


def _html_corpus():
    """
    EVERY tracked `.html` file under `src/`, repo-relative, sorted.

    Ensures:
        - the same population the defect-finding measurement used, so the figure
          asserted here and the figure in that measurement are the same figure

    ⚠️ 42 AND 32 ARE BOTH CORRECT — reconciled, not adjudicated. 42 is every tracked
    `.html` under `src/`; 32 is the subset in `static/html/` plus `templates/`. The
    ten between them are `static/lupin-mobile-test/`, four `src/rnd/` reports, two
    `src/templates/` and four `src/tests/` fixtures. This guard takes the WIDER one:
    a page that starts versioning assets is unwatched wherever it lives, and the
    narrower corpus is a place for it to hide. Same for JavaScript — 27 tracked
    under `static/` outside the excluded bundles, against the 16 a `static/js/`-only
    walk saw, and those eleven were the finding.
    """
    return sorted( h for h in _tracked( "src" ) if h.endswith( ".html" ) )


def test_the_js_corpus_exclusions_are_pinned():
    """
    The excluded-directory set is pinned, because it is the one input that can
    shrink the corpus without any comparison noticing.

    Ensures:
        - fails when a directory is added to `_JS_CORPUS_EXCLUDED_DIRS`

    This is a POLICY pin, not a moving baseline: it changes when someone decides a
    directory is third-party, which is rare and deliberate — unlike the per-slice
    token baseline this file exists to replace, which had to be hand-bumped every
    time anyone shipped and was therefore the defect it was written to catch.
    """
    assert _JS_CORPUS_EXCLUDED_DIRS == frozenset( { "vendor", "canvaskit" } ), (
        f"the JS corpus exclusions changed to {sorted( _JS_CORPUS_EXCLUDED_DIRS )}.\n"
        f"Every excluded directory is a hole these guards cannot see into. Widen it "
        f"only for a genuinely third-party bundle this repo does not author, and say "
        f"so here — a corpus that narrows quietly is a guard that goes green by "
        f"looking away."
    )


def test_the_guarded_corpus_is_enumerated_and_nonempty():
    """
    The corpus these guards scan must be enumerated, non-empty, and no smaller than
    what git tracks — and the counts must be visible in the run's output.

    Requires:
        - the repo is a git checkout

    Ensures:
        - fails when either corpus is empty (a guard watching nothing)
        - fails when the JS walk stops covering a tracked file outside the pinned
          exclusions — the expected side comes from git, NOT from the exclusion set
        - fails when a file already known to carry tokens is outside the corpus
          (the positive control: a search that cannot return a hit cannot be trusted
          when it returns a miss)
        - prints both counts, so a green run reports its own scale
    """
    html_corpus = _html_corpus()
    js_corpus   = _shipped_js_sources()

    # THE EXPECTED SIDE IS GIT'S, NOT THE WALK'S. Deriving it from
    # _JS_CORPUS_EXCLUDED_DIRS is what made the first cut of this test blind.
    tracked_js  = [ j for j in _tracked( "src/lupin_app/static" ) if j.endswith( ".js" ) ]
    excluded    = [ j for j in tracked_js if "/vendor/" in j or "/canvaskit/" in j ]
    expected_js = [ j for j in tracked_js if j not in set( excluded ) ]

    print( f"\n[cache-bust corpus] html={len( html_corpus )} scanned  "
           f"js={len( js_corpus )} scanned of {len( tracked_js )} tracked "
           f"({len( excluded )} excluded: {sorted( _JS_CORPUS_EXCLUDED_DIRS )})  "
           f"versioned-page-links={len( _DISCOVERED_ASSETS )}  "
           f"versioned-js-imports={len( _DISCOVERED_JS )}" )

    assert html_corpus, "the HTML corpus is EMPTY — these guards would pass forever watching nothing"
    assert js_corpus,   "the JS corpus is EMPTY — the import guards would pass forever watching nothing"

    missing = sorted( set( expected_js ) - set( js_corpus ) )
    assert not missing, (
        f"the JS walk no longer covers {len( missing )} file(s) git tracks outside the "
        f"pinned exclusions: {missing[ :5 ]}. A corpus that narrows quietly is a guard "
        f"that goes green by looking away."
    )

    assert NOTIF_HTML_REL in html_corpus, \
        f"{NOTIF_HTML_REL} is OUTSIDE the enumerated HTML corpus — the page guards are scanning something else"
    for source_rel, _url in EXPECTED_JS_IMPORTS:
        assert source_rel in js_corpus, \
            f"{source_rel} carries a versioned import but is OUTSIDE the enumerated JS corpus"


def test_exactly_the_expected_pages_carry_cache_bust_tokens():
    """
    Across the WHOLE tracked HTML corpus, exactly the expected pages carry `?v=`
    tokens.

    Requires:
        - the repo is a git checkout

    Ensures:
        - fails when a NEW page starts versioning assets, because every page guard
          above reads one file and would never look at it
        - fails when the known page STOPS carrying tokens (the search going blind)

    This is the assertion form of the measurement that found the defect. Written as
    a comment it informs; written here it holds.
    """
    tokened = sorted(
        h for h in _html_corpus()
        if at.REF_RE.search( _read( os.path.join( cu.get_project_root(), h ) ) )
    )
    assert tokened == [ NOTIF_HTML_REL ], (
        f"the set of token-carrying pages changed: {tokened}\n"
        f"Every page guard in this file reads ONLY {NOTIF_HTML_REL}. A second page "
        f"versioning its assets is unwatched the moment it appears — which is exactly "
        f"how a versioned reference outside the scanned corpus goes stale unnoticed."
    )


# ---------------------------------------------------------------------------
# THE REFERENCE STYLES NO GUARD IN THIS FILE CAN FOLLOW
# ---------------------------------------------------------------------------
#
# Everything above follows a `?v=` token that is a LITERAL in the source — an `href`
# or `src` attribute, or a JS `import( "…?v=…" )`. Two other ways exist to version an
# asset, and a guard that reads literals cannot follow either:
#
#   (a) a CSS `@import url( "other.css?v=…" )` — a stylesheet pulling a stylesheet
#   (b) a token BUILT at runtime — `"…?v=" + VERSION`, or `` `…?v=${VERSION}` ``
#
# Measured 2026-09-02, and BOTH ARE EMPTY TODAY:
#
#   CSS `@import`  0 real, across 31 tracked .css files. There is exactly one textual
#                  hit and it is a COMMENT — proxy-ratify.css:5 says badge classes are
#                  "shared with proxy-dashboard.css via @import" and the file contains
#                  no @import at all. A comment describing an implementation that does
#                  not exist, which is the same trap `strip_js_comments` was written
#                  for one file over.
#   built tokens   0, across the 86 client .js/.css/.html files we author (the
#                  vendored flutter and canvaskit bundles excluded — they carry
#                  `flutter_service_worker.js?v=${i}`, which is theirs, not ours).
#
# 🔴 SO THIS GUARD EXISTS FOR THE DAY THE POPULATION STOPS BEING EMPTY, and its whole
# risk is that a zero from a broken search is indistinguishable from a zero from a
# clean corpus. The control is therefore INSIDE the assertion path rather than in a
# comment: the same regexes are run against planted samples on every run, so a regex
# that stops matching fails LOUDLY instead of certifying an empty result forever.
#
# ⚠️ A THIRD MECHANISM EXISTS AND IS BETTER THAN ALL OF THIS — see
# multiplexer.html, which resolves a CONTENT-HASHED bundle name from a build manifest
# at runtime. There is no token to forget because the hash IS the content. It is not
# guarded here and does not need to be; it is the direction notifications.html should
# eventually move, and it is named here so the next reader finds it.

# Both forms carry a `?v=` that no literal-scanning guard in this file can resolve.
UNFOLLOWABLE_REFERENCE_FORMS = (
    ( "css-@import",   re.compile( r"@import[^;]*\?v=" ) ),
    ( "built-token",   re.compile( r"""\?v="\s*\+|\?v=\$\{|\+\s*"\?v=""" ) ),
)

# Third-party bundles we neither author nor version. Same rule as the JS corpus above:
# every name is a hole, so the list stays tiny and its effect is reported.
_UNFOLLOWABLE_SCAN_EXCLUDED = ( "/vendor/", "/canvaskit/", "/lupin-mobile-test/" )


def _authored_client_files():
    """
    The client files THIS repo authors: tracked .js/.css/.html under static, minus the
    vendored bundles.

    Ensures:
        - returns POSIX repo-relative paths, sorted
        - git-derived, so the expected side of the coverage check below never comes
          from the same walk it is checking
    """
    return sorted(
        f for f in _tracked( "src/lupin_app/static" )
        if f.endswith( ( ".js", ".css", ".html" ) )
        and not any( x in f for x in _UNFOLLOWABLE_SCAN_EXCLUDED )
    )


def test_the_unfollowable_reference_regexes_can_find_a_positive():
    """
    THE CONTROL THAT MAKES THE ZERO BELOW MEAN SOMETHING.

    Ensures:
        - each regex matches a planted sample of the form it is meant to catch
        - each regex does NOT match ordinary versioned markup, so it is not matching
          everything and calling that success

    An absence claim is the one finding that looks the same whether the work was done
    or not. Running the same regexes against known positives on every run is the
    difference between "nothing is there" and "nothing was looked at".
    """
    positives = {
        "css-@import" : '@import url( "/static/css/other.css?v=20260101a" );',
        "built-token" : 'const u = "/static/js/a.js?v=" + VER; const t = `/x.js?v=${VER}`;',
    }
    negative = '<link href="/static/css/task-list.css?v=20260902e">'

    for name, pattern in UNFOLLOWABLE_REFERENCE_FORMS:
        assert pattern.search( positives[ name ] ), \
            f"{name} regex no longer matches its own planted positive — the zero below would be meaningless"
        assert not pattern.search( negative ), \
            f"{name} regex matches an ordinary literal ?v= link; it would report every page as unfollowable"


def test_no_authored_client_file_versions_an_asset_in_an_unfollowable_way():
    """
    No client file we author may reference a versioned asset in a form the guards
    above cannot follow.

    Requires:
        - the repo is a git checkout

    Ensures:
        - fails when a CSS `@import` or a runtime-built `?v=` token appears in our own
          client code, naming the file and the form
        - prints the corpus size, so a green run reports its own scale

    Neither form is banned in principle — a CSS `@import` is legitimate markup. What
    is banned is introducing one WITHOUT extending the guards, because a versioned
    reference that no guard can follow is exactly how `ws-channel.js` sat six weeks
    stale with a clean suite.
    """
    corpus = _authored_client_files()
    assert corpus, "the authored-client corpus is EMPTY — this guard would pass forever watching nothing"

    hits = []
    for rel in corpus:
        try:
            text = _read( os.path.join( cu.get_project_root(), rel ) )
        except OSError:
            continue
        for name, pattern in UNFOLLOWABLE_REFERENCE_FORMS:
            for match in pattern.finditer( text ):
                hits.append( ( rel, name, match.group( 0 )[ :60 ] ) )

    print( f"\n[unfollowable-reference scan] authored client files={len( corpus )}  "
           f"excluded={list( _UNFOLLOWABLE_SCAN_EXCLUDED )}  hits={len( hits )}" )

    assert not hits, (
        "a versioned asset is referenced in a form no guard in this file can follow:\n"
        + "\n".join( f"  {rel}  [{name}]  {snippet}" for rel, name, snippet in hits )
        + "\nEither use a literal `?v=` attribute/import (which the guards above follow), "
          "or extend those guards to this form. A reference nothing watches goes stale silently."
    )
