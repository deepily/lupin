"""
Regression guard for bug f7486a9d — task-detail 📄 body-overlay cache-staleness.

Bug: src/lupin_app/static/css/task-list.css gained the `.task-body-overlay`
modal rule (position:fixed; inset:0; centered) in commit 59e381af (2026-06-29),
but notifications.html kept linking it with a STALE `?v=20260617a` cache-bust
token (last bumped 2026-06-19, commit 53fef419). Because the `?v=` query string
is part of the browser cache KEY, returning browsers kept serving the OLD cached
CSS — which lacked the overlay rule — so the overlay div fell back to
position:static and dumped the task body as an unstyled block at the page foot
instead of opening a centered modal popup.

This is a STATIC / pure-Python guard (:7999-eligible — no server, no state
mutation). It catches the ROOT-CAUSE CLASS: a manually-maintained cache-bust
token that drifts out of sync with the CSS file it versions. The symptom-level
computed-style assertion (click 📄 → getComputedStyle(overlay).position ==
"fixed", centered, dismiss-on-backdrop/Esc, in a real browser) lives in the
e2e_ui Playwright suites — this file does not duplicate it.

Verifies:
  - Both client stylesheets (legacy task-list.css + multiplexer/task-list.css)
    actually carry the `.task-body-overlay { position: fixed }` modal rule.
  - notifications.html links task-list.css with a well-formed `?v=YYYYMMDD`
    cache-bust token (the versioned legacy client must cache-bust).
  - That token is NOT stale relative to the CSS file's most-recent git commit —
    i.e. whenever task-list.css changes, the token must be bumped to >= the
    file's commit date. This assertion FAILS on the exact f7486a9d shape
    (token 20260617 < css commit 20260629).

Parity note (verified for f7486a9d): multiplexer.html links the mux sheet
UNVERSIONED, so its cache key is the bare URL. It is intentionally left
token-free — adding a manual token would re-introduce exactly the drift this
guard exists to catch — and the freshness assertion is therefore scoped to the
versioned legacy link only.

🔴 DEPLOYMENT NOTE — WHAT A STALE TOKEN ACTUALLY COSTS (measured 2026-08-30, row
a0a8ac19; this paragraph CORRECTS an overstatement that stood here and in the
failure message). Both pages are served by the SAME bare `StaticFiles` mount,
which sends NO Cache-Control and NO Expires — only a content-based ETag and a
Last-Modified. Probed live rather than read off the code:

    cache-control:  (absent)
    expires:        (absent)
    etag:           "f9c63b1d1e6806360c6e8fbceacbaa99"
    last-modified:  Sat, 29 Aug 2026 22:19:11 GMT
    If-None-Match → 304

With no Cache-Control a browser falls back to HEURISTIC freshness (roughly a
tenth of the cached copy's age). So a stale token does NOT strand a user
permanently: the entry goes stale on its own within hours, the browser
revalidates, the content-based ETag no longer matches, and it gets the new file.
Nothing in docker/, src/terraform/ or docker-compose.yml adds cache headers in
front of it.

⇒ The earlier framing here — that the mux "does NOT share the legacy's
permanent-staleness defect" — was wrong in BOTH halves: there is no permanent
defect to share, and the legacy path self-heals by the same mechanism the mux
does. Neither is permanent, because permanence needs a long `max-age` or
`immutable`, which this deployment does not ship.

⚠️ THIS DOES NOT WEAKEN THE GUARD, and the assertion below is unchanged. A FRESH
token is a NEW cache key, so the new asset is fetched IMMEDIATELY — window zero.
A STALE token reuses the old key and leaves a heuristic-freshness window during
which a warm browser runs old front-end code against a new server. The token's
value is eliminating that window, not preventing a permanence that was never
there. It also becomes load-bearing the moment anyone puts a CDN or a
`max-age` in front of /static — at which point the overstatement above would
become true, and this guard is what keeps the tokens honest until then.

Stating the cost accurately matters for triage: five reds under the old wording
read as a live user-facing incident, and under the correct wording they are
hygiene. A guard that overstates its own finding gets discounted the first time
somebody checks it.
"""

import os
import re
import subprocess

import pytest

import cosa.utils.util as cu

