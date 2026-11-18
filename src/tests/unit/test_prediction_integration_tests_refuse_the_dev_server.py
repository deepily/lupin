"""
The three prediction integration tests refuse a base url on the dev server, :7999.

Each file posts to the reset route with drop_table, which empties the decision rows. The proof imports
each file in a fresh interpreter with the variable set. A guard that was removed shows as a clean import
where a refusal belongs. The restart file takes its base url from the engine file.
"""

import os
import subprocess
import sys

import pytest

from tests.helpers.dev_server_guard import refuse_dev_server

FILES = [ "test_prediction_engine_e2e", "test_prediction_restart_e2e", "test_prediction_vote_steering_e2e" ]


def _import( name, base_url ):
    """Import one integration file in a fresh interpreter; return the finished process."""
    env = dict( os.environ, LUPIN_TEST_BASE_URL=base_url, PYTHONPATH=os.environ[ "LUPIN_ROOT" ] + "/src" )
    return subprocess.run( [ sys.executable, "-c", f"import tests.integration.{name}" ], env=env, capture_output=True, text=True, timeout=120 )


@pytest.mark.parametrize( "name", FILES )
def test_a_file_refuses_a_base_url_on_the_dev_server( name ):
    done = _import( name, "http://localhost:7999" )
    assert done.returncode != 0 and "dev server" in done.stderr, done.stderr[ -400: ]


@pytest.mark.parametrize( "name", FILES )
def test_the_same_file_imports_on_the_test_server_url( name ):
    done = _import( name, "http://localhost:8000" )
    assert done.returncode == 0, done.stderr[ -400: ]


@pytest.mark.parametrize( "url", [ "http://127.0.0.1:7999", "https://dev.example:7999/x" ] )
def test_any_host_on_port_7999_is_refused( url ):
    with pytest.raises( RuntimeError, match="7999" ):
        refuse_dev_server( url )


@pytest.mark.parametrize( "url", [ "http://localhost:8000", "http://localhost", "http://localhost:17999" ] )
def test_other_urls_pass_through_unchanged( url ):
    assert refuse_dev_server( url ) == url
