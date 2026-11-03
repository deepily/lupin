"""Two tests that run main must not change what a later test sees in os.environ."""
import os
import subprocess
import sys

import pytest

VICTIM   = "src/tests/unit/test_reuse_pack_route.py::test_a_packed_live_run_without_a_token_ceiling_is_refused_at_the_start_with_or_without_a_run_name"
SUSPECTS = (
    "src/tests/unit/test_reuse_needset_forced_judge.py::test_a_live_run_sets_the_run_name_and_ceiling_judges_each_row_and_closes_the_spend_run",
    "src/tests/unit/test_reuse_needset_expansion_run.py::test_without_live_main_plans_from_files_and_takes_the_run_name_from_the_env_file",
)


@pytest.mark.parametrize( "suspect", SUSPECTS )
def test_the_pack_route_refusal_still_passes_after_a_test_that_runs_main( suspect ):
    """
    Ensures: the suspect and then the victim pass together, in that order.

    The root is taken from this file's location only to name the tree the child runs in.
    """
    root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
    env  = { **os.environ, "LUPIN_ROOT": root, "PYTHONPATH": os.path.join( root, "src" ) }
    run  = subprocess.run( [ sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:randomly", suspect, VICTIM ], cwd=root, env=env, capture_output=True, text=True )
    assert run.returncode == 0, run.stdout[ -1500: ]
    assert "2 passed" in run.stdout