STATIC        = os.path.join( cu.get_project_root(), "src", "lupin_app", "static" )
LEGACY_CSS    = os.path.join( STATIC, "css", "task-list.css" )
MUX_CSS       = os.path.join( STATIC, "css", "multiplexer", "task-list.css" )
NOTIF_HTML    = os.path.join( STATIC, "html", "notifications.html" )
NOTIF_HTML_REL = "src/lupin_app/static/html/notifications.html"

# the versioned <link> in notifications.html: /static/css/task-list.css?v=YYYYMMDD[suffix]
TOKEN_LINK_RE = re.compile( r"/static/css/task-list\.css\?v=(\d{8})([a-z]?)" )

# GENERALIZED guard (row 14e2c5c7): every versioned asset the page links, not just
# task-list.css. A `?v=` token is part of the browser cache KEY, so ANY tokened
# asset whose token date drifts behind the file's last commit lets a warm browser go
# on serving the old cached copy for as long as its cache entry stays fresh (bounded,
# not forever — see the deployment note above). task-list.css was the only guarded one of SIX; bumping
# just it would green the alarm while five siblings stayed broken (the failure mode
# the row names). This regex discovers every `href`/`src` under /static/ carrying a
# ?v=YYYYMMDD[suffix] token, so asset seven is covered the day it is linked.
VERSIONED_ASSET_RE = re.compile( r'(?:href|src)="(/static/[^"?]+)\?v=(\d{8})([a-z]?)"' )

# The versioned assets EXPECTED on the page — the non-vacuous-discovery anchor. If
# the regex silently matches nothing (markup reshaped, quoting changed), the
# parametrized freshness test would collect zero cases and pass VACUOUSLY; this set
# makes that impossible by asserting discovery found exactly these. Update it
# deliberately when the page's versioned-asset set genuinely changes.
#
# 2026-08-24 (row aa6afbd8): grew six -> eight. agent-select.js and arg-interview.js
# had been linked on the page with ?v= tokens but were never added here, so this
# anchor was red — and that is the anchor working as designed: a new versioned
# asset joining the page must also join the freshness guard, or it rots unwatched.
# Bumping the stale tokens alone would NOT have cleared it.
EXPECTED_VERSIONED_ASSETS = frozenset( {
    "/static/css/notifications.css",
    "/static/css/broadcast-panel.css",
    "/static/css/task-list.css",
    "/static/css/epic-board.css",
    "/static/js/shared/task-list-query.js",
    "/static/js/shared/agent-select.js",
    "/static/js/shared/arg-interview.js",
    "/static/js/notifications.js",
    "/static/js/broadcast-panel.js",
} )


def _static_url_to_repo_rel( static_url ):
    """
    Map a `/static/<rel>` asset URL to its repo-relative source path.

    Requires:
        - static_url starts with "/static/"

    Ensures:
        - returns "src/lupin_app/static/<rel>" (POSIX repo-relative — what git wants)
    """
    assert static_url.startswith( "/static/" ), static_url
    return "src/lupin_app/static/" + static_url[ len( "/static/" ) : ]


def _versioned_assets( html_text ):
    """
    Discover every versioned asset the page links: [ ( static_url, token_date ), ... ].

    Ensures:
        - one entry per `href`/`src="/static/...?v=YYYYMMDD[suffix]"` occurrence
        - token_date is the 8-digit YYYYMMDD (suffix ignored — the guard compares dates)
        - input order preserved
    """
    return [ ( m.group( 1 ), m.group( 2 ) ) for m in VERSIONED_ASSET_RE.finditer( html_text ) ]


def _versioned_assets_full( html_text ):
    """
    Discover every versioned asset with its FULL token: [ ( static_url, "YYYYMMDDs" ), ... ].

    Ensures:
        - identical discovery to `_versioned_assets`, but the token retains its
          single-letter suffix

    🔴 WHY A SECOND DISCOVERY EXISTS, and it is not duplication. `_versioned_assets`
    deliberately DROPS the suffix, because the staleness test above compares dates.
    The two tests below compare tokens for IDENTITY, and a suffix-stripped token
    compares "20260902" against "20260902j" — unequal on every run, so the
    assertion can never fail and the guard is blind in the flattering direction.
    That is not hypothetical: both tests were first written over `_versioned_assets`
    and went GREEN against a deliberately broken asset. The suffix is the entire
    within-day signal; a test that asserts identity must read it.
    """
    return [ ( m.group( 1 ), m.group( 2 ) + m.group( 3 ) )
             for m in VERSIONED_ASSET_RE.finditer( html_text ) ]


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def _overlay_block( css_text ):
    """Return the body of the `.task-body-overlay { ... }` rule (without braces)."""
    return css_text.split( ".task-body-overlay {" )[ 1 ].split( "}" )[ 0 ]


