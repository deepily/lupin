"""
Multiplexer Phase 6a — visual regression baseline capture.

Per AC11a + AC11b ratification (design doc 08):
    - AC11a: submission via `POST /api/test-suite/submit` with
      `--update-snapshots -k multiplexer_phase6a` returns HTTP 200 + valid
      `submission_id`.  The HUMAN gate is slot-coordination ONLY (calendar);
      the AI executes the submission via the /schedule-tests skill.
    - AC11b: post-run state — assert PNGs exist under
      `io/test-suite/visual-baselines/test_multiplexer_phase6a_visual/` AND
      container log shows `Test suite complete` + `e2e: 1 passed, 0 errors`
      on Run #2 (regression check, no `--update-snapshots`).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
the e2e_ui conftest standard (`LUPIN_TEST_BASE_URL` env var; default
`http://localhost:8000`). NO hardcoded `:8000` literal.

**Venue**: `:8000` monopolize-mode (e2e_ui suite gate). Schedule via
`POST /api/test-suite/submit` with non-overlapping `scheduled_at` slot per
`feedback_test_server_monopolize_mode`. Side-door injection (ad-hoc curl,
direct queue push, in-process server instantiation) is PROHIBITED.

The `-k multiplexer_phase6a` filter ensures ONLY this file's tests run during
the scheduled slot — NOT the full ~285 functional + 12 visual E2E sweep.
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Test hook usage — see boot.ts `window.__multiplexerTestHook` (D-E)
# ---------------------------------------------------------------------------

# Inject 5 deterministic job fixtures spanning all 4 active buckets + history,
# via job_state_transition + job_removed events. Uses FIXED timestamps (NOT
# new Date()) so rendered .job-timing text is byte-identical across runs.
#
# Per pytest-playwright-visual-snapshot: pixel-diff includes ALL rendered
# text. Dynamic timing displays MUST be fixed BEFORE the screenshot.
_INJECT_JOB_FIXTURES_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }
    const bus = hook.eventBus;

    // Fixed timestamps for byte-identical rendering across runs.
    const TS_BASE      = '2026-05-06T18:00:00.000Z';   // 14:00 EDT
    const TS_PLUS_5M   = '2026-05-06T18:05:00.000Z';
    const TS_PLUS_10M  = '2026-05-06T18:10:00.000Z';
    const TS_PLUS_15M  = '2026-05-06T18:15:00.000Z';
    const TS_PLUS_20M  = '2026-05-06T18:20:00.000Z';

    // Job 1: todo bucket (server state pending → UI status todo).
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'phase6a_visual_todo',
            id_hash    : 'phase6a_visual_todo',
            from_state : null,
            to_state   : 'pending',
            timestamp  : TS_BASE,
            metadata   : { agent_type: 'DeepResearchJob' },
        },
        source : 'phase6a-visual',
        ts     : 1778097600000,
    });

    // Job 2: running bucket.
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'phase6a_visual_running',
            id_hash    : 'phase6a_visual_running',
            from_state : null,
            to_state   : 'running',
            timestamp  : TS_PLUS_5M,
            metadata   : { agent_type: 'PodcastGeneratorJob' },
        },
        source : 'phase6a-visual',
        ts     : 1778097900000,
    });

    // Job 3: done bucket.
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'phase6a_visual_done',
            id_hash    : 'phase6a_visual_done',
            from_state : null,
            to_state   : 'completed',
            timestamp  : TS_PLUS_10M,
            metadata   : { agent_type: 'PresentationGeneratorJob' },
        },
        source : 'phase6a-visual',
        ts     : 1778098200000,
    });

    // Job 4: dead bucket.
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'phase6a_visual_dead',
            id_hash    : 'phase6a_visual_dead',
            from_state : null,
            to_state   : 'failed',
            timestamp  : TS_PLUS_15M,
            metadata   : { agent_type: 'BugFixExpediterJob' },
        },
        source : 'phase6a-visual',
        ts     : 1778098500000,
    });

    // Job 5: history bucket — done then removed (reducer routes done → history).
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'phase6a_visual_history',
            id_hash    : 'phase6a_visual_history',
            from_state : null,
            to_state   : 'completed',
            timestamp  : TS_PLUS_20M,
            metadata   : { agent_type: 'TestFixExpediterJob' },
        },
        source : 'phase6a-visual',
        ts     : 1778098800000,
    });
    bus.emit({
        type    : 'job_removed',
        payload : { job_id: 'phase6a_visual_history', id_hash: 'phase6a_visual_history' },
        source  : 'phase6a-visual',
        ts      : 1778098810000,
    });

    return true;
}
"""


# Pin all dynamic .job-timing text to deterministic placeholders before
# screenshot. Without this stabilization, the running job's "running for Ns"
# text drifts every render (Date.now() reads at render time).
_STABILIZE_DOM_JS = """
() => {
    const TIMING_PINS = {
        'phase6a_visual_todo'    : '0s',
        'phase6a_visual_running' : 'running for 1m 0s',
        'phase6a_visual_done'    : '0s',
        'phase6a_visual_dead'    : '0s',
        'phase6a_visual_history' : '0s',
    };
    document.querySelectorAll( '.job-card[data-id-hash]' ).forEach( card => {
        const idHash = card.getAttribute( 'data-id-hash' );
        const pin    = TIMING_PINS[ idHash ];
        if ( pin === undefined ) return;
        const timing = card.querySelector( '.job-timing' );
        if ( timing !== null ) timing.textContent = pin;
    } );
    return true;
}
"""


# ---------------------------------------------------------------------------
# Visual regression — Phase 6a jobs pane
# ---------------------------------------------------------------------------

