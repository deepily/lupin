"""
Reads the junit report of the docker smoke files and says whether the step passed.

The three files start a throwaway Postgres or read the compute containers, so inside the merge gate's
containers every one of their tests skips. A skip there is a test that did not run, not a pass.
This module counts a skip, an error and a file with no test as failures. The host step cannot go green
on a run that checked nothing.

Called by src/tests/run-docker-smoke-gate.sh; the exit codes are 0 pass, 1 failed, 2 nothing checked.
"""

import sys
import xml.etree.ElementTree as ET

EXPECTED_FILES = (
    "test_credential_mount_shape",
    "test_db_roles_rollback_real_postgres",
    "test_db_grants_real_postgres",
)


def summarize( junit_path, expected=EXPECTED_FILES ):
    """
    Count the outcomes in one junit file.

    Requires:
        - junit_path names a junit xml file
        - expected is a sequence of test module names, without the .py suffix

    Ensures:
        - returns { total, passed, failed, skipped, skips, missing }
        - failed counts failures, errors, skips and missing files together
        - skips is a list of "node id: reason" strings, in report order
        - missing lists each expected module that has no test case in the report

    Raises:
        - xml.etree.ElementTree.ParseError when the file is not xml
        - OSError when the file cannot be read
    """
    cases   = ET.parse( junit_path ).getroot().iter( "testcase" )
    total   = passed = failed = 0
    skips   = []
    seen    = set()
    for case in cases:
        total      += 1
        classname   = case.get( "classname", "" )
        seen.update( classname.split( "." ) )
        skipped     = case.find( "skipped" )
        if skipped is not None:
            skips.append( f"{classname}::{case.get( 'name', '' )}: {skipped.get( 'message', '' )}" )
            failed += 1
        elif case.find( "failure" ) is not None or case.find( "error" ) is not None:
            failed += 1
        else:
            passed += 1
    missing = [ name for name in expected if name not in seen ]
    return {
        "total"   : total,
        "passed"  : passed,
        "failed"  : failed + len( missing ),
        "skipped" : len( skips ),
        "skips"   : skips,
        "missing" : missing,
    }


def render( summary ):
    """
    Turn a summary into the lines the runner prints.

    Requires:
        - summary comes from summarize()

    Ensures:
        - the text holds Total Tests, Passed, Failed and Skipped lines, one per line
        - each skip and each missing file gets its own line above the counts
    """
    lines  = [ f"SKIPPED {skip}" for skip in summary[ "skips" ] ]
    lines += [ f"MISSING {name}: no test of this file is in the report" for name in summary[ "missing" ] ]
    lines += [
        f"Total Tests: {summary[ 'total' ]}",
        f"Passed: {summary[ 'passed' ]}",
        f"Failed: {summary[ 'failed' ]}",
        f"Skipped: {summary[ 'skipped' ]}",
    ]
    return "\n".join( lines )


def main( argv ):
    """
    Print the verdict for one junit file.

    Requires:
        - argv holds the program name and the junit path

    Ensures:
        - returns 0 when nothing failed, was skipped or is missing
        - returns 1 when any did
        - returns 2, with a refusal line and no counts, when the report is absent or not xml
    """
    path = argv[ 1 ] if len( argv ) > 1 else ""
    try:
        summary = summarize( path )
    except ( OSError, ET.ParseError ) as error:
        print( f"REFUSING: the junit report could not be read ({error}). Nothing was checked." )
        return 2
    print( render( summary ) )
    return 1 if summary[ "failed" ] else 0


if __name__ == "__main__":
    sys.exit( main( sys.argv ) )  # pragma: no cover  (entry point; main() is tested directly)