def _git_last_commit_date( repo_rel_path ):
    """
    YYYYMMDD of the most recent commit that touched repo_rel_path — the repo's
    ground-truth 'mtime' for the file (worktree-safe; independent of checkout
    filesystem mtimes).

    Requires:
        - repo_rel_path is tracked by git under the project root

    Ensures:
        - returns an 8-digit YYYYMMDD string
    """
    out = subprocess.run(
        [ "git", "log", "-1", "--format=%cd", "--date=format:%Y%m%d", "--", repo_rel_path ],
        cwd=cu.get_project_root(), capture_output=True, text=True, check=True
    ).stdout.strip()
    return out


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
# notifications.html versions the legacy sheet + the token is not stale
# ---------------------------------------------------------------------------

def test_notifications_links_versioned_task_list_css():
    """The legacy client must cache-bust task-list.css with a ?v=YYYYMMDD token."""
    match = TOKEN_LINK_RE.search( _read( NOTIF_HTML ) )
    assert match, \
        "notifications.html must link task-list.css with a ?v=YYYYMMDD[suffix] cache-bust token"


# Discovered ONCE at collection time (after _read is defined) so the freshness test
# can parametrize over it.
_DISCOVERED_ASSETS = _versioned_assets( _read( NOTIF_HTML ) )
_DISCOVERED_FULL   = _versioned_assets_full( _read( NOTIF_HTML ) )


def test_versioned_asset_discovery_is_nonvacuous():
    """
    Discovery must find EXACTLY the expected versioned-asset set (row 14e2c5c7).

    The freshness test below parametrizes over `_DISCOVERED_ASSETS`; if the regex
    matched nothing (markup reshaped, quoting changed), that test would collect
    zero cases and pass VACUOUSLY — a green that certifies nothing. This anchor
    fails loudly instead, and also catches a NEW versioned asset being added
    without anyone extending the expected set (extend it deliberately).
    """
    found = { url for url, _date in _DISCOVERED_ASSETS }
    assert found == EXPECTED_VERSIONED_ASSETS, (
        f"versioned-asset discovery drifted from the expected set.\n"
        f"  missing (expected, not found): {sorted( EXPECTED_VERSIONED_ASSETS - found )}\n"
        f"  unexpected (found, not listed): {sorted( found - EXPECTED_VERSIONED_ASSETS )}\n"
        f"If the page's versioned assets genuinely changed, update "
        f"EXPECTED_VERSIONED_ASSETS; a new asset must join the freshness guard."
    )


@pytest.mark.parametrize( "static_url,token_date",
                          _DISCOVERED_ASSETS,
                          ids=[ url for url, _d in _DISCOVERED_ASSETS ] )
def test_versioned_asset_token_not_stale( static_url, token_date ):
    """
    EVERY versioned asset's ?v= token date must be >= that file's last commit date.

    The generalized f7486a9d recurrence guard (row 14e2c5c7): a `?v=` token is part
    of the browser cache KEY, so any asset whose token drifts behind its file's
    last commit lets a returning browser go on serving the OLD cached copy — a
    rendering fault that looks like a bug on stage and cannot be diagnosed live.
    ⚠️ The window is BOUNDED, not permanent — see the deployment note in the module
    docstring; the token's job is to make it ZERO. Naming
    task-list.css alone let five siblings rot unguarded; this asserts the property
    over the whole set, so bumping one token can never green the page while another
    stays stale.
    """
    repo_rel      = _static_url_to_repo_rel( static_url )
    commit_date   = _git_last_commit_date( repo_rel )
    assert re.fullmatch( r"\d{8}", commit_date ), \
        f"could not resolve {repo_rel} git commit date (got {commit_date!r}); is it tracked?"

    assert token_date >= commit_date, (
        f"notifications.html links {static_url}?v={token_date}, STALE vs the file's "
        f"last commit {commit_date} — bump the ?v= token to >= {commit_date} (e.g. "
        f"?v={commit_date}a) so returning browsers refetch it IMMEDIATELY. A `?v=` "
        f"token is part of the cache key: a fresh one is a new key, so the new asset is "
        f"fetched at once; a stale one reuses the old key and lets a warm browser serve "
        f"the OLD asset until its cache entry goes stale on its own."
    )


