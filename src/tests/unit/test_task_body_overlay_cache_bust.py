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

# repo-relative path git needs to resolve the CSS file's commit history
LEGACY_CSS_REL = os.path.join( "src", "lupin_app", "static", "css", "task-list.css" )

# the versioned <link> in notifications.html: /static/css/task-list.css?v=YYYYMMDD[suffix]
TOKEN_LINK_RE = re.compile( r"/static/css/task-list\.css\?v=(\d{8})([a-z]?)" )


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


def test_notifications_task_list_token_not_stale_vs_css():
    """
    The cache-bust token date must be >= the CSS file's most-recent commit date.

    This is the f7486a9d recurrence guard: editing task-list.css without bumping
    the ?v= token leaves returning browsers serving the stale cached sheet. On
    the bug shape (token 20260617 vs css commit 20260629) this assertion fails
    loudly, naming the remedy.
    """
    match = TOKEN_LINK_RE.search( _read( NOTIF_HTML ) )
    assert match, "notifications.html lost its versioned task-list.css link"
    token_date = match.group( 1 )

    css_date = _git_last_commit_date( LEGACY_CSS_REL )
    assert re.fullmatch( r"\d{8}", css_date ), \
        f"could not resolve task-list.css git commit date (got {css_date!r}); is the file tracked?"

    assert token_date >= css_date, (
        f"notifications.html task-list.css?v={token_date} is STALE vs the CSS file's "
        f"last commit {css_date} — bump the ?v= token (e.g. ?v={css_date}a) so returning "
        f"browsers refetch the .task-body-overlay rule. Without it the 📄 detail overlay "
        f"renders position:static and dumps the body at the page foot (bug f7486a9d)."
    )
