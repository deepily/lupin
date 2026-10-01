"""
Both rest containers run Docker's init at PID 1 — row 3c86391e.

Measured 2026-09-30: lupin-rest-test held 48 zombie `chrome-headless` processes, all children
of PID 1, which is `python3 -m lupin_app.main`; `HostConfig.Init` was null. The test-suite job's
direct child is reaped (`process.poll()`, `process.wait()` in job.py), but the grandchildren of a
finished or killed suite reparent to PID 1, and the Python server never waits for children it
did not spawn. `init: true` puts tini at PID 1, which does.

⚠️ A compose change lands only on `up -d --force-recreate`; this guards the FILE, not the running
container. Venue: :7999-eligible, reads one YAML file.
"""
import pytest
import yaml

import cosa.utils.util as cu

COMPOSE = f"{cu.get_project_root()}/docker-compose.yml"
SERVICES = ( "lupin-rest-dev", "lupin-rest-test" )


@pytest.fixture( scope="module" )
def services():
    with open( COMPOSE ) as f:
        return yaml.safe_load( f )[ "services" ]


@pytest.mark.parametrize( "name", SERVICES )
def test_the_rest_service_runs_an_init_at_pid_1( services, name ):
    assert name in services, f"{name} is gone from docker-compose.yml — this guard is looking at nothing"
    assert services[ name ].get( "init" ) is True, (
        f"{name} has no `init: true`: orphaned grandchildren of a test-suite job become zombies of the "
        f"server at PID 1 (row 3c86391e)"
    )
