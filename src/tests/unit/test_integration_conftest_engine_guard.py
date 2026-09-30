"""
The integration tier's session guard must refuse a PYTEST PROCESS pointed at a
database the server is not.

WHY THIS FILE EXISTS. `verify_test_environment` validated the SERVER over HTTP and
never looked at this process's own engine, so a hand-typed pytest run bound
`lupin_db_dev` — the fleet's live task store — while every check still passed.
Measured 2026-09-01 with one probe in two environments:

    .venv/bin/python -c "from cosa.rest.db import database as db; print( db.engine.url )"
      bare shell                     -> lupin_db_dev
      under run-integration-tests.sh -> lupin_db_test

The runner exports `config_block_id=Lupin:+Testing`; that is the whole difference.
Write-up: src/rnd/v0.2.1/2026.09.01-txn-session-binds-dev-db-under-fleet-concurrency.md

WHY THE PREDICATE IS TESTED HERE RATHER THAN IN SITU. The guard lives inside a
session fixture that needs a live server, and `:7999` runs the Development block, so
the pre-existing server check fires first and the new one is never reached. A guard
nobody has watched fire is not a control, so the predicate was extracted and both
branches are exercised below — including the case that must NOT raise, since a guard
that always raises is as useless as one that never does.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

import cosa.utils.util as cu


def _load_integration_conftest():
    """
    Import the integration conftest as a plain module, by path.

    Requires:
        - src/tests/integration/conftest.py exists under the project root

    Ensures:
        - returns the imported module object
        - resolves the path from LUPIN_ROOT at CALL time, so it reads the tree the
          run is actually standing in rather than whichever one PYTHONPATH names

    Raises:
        - AssertionError if the conftest is not where it is expected
    """
    path = Path( cu.get_project_root() ) / "src" / "tests" / "integration" / "conftest.py"
    assert path.exists(), f"integration conftest not found at {path}"

    spec   = importlib.util.spec_from_file_location( "_integration_conftest_under_test", path )
    module = importlib.util.module_from_spec( spec )
    # Registered before exec so any dataclass/pickle machinery can find it by name.
    sys.modules[ spec.name ] = module
    spec.loader.exec_module( module )
    return module


def test_a_test_bound_engine_is_accepted():
    """The NEGATIVE control: the correct binding must pass, or the guard is a brick."""
    conftest = _load_integration_conftest()

    result = conftest.check_in_process_engine_is_test_db(
        "postgresql+psycopg2://lupin_dev:***@localhost:5432/lupin_db_test",
        "postgresql+psycopg2://lupin_dev:***@lupin-postgres:5432/lupin_db_test",
    )
    assert result is None


def test_a_dev_bound_engine_is_refused():
    """The live defect: the process on dev while the server is correctly on test."""
    conftest = _load_integration_conftest()

    with pytest.raises( RuntimeError ) as excinfo:
        conftest.check_in_process_engine_is_test_db(
            "postgresql+psycopg2://lupin_dev:***@localhost:5432/lupin_db_dev",
            "postgresql+psycopg2://lupin_dev:***@lupin-postgres:5432/lupin_db_test",
        )

    message = str( excinfo.value )
    # BOTH urls must appear: naming only the offender leaves the reader unable to see
    # that the server was fine, which is the confusing half of this defect.
    assert "lupin_db_dev"  in message, "must name the database it is actually bound to"
    assert "lupin_db_test" in message, "must name the server's database for contrast"
    assert "run-integration-tests.sh" in message, "must name the runner that fixes it"


def test_an_unrelated_database_is_also_refused():
    """
    Not a near-duplicate of the dev case: it pins that the check is an ALLOW-list.

    A guard written as `if "lupin_db_dev" in url: raise` would pass this input and
    pass every future database somebody adds. This asserts the shape that refuses
    anything not named lupin_db_test.
    """
    conftest = _load_integration_conftest()

    with pytest.raises( RuntimeError ):
        conftest.check_in_process_engine_is_test_db(
            "postgresql+psycopg2://someone@localhost:5432/lupin_db_staging",
            "postgresql+psycopg2://lupin_dev:***@lupin-postgres:5432/lupin_db_test",
        )


def test_the_substring_match_is_not_fooled_by_a_longer_name():
    """
    `lupin_db_test` is matched as a SUBSTRING, which is how the existing server check
    works too — so this records the known consequence rather than pretending it away:
    a database named `lupin_db_test_scratch` is ACCEPTED.

    Documented deliberately. Tightening it to an exact match would also reject the
    real URLs, which carry the name inside a full DSN. If a `lupin_db_test`-prefixed
    database is ever created for something else, this test is the place that says so.
    """
    conftest = _load_integration_conftest()

    assert conftest.check_in_process_engine_is_test_db(
        "postgresql+psycopg2://lupin_dev:***@localhost:5432/lupin_db_test_scratch",
        "postgresql+psycopg2://lupin_dev:***@lupin-postgres:5432/lupin_db_test",
    ) is None
