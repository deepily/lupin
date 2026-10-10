"""
Run the documentation commit gate over every commit of a range.

The commit gate reads the index, so it cannot judge a commit that already exists. This module
replays each commit of base..head in a detached worktree of its own. It checks out the parent,
stages exactly what the commit changed, and runs the gate of that tree as the hook runs it.
"""

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from collections import namedtuple

GATE_REFUSED   = 3
EXIT_PASSED    = 0
EXIT_REFUSED   = 1
EXIT_UNCHECKED = 2



class RangeRefused( Exception ):
    """
    A range the checker will not judge at all.

    Requires:
        - the message names the reason and, for a merge, the commit

    Ensures:
        - carries the reason as text, for the report and for the exit code 2

    Raises:
        - nothing
    """


Result = namedtuple( "Result", [ "sha", "subject", "verdict", "gate_rc", "lines" ] )


def git( root, *args ):
    """
    Run one git command in a working tree and return its output.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the command's standard output as text
        - the output is decoded as UTF-8 with replacement for bad bytes

    Raises:
        - RuntimeError naming the command and its error text when git exits non-zero
    """
    res = subprocess.run( [ "git", "-C", root ] + list( args ), capture_output=True )
    if res.returncode != 0: raise RuntimeError( f"git {' '.join( args )} failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return res.stdout.decode( "utf-8", "replace" )


def list_commits( root, base, head ):
    """
    List the commits of base..head, oldest first.

    Requires:
        - root is a git working tree; base and head name commits in it

    Ensures:
        - returns full shas in the order a lander would apply them
        - a merge commit is listed like any other; check_range refuses a range that holds one

    Raises:
        - RuntimeError when git cannot list the range
    """
    return git( root, "rev-list", "--reverse", f"{base}..{head}" ).split()


def changes( root, sha ):
    """
    List what one commit changed against its first parent.

    Requires:
        - root is a git working tree; sha is a commit with a parent

    Ensures:
        - returns tuples ( status, path, old_path ), status being A, C, M, D or R
        - old_path is the source of a rename and None for every other status
        - a merge commit is judged against its first parent

    Raises:
        - RuntimeError when sha has no parent or git fails
    """
    tokens = git( root, "diff", "-M", "--name-status", "-z", f"{sha}^1", sha ).split( "\0" )
    found, i = [], 0
    while i < len( tokens ) and tokens[ i ]:
        status = tokens[ i ][ 0 ]
        if status in ( "R", "C" ):
            found.append( ( status, tokens[ i + 2 ], tokens[ i + 1 ] ) )
            i += 3
        else:
            found.append( ( status, tokens[ i + 1 ], None ) )
            i += 2
    return found


def stage( worktree, sha, found ):
    """
    Stage the changes of a commit in a worktree that holds its parent.

    Requires:
        - worktree is a git working tree checked out at the parent of sha
        - found is the list changes() returned for sha

    Ensures:
        - an added, copied or modified path is staged with the content it has in sha
        - a deleted path is staged as a deletion and a rename stages the old path's deletion and the new path
        - the index then equals the tree of sha apart from nothing the commit left unchanged

    Raises:
        - RuntimeError when a git command fails
    """
    for status, path, old in found:
        if status == "D": git( worktree, "rm", "-q", "--", path )
        else:
            if status == "R": git( worktree, "rm", "-q", "--", old )
            git( worktree, "checkout", sha, "--", path )


def run_gate( worktree, python=None ):
    """
    Run the commit gate of a worktree the way the pre-commit chain runs it.

    Requires:
        - worktree is a git working tree with its changes staged

    Ensures:
        - returns ( exit_code, output_text ) of python -m cosa.repo.doc_lint.gate for that tree
        - the gate code comes from the worktree, with LUPIN_ROOT and PYTHONPATH pinned to it
        - the worktree's own commit hook is not involved

    Raises:
        - nothing
    """
    env = dict( os.environ, LUPIN_ROOT=worktree, PYTHONPATH=os.path.join( worktree, "src" ) )
    res = subprocess.run( [ python or sys.executable, "-m", "cosa.repo.doc_lint.gate", "--repo-root", worktree ], capture_output=True, env=env, cwd=worktree )
    return res.returncode, ( res.stdout + res.stderr ).decode( "utf-8", "replace" )


def check_commit( root, worktree, sha, runner=run_gate ):
    """
    Judge one commit as the commit gate would have judged it.

    Requires:
        - root is the repository; worktree is a detached worktree of it, free to be reset
        - runner( worktree ) returns ( exit_code, output_text )

    Ensures:
        - returns a Result whose verdict is passed, refused or unchecked
        - exit 3 from the gate is refused and carries the lines that name a refusal
        - exit 0 is passed; any other exit, and any git failure, is unchecked
        - the worktree is left holding the staged commit, to be reset by the next call

    Raises:
        - nothing
    """
    subject = ""
    try:
        subject = git( root, "log", "-1", "--format=%s", sha ).strip()
        found   = changes( root, sha )
        git( worktree, "checkout", "-q", "-f", "--detach", f"{sha}^1" )
        git( worktree, "clean", "-fdq" )
        stage( worktree, sha, found )
        code, output = runner( worktree )
    except RuntimeError as error:
        return Result( sha, subject, "unchecked", None, [ str( error ) ] )
    if code == GATE_REFUSED:
        return Result( sha, subject, "refused", code, [ line for line in output.splitlines() if "REFUSED" in line or "refus" in line ] )
    if code == 0: return Result( sha, subject, "passed", code, [] )
    return Result( sha, subject, "unchecked", code, output.splitlines()[ -3: ] )


def check_range( root, base, head, worktree, runner=run_gate ):
    """
    Judge every commit of base..head.

    Requires:
        - root is the repository; worktree is a detached worktree of it

    Ensures:
        - returns one Result per commit, oldest first
        - a commit that cannot be judged does not stop the commits after it

    Raises:
        - RangeRefused when the range holds no commit, or holds a merge commit, which is named
        - RuntimeError when the range cannot be listed
    """
    commits = list_commits( root, base, head )
    if not commits: raise RangeRefused( f"range {base}..{head} holds 0 commits, nothing was checked" )
    merges = git( root, "rev-list", "--merges", f"{base}..{head}" ).split()
    if merges: raise RangeRefused( f"range {base}..{head} holds a merge commit, {merges[ 0 ]}: a lander applies a merge differently, so no commit was judged" )
    return [ check_commit( root, worktree, sha, runner ) for sha in commits ]


def exit_code( results ):
    """
    Turn the results of a range into one exit code.

    Requires:
        - results is a list of Result

    Ensures:
        - returns 2 when any commit was unchecked, else 1 when any was refused, else 0
        - an unchecked commit outranks a refusal, since the range is then not fully judged

    Raises:
        - nothing
    """
    verdicts = [ r.verdict for r in results ]
    if "unchecked" in verdicts: return EXIT_UNCHECKED
    return EXIT_REFUSED if "refused" in verdicts else EXIT_PASSED


def report( base, head, results ):
    """
    Format the results of a range as text.

    Requires:
        - results is a list of Result

    Ensures:
        - one line per commit with its verdict, short sha and subject, then its refusal lines indented
        - a final line counts the verdicts and names the range

    Raises:
        - nothing
    """
    lines = []
    for r in results:
        lines.append( f"{r.verdict:<9} {r.sha[ :9 ]} gate={r.gate_rc} {r.subject}" )
        lines += [ f"    {line}" for line in r.lines ]
    counts = { v: sum( 1 for r in results if r.verdict == v ) for v in ( "passed", "refused", "unchecked" ) }
    lines.append( f"range {base}..{head}: {len( results )} commits, {counts[ 'passed' ]} passed, {counts[ 'refused' ]} refused, {counts[ 'unchecked' ]} unchecked" )
    return "\n".join( lines ) + "\n"


def holder_pid( name ):
    """
    Read the pid out of a holder's name.

    Requires:
        - name is the name of a folder under the worktrees folder

    Ensures:
        - returns the integer in a name shaped range-gate-PID-suffix, PID being decimal digits
        - returns None for any other name, so such a folder is treated as left behind

    Raises:
        - nothing
    """
    parts = name.split( "-", 3 )
    return int( parts[ 2 ] ) if len( parts ) == 4 and parts[ 0 ] == "range" and parts[ 1 ] == "gate" and parts[ 2 ].isdigit() else None


def sweep_stale( root, parent ):
    """
    Remove the holders that a killed run left under the worktrees folder.

    Requires:
        - root is a git working tree; parent is the folder that holds the range-gate-* holders

    Ensures:
        - a holder whose name carries the pid of a live process is kept, from the moment the folder exists
        - a holder whose pid is dead, or whose name carries no pid, is removed with its worktree
        - a folder whose name does not start with range-gate- is never touched
        - stale registrations are pruned, so a holder whose tree is already gone leaves no entry
        - returns the names of the holders it removed, sorted

    Raises:
        - nothing
    """
    removed = []
    for name in sorted( os.listdir( parent ) ):
        holder = os.path.join( parent, name )
        if not name.startswith( "range-gate-" ) or not os.path.isdir( holder ): continue
        pid = holder_pid( name )
        if pid is not None and os.path.exists( f"/proc/{pid}" ): continue
        subprocess.run( [ "git", "-C", root, "worktree", "remove", "--force", os.path.join( holder, "tree" ) ], capture_output=True )
        shutil.rmtree( holder, ignore_errors=True )
        removed.append( name )
    subprocess.run( [ "git", "-C", root, "worktree", "prune" ], capture_output=True )
    return removed


def _terminate( signum, frame ):
    """
    Turn a termination signal into a normal exit, so the cleanup in main runs.

    Requires:
        - installed as the SIGTERM handler for the length of main

    Ensures:
        - raises SystemExit with the conventional code, 128 plus the signal number

    Raises:
        - SystemExit always
    """
    raise SystemExit( 128 + signum )


def main( argv=None, out=None, runner=run_gate ):
    """
    Check a range from the command line.

    Requires:
        - run inside the repository; --base and --head name commits; --out may name a file to write

    Ensures:
        - makes a detached worktree under the main checkout's .claude/worktrees, from a linked worktree too, and removes it on every path
        - prints the report and writes it to --out when given
        - returns 0 when every commit passes, 1 when any is refused and 2 when any could not be judged
        - returns 2 and prints the reason when the range is empty or holds a merge commit
        - a termination signal removes the worktree before the process ends
        - the holder folder is named range-gate-PID-suffix from the moment it exists, so a sweep never takes a live run's
        - a holder left by a run that was killed outright is swept when the next run starts

    Raises:
        - nothing
    """
    parser = argparse.ArgumentParser( description="Run the commit gate over every commit of a range." )
    parser.add_argument( "--base", required=True )
    parser.add_argument( "--head", required=True )
    parser.add_argument( "--out", default=None )
    parser.add_argument( "--repo-root", default=os.getcwd() )
    args   = parser.parse_args( argv )
    out    = out or sys.stdout
    common = git( args.repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir" ).strip()
    parent = os.path.join( os.path.dirname( common ), ".claude", "worktrees" )
    os.makedirs( parent, exist_ok=True )
    sweep_stale( args.repo_root, parent )
    holder = tempfile.mkdtemp( prefix=f"range-gate-{os.getpid()}-", dir=parent )
    work   = os.path.join( holder, "tree" )
    previous = signal.signal( signal.SIGTERM, _terminate )
    try:
        git( args.repo_root, "worktree", "add", "--detach", work, args.head )
        try: results = check_range( args.repo_root, args.base, args.head, work, runner )
        except RangeRefused as reason:
            out.write( f"{reason}\n" )
            return EXIT_UNCHECKED
        text    = report( args.base, args.head, results )
        out.write( text )
        if args.out is not None:
            with open( args.out, "w", encoding="utf-8" ) as handle: handle.write( text )
        return exit_code( results )
    finally:
        signal.signal( signal.SIGTERM, previous )
        subprocess.run( [ "git", "-C", args.repo_root, "worktree", "remove", "--force", work ], capture_output=True )
        shutil.rmtree( holder, ignore_errors=True )


if __name__ == "__main__":
    sys.exit( main() )
