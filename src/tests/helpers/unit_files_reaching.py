"""
List the unit test files that reach given modules, from git, as Python files only.

A pathspec such as src/tests/unit/* also matches a TypeScript test.
Pytest answers a .ts path with "ERROR: not found" and exit code 4, and runs no test.
A manager's merge check hit this on 24 Nov 2026, and Rick adopted this helper as the fix.
This helper searches wherever it is told and keeps only the .py names.
A caller never builds that list by hand.

    PYTHONPATH=src python -m tests.helpers.unit_files_reaching full_answer context_baseline
"""
import subprocess
import sys

DEFAULT_PATHSPECS = ( "src/tests/unit", "src/cosa/tests/unit" )


def _git_lines( root, *args ):
    """
    Run one git command in a tree and return its output lines.

    Requires:
        - root is a directory inside a git working tree; args are git arguments

    Ensures:
        - returns the non-empty output lines, and [] when git finds no match (exit 1 from grep)

    Raises:
        - RuntimeError naming the command and its error text when git exits with anything but 0 or 1
    """
    done = subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True )
    if done.returncode not in ( 0, 1 ): raise RuntimeError( f"git {' '.join( args )} exited {done.returncode}: {done.stderr.strip()}" )
    return [ line for line in done.stdout.split( "\n" ) if line ]


def unit_files_reaching( terms, root, pathspecs=DEFAULT_PATHSPECS, include_staged=True ):
    """
    List the tracked unit test files whose text holds any of the terms, as .py paths only.

    Requires:
        - terms is a non-empty list of fixed strings, such as module names
        - root is the working tree to search; pathspecs are repo-relative directories or globs, anchored by git -C root

    Ensures:
        - returns a sorted list of repo-relative paths, each ending in .py, each once
        - a file of any other kind that the pathspecs reach, such as a .ts test, is left out
        - with include_staged, the .py files staged under the pathspecs join the list even when they hold no term
        - searches tracked files only; an untracked file is not listed

    Raises:
        - ValueError when terms is empty
        - RuntimeError when git fails
    """
    if not terms: raise ValueError( "unit_files_reaching needs at least one term" )
    needles = [ arg for term in terms for arg in ( "-e", term ) ]
    found   = _git_lines( root, "grep", "-l", "-F", *needles, "--", *pathspecs )
    if include_staged: found += _git_lines( root, "diff", "--cached", "--name-only", "--", *pathspecs )
    return sorted( { path for path in found if path.endswith( ".py" ) } )


def main( argv=None, out=sys.stdout, root="." ):
    """
    Print the unit test files that reach the modules named on the command line, one per line.

    Requires:
        - argv holds one or more module names or other fixed strings; root is the working tree

    Ensures:
        - returns 0 after printing the list, which can be empty
        - returns 2 and prints nothing to out when no term is given
    """
    terms = sys.argv[ 1: ] if argv is None else argv
    if not terms: return 2
    for path in unit_files_reaching( terms, root ): print( path, file=out )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
