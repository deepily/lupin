"""
Multiplexer Phase 6b — visual regression baseline capture.

Per AC11a + AC11b ratification (design doc 09):
    - AC11a: submission via `POST /api/test-suite/submit` with
      `--update-snapshots -k multiplexer_phase6b` returns HTTP 200 + valid
      `submission_id`. The HUMAN gate is slot-coordination ONLY (calendar);
      the AI executes the submission via the /schedule-tests skill.
    - AC11b: post-run state — assert PNGs exist under
      `io/test-suite/visual-baselines/test_multiplexer_phase6b_visual/` AND
      container log shows `Test suite complete` + `e2e: 2 passed, 0 errors`
      on Run #2 (regression check, no `--update-snapshots`).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via the
e2e_ui conftest standard (`LUPIN_TEST_BASE_URL` env var; default
`http://localhost:8000`). NO hardcoded `:8000` literal.

**Venue**: `:8000` monopolize-mode (e2e_ui suite gate). Schedule via
`POST /api/test-suite/submit` with non-overlapping `scheduled_at` slot per
`feedback_test_server_monopolize_mode`. Side-door injection (ad-hoc curl,
direct queue push, in-process server instantiation) is PROHIBITED.

The `-k multiplexer_phase6b` filter ensures ONLY this file's tests run during
the scheduled slot — NOT the full ~285 functional + 12 visual E2E sweep.
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Test-hook injection — 3 action_required prompts, one per response_type.
#
# Per ActionRequiredStore: prompts arrive via `notification_queue_update` with
# `notification.response_requested === true`. Fixed timestamps + fixed
# timeout_seconds so the rendered countdown is byte-identical across runs
# AFTER countdown-text stabilization.
# ---------------------------------------------------------------------------

_INJECT_ACTION_REQUIRED_FIXTURES_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }
    const bus = hook.eventBus;

    // Fixed timestamps for byte-identical wire payloads.
    const TS_YES_NO = '2026-05-12T18:00:00.000Z';
    const TS_MC     = '2026-05-12T18:01:00.000Z';
    const TS_OPEN   = '2026-05-12T18:02:00.000Z';

    // Prompt 1: yes_no.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'phase6b_visual_yes_no',
                message             : 'Continue with the deployment?',
                response_requested  : true,
                response_type       : 'yes_no',
                response_options    : [],
                response_default    : 'no',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-visual',
                timestamp           : TS_YES_NO,
            },
        },
        source : 'phase6b-visual',
        ts     : 1778702400000,
    });

    // Prompt 2: multiple_choice (single-select).
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'phase6b_visual_mc',
                message             : 'Pick a database backend.',
                response_requested  : true,
                response_type       : 'multiple_choice',
                response_options    : [ 'PostgreSQL', 'SQLite', 'MongoDB' ],
                response_default    : 'PostgreSQL',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-visual',
                timestamp           : TS_MC,
            },
        },
        source : 'phase6b-visual',
        ts     : 1778702460000,
    });

    // Prompt 3: open_ended.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'phase6b_visual_open',
                message             : 'What should I name the new service?',
                response_requested  : true,
                response_type       : 'open_ended',
                response_options    : [],
                response_default    : '',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-visual',
                timestamp           : TS_OPEN,
            },
        },
        source : 'phase6b-visual',
        ts     : 1778702520000,
    });

    return true;
}
"""


# Pin every `.action-required-countdown` to a deterministic placeholder so the
# pixel-diff is stable across runs. Without this, the 1Hz countdown tick
# emitted by ActionRequiredStore's per-actor setInterval would drift the
# rendered text every second.
_STABILIZE_COUNTDOWN_JS = """
() => {
    const PIN = '5m 0s';
    document.querySelectorAll( '.action-required-countdown' ).forEach( el => {
        el.textContent = PIN;
    } );
    return true;
}
"""


# ---------------------------------------------------------------------------
# Visual regression — action-required interactive widgets
# ---------------------------------------------------------------------------

