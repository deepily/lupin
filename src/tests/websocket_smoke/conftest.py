"""
Collection-time notice for the websocket-smoke tree — a bare `pytest` here is NOT the suite.

WHY THIS FILE EXISTS. On 2026-08-20 I ran `pytest src/tests/websocket_smoke/`, got
"5 passed, 1 skipped", and reported the websocket-smoke tier as green on a merge
ladder. It is not the tier. Bare pytest collects the SIX pytest-style functions that
happen to live in this tree; the actual suite is driven by
`infrastructure/smoke_test_runner.py` (via `src/scripts/run-websocket-smoke-tests.sh`)
against a LIVE server, and it builds its result list at runtime rather than exposing
pytest test functions at all. Mr Radio caught the number by checking it against what
the tree contains instead of accepting it.

⇒ A green covering a fraction of a suite, reported as the suite, is worse than no run:
  it retires the question. This notice puts the warning AT THE LINE somebody actually
  reaches, because a caveat that lives only in a chat message or a merge checklist is
  one a future reader never sees.

SECOND TRAP, and it survives fixing the first. Even the CORRECT invocation talks to
whatever code the server is serving — the main tree — so running it from a worktree
branch says nothing about that branch. Websocket smoke is POST-merge, POST-bounce work
(Mr Radio's sequencing, 2026-08-20): merge, bounce :7999 with the sanctioned script,
THEN run it through run-websocket-smoke-tests.sh.

This file adds no fixtures and changes no behaviour. It only makes the mistake loud.
"""

import warnings


def pytest_collection_modifyitems( session, config, items ):
    """
    Warn, loudly and once, when this tree is collected by bare pytest.

    Requires:
        - items is the collected item list for the whole run

    Ensures:
        - emits a warning naming the real runner when any item from this directory
          is collected
        - never fails, skips, or reorders anything — the six genuine pytest tests here
          ARE worth running on their own, and a hard failure would break them
    """
    mine = [ item for item in items if "websocket_smoke" in str( item.fspath ) ]
    if not mine:
        return
    message = (
        f"BARE PYTEST OVER websocket_smoke IS NOT THE WEBSOCKET-SMOKE TIER — "
        f"collected {len( mine )} pytest function(s). The tier is "
        f"src/scripts/run-websocket-smoke-tests.sh "
        f"(python -m tests.websocket_smoke.infrastructure.smoke_test_runner), which needs "
        f"a LIVE server and reports its own totals. Do not report this run as that tier. "
        f"It also exercises only what the SERVER is serving, so from a worktree branch it "
        f"says nothing about your branch until you merge and bounce :7999."
    )
    warnings.warn( message, UserWarning, stacklevel=1 )
