"""
Unified Watchdog Initialization Facade.

Single entry point for initializing both queue watchdogs at server startup:
    - DeadQueueWatchdog (BFE — fires on dead-queue push for crashed jobs)
    - TestSuiteCompletionWatchdog (TFE — fires on done-queue push for failed test suites)

This avoids the bug where main.py initialized only one watchdog and the other
silently no-op'd because its singleton was never constructed.
"""

from typing import Optional, Tuple

from cosa.rest.dead_queue_watchdog import (
    DeadQueueWatchdog,
    init_watchdog as init_bfe_watchdog,
)
from cosa.rest.test_suite_completion_watchdog import (
    TestSuiteCompletionWatchdog,
    init_watchdog as init_tfe_watchdog,
)


def init_watchdogs(
    config_mgr,
    todo_queue,
    debug: bool = False,
    verbose: bool = False,
) -> Tuple[ Optional[ DeadQueueWatchdog ], Optional[ TestSuiteCompletionWatchdog ] ]:
    """
    Initialize both queue watchdog singletons in one call.

    Requires:
        - config_mgr is an initialized ConfigurationManager
        - todo_queue is the active TodoFifoQueue (used by both watchdogs to
          enqueue spawned BFE/TFE jobs)

    Ensures:
        - DeadQueueWatchdog singleton is constructed via dead_queue_watchdog.init_watchdog
        - TestSuiteCompletionWatchdog singleton is constructed via
          test_suite_completion_watchdog.init_watchdog
        - Failures in one watchdog do NOT prevent the other from initializing
        - A single summary line is logged showing the enabled state of both

    Args:
        config_mgr: ConfigurationManager
        todo_queue: TodoFifoQueue
        debug: Enable debug output for both watchdogs
        verbose: Enable verbose output (TFE only — BFE has no verbose flag)

    Returns:
        Tuple of (bfe_watchdog, tfe_watchdog). Either element may be None if
        construction failed for that watchdog.
    """
    bfe_watchdog: Optional[ DeadQueueWatchdog ]                 = None
    tfe_watchdog: Optional[ TestSuiteCompletionWatchdog ]       = None

    # BFE watchdog
    try:
        bfe_watchdog = init_bfe_watchdog( config_mgr, todo_queue, debug=debug )
    except Exception as e:
        print( f"[Watchdogs] BFE init FAILED: {e}" )

    # TFE watchdog
    try:
        tfe_watchdog = init_tfe_watchdog(
            config_mgr,
            todo_queue=todo_queue,
            repair_tracker=None,
            debug=debug,
            verbose=verbose,
        )
    except Exception as e:
        print( f"[Watchdogs] TFE init FAILED: {e}" )

    bfe_state = "ENABLED" if ( bfe_watchdog is not None and getattr( bfe_watchdog, "enabled", False ) ) else "DISABLED"
    tfe_state = "ENABLED" if ( tfe_watchdog is not None and getattr( tfe_watchdog, "enabled", False ) ) else "DISABLED"
    print( f"[Watchdogs] BFE={bfe_state}, TFE={tfe_state}" )

    return bfe_watchdog, tfe_watchdog
