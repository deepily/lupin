"""
Pytest config for smoke tests.

Registers `--auto-proxy` and `--cost-cap-usd` as accepted CLI flags so
pytest doesn't error on `unrecognized arguments` when a scheduler injects
them at the suite-level (Phase 6 of 2026.05.01-postmortem-fixes-plan.md).

Background:
  - Two smoke tests (`test_presentation_live_smoke`,
    `test_research_to_presentation_live_smoke`) require `--auto-proxy`
    and a cost cap. Their `pre_run_hook` raises `RuntimeError` if
    `--auto-proxy` is missing from `sys.argv`.
  - Those tests parse `sys.argv` themselves via `argparse` inside the
    test function (see `tests/smoke/utilities/live_pipeline_base.py`).
  - When pytest is the parent process, pytest itself rejects unknown
    flags at startup. To allow the scheduler to pass these flags
    transparently, we register them here as no-op pytest options —
    pytest accepts them silently; the test's own argparse picks them up
    from `sys.argv` at run time.

This conftest does NOT consume the flags or change pytest behavior — it
exists ONLY so pytest doesn't reject the args before reaching the test
functions that actually parse them.
"""

def pytest_addoption( parser ):
    """
    Register custom CLI flags consumed by individual smoke tests.

    These are registered as pytest options purely so pytest accepts them
    without error. The actual flag values are read from `sys.argv` by
    each test's own argparse machinery in `live_pipeline_base.py`.
    """
    parser.addoption(
        "--auto-proxy",
        action  = "store_true",
        default = False,
        help    = "Enable auto-answer proxy for interactive notification gates "
                  "(consumed by live_smoke tests via their own argparse)"
    )
    parser.addoption(
        "--cost-cap-usd",
        action  = "store",
        default = None,
        help    = "Cost cap in USD for live LLM calls (consumed by live_smoke "
                  "tests via their own argparse)"
    )
    parser.addoption(
        "--no-confirm",
        action  = "store_true",
        default = False,
        help    = "Skip the test-runner confirmation prompt (consumed by "
                  "live_smoke tests via their own argparse)"
    )
    parser.addoption(
        "--group",
        action  = "store",
        default = None,
        help    = "Filter scenarios by group, e.g. 'expediter' or 'crud' "
                  "(consumed by test_proxy_integration's own argparse)"
    )
    parser.addoption(
        "--scenario-id",
        action  = "store",
        default = None,
        help    = "Filter to a single scenario ID (consumed by tests' own argparse)"
    )
