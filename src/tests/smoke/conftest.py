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

`--auto-proxy` under pytest also drives the module-scoped autouse
fixture `_auto_proxy_for_module` defined below, which launches a
notification proxy subprocess before any test in a module that contains
an `EmbeddedProxyMixin` subclass. This closes the May-5 Phase 4b finding
that pre_run_hook (the legacy startup path) only fires on `__main__`
invocation, not under pytest discovery — without the fixture, pytest
runs would 503-cascade despite the `--auto-proxy` flag being present.
See `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md`
§Phase 5 for the design rationale.
"""

import os

import pytest


def pytest_addoption( parser ):
    """
    Register custom CLI flags consumed by individual smoke tests and by
    the module-scoped auto-proxy fixture below.

    Most flags are read from `sys.argv` by each test's own argparse
    machinery in `live_pipeline_base.py`. `--auto-proxy` is additionally
    consumed by `_auto_proxy_for_module` to launch a notification proxy
    under pytest where `pre_run_hook` does not fire.
    """
    parser.addoption(
        "--auto-proxy",
        action  = "store_true",
        default = False,
        help    = "Enable auto-answer proxy for interactive notification gates "
                  "(consumed by live_smoke tests via their own argparse AND "
                  "by the module-scoped auto-proxy fixture below)"
    )
    parser.addoption(
        "--proxy-debug",
        action  = "store_true",
        default = False,
        help    = "Enable debug output and real-time log streaming for the "
                  "auto-launched proxy (consumed by the module-scoped fixture)"
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


@pytest.fixture( scope="module", autouse=True )
def _auto_proxy_for_module( request ):
    """
    Auto-launch a notification proxy subprocess for the test module when
    `--auto-proxy` is passed under pytest.

    Requires:
        - `--auto-proxy` is registered via pytest_addoption above
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL/_PASSWORD env vars set
          (when --auto-proxy is active)

    Ensures:
        - When `--auto-proxy` is False or the test module contains no
          EmbeddedProxyMixin subclass, the fixture is a no-op
        - When active, instantiates the EmbeddedProxyMixin subclass and
          calls `_start_proxy(...)` with module-credentials before any
          test runs
        - Proxy is stopped at module teardown
        - On startup failure, calls `pytest.fail(..., pytrace=False)` to
          abort the affected module before scenarios run (cascade
          prevention contract from May-5 Phase 2)

    Scope is module-not-session because each test file declares its own
    PROXY_PROFILE — one session-wide proxy cannot serve all of them.
    See `src/rnd/v0.1.7/2026.05.05-503-cascade-real-root-cause/01-design.md`
    §Phase 5 for the design rationale.
    """
    if not request.config.getoption( "--auto-proxy", default=False ):
        yield
        return

    from tests.smoke.utilities.embedded_proxy import EmbeddedProxyMixin

    module      = request.module
    proxy_class = None
    for name in dir( module ):
        obj = getattr( module, name )
        if not isinstance( obj, type ): continue
        if not issubclass( obj, EmbeddedProxyMixin ): continue
        if obj is EmbeddedProxyMixin: continue
        # Only classes DEFINED in this module — skip imported parents
        # (e.g. InteractiveSmokeTest is the base, ProxyIntegrationTest is
        # the concrete subclass we want).
        if obj.__module__ != module.__name__: continue
        proxy_class = obj
        break

    if proxy_class is None:
        yield
        return

    holder   = proxy_class()
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    debug    = request.config.getoption( "--proxy-debug", default=False )

    try:
        holder._start_proxy( debug=debug, email=email, password=password )
    except RuntimeError as e:
        pytest.fail(
            f"Proxy startup failed for module {module.__name__} "
            f"(class {proxy_class.__name__}): {e}",
            pytrace=False,
        )

    yield

    holder._stop_proxy()
