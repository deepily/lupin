"""
Run the documentation commit gate over every commit of a range.

The commit gate reads the index, so it cannot judge a commit that already exists. This module
replays each commit of base..head in a detached worktree of its own. It checks out the parent,
stages exactly what the commit changed, and runs the gate of that tree.

The hook runs the gate with --blocking. A commit made before the hook did so was never held to that.
The replay therefore passes --blocking only for a commit whose parent descends from the blocking epoch.
The epoch is one sha recorded in EPOCH_PATH. With none recorded, every commit is replayed in warn mode.
The epoch is read from the head of the range, and the working copy of the file must record the same value.
"""

import argparse
import datetime
import os
import re
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
EPOCH_PATH     = "src/conf/doc-gate-blocking-epoch.txt"
FULL_SHA       = re.compile( r"[0-9a-f]{40}" )
OLD_GATE_HINT  = "the gate exited 1 under --blocking: a gate.py that predates blocking does that on a finding, and then the recorded blocking epoch is earlier than the commit that made the gate block"


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


Result = namedtuple( "Result", [ "sha", "subject", "verdict", "gate_rc", "lines", "blocking" ], defaults=( False, ) )


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


def parse_blocking_epoch( text ):
    """
    Read the blocking epoch out of the text of the epoch file.

    Requires:
        - text is the content of EPOCH_PATH

    Ensures:
        - returns None when no line holds a value, a line being blank or starting with # after its spaces
        - returns the sha when exactly one line holds a value and it is 40 lower-case hex characters

    Raises:
        - RangeRefused naming the file when there are two values or the value is not one full sha
    """
    values = [ line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith( "#" ) ]
    if not values: return None
    if len( values ) != 1 or not FULL_SHA.fullmatch( values[ 0 ] ):
        raise RangeRefused( f"the blocking epoch in {EPOCH_PATH} is malformed: it must be one full 40-character lower-case sha on a line of its own, or no value at all; no commit was judged" )
    return values[ 0 ]


def read_blocking_epoch( root ):
    """
    Read the blocking epoch that a working tree records.

    Requires:
        - root is a git working tree

    Ensures:
        - returns None when root has no EPOCH_PATH file or the file holds no value, so no commit is held to blocking
        - returns the sha when the file holds one that names a commit in the repository

    Raises:
        - RangeRefused when the value is malformed, or is a sha that require_commit refuses
    """
    text  = working_epoch_text( root )
    epoch = parse_blocking_epoch( text ) if text is not None else None
    return require_commit( root, epoch ) if epoch is not None else None


def working_epoch_text( root ):
    """
    Read the epoch file of a working tree.

    Requires:
        - root is a git working tree

    Ensures:
        - returns the text of EPOCH_PATH under root, or None when root has no such file

    Raises:
        - nothing
    """
    path = os.path.join( root, EPOCH_PATH )
    if not os.path.exists( path ): return None
    with open( path, encoding="utf-8" ) as handle: return handle.read()


def require_commit( root, epoch ):
    """
    Check that an epoch value is the sha of a commit object itself.

    Requires:
        - root is a git working tree; epoch is 40 hex characters

    Ensures:
        - returns epoch when the repository holds a commit object with that sha
        - a tag is refused even when it points at a commit, since the value must be the commit's own sha

    Raises:
        - RangeRefused naming what the sha is instead: a tag, a tree, a blob, or no object at all
    """
    res  = subprocess.run( [ "git", "-C", root, "cat-file", "-t", epoch ], capture_output=True )
    kind = res.stdout.decode( "utf-8", "replace" ).strip() if res.returncode == 0 else None
    if kind != "commit":
        raise RangeRefused( f"the blocking epoch {epoch} in {EPOCH_PATH} names no commit in this repository ({f'it is a {kind}' if kind else 'no such object'}); no commit was judged" )
    return epoch


def resolve_blocking_epoch( root, head ):
    """
    Settle which blocking epoch a range is judged against.

    Requires:
        - root is the working tree the check runs in; head names the last commit of the range

    Ensures:
        - returns ( epoch, from_head ), epoch being a commit sha or None when no value is recorded
        - when head's tree holds EPOCH_PATH, its value is the epoch and from_head is True
        - then the working copy under root must record the same value, an absent file counting as no value
        - when head's tree has no such file, the range predates it: the working copy's value is used and from_head is False

    Raises:
        - RangeRefused naming both values when head and the working copy disagree, so an emptied or deleted working copy cannot lift blocking
        - RangeRefused when either value is malformed, or the epoch is a sha that require_commit refuses
    """
    res     = subprocess.run( [ "git", "-C", root, "show", f"{head}:{EPOCH_PATH}" ], capture_output=True )
    text    = working_epoch_text( root )
    working = parse_blocking_epoch( text ) if text is not None else None
    if res.returncode != 0: return ( require_commit( root, working ) if working is not None else None ), False
    recorded = parse_blocking_epoch( res.stdout.decode( "utf-8", "replace" ) )
    if recorded != working:
        have = working or ( "no file" if text is None else "no value" )
        raise RangeRefused( f"the blocking epoch differs: the head of the range records {recorded or 'no value'}, the working copy of {EPOCH_PATH} records {have}; no commit was judged" )
    return ( require_commit( root, recorded ) if recorded is not None else None ), True