def test_multiplexer_phase6b_action_required_visual(
    request, clean_test_db, assert_snapshot_height_tolerant, logged_in_page,
):
    """
    Capture the Phase 6b action-required-section in its rendered baseline state.

    Fixture: 3 action_required prompts (one per response_type):
        - yes_no             — Yes / No buttons
        - multiple_choice    — 3 radio options
        - open_ended         — text input + Submit button

    Requires:
        - Server running on `:8000` with Testing config
        - `logged_in_page` fixture (authenticated session)
        - `assert_snapshot_height_tolerant` fixture (bug 660d02b4 — ≤1px
          height-tolerant; forgives the benign --update-vs-compare row-height flap)
        - `--update-snapshots` flag on first run to establish the baseline

    Ensures:
        - `/app/multiplexer` loads under authenticated session
        - boot.ts test hook is reachable
        - 3 action_required fixtures inject + render as interactive widgets
        - Snapshot of `#action-required-section` matches baseline
    """
    page = logged_in_page

    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )

    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_ACTION_REQUIRED_FIXTURES_JS )

    for id_hash in [
        "phase6b_visual_yes_no",
        "phase6b_visual_mc",
        "phase6b_visual_open",
    ]:
        page.wait_for_selector( f'.action-required-widget[data-id-hash="{id_hash}"]', timeout=2000 )

    # Stabilize the live 1Hz countdown text before screenshot.
    page.evaluate( _STABILIZE_COUNTDOWN_JS )

    # Brief settle window for layout repaint after stabilization.
    time.sleep( 0.2 )

    # Height-tolerant compare (bug 660d02b4): forgives a benign ≤1px sub-pixel
    # row-height rounding flap between --update-snapshots and a plain COMPARE,
    # while staying strict on width + overlapping pixels. (A larger genuine
    # height change — e.g. the 0a/0c section-header +57px — still fails until the
    # baseline is legitimately re-captured.)
    section = page.locator( '#action-required-section' )
    assert_snapshot_height_tolerant( section, name="multiplexer_phase6b_action_required.png" )

    print( "✓ multiplexer_phase6b_action_required: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Visual regression — TTS chrome (idle state)
# ---------------------------------------------------------------------------

def test_multiplexer_phase6b_tts_chrome_visual(
    request, clean_test_db, assert_snapshot_height_tolerant, logged_in_page,
):
    """
    Capture the Phase 6b TTS chrome in its idle baseline state.

    No fixture injection: with no audio chunks flowing, the chrome renders in
    its idle state (no `is-playing-current` / `is-paused-current` class on
    `.tts-chrome`; queue-length pill reads 0).

    Ensures:
        - `/app/multiplexer` loads under authenticated session
        - boot.ts mounts TtsChromeRenderer onto `#tts-pane`
        - `hidden` + `data-phase6-pending` attributes are lifted
        - Snapshot of `#tts-pane` matches the idle-state baseline
    """
    page = logged_in_page

    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )

    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    # Wait for the tts-chrome to render its IDLE panel (sanity check before
    # snapshot). Straggler bug a90cc63e: the prior gate waited for
    # `#tts-pane .tts-controls`, but `.tts-controls` is emitted ONLY by the
    # PLAYING/paused branch of renderTtsChrome (templates/ttsChrome.ts:135). This
    # test captures the IDLE state (no audio flowing), where the STATE-driven
    # empty panel renders `.tts-chrome-empty` + `.tts-queue-empty-state` and NO
    # `.tts-controls` (renderTtsEmpty, ttsChrome.ts:86-92; locked by unit test
    # templates_tts_chrome.test.ts:48). The old selector could therefore NEVER
    # resolve idle → a guaranteed 2000ms timeout, not a contention flake. Wait
    # instead for the idle observability handle the template DOES emit for every
    # state (data-testid + data-state, ttsChrome.test.ts:223), with a generous
    # timeout matching the test-hook wait above.
    page.wait_for_selector(
        '#tts-pane [data-testid="multiplexer-tts-chrome"][data-state="idle"]',
        timeout=15000,
    )

    # Brief settle window for any post-mount layout repaint.
    time.sleep( 0.2 )

    # Height-tolerant compare (bug 660d02b4): forgives the benign ≤1px sub-pixel
    # row-height rounding flap (e.g. 129 vs 130) between --update-snapshots and a
    # plain COMPARE, while staying strict on width + overlapping pixels.
    pane = page.locator( '#tts-pane' )
    assert_snapshot_height_tolerant( pane, name="multiplexer_phase6b_tts_chrome.png" )

    print( "✓ multiplexer_phase6b_tts_chrome: visual snapshot compared" )
