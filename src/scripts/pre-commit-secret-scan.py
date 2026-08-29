#!/usr/bin/env python3
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

🔴 THIS GATE IS CWD-IMMUNE BY VIRTUE OF GIT, NOT BY ANYTHING IN THIS FILE.
Written down 2026-08-25 (row 0adf242e) because it is a LOAD-BEARING EXTERNAL
GUARANTEE holding up a security control, and it was recorded nowhere.

Two facts, both measured rather than taken from the docs:

  1. `git` chdir's to the top level of the working tree before invoking ANY hook.
     So this script runs from the repo root no matter which directory the human
     typed `git commit` in. Probe hook run from a subdirectory reported the ROOT
     as its cwd.
  2. It reads the STAGED DIFF (`git diff --cached`), not a walk of the working
     tree — so there is no directory-relative file enumeration to go narrow.

⇒ Nobody's commits have ever received a narrower scan than a commit made at the
root. That was checked when `secret_scan.py worktree` was found to be CWD-scoped
(256 findings from the root, 38 from src/cosa). THE TWO ARE DIFFERENT ENTRY
POINTS. That defect degraded the hand-run INVENTORY sweep; it never touched this
gate.

⚠️ WHY IT IS WRITTEN HERE ANYWAY. Fact 1 is not ours. If a future harness invokes
this script directly — a CI step, a wrapper, a human debugging from src/cosa —
git's chdir does not happen and the guarantee evaporates silently. That is the
same shape as `diff.relative` being unset: correct today, correct for a reason
nobody recorded, and nothing announces it when it stops being true.

That is why `--no-relative` is passed below even though the hook path does not
need it. It costs nothing and it is what makes the MANUAL path safe: run by hand
from a subdirectory with `diff.relative=true`, this script exited 0 — silently
clean — before that flag. Do not remove it as redundant; it is redundant only
for the one invocation path git happens to protect.

Pinned by tests in src/tests/unit/deploy/test_git_pathspecs_are_anchored.py:
git-runs-hooks-from-the-repo-root, the end-to-end gate, and the manual case.

Requires:
    - run from inside the repo, with changes staged
Ensures:
    - exit 0 when no staged ADDED line carries a credential value
    - exit 1 with a masked report otherwise
    - the verdict does not depend on the caller's directory
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
