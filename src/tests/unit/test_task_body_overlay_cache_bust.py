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
UNVERSIONED. Static files are served by Starlette StaticFiles with NO
Cache-Control header — only ETag + Last-Modified — so the mux cache key is the
bare URL and returning browsers revalidate + self-heal from the file's mtime.
The mux therefore does NOT share the legacy's permanent-staleness defect and is
intentionally left token-free (adding a manual token would re-introduce exactly
the drift this guard exists to catch). Hence the freshness assertion is scoped
to the versioned legacy link only.
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

# the versioned <link> in notifications.html: /static/css/task-list.css?v=YYYYMMDD[suffix]
TOKEN_LINK_RE = re.compile( r"/static/css/task-list\.css\?v=(\d{8})([a-z]?)" )

# GENERALIZED guard (row 14e2c5c7): every versioned asset the page links, not just
# task-list.css. A `?v=` token is part of the browser cache KEY, so ANY tokened
# asset whose token date drifts behind the file's last commit serves a stale cached
# copy to returning browsers. task-list.css was the only guarded one of SIX; bumping
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
    last commit serves a STALE cached copy to returning browsers — a rendering
    fault that looks like a bug on stage and cannot be diagnosed live. Naming
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
        f"?v={commit_date}a) so returning browsers refetch it. A `?v=` token is part "
        f"of the cache key, so a stale token permanently serves the old cached asset."
    )
