"""
Pre-commit gate: refuse a commit that ADDS a credential value.

Scope is deliberately the ADDED lines of the staged change, not the whole file. The
repo already carries known credential-shaped lines that live on their own rows; a gate
that fires on those would be turned off within a day, and a gate that is off is worse
than no gate because it reads as coverage.

THE TRADE THAT BUYS, named rather than discovered later: an existing secret edited
NEARBY does not fire. Reformat the file, move the line, change the line above it — the
gate stays quiet, because the credential line itself was not added. That is accepted on
purpose. What this gate promises is "no NEW credential enters"; the standing inventory
of what is already in the tree is the sweep's job, not this one's.

INSTALL IT DELIBERATELY, not automatically — this repo is worked by several sessions at
once and a hook installed under one of them silently changes how everybody else commits:

    ln -s ../../src/scripts/pre-commit-secret-scan.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit

WHEN IT FIRES, the fix is to remove the value and read it from the environment or the
secret store — never to bypass. If you genuinely must commit a flagged line (a fixture,
a documented example), `git commit --no-verify` is the escape hatch, and the reason
belongs in the commit message where a reviewer will see it.

The output is masked: key, line and a truncated sha256, never the value.

Requires:
    - run from inside the repo, with changes staged
Ensures:
    - exit 0 when no staged ADDED line carries a credential value
    - exit 1 with a masked report otherwise
"""

import os
import re
import subprocess
import sys

sys.path.insert( 0, os.path.dirname( os.path.abspath( __file__ ) ) )

import secret_scan


_HUNK = re.compile( r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@" )


def added_lines_by_file( diff=None ):
    """
    Map each staged file to the set of line numbers the change ADDS.

    Requires:
        - diff is None (read the staged diff from git) or a unified=0 diff string

    Ensures:
        - returns { path: set( lineno ) } for changed paths only
        - a deleted or renamed-away path never appears
    """
    if diff is None:
        diff = subprocess.run( [ "git", "diff", "--cached", "--unified=0",
                                 "--diff-filter=ACMR" ],
                               capture_output=True, text=True ).stdout
    added, path, lineno = {}, None, 0
    for line in diff.splitlines():
        if line.startswith( "+++ b/" ):
            path   = line[ 6 : ]
            lineno = 0
            continue
        m = _HUNK.match( line )
        if m:
            lineno = int( m.group( "start" ) )
            continue
        if path and line.startswith( "+" ) and not line.startswith( "+++" ):
            added.setdefault( path, set() ).add( lineno )
            lineno += 1
    return added


def main():
    added = added_lines_by_file()
    if not added:
        return 0

    findings = []
    for path, linenos in sorted( added.items() ):
        if not secret_scan._is_text_path( path ):
            continue
        blob = subprocess.run( [ "git", "show", f":{path}" ], capture_output=True )
        if blob.returncode != 0:
            continue
        text = blob.stdout.decode( "utf-8", "replace" )
        # scan the STAGED content, then keep only what this change introduced
        findings += [ f for f in secret_scan.scan_text( text, path ) if f[ 1 ] in linenos ]

    if not findings:
        return 0

    print( "COMMIT BLOCKED — a staged line adds what looks like a credential VALUE.", file=sys.stderr )
    print( "Values are masked below; remove the secret and read it from the environment", file=sys.stderr )
    print( "or the secret store. `git commit --no-verify` bypasses this, and the reason", file=sys.stderr )
    print( "belongs in the commit message.\n", file=sys.stderr )
    for origin, lineno, key, length, digest in findings:
        print( f"  {origin}:{lineno}\t{key}\t{length}\t{digest}", file=sys.stderr )
    print( f"\n{len( findings )} flagged line(s).", file=sys.stderr )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
