#!/usr/bin/env python3
"""
Pre-commit gate that refuses a commit adding a credential value.

The scan covers only the lines the staged change adds, not whole files.
Known credential-shaped lines already sit in the repo on their own rows.
A gate that fired on them would be switched off, and an off gate reads as coverage.

Requires:
    - run from inside the repo, with changes staged
Ensures:
    - exit 0 when no staged added line carries a credential value
    - exit 1 with a masked report otherwise
    - the verdict does not depend on the caller's directory
    - the report shows key, line and a truncated sha256, never the value
    - an existing secret edited nearby does not fire, because its own line was not
      added; the gate promises that no new credential enters, and the inventory of
      what is already in the tree is the sweep's job
    - install by hand, never automatically, since a hook installed by one session
      silently changes how every other session commits:
      ln -s ../../src/scripts/pre-commit-secret-scan.py .git/hooks/pre-commit
      then chmod +x .git/hooks/pre-commit
    - when it fires, remove the value and read it from the environment or the
      secret store; for a fixture or documented example, git commit --no-verify
      bypasses it, and the reason belongs in the commit message
    - the cwd immunity comes from git, not from this file: git changes to the top
      level of the working tree before running any hook, and the scan reads the
      staged diff, so there is no directory-relative file walk to go narrow
    - a harness that runs this script directly (CI, a wrapper, a human in a
      subdirectory) loses git's directory change, so --no-relative is passed to
      git diff; without it a diff.relative=true setting made the manual run exit 0
      on a clean-looking scan, and the flag must stay
    - tests in src/tests/unit/deploy/test_git_pathspecs_are_anchored.py pin the
      hook-runs-from-root fact, the end-to-end gate and the manual case
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
    Map each staged file to the set of line numbers the change adds.

    Requires:
        - diff is None (read the staged diff from git) or a unified=0 diff string

    Ensures:
        - returns { path: set( lineno ) } for changed paths only
        - a deleted or renamed-away path never appears
    """
    if diff is None:
        # `--no-relative` is LOAD-BEARING (row 0adf242e, 2026-08-25). Without it the
        # diff is scoped to the caller's CWD whenever `diff.relative` is set, and the
        # scanner then sees NOTHING for files staged outside that directory while still
        # reporting clean. Measured: with `-c diff.relative=true`, run from src/ with
        # .gitignore staged, this command yields ZERO hunks.
        #
        # `diff.relative` is not set in this repo today — which is exactly why it is worth
        # pinning here. The invariant was COINCIDENTAL, resting on a config nobody has
        # touched, and a secret scanner must not depend on a setting staying unset.
        diff = subprocess.run( [ "git", "diff", "--cached", "--unified=0",
                                 "--no-relative", "--diff-filter=ACMR" ],
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
