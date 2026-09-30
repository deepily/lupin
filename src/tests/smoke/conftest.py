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

PORTS AROUND :7999 — 7998 IS TAKEN, AND IT ANSWERS /health WITH 200
  Measured 2026-09-01. The three adjacent ports are all occupied, on both the
  IPv4 and IPv6 stacks:

      7998  lupin-model-server   <- NOT free, and NOT the app
      7999  lupin-rest-dev       <- the dev venue
      8000  lupin-rest-test      <- the test venue (maps to 7999 in-container)
      8001  the arbiter

  The trap is 7998 specifically, and it is sharper than "that port is in use".
  `GET :7998/health` returns **200** with `{"status":"ready","models_loaded":
  [...]}` — so a venue guard that decides "is my server up?" by health-checking
  a port sees a HEALTHY SERVER THAT IS THE WRONG SERVICE, proceeds, and then
  fails somewhere confusing downstream (`/auth/login` -> 404, because the model
  server has no such route). A /health check answers "is something alive here",
  never "is this the service I meant".

  SCOPE, narrowed by a sweep of this directory rather than left implied: every
  other smoke test here health-checks its OWN configured base URL, which is
  correct and cannot hit the wrong service. `test_model_server_smoke.py` targets
  :7998 deliberately and already distinguishes it from :7999. So this is NOT a
  latent defect in the existing guards — it bites when a base URL is REPOINTED,
  which is what a negative arm does, and it is the negative arm that had it.

  ⇒ NEVER ASSUME A PORT IS FREE, INCLUDING FOR A NEGATIVE ARM. If a test needs
  an unreachable address — to prove its own venue guard skips rather than
  errors — it must BIND a port and let the bind fail, then use the port it
  actually got:

      import socket
      s = socket.socket()
      s.bind( ( "127.0.0.1", 0 ) )      # 0 = let the OS pick a free one
      free_port = s.getsockname()[ 1 ]
      s.close()

  Receipt for why this is written down: a negative arm was pointed at 7998 on
  the assumption that a port next to 7999 would be free. It was not. The arm
  reported a FAILURE that looked like a broken venue guard, and the guard was
  correct — it declined to skip because something really did answer. An
  assumed-dead port is the same defect as an assumed-empty population: the
  wrong result and the right result print the same thing.
"""

import os

import pytest

from tests.smoke.tmux_isolation import restore_tmux_context, strip_tmux_context


@pytest.fixture( scope="session", autouse=True )
def tmux_fleet_socket_isolation( tmp_path_factory ):
    """
    Fixtures arm at first-test SETUP; import/collection-time tmux in smoke
    modules stays prohibited.

    Fleet-killer CLASS guard (P0, 2026-07-14): strip the ambient tmux pane
    context ($TMUX/$TMUX_PANE) and pin a per-session private TMUX_TMPDIR so
    ANY bare `tmux` from ANY smoke test auto-isolates from the shared fleet
    socket (/tmp/tmux-<uid>/default). On tmux 3.2a an inherited $TMUX BEATS
    TMUX_TMPDIR for socket selection — stripping is what makes the pin win.
    Pure logic lives in tests.smoke.tmux_isolation (unit-tested to 100%);
    this wrapper is measured under smoke-suite coverage.

    The strip arms at first-test setup and stays live through the end of the
    WHOLE pytest session — in a mixed repo-root run, non-smoke tests running
    after arm-time also see the stripped env (by design: no legitimate test
    may address the fleet socket). The prior environment is restored
    byte-for-byte at session teardown.

    Requires:
        - tmp_path_factory (pytest built-in session fixture)

    Ensures:
        - TMUX/TMUX_PANE absent and TMUX_TMPDIR pinned to a private dir for
          the whole pytest session from first-test setup onward
        - yields the pinned dir (the AC2 regression test requests this
          fixture BY NAME and asserts the pin)
        - snapshot restored byte-for-byte at session teardown (absent keys
          end absent; present keys end at their snapshot value)

    Raises:
        - None

    Design: fix plan §5.2 + revision-handoff §4 (shared-mutable-state matrix).
    """
    snapshot = strip_tmux_context( os.environ )
    pinned   = tmp_path_factory.mktemp( "tmux-isolated" )
    os.environ[ "TMUX_TMPDIR" ] = str( pinned )

    yield pinned

    restore_tmux_context( os.environ, snapshot )


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
    # Flags below are defined by individual live-smoke tests' OWN argparse and
    # passed through by run-presentation-regression.sh. pytest must ACCEPT them
    # (else "unrecognized arguments" aborts the tier before collection); the
    # tests still read the values from sys.argv themselves. Registered here to
    # kill the drift class where a runner flag has no matching pytest option.
    parser.addoption(
        "--content-model",
        action  = "store",
        default = None,
        help    = "Override presentation content model (consumed by "
                  "test_presentation_live_smoke's own argparse)"
    )
    parser.addoption(
        "--lead-model",
        action  = "store",
        default = None,
        help    = "Override deep-research lead model (consumed by "
                  "test_research_to_presentation_live_smoke's own argparse)"
    )
    # NOTE: --timeout is intentionally NOT registered here — pytest already
    # provides it (pytest-timeout plugin), so re-adding it raises an argparse
    # option conflict. The runner's --timeout is accepted by that plugin.
    parser.addoption(
        "--yaml-path",
        action  = "store",
        default = None,
        help    = "Explicit YAML source path for render-only (consumed by "
                  "test_presentation_render_only_smoke's own argparse)"
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
