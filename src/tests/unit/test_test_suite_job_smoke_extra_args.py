"""
Unit test for the per-suite `test suite {suite} extra pytest args` INI keys
introduced in Phase 6 / Cluster B of the 2026-05-01 post-mortem fixes plan.

Asserts that:
1. The INI keys exist with expected default values (smoke gets the
   --auto-proxy + --cost-cap-usd; others empty).
2. The matching splainer entries exist (CLAUDE.md mandate: every INI key
   must have a splainer doc string).
3. The smoke conftest.py registers --auto-proxy and --cost-cap-usd so
   pytest doesn't reject these args.

The end-to-end behavior (TestSuiteJob._run_suite actually appends the
extra args to the subprocess command) is not unit-tested here because it
requires either a live subprocess or substantial subprocess mocking; the
INI-key + conftest invariants below are the meaningful hooks that make
the integration work, and a regression in either would catch the bug.
"""

import os

import pytest


_LUPIN_ROOT = os.environ.get(
    "LUPIN_ROOT",
    "/mnt/DATA01/include/www.deepily.ai/projects/lupin",
)


def _read_ini_keys( ini_path, prefix ):
    """
    Parse a flat 'key = value' INI without configparser quoting headaches.
    Returns a dict of keys starting with `prefix`.
    """
    keys = {}
    with open( ini_path, encoding="utf-8" ) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith( "#" ) or stripped.startswith( "[" ):
                continue
            if "=" not in stripped:
                continue
            key, _, value = stripped.partition( "=" )
            key = key.strip()
            if key.startswith( prefix ):
                keys[ key ] = value.strip()
    return keys


def test_per_suite_extra_pytest_args_keys_exist_in_lupin_app_ini():
    """
    All five per-suite extra-args keys must exist (smoke, integration, e2e,
    websocket, unit). Missing any of them is a regression of Phase 6.
    """
    ini_path = os.path.join( _LUPIN_ROOT, "src", "conf", "lupin-app.ini" )
    keys = _read_ini_keys( ini_path, "test suite " )

    expected_keys = {
        "test suite smoke extra pytest args",
        "test suite integration extra pytest args",
        "test suite e2e extra pytest args",
        "test suite websocket extra pytest args",
        "test suite unit extra pytest args",
    }

    missing = expected_keys - set( keys.keys() )
    assert not missing, f"Missing per-suite extra-args INI keys: {missing}"


def test_smoke_extra_args_default_includes_auto_proxy():
    """
    The smoke suite's extra-args default MUST include --auto-proxy and
    --cost-cap-usd so the two live_smoke tests don't bail in pre_run_hook.
    Empty or missing default reverts to the 2026-04-30 22:15-EDT failure mode.
    """
    ini_path = os.path.join( _LUPIN_ROOT, "src", "conf", "lupin-app.ini" )
    keys = _read_ini_keys( ini_path, "test suite smoke" )

    default = keys.get( "test suite smoke extra pytest args", "" )

    assert "--auto-proxy" in default, (
        f"smoke extra-args missing --auto-proxy: {default!r}. "
        f"This is the regression target — without it, "
        f"test_presentation_live_smoke and test_research_to_presentation_live_smoke "
        f"will bail in pre_run_hook with RuntimeError on the next :8000 run."
    )
    assert "--cost-cap-usd" in default, (
        f"smoke extra-args missing --cost-cap-usd: {default!r}"
    )


def test_per_suite_extra_args_have_splainer_entries():
    """
    Per CLAUDE.md mandate, every INI key in lupin-app.ini must have a
    matching splainer entry in lupin-app-splainer.ini.
    """
    splainer_path = os.path.join(
        _LUPIN_ROOT, "src", "conf", "lupin-app-splainer.ini"
    )
    splainer_keys = _read_ini_keys( splainer_path, "test suite " )

    expected = {
        "test suite smoke extra pytest args",
        "test suite integration extra pytest args",
        "test suite e2e extra pytest args",
        "test suite websocket extra pytest args",
        "test suite unit extra pytest args",
    }

    missing = expected - set( splainer_keys.keys() )
    assert not missing, (
        f"Missing splainer entries for: {missing}. "
        f"CLAUDE.md mandate: every INI key must be explained in lupin-app-splainer.ini."
    )

    # Smoke entry should mention provenance + the regression context
    smoke_explanation = splainer_keys.get( "test suite smoke extra pytest args", "" )
    assert "auto-proxy" in smoke_explanation.lower() or "live_smoke" in smoke_explanation.lower(), (
        f"smoke splainer entry should reference --auto-proxy / live_smoke: {smoke_explanation!r}"
    )


def test_smoke_conftest_registers_auto_proxy_option():
    """
    `src/tests/smoke/conftest.py` must register --auto-proxy and
    --cost-cap-usd via pytest_addoption so pytest accepts the flags
    without erroring when the scheduler injects them at the suite level.
    """
    conftest_path = os.path.join(
        _LUPIN_ROOT, "src", "tests", "smoke", "conftest.py"
    )
    assert os.path.isfile( conftest_path ), (
        f"src/tests/smoke/conftest.py is missing — scheduler-injected flags "
        f"like --auto-proxy will cause pytest to error before any test runs."
    )

    with open( conftest_path, encoding="utf-8" ) as f:
        content = f.read()

    assert "pytest_addoption" in content, (
        f"smoke conftest.py must define pytest_addoption to accept custom flags"
    )
    assert "--auto-proxy" in content, (
        f"smoke conftest.py must register --auto-proxy"
    )
    assert "--cost-cap-usd" in content, (
        f"smoke conftest.py must register --cost-cap-usd"
    )
