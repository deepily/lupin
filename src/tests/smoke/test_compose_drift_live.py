#!/usr/bin/env python3
"""
Row 92374685 — the LIVE check: do the two rest containers still match their compose
services? A container that was only ever restarted after a compose change keeps the old
tmpfs, mounts and environment, and a restart will never fix it.

VENUE: :7999-eligible. It runs `docker inspect` and `docker compose config` (both read-only),
takes about a second, and needs no monopoly. It SKIPS a container that is not present, so a
host without the test stack still runs it.

A red names the drifted fields, never an environment value. The fix is
`docker compose up -d --force-recreate <container>`, or bounce-dev-server.sh for the dev one.
"""
import os
import subprocess
import sys

import pytest

import cosa.utils.util as cu

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import compose_drift_probe as probe_module  # noqa: E402


def _present( name ):
    try:
        return subprocess.run( [ "docker", "inspect", name ], capture_output=True, timeout=15 ).returncode == 0
    except ( OSError, subprocess.TimeoutExpired ):
        return False


# src/tests/conftest.py seeds JWT_SECRET_KEY with this prefix when the shell has none, so
# modules import at collection time. Compose must not see that value: the compose file takes
# JWT_SECRET_KEY from .env, and an inherited test value reads as drift on both containers
# (measured 2026-09-15, the first run of this test). A real value from the shell is kept.
CONFTEST_SEEDED_PREFIX = "test-only-generated-per-run-"


def _environ_without_the_conftest_seed():
    env = dict( os.environ )
    if env.get( "JWT_SECRET_KEY", "" ).startswith( CONFTEST_SEEDED_PREFIX ): del env[ "JWT_SECRET_KEY" ]
    return env


def test_the_conftest_seed_is_the_only_thing_removed( monkeypatch ):
    monkeypatch.setenv( "JWT_SECRET_KEY", CONFTEST_SEEDED_PREFIX + "abc" )
    assert "JWT_SECRET_KEY" not in _environ_without_the_conftest_seed()
    monkeypatch.setenv( "JWT_SECRET_KEY", "a-real-shell-value" )
    assert _environ_without_the_conftest_seed()[ "JWT_SECRET_KEY" ] == "a-real-shell-value"


@pytest.mark.parametrize( "container", [ "lupin-rest-dev", "lupin-rest-test" ] )
def test_the_container_matches_its_compose_service( container ):
    if not _present( container ): pytest.skip( f"{container} is not running on this host" )
    code, fields, _ = probe_module.probe( container, environ=_environ_without_the_conftest_seed() )
    assert code != probe_module.EXIT_UNKNOWN, f"the probe could not answer for {container}: {fields}"
    assert code == probe_module.EXIT_NO_DRIFT, (
        f"{container} lacks compose values a restart will not apply: {fields} — "
        f"run: docker compose up -d --force-recreate {container}"
    )