def test_multiplexer_phase6a_jobs_pane_visual(
    request, clean_test_db, assert_snapshot_height_tolerant, logged_in_page,
):
    """
    Capture the Phase 6a jobs pane in its rendered baseline state.

    Fixture: 5 jobs spanning all 5 buckets:
        - todo bucket    (DeepResearchJob, status=pending → todo)
        - running bucket (PodcastGeneratorJob)
        - done bucket    (PresentationGeneratorJob)
        - dead bucket    (BugFixExpediterJob, status=failed → dead)
        - history bucket (TestFixExpediterJob, status=completed → done →
                          removed → history via reducer; per Pass 2 F19,
                          status field stays "done" end-to-end)

    Requires:
        - Server running on `:8000` with Testing config
        - `logged_in_page` fixture (authenticated session)
        - `assert_snapshot_height_tolerant` fixture (bug 660d02b4 — ≤1px
          height-tolerant; forgives the benign --update-vs-compare row-height flap)
        - `--update-snapshots` flag on first run to establish the baseline

    Ensures:
        - `/app/multiplexer` loads under authenticated session
        - boot.ts test hook (`window.__multiplexerTestHook`) is reachable
        - 5 job fixture events inject + render synchronously
        - Snapshot of `#jobs-pane` matches baseline (or establishes baseline
          on first run with `--update-snapshots`)

    Per design doc 08 § AC11: the baseline established here is the canonical
    Phase 6a visual state. NOT measured against `/app/notifications`.

    Parity A-2 #1 (2026-09-16, plan §3 R1) reversed Lane 0c: the Job Queues
    pane now starts VISIBLE, so the toggle-first reveal the 2026-07-02 sweep added
    to this test, test_multiplexer_section_toolbar.py and
    test_multiplexer_cold_load_hydration.py is gone from all three — a click on
    that toggle would now hide the pane.
    """
    page = logged_in_page

    # JOB-HISTORY COUNT STUB (row f0e00f01 R5, 2026-09-17). The pane renders a LIVE
    # `total` from GET /api/job-history in the band at x761–789, so a capture freezes
    # whatever the box's history held that day and the test reddens the next day —
    # the reason R5 said to rebaseline only AFTER a stub existed. Nobody owned it.
    #
    # The route is fulfilled with a fixed, empty history: the endpoint's real shape
    # (`jobs`/`total`/`filtered_by`/`limit`/`offset`, queues.py) with total 0. The five
    # cards in this frame do NOT come from this response — they are injected through
    # the boot test hook below — so stubbing it removes the moving number and leaves
    # the fixture intact. Only the collection endpoint is intercepted: `/job-history/all`
    # and the per-id DELETE keep their real routes, since this test never calls them and
    # a broader glob would silently swallow a future caller's request.
    def _stub_job_history( route ):
        route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = '{"jobs": [], "total": 0, "filtered_by": "all", "limit": 20, "offset": 0}',
        )

    page.route( "**/api/job-history?**", _stub_job_history )
    page.route( "**/api/job-history", _stub_job_history )

    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )

    # Wait for boot.ts test hook (post boot_complete).
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    # Inject the 5 job fixtures.
    page.evaluate( _INJECT_JOB_FIXTURES_JS )

    # Parity A-2 #1: the Job Queues pane starts visible, so no toolbar reveal.
    page.wait_for_selector( '[data-testid="multiplexer-jobs-pane"]', state="visible", timeout=10000 )

    # Wait for all 5 cards to render across their buckets.
    for id_hash in [
        "phase6a_visual_todo",
        "phase6a_visual_running",
        "phase6a_visual_done",
        "phase6a_visual_dead",
        "phase6a_visual_history",
    ]:
        page.wait_for_selector( f'[data-id-hash="{id_hash}"]', timeout=2000 )

    # Stabilize all dynamic .job-timing text before screenshot.
    page.evaluate( _STABILIZE_DOM_JS )

    # Font-load barrier (Gate D FAIL 1 — font-load race, task 006cb393): the
    # NotoColorEmoji status icons (⏳ todo / ⚙ running) load lazily; a screenshot
    # taken before the color-emoji font is ready captures a FALLBACK glyph — a
    # ~1881px contiguous block on this pane → intermittent visual FAIL. The
    # `networkidle` wait above does NOT gate font loading. Await
    # document.fonts.ready + two animation frames so the final glyph is committed
    # before capture. Mirrors test_multiplexer_task_editing.py:316-318 (the one
    # test already doing this right). Pure load barrier — comparators/tolerances
    # untouched.
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )

    # Brief settle window for any post-inject layout repaint.
    time.sleep( 0.2 )

    # Capture the entire #jobs-pane (avoids body-level layout drift).
    # Height-tolerant compare (bug 660d02b4): --update-snapshots and a plain
    # COMPARE can differ by ±1px on a benign sub-pixel row-height rounding
    # (e.g. 403 vs 404). The stock assert_snapshot is zero-tolerance on
    # dimensions (hard ValueError on a 1px flap); assert_snapshot_height_tolerant
    # forgives ≤1px height while staying strict on width + overlapping pixels.
    #
    # snap_y (rows 807a03bf, f0e00f01): the pane sits below the TTS pane, so its top
    # lands on whatever fraction the content above adds up to, and that fraction
    # moved between runs on unchanged code (398 px, 397 px, then 289 px of glyph
    # anti-aliasing in three text bands). The fixture moves it to an integer y
    # with a spacer and asserts it landed; see snap_to_integer_y in conftest.py.
    pane = page.locator( '[data-testid="multiplexer-jobs-pane"]' )
    assert_snapshot_height_tolerant( pane, name="multiplexer_phase6a_jobs_pane.png", snap_y=True )

    print( "✓ multiplexer_phase6a_jobs_pane: visual snapshot compared" )
