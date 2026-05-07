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
    request, clean_test_db, assert_snapshot, logged_in_page,
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
        - `assert_snapshot` fixture (pytest-playwright-visual-snapshot)
        - `--update-snapshots` flag on first run to establish the baseline

    Ensures:
        - `/app/multiplexer` loads under authenticated session
        - boot.ts test hook (`window.__multiplexerTestHook`) is reachable
        - 5 job fixture events inject + render synchronously
        - Snapshot of `#jobs-pane` matches baseline (or establishes baseline
          on first run with `--update-snapshots`)

    Per design doc 08 § AC11: the baseline established here is the canonical
    Phase 6a visual state. NOT measured against `/app/notifications`.
    """
    page = logged_in_page

    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )

    # Wait for boot.ts test hook (post boot_complete).
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    # Inject the 5 job fixtures.
    page.evaluate( _INJECT_JOB_FIXTURES_JS )

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

    # Brief settle window for any post-inject layout repaint.
    time.sleep( 0.2 )

    # Capture the entire #jobs-pane (avoids body-level layout drift).
    pane = page.locator( '[data-testid="multiplexer-jobs-pane"]' )
    assert_snapshot( pane, name="multiplexer_phase6a_jobs_pane.png" )

    print( "✓ multiplexer_phase6a_jobs_pane: visual snapshot compared" )