def descends( root, ancestor, commit ):
    """
    Say whether one commit is another or descends from it.

    Requires:
        - root is a git working tree; ancestor and commit name commits

    Ensures:
        - True when ancestor is commit or an ancestor of it, False when it is not

    Raises:
        - RuntimeError naming the git command when git cannot compare the two commits
    """
    res = subprocess.run( [ "git", "-C", root, "merge-base", "--is-ancestor", ancestor, commit ], capture_output=True )
    if res.returncode not in ( 0, 1 ): raise RuntimeError( f"git merge-base --is-ancestor {ancestor} {commit} failed: {res.stderr.decode( 'utf-8', 'replace' ).strip()}" )
    return res.returncode == 0


def is_held( root, epoch, sha ):
    """
    Say whether a commit is held to the blocking gate.

    Requires:
        - root is a git working tree; sha is a commit with a parent
        - epoch is a sha read_blocking_epoch returned, or None

    Ensures:
        - False when epoch is None
        - True when the first parent of sha is the epoch or descends from it, False when it does not

    Raises:
        - RuntimeError naming the git command when git cannot compare the two commits
    """
    return epoch is not None and descends( root, epoch, f"{sha}^1" )


def run_gate( worktree, blocking=False, python=None ):
    """
    Run the commit gate of a worktree, with --blocking when the commit is held to it.

    Requires:
        - worktree is a git working tree with its changes staged
        - blocking is True for a commit is_held accepts, which is how the pre-commit chain runs the gate

    Ensures:
        - returns ( exit_code, output_text ) of python -m cosa.repo.doc_lint.gate for that tree
        - the gate code comes from the worktree, with LUPIN_ROOT and PYTHONPATH pinned to it
        - the worktree's own commit hook is not involved

    Raises:
        - nothing
    """
    env  = dict( os.environ, LUPIN_ROOT=worktree, PYTHONPATH=os.path.join( worktree, "src" ) )
    mode = [ "--blocking" ] if blocking else []
    res  = subprocess.run( [ python or sys.executable, "-m", "cosa.repo.doc_lint.gate" ] + mode + [ "--repo-root", worktree ], capture_output=True, env=env, cwd=worktree )
    return res.returncode, ( res.stdout + res.stderr ).decode( "utf-8", "replace" )


def now():
    """
    Give the local time with its offset, to the second.

    Requires:
        - nothing

    Ensures:
        - returns an ISO 8601 string such as 2026-10-10T01:02:03-04:00

    Raises:
        - nothing
    """
    return datetime.datetime.now().astimezone().isoformat( timespec="seconds" )


def where( worktree ):
    """
    Name the worktree and the moment, for a line that could not be judged.

    Requires:
        - worktree is the path the check ran in

    Ensures:
        - returns two lines, worktree and at, in that order

    Raises:
        - nothing
    """
    return [ f"worktree {worktree}", f"at {now()}" ]


def check_commit( root, worktree, sha, runner=run_gate, epoch=None, apart=False ):
    """
    Judge one commit by the gate of its own tree, in the mode the commit was made under.

    Requires:
        - root is the repository; worktree is a detached worktree of it, free to be reset
        - runner( worktree, blocking ) returns ( exit_code, output_text )
        - epoch is the blocking epoch, or None when none is recorded
        - apart is True when the epoch is not in the history of the range at all

    Ensures:
        - returns a Result whose verdict is passed, refused or unchecked, and whose blocking says which mode the gate ran in
        - the gate runs with blocking True only for a commit is_held accepts, and for none when apart is True
        - with apart True the warn-mode line says the epoch is not an ancestor of the head of the range, since nothing there predates it
        - exit 3 from the gate is refused and carries the lines that name a refusal
        - exit 0 is passed; any other exit, and any git failure, is unchecked
        - with an epoch recorded, a commit judged in warn mode carries a line that says it predates blocking
        - exit 1 under blocking is unchecked and carries OLD_GATE_HINT, since a gate.py that predates blocking exits 1 on a finding
        - an unchecked result keeps every line of a git error and ends with the worktree path and the time
        - the worktree is left holding the staged commit, to be reset by the next call

    Raises:
        - nothing
    """
    subject, blocking = "", False
    try:
        subject  = git( root, "log", "-1", "--format=%s", sha ).strip()
        found    = changes( root, sha )
        blocking = not apart and is_held( root, epoch, sha )
        git( worktree, "checkout", "-q", "-f", "--detach", f"{sha}^1" )
        git( worktree, "clean", "-fdq" )
        stage( worktree, sha, found )
        code, output = runner( worktree, blocking )
    except RuntimeError as error:
        return Result( sha, subject, "unchecked", None, str( error ).splitlines() + where( worktree ), blocking )
    why   = "" if epoch is None else f"the blocking epoch {epoch[ :9 ]} is not an ancestor of the head of this range" if apart else f"predates the blocking epoch {epoch[ :9 ]}"
    older = [] if blocking or epoch is None else [ f"{why}: judged in warn mode, findings on its staged lines were not enforced" ]
    if code == GATE_REFUSED:
        return Result( sha, subject, "refused", code, [ line for line in output.splitlines() if "REFUSED" in line or "refus" in line ] + older, blocking )
    if code == 0: return Result( sha, subject, "passed", code, older, blocking )
    hint = [ OLD_GATE_HINT ] if blocking and code == 1 else []
    return Result( sha, subject, "unchecked", code, output.splitlines()[ -3: ] + hint + where( worktree ), blocking )


