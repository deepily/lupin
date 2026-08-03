"""
E2E UI — podcast completion "Play Here" overlay click-through (2026-08-03).

Covers the seam nobody else owns: the click-through from a completion abstract
to Rio's floating overlay. The three pieces:
  - EMIT (Rachel, f03bf73f): the completion abstract carries
      [▶️ Play Here](/app/audio?path=<enc>&embed=1) | [🎧 Listen](/app/audio?path=<enc>) | [⬇️ Download](…)
  - OVERLAY (Rio): the client intercepts a click on ANY a[href] matching
      /app/audio?path=...&embed=1 and shows an in-tab floating overlay whose
      iframe src is that &embed=1 URL verbatim. Dismiss removes the iframe
      (= stops playback). Works in BOTH layout modes.
  - EMBED PAGE (Krishna): /app/audio?...&embed=1 renders <audio controls>.

This test renders the abstract through the app's OWN renderer
(`notificationsUI.renderAbstractSection`, the exact method the completion path
uses at notifications.js:5577), so the anchors are real app-rendered anchors
and Rio's document-level interception fires on a real click — no invented
selectors, no hand-built markup.

Rio's contract (DM 2026-08-03), stable:
  - overlay container : [data-testid="podcast-overlay"]  (also #podcast-overlay)
  - iframe            : [data-testid="podcast-overlay-frame"]
  - dismiss (button)  : [data-testid="podcast-overlay-dismiss"]  (aria-label "Dismiss podcast player")
  - Listen (plain /app/audio, NO &embed=1) is NOT intercepted → opens a new tab.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_podcast_overlay_playhere",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }

SKIP GUARD: skipped until Rio's overlay SHA + Krishna's ?embed=1 page land on
the branch. Remove the `pytestmark` line to schedule (that is the unskip).
"""

from __future__ import annotations

import pytest

from .conftest import BASE_URL

pytestmark = pytest.mark.skip(
    reason="overlay surface lands with Rio's SHA + Krishna's ?embed=1 page; "
           "unskip (remove this pytestmark) when scheduling the :8000 run"
)

# Real emit format — matches podcast_generator/job.py:342 (unit-verified in
# test_job.py::test_completion_abstract_emits_play_here_and_listen_links).
ENC           = "pod/ep.mp3"
PLAY_HERE_URL = f"/app/audio?path={ENC}&embed=1"
LISTEN_URL    = f"/app/audio?path={ENC}"
ABSTRACT_MD   = (
    "**Podcast Activity Report**\n\n"
    "**Segments**: 3 (~2.0 min)\n"
    "**Languages**: en, es-MX\n"
    f"**Audio**: [▶️ Play Here]({PLAY_HERE_URL}) | "
    f"[🎧 Listen]({LISTEN_URL}) | "
    f"[⬇️ Download](/api/io/file?path={ENC}&download=true)"
)

OVERLAY   = '[data-testid="podcast-overlay"]'
FRAME     = '[data-testid="podcast-overlay-frame"]'
DISMISS   = '[data-testid="podcast-overlay-dismiss"]'
ABS_HOST  = "[data-test-podcast-abstract='1']"


def _render_abstract( page ):
    """
    Render the completion abstract through the app's OWN renderer into the
    notifications DOM, so the anchors are real app-rendered anchors (DOMPurify'd)
    and Rio's document-level click interception fires on a genuine click.
    """
    page.evaluate(
        """( md ) => {
            const host = document.createElement( 'div' );
            host.dataset.testPodcastAbstract = '1';
            host.innerHTML = window.notificationsUI.renderAbstractSection( md );
            ( document.querySelector( '.notifications-container' ) || document.body ).appendChild( host );
        }""",
        ABSTRACT_MD,
    )


class TestPodcastOverlayPlayHere:
    """Play Here → overlay; dismiss → closed; Listen → plain tab, unchanged."""

    def test_play_here_opens_overlay_with_embed_iframe_and_audio( self, notifications_page ):
        page = notifications_page
        _render_abstract( page )

        # Click the real Play Here anchor (the &embed=1 link).
        page.locator( f"{ABS_HOST} a[href*='embed=1']" ).click()

        # Overlay opens, iframe src is the &embed=1 URL verbatim.
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        src = page.locator( FRAME ).get_attribute( "src" )
        assert src is not None and "/app/audio?path=" in src and src.endswith( "&embed=1" ), \
            f"iframe src must be the &embed=1 player URL verbatim; got {src!r}"

        # The embed page (Krishna) renders an <audio> control inside the iframe.
        # Same-origin (/app/audio is SAMEORIGIN), so the frame content is inspectable.
        page.frame_locator( FRAME ).locator( "audio" ).wait_for( state="attached", timeout=5000 )

    def test_dismiss_removes_the_iframe( self, notifications_page ):
        page = notifications_page
        _render_abstract( page )
        page.locator( f"{ABS_HOST} a[href*='embed=1']" ).click()
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )

        # Dismiss removes the iframe → playback stops (Rio: ✕ removes the iframe).
        page.locator( DISMISS ).click()
        page.locator( FRAME ).wait_for( state="detached", timeout=5000 )
        assert page.locator( FRAME ).count() == 0, "dismiss must remove the iframe (stop playback)"

    def test_play_here_works_in_horizontal_mode_too( self, notifications_page ):
        # Rio: interception is NOT gated on layout — works in both modes.
        page = notifications_page
        page.locator( "#layout-mode-toggle" ).click()      # → horizontal
        page.wait_for_timeout( 100 )
        _render_abstract( page )
        page.locator( f"{ABS_HOST} a[href*='embed=1']" ).click()
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        assert page.locator( FRAME ).get_attribute( "src" ).endswith( "&embed=1" )

    def test_listen_link_opens_a_tab_and_never_the_overlay( self, notifications_page ):
        # NEGATIVE: a plain /app/audio link (no &embed=1) is NOT intercepted —
        # it still opens a standalone tab and does NOT trigger the overlay.
        page = notifications_page
        _render_abstract( page )

        listen = page.locator( f"{ABS_HOST} a[href$='path={ENC}']" )   # ends with path=…, no &embed=1
        with page.context.expect_page() as popup_info:
            listen.click()
        popup = popup_info.value
        assert "/app/audio?path=" in popup.url and "embed=1" not in popup.url, \
            f"Listen must open the plain player tab, not the embed URL; got {popup.url!r}"
        assert page.locator( OVERLAY ).count() == 0, "Listen must NOT open the overlay"
        popup.close()