# ---------------------------------------------------------------------------
# The token must have FOLLOWED the asset's last change (commit-ordered, derived)
# ---------------------------------------------------------------------------
#
# 🔴 WHY THE DATE COMPARISON ABOVE IS NOT ENOUGH, AND WHAT IT LET THROUGH.
# `test_versioned_asset_token_not_stale` compares an 8-digit DAY against a commit
# DAY. This fleet lands several slices a day: on 2026-09-02 alone, notifications.js
# was changed by 8e0b71af, 2f99adba, 0a53561d, fe8642c7, a1e46d62, b38d2843,
# cd2ea523 and 9e27a64f. Every one of those has commit date 20260902, so a token
# reading `20260902g` satisfies `token_date >= commit_date` no matter how many
# same-day slices shipped behind it. The guard is blind for the whole day — which
# is the entire window in which the asset is actually being edited.
#
# ⚠️ notifications.js was never MISSING from the guarded set — it is in
# EXPECTED_VERSIONED_ASSETS above. It was watched by an assertion that could not
# resolve the timescale on which it changes. A guarded asset and a guarded property
# are different things, and only the second one catches anything.
#
# THE DERIVED PROPERTY, with no literal token anywhere in it: let A be the most
# recent commit that touched the asset. The token the page carries today must
# DIFFER from the token it carried at A's parent. If it is the same string, the
# token did not move when the asset moved — the returning browser's cache key is
# unchanged and it goes on serving the old copy. This is commit-ordered rather than
# date-compared, so it sees inside a day, and it needs no hand-maintained baseline:
# the value it refuses is read out of git and out of the shipped page on every run.