def check_range( root, base, head, worktree, runner=run_gate, epoch=None ):
    """
    Judge every commit of base..head.

    Requires:
        - root is the repository; worktree is a detached worktree of it
        - epoch is the blocking epoch, or None when none is recorded

    Ensures:
        - returns one Result per commit, oldest first
        - a commit that cannot be judged does not stop the commits after it

    Raises:
        - RangeRefused when the range holds no commit, or holds a merge commit, which is named
        - RuntimeError when the range cannot be listed, or the epoch cannot be compared with head
    """
    commits = list_commits( root, base, head )
    if not commits: raise RangeRefused( f"range {base}..{head} holds 0 commits, nothing was checked" )
    merges = git( root, "rev-list", "--merges", f"{base}..{head}" ).split()
    if merges: raise RangeRefused( f"range {base}..{head} holds a merge commit, {merges[ 0 ]}: a lander applies a merge differently, so no commit was judged" )
    apart = epoch is not None and not descends( root, epoch, head )
    return [ check_commit( root, worktree, sha, runner, epoch, apart ) for sha in commits ]


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


def epoch_line( epoch, results, from_head=True ):
    """
    Say which blocking epoch a range was judged against, in one line.

    Requires:
        - epoch is the blocking epoch, or None when none is recorded; results is a list of Result
        - from_head is False when the head of the range has no epoch file and the working copy was read

    Ensures:
        - with no epoch, the line says none is recorded and that every commit was judged in warn mode
        - with one, the line names it and counts the commits held to blocking and those judged in warn mode
        - with from_head False, the line ends by saying the value came from the working copy

    Raises:
        - nothing
    """
    source = "" if from_head else " (read from the working copy: the head of the range has no epoch file)"
    if epoch is None: return f"blocking epoch: none recorded in {EPOCH_PATH}, every commit was judged in warn mode{source}"
    held = sum( 1 for r in results if r.blocking )
    return f"blocking epoch {epoch[ :9 ]}: {held} commits held to blocking, {len( results ) - held} judged in warn mode{source}"


def report( base, head, results, epoch_text=None ):
    """
    Format the results of a range as text.

    Requires:
        - results is a list of Result
        - epoch_text is the line epoch_line gives, or None to leave it out

    Ensures:
        - one line per commit with its verdict, short sha and subject, then its refusal lines indented
        - the epoch line, when given, comes just before the final line
        - a final line counts the verdicts and names the range

    Raises:
        - nothing
    """
    lines = []
    for r in results:
        lines.append( f"{r.verdict:<9} {r.sha[ :9 ]} gate={r.gate_rc} {r.subject}" )
        lines += [ f"    {line}" for line in r.lines ]
    counts = { v: sum( 1 for r in results if r.verdict == v ) for v in ( "passed", "refused", "unchecked" ) }
    if epoch_text is not None: lines.append( epoch_text )
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
        - returns 2 and prints the reason when the blocking epoch is malformed, names no commit, or differs between --head and the working copy of --repo-root, and judges no commit
        - a commit is replayed with --blocking only when its parent descends from that epoch; the report names the epoch
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
        try:
            epoch, from_head = resolve_blocking_epoch( args.repo_root, args.head )
            results          = check_range( args.repo_root, args.base, args.head, work, runner, epoch )
        except RangeRefused as reason:
            out.write( f"{reason}\n" )
            return EXIT_UNCHECKED
        text    = report( args.base, args.head, results, epoch_line( epoch, results, from_head ) )
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
