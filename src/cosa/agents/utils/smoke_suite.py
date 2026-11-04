#!/usr/bin/env python3
"""
Shared runner for an agent package's full smoke-test suite.

Imports each listed module, calls its quick_smoke_test(), and prints a pass/fail summary.
Used by the podcast and presentation generators' __main__ modules.
"""


def run_import_smoke_suite( title: str, modules: list, error_chars: int = 80 ) -> bool:
    """
    Import each module, run its quick_smoke_test(), and print a summary table.

    Requires:
        - title names the package, such as "Podcast Generator"
        - modules is a list of ( display name, dotted module path ) pairs
        - each module defines quick_smoke_test()
        - error_chars is a positive int

    Ensures:
        - Runs every module even when an earlier one fails
        - Prints one pass or fail line per module, with the error cut to error_chars
        - Returns True when no module failed, else False
    """
    import cosa.utils.util as cu

    cu.print_banner( f"{title} - Full Smoke Test Suite", prepend_nl=True )

    results = []

    for name, module_path in modules:
        try:
            print( f"\n{'=' * 60}" )
            print( f"Running: {name}" )
            print( '=' * 60 )

            module = __import__( module_path, fromlist=[ "quick_smoke_test" ] )
            module.quick_smoke_test()
            results.append( ( name, "PASSED", None ) )

        except Exception as e:
            results.append( ( name, "FAILED", str( e ) ) )

    # Summary table
    print( f"\n{'=' * 60}" )
    print( "SMOKE TEST SUMMARY" )
    print( '=' * 60 )

    passed = sum( 1 for _, status, _ in results if status == "PASSED" )
    failed = sum( 1 for _, status, _ in results if status == "FAILED" )

    for name, status, error in results:
        status_icon = "✓" if status == "PASSED" else "✗"
        print( f"  {status_icon} {name}: {status}" )
        if error:
            print( f"      Error: {error[ :error_chars ]}" )

    print( f"\nTotal: {passed} passed, {failed} failed out of {len( results )} modules" )

    return failed == 0