def _git_last_commit_sha( repo_rel_path ):
    """
    Full sha of the most recent commit that touched repo_rel_path.

    Requires:
        - repo_rel_path is tracked by git under the project root

    Ensures:
        - returns a 40-character sha, or "" when the path has no history
    """
    return subprocess.run(
        [ "git", "log", "-1", "--format=%H", "--", repo_rel_path ],
        cwd=cu.get_project_root(), capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_first_parent( sha ):
    """
    First parent of `sha`, or None when `sha` is a root commit.

    Requires:
        - sha names a commit in this repository

    Ensures:
        - returns a 40-character sha, or None on a root commit (never raises)
    """
    done = subprocess.run(
        [ "git", "rev-parse", "--verify", "--quiet", f"{sha}^1" ],
        cwd=cu.get_project_root(), capture_output=True, text=True
    )
    parent = done.stdout.strip()
    return parent if parent else None


def _token_at_rev( rev, static_url, source_rel=NOTIF_HTML_REL ):
    """
    The `?v=` token that `source_rel` carried for `static_url` at `rev`.

    Requires:
        - rev names a commit, or "HEAD"
        - static_url is a "/static/..." asset URL
        - source_rel is the repo-relative path of the file that references it

    Ensures:
        - returns the token string (8-digit date plus optional single-letter suffix),
          or None when that source did not exist at `rev`, or did not reference the
          asset with a token there
        - matches an HTML `href`/`src` attribute OR a JS `import( "..." )`, because
          the quotes are the only delimiter the two styles share
    """
    done = subprocess.run(
        [ "git", "show", f"{rev}:{source_rel}" ],
        cwd=cu.get_project_root(), capture_output=True, text=True
    )
    if done.returncode != 0: return None

    match = re.search(
        r'["\']' + re.escape( static_url ) + r'\?v=(\d{8}[a-z]?)["\']', done.stdout
    )
    return match.group( 1 ) if match else None


def _differs_from_head( repo_rel_path ):
    """
    Whether the working tree's copy of repo_rel_path differs from HEAD.

    Ensures:
        - True for a staged OR unstaged edit (git diff HEAD covers both)
    """
    done = subprocess.run(
        [ "git", "diff", "--quiet", "HEAD", "--", repo_rel_path ],
        cwd=cu.get_project_root(), capture_output=True, text=True
    )
    return done.returncode != 0


@pytest.mark.parametrize( "static_url,token_full",
                          _DISCOVERED_FULL,
                          ids=[ url for url, _t in _DISCOVERED_FULL ] )
def test_versioned_asset_token_followed_its_last_change( static_url, token_full ):
    """
    The page's token for an asset must DIFFER from the one it carried immediately
    before that asset's most recent change — i.e. the bump travelled with the asset.

    Requires:
        - the asset is tracked by git and linked with a ?v= token

    Ensures:
        - fails when the token is byte-identical across the asset's last change
        - the refused value is DERIVED from git at run time; no literal token
          appears in the assertion and there is no baseline to hand-bump
    """
    repo_rel  = _static_url_to_repo_rel( static_url )
    asset_sha = _git_last_commit_sha( repo_rel )
    assert re.fullmatch( r"[0-9a-f]{40}", asset_sha ), \
        f"could not resolve a last commit for {repo_rel} (got {asset_sha!r}); is it tracked?"

    parent = _git_first_parent( asset_sha )
    if parent is None:
        pytest.skip( f"{repo_rel} last changed in a root commit — nothing to compare against" )

    token_before = _token_at_rev( parent, static_url )
    if token_before is None:
        pytest.skip( f"{static_url} was not linked with a token at {parent[ :8 ]}" )

    assert token_full != token_before, (
        f"{static_url} last changed in commit {asset_sha[ :8 ]}, but the page still "
        f"carries ?v={token_full} — the SAME token it carried at {parent[ :8 ]}, "
        f"BEFORE that change. The token did not follow the asset, so a returning "
        f"browser's cache key is unchanged and it keeps serving the OLD copy: the "
        f"change looks landed in git and absent on screen. Bump the suffix.\n"
        f"⚠️ The date comparison in this file CANNOT catch this — several slices "
        f"land on one day and every one of them satisfies token_date >= commit_date."
    )


@pytest.mark.parametrize( "static_url,token_full",
                          _DISCOVERED_FULL,
                          ids=[ url for url, _t in _DISCOVERED_FULL ] )
def test_uncommitted_asset_edit_bumped_its_token( static_url, token_full ):
    """
    An asset edited in the WORKING TREE must carry a bumped token in the working
    tree too.

    Requires:
        - the asset is tracked by git

    Ensures:
        - skips when the asset matches HEAD (nothing uncommitted to guard)
        - otherwise fails when the token is byte-identical to HEAD's
        - the refused value is HEAD's token, read out of git at run time

    The commit-ordered test above can only speak about history, so without this one
    a forgotten bump stays invisible right up until it is committed — which is after
    the point where it is cheap to fix.
    """
    repo_rel = _static_url_to_repo_rel( static_url )
    if not _differs_from_head( repo_rel ):
        pytest.skip( f"{repo_rel} matches HEAD — nothing uncommitted to guard" )

    token_at_head = _token_at_rev( "HEAD", static_url )
    assert token_full != token_at_head, (
        f"{repo_rel} has uncommitted changes, but notifications.html still links it "
        f"?v={token_full} — the same token HEAD carries. Bump the token in the same "
        f"edit as the asset: a `?v=` token is part of the browser cache key, so an "
        f"unchanged token means a warm browser serves the OLD file."
    )


# ---------------------------------------------------------------------------
# Assets referenced from JAVASCRIPT, not from the page
# ---------------------------------------------------------------------------
#
# 🔴 EVERY GUARD ABOVE SCANS ONE .html FILE, AND AN ASSET CAN BE VERSIONED WITHOUT
# APPEARING IN ONE. notifications.js:2443 does
#
#     const mod = await import( "/static/js/ws-channel.js?v=20260503a" );
#
# — a dynamic ES-module import carrying its own cache-bust token. No guard here
# could see it, because none of them read a .js file. Measured 2026-09-02:
# ws-channel.js last changed 2026-06-19 in 53fef419, so that token was SIX WEEKS
# stale and nothing in the suite was looking. It is the only case in this file
# where a returning browser was actually being handed the wrong module.
#
# WHY SCANNING ONE PAGE LOOKED SUFFICIENT — the population, named, with a positive
# control, because an empty search result and a wrong search result print the same
# thing. Of 42 tracked .html files under src/, EXACTLY ONE carries a `?v=` token
# (notifications.html), and the search that found that one is the same search that
# returns nothing for the other 41 — so the page scan really is complete FOR PAGES.
# The gap was never a missing page. It was a second reference STYLE: 32 tracked .js
# files under static/, one of which versions an import.
#
# ⇒ The guarded population is now "every versioned reference", not "every versioned
# link on the page". A third style (a CSS `@import`, a token built by string
# concatenation) would still escape both — which is why the discovery below has its
# own non-vacuous anchor rather than trusting the regex to keep matching.

# Third-party bundles this repo neither authors nor versions. EVERY NAME HERE IS A
# HOLE IN THE CORPUS, so the set is pinned by a test below: widening it is a
# deliberate edit in two places, never a quiet one in this line.
_JS_CORPUS_EXCLUDED_DIRS = frozenset( { "vendor", "canvaskit" } )

JS_IMPORT_RE = re.compile( r'import\(\s*["\'](/static/[^"\']+)\?v=(\d{8}[a-z]?)["\']' )

# The versioned JS imports EXPECTED in the shipped client, same purpose as
# EXPECTED_VERSIONED_ASSETS: if the regex stops matching, the parametrized tests
# below collect zero cases and pass VACUOUSLY. Entries are ( source, imported ).
EXPECTED_JS_IMPORTS = frozenset( {
    ( "src/lupin_app/static/js/notifications.js", "/static/js/ws-channel.js" ),
} )


def _shipped_js_sources():
    """
    Every shipped `.js` file under the static tree, repo-relative, sorted.

    Ensures:
        - returns POSIX repo-relative paths (what git wants)
        - reads the DISK, not the index: a new client file is covered before it is
          committed, which is when a forgotten token is cheapest to fix
        - walks the WHOLE static tree, not `static/js/`

    🔴 IT WALKED `static/js/` ONLY IN ITS FIRST CUT AND MISSED 11 TRACKED FILES —
    the same population defect this file was written to fix, one level down and in
    my own code. They live under `static/html/admin/js/`,
    `static/html/auth/admin/js/` and `static/html/auth/js/`. None versions an import
    TODAY, which is exactly why it would have gone unnoticed: a corpus gap costs
    nothing until something moves into it.
    """
    root  = cu.get_project_root()
    found = []
    for dirpath, dirnames, filenames in os.walk( STATIC ):
        dirnames[ : ] = [ d for d in dirnames if d not in _JS_CORPUS_EXCLUDED_DIRS ]
        for name in filenames:
            if not name.endswith( ".js" ): continue
            full = os.path.join( dirpath, name )
            found.append( os.path.relpath( full, root ).replace( os.sep, "/" ) )
    return sorted( found )


def _discover_js_imports():
    """
    Every versioned dynamic import across the shipped client JS.

    Ensures:
        - returns [ ( source_rel, static_url, token_full ), ... ], sorted
        - token_full keeps its suffix — the within-day signal
    """
    out = []
    for source_rel in _shipped_js_sources():
        try:
            text = _read( os.path.join( cu.get_project_root(), source_rel ) )
        except OSError:
            continue
        for match in JS_IMPORT_RE.finditer( text ):
            out.append( ( source_rel, match.group( 1 ), match.group( 2 ) ) )
    return sorted( out )


_DISCOVERED_JS = _discover_js_imports()
_JS_IDS        = [ f"{src.rsplit( '/', 1 )[ -1 ]}->{url}" for src, url, _t in _DISCOVERED_JS ]


def test_js_import_discovery_is_nonvacuous():
    """
    Discovery must find EXACTLY the expected versioned-import set.

    Ensures:
        - a regex that silently stopped matching fails loudly here rather than
          greening the three tests below by collecting nothing
        - a NEW versioned import joining the client must also join this anchor
    """
    found = { ( src, url ) for src, url, _t in _DISCOVERED_JS }
    assert found == EXPECTED_JS_IMPORTS, (
        f"versioned JS-import discovery drifted from the expected set.\n"
        f"  missing (expected, not found): {sorted( EXPECTED_JS_IMPORTS - found )}\n"
        f"  unexpected (found, not listed): {sorted( found - EXPECTED_JS_IMPORTS )}\n"
        f"A new versioned import must join this anchor, or it rots unwatched — which "
        f"is exactly how ws-channel.js went six weeks stale."
    )


@pytest.mark.parametrize( "source_rel,static_url,token_full", _DISCOVERED_JS, ids=_JS_IDS )
def test_js_import_token_not_stale( source_rel, static_url, token_full ):
    """
    A dynamically-imported module's token date must be >= that module's last commit
    date — the same property the page's links carry, applied to the other reference
    style.

    Requires:
        - the imported module is tracked by git

    Ensures:
        - fails when the importing JS pins a token older than the module it imports
    """
    repo_rel    = _static_url_to_repo_rel( static_url )
    commit_date = _git_last_commit_date( repo_rel )
    assert re.fullmatch( r"\d{8}", commit_date ), \
        f"could not resolve {repo_rel} git commit date (got {commit_date!r}); is it tracked?"

    assert token_full[ :8 ] >= commit_date, (
        f"{source_rel} imports {static_url}?v={token_full}, STALE vs that module's "
        f"last commit {commit_date}. A `?v=` token is part of the browser cache key, "
        f"so a returning browser re-executes the OLD module while the rest of the "
        f"page is new. Bump the token in the import to >= {commit_date}.\n"
        f"⚠️ No guard scanning notifications.html can see this — the reference lives "
        f"in a .js file."
    )


@pytest.mark.parametrize( "source_rel,static_url,token_full", _DISCOVERED_JS, ids=_JS_IDS )
def test_js_import_token_followed_its_last_change( source_rel, static_url, token_full ):
    """
    The import's token must differ from the one the SAME source carried before the
    imported module's most recent change — the commit-ordered property, so a
    same-day slice cannot hide behind an unchanged day.

    Ensures:
        - the refused value is read out of git at run time; no literal token
        - skips honestly when the source did not reference the module at that
          parent, rather than inventing a comparison
    """
    repo_rel  = _static_url_to_repo_rel( static_url )
    asset_sha = _git_last_commit_sha( repo_rel )
    assert re.fullmatch( r"[0-9a-f]{40}", asset_sha ), \
        f"could not resolve a last commit for {repo_rel} (got {asset_sha!r}); is it tracked?"

    parent = _git_first_parent( asset_sha )
    if parent is None:
        pytest.skip( f"{repo_rel} last changed in a root commit — nothing to compare against" )

    token_before = _token_at_rev( parent, static_url, source_rel )
    if token_before is None:
        pytest.skip( f"{source_rel} did not import {static_url} with a token at {parent[ :8 ]}" )

    assert token_full != token_before, (
        f"{source_rel} imports {static_url}?v={token_full}, the SAME token it carried "
        f"at {parent[ :8 ]} — before {static_url} last changed in {asset_sha[ :8 ]}. "
        f"The token did not follow the module."
    )


@pytest.mark.parametrize( "source_rel,static_url,token_full", _DISCOVERED_JS, ids=_JS_IDS )
def test_uncommitted_js_import_target_bumped_its_token( source_rel, static_url, token_full ):
    """
    A dynamically-imported module edited in the WORKING TREE must have its import
    token bumped in the working tree too.

    Ensures:
        - skips when the module matches HEAD (nothing uncommitted to guard)
        - otherwise fails when the token is byte-identical to HEAD's
    """
    repo_rel = _static_url_to_repo_rel( static_url )
    if not _differs_from_head( repo_rel ):
        pytest.skip( f"{repo_rel} matches HEAD — nothing uncommitted to guard" )

    token_at_head = _token_at_rev( "HEAD", static_url, source_rel )
    assert token_full != token_at_head, (
        f"{repo_rel} has uncommitted changes, but {source_rel} still imports it "
        f"?v={token_full} — the same token HEAD carries. Bump it in the same edit."
    )


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
        if VERSIONED_ASSET_RE.search( _read( os.path.join( cu.get_project_root(), h ) ) )
    )
    assert tokened == [ NOTIF_HTML_REL ], (
        f"the set of token-carrying pages changed: {tokened}\n"
        f"Every page guard in this file reads ONLY {NOTIF_HTML_REL}. A second page "
        f"versioning its assets is unwatched the moment it appears — which is exactly "
        f"how a versioned reference outside the scanned corpus goes stale unnoticed."
    )
