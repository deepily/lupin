"""
The run spec: what Rick froze, checked against the commit before any run starts.

The feature list, the plan and the acceptance tests are frozen together at one sha (plan 3, section 7.2).
A run is given that sha as its server commit and the test ids that sha holds. Nothing is read from the working tree.
The map from tests to features is checked here. So a run cannot start against a test no feature owns, or a feature no test covers.
"""
import ast
import posixpath
import re

from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import run as harness

FEATURE_LIST = "src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.25-experiment-build-task-feature-list.md"
TEST_DIR     = "src/tests/experiment_acceptance"
FEATURE_ROW  = re.compile( r"^\| (F\d{2})(?: \(opt\))? \|", re.M )
FUNCTIONS    = ( ast.FunctionDef, ast.AsyncFunctionDef )


def feature_ids( text ):
    """
    Return the feature ids in a feature list's tables, in order.

    Requires:
        - text is the feature list
    """
    return FEATURE_ROW.findall( text )


def _features_of( node ):
    """Return the feature ids a test function is marked with, in the order of its decorators."""
    found = []
    for decorator in node.decorator_list:
        if isinstance( decorator, ast.Call ) and isinstance( decorator.func, ast.Attribute ) and decorator.func.attr == "feature":
            found.extend( argument.value for argument in decorator.args if isinstance( argument, ast.Constant ) )
    return found


def collect_tests( sources ):
    """
    Map each acceptance test to the features it is marked with.

    Requires:
        - sources maps a test file path to its text; only the files named test_*.py are read

    Ensures:
        - returns { "<path>::<function>": [ feature ids ] } for every module-level test function, in file order
        - a test with no feature marker maps to an empty list

    Raises:
        - HarnessError FEATURE_MAP if a file holds a Test class, because its methods would go uncounted
    """
    tests = {}
    for path in sorted( sources ):
        if not posixpath.basename( path ).startswith( "test_" ): continue
        for node in ast.parse( sources[ path ] ).body:
            if isinstance( node, ast.ClassDef ) and node.name.startswith( "Test" ): raise err.HarnessError( err.FEATURE_MAP, f"{path} holds the class {node.name}, whose tests would go uncounted" )
            if isinstance( node, FUNCTIONS ) and node.name.startswith( "test_" ): tests[ f"{path}::{node.name}" ] = _features_of( node )
    return tests


def check_feature_map( tests, ids ):
    """
    Refuse a test set that does not map onto the feature list.

    Requires:
        - tests is the result of collect_tests and ids the feature ids of the list

    Ensures:
        - returns None when every test carries a marker, every marker names a listed feature and every feature has a test

    Raises:
        - HarnessError FEATURE_MAP naming the unmarked tests, the unknown features or the uncovered features
    """
    if not tests: raise err.HarnessError( err.FEATURE_MAP, "no acceptance tests were found" )
    unmarked = [ test for test, features in tests.items() if not features ]
    if unmarked: raise err.HarnessError( err.FEATURE_MAP, f"tests with no feature marker: {unmarked}" )
    cited    = { feature for features in tests.values() for feature in features }
    unknown  = sorted( cited - set( ids ) )
    if unknown: raise err.HarnessError( err.FEATURE_MAP, f"markers naming no listed feature: {unknown}" )
    uncovered = [ feature for feature in ids if feature not in cited ]
    if uncovered: raise err.HarnessError( err.FEATURE_MAP, f"features with no test: {uncovered}" )


def build_spec( git, run_id, arm, model_id, frozen_sha, cap_seat_hours, main_ref="main" ):
    """
    Build the spec of one run from the frozen commit.

    Requires:
        - git has resolve, is_ancestor, list_at and file_at, as GitRepo does
        - frozen_sha is the sha Rick named; main_ref names the line the freeze must be on

    Ensures:
        - server_commit is the full sha of the frozen commit
        - test_ids are the tests that commit holds, in file order, so two runs of one freeze get one list
        - the result passes run.check_spec

    Raises:
        - HarnessError NOT_FROZEN if main_ref does not hold the commit
        - HarnessError FEATURE_MAP for a map that does not close
        - HarnessError BAD_ARM or BAD_SPEC from check_spec
    """
    full = git.resolve( frozen_sha )
    if not git.is_ancestor( full, main_ref ): raise err.HarnessError( err.NOT_FROZEN, f"{full} is not on {main_ref}" )
    sources = { path: git.file_at( full, path ) for path in git.list_at( full, TEST_DIR ) if path.endswith( ".py" ) }
    tests   = collect_tests( sources )
    check_feature_map( tests, feature_ids( git.file_at( full, FEATURE_LIST ) ) )
    spec    = { "run_id" : run_id, "arm" : arm, "model_id" : model_id, "server_commit" : full, "cap_seat_hours" : cap_seat_hours, "test_ids" : list( tests ) }
    harness.check_spec( spec )
    return spec
