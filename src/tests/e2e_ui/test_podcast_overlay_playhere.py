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

Surface landed: Rio's overlay 63dd16f1, Krishna's ?embed=1 page dd371040,
Rachel's emit f03bf73f. Unskipped + scheduled on :8000 after a bounce (cache-bust
20260803b).
"""

from __future__ import annotations

from .conftest import BASE_URL

# Real emit format — matches podcast_generator/job.py:342 (unit-verified in
# test_job.py::test_completion_abstract_emits_play_here_and_listen_links).
# A REAL, playable podcast the test user can read (/api/io/file gates on auth +
# path-traversal, NOT ownership — proven empirically by Rio: the test-user token
# reads this 6.3MB mp3, 200). The player JS-injects <audio> only after a
# successful auth'd byte-fetch (blob → object URL), so a non-existent path lands
# in the loud error state and never mounts audio — the file must be real.
ENC           = "podcasts/ricardo.felipe.ruiz@gmail.com/2026.01.21-172309-quantum-computing-when-reality-gets-wei.mp3"
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

    The host is PINNED (fixed, bottom-left, high z-index) so its anchors are
    always actionable: the notifications toolbar sits at a high z-index and
    otherwise intercepts the pointer on the leftmost Play Here link (the rightmost
    Listen link happened to clear it). Rio's interception is document-level on any
    a[href*=embed=1] click, so where the anchor lives does not matter — pinning
    only removes a layout-dependent flake, it does not weaken the trigger.
    """
    page.evaluate(
        """( md ) => {
            const host = document.createElement( 'div' );
            host.dataset.testPodcastAbstract = '1';
            host.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;background:#222;padding:8px;';
            host.innerHTML = window.notificationsUI.renderAbstractSection( md );
            document.body.appendChild( host );
        }""",
        ABSTRACT_MD,
    )


def _click_play_here( page ):
    """
    Click the real Play Here (&embed=1) anchor to fire Rio's interception, then
    REMOVE the pinned trigger host so it cannot overlap the overlay's own
    controls (e.g. the dismiss button) during the assertions that follow.
    """
    page.locator( f"{ABS_HOST} a[href*='embed=1']" ).click()
    page.evaluate(
        "() => { const h = document.querySelector( \"[data-test-podcast-abstract='1']\" ); if ( h ) h.remove(); }"
    )


class TestPodcastOverlayPlayHere:
    """Play Here → overlay; dismiss → closed; Listen → plain tab, unchanged."""

    def test_play_here_opens_overlay_with_embed_iframe_and_audio( self, notifications_page ):
        page = notifications_page
        _render_abstract( page )

        # Click the real Play Here anchor (the &embed=1 link); fires Rio's interception.
        _click_play_here( page )

        # Overlay opens, iframe src is the &embed=1 URL verbatim.
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        src = page.locator( FRAME ).get_attribute( "src" )
        assert src is not None and "/app/audio?path=" in src and "&embed=1" in src, \
            f"iframe src must be the embed player URL; got {src!r}"
        assert "autoplay=1" in src, f"overlay must auto-start (autoplay=1); got {src!r}"

        # Prove ACTUAL playback inside the frame, not mere element presence.
        _assert_frame_audio_playing( page )

    def test_dismiss_removes_the_iframe( self, notifications_page ):
        page = notifications_page
        _render_abstract( page )
        _click_play_here( page )
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        # Dismiss must stop a LIVE player — prove it is actually playing first, so
        # an element-only (or DENY-blocked, or error-state) frame can't false-green.
        _assert_frame_audio_playing( page )

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
        _click_play_here( page )
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )
        assert "&embed=1" in ( page.locator( FRAME ).get_attribute( "src" ) or "" )
        # Not a src-only false-green: require the framed player to actually play.
        _assert_frame_audio_playing( page )

    def test_listen_link_opens_a_tab_and_never_the_overlay( self, notifications_page ):
        # NEGATIVE: a plain /app/audio link (no &embed=1) is NOT intercepted —
        # it still opens a standalone tab and does NOT trigger the overlay.
        page = notifications_page
        _render_abstract( page )

        # Path-agnostic: the Listen link targets /app/audio WITHOUT &embed=1.
        listen = page.locator( f"{ABS_HOST} a[href*='/app/audio']:not([href*='embed=1'])" )
        with page.context.expect_page() as popup_info:
            listen.click()
        popup = popup_info.value
        assert "/app/audio?path=" in popup.url and "embed=1" not in popup.url, \
            f"Listen must open the plain player tab, not the embed URL; got {popup.url!r}"
        assert page.locator( OVERLAY ).count() == 0, "Listen must NOT open the overlay"
        popup.close()
