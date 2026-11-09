"""
The daily duplicate check: judge the new definitions of main against the rest of the tree.

The window runs from the last successful run to now. The pool and the new definitions come from a detached worktree
at the window's end commit. The pool leaves out every earlier version of a new definition. Judge calls are capped per run.
What the cap leaves is carried to the next run. It is the daily check of the third remediation plan.
With --ceiling the cap is the carried backlog plus the day's inflow, up to the ceiling. With --baseline the new definitions are every
definition of the tree, and the carried ones are drained over several runs. A carried count that rises on several daily runs in a row alerts Rick.
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import math
import os
import pathlib
import shlex
import subprocess
import sys
import time
import uuid

from cosa.repo.doc_lint import model_transport
from cosa.repo.duplicate_check import cluster, extract, pipeline
from cosa.repo.duplicate_check import config as cfg_mod
from cosa.repo.duplicate_check import errors as err
from cosa.repo.duplicate_check.proof import label_prep, proof_cli
from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import vector_build
from lupin_mcp import duplicate_check_audit as audit
from lupin_mcp import duplicate_check_filing as filing
from lupin_mcp import duplicate_check_history as history
from lupin_mcp import duplicate_check_status as status_mod
from lupin_mcp import reuse_behaviour as behaviour
from lupin_mcp import reuse_exit_gate as eg
from lupin_mcp import reuse_tie as tie_mod
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import source_at

FOLDER            = ( "duplicate-check-daily", )
LAST_SUCCESS      = "last-success.json"
RUN_LOCK          = "run.lock"        # held by the one run in flight; a boot near 10:00 starts the cron line and the reboot line together
VECTORS_DIR       = "vectors"
WORKTREE_PREFIX   = "duplicate-check-daily-"
WINDOW_HOURS      = 24
BRANCH            = "main"
BRANCH_AUTO       = "auto"            # --branch auto: the newest local branch matching the glob below, else main
WORKING_GLOB      = "wip-*"
TRIGGERS          = ( "cron", "reboot", "hand" )
CARRIED_CODES     = ( err.JUDGE_CAP_REACHED, err.JUDGE_CALL_FAILED )
PREREQ_EMBEDDINGS = "embedding_endpoint"
PREREQ_BINARY     = "claude_binary"
PREREQ_FROZEN     = "frozen_config"
STAGE_JUDGING     = "judging"                                   # the stage named in a result file when the pool build, the embeddings or the judge failed
UNREADABLE        = "unreadable"
CRON_TAG          = "# duplicate-check-daily"
CRON_SCHEDULE     = "0 10 * * *"      # 10:00 every day, weekends included; nothing runs after last call, when the server is turned off
HOURLY_SCHEDULE   = "0 10-22 * * *"   # the adaptive slots: every hour from 10:00 to 22:00, while the host is on
HOUR_SECONDS      = 3600
HOUR_FILL         = 0.8               # share of an hour a chunk of judge calls is sized to fill, so a run ends before the next slot
SECONDS_PER_CALL  = 3.5               # wall-clock seconds a judge call took on 6 Nov at parallel 4, until the history gives a better figure
MIN_BASELINE_CALLS = 20               # the baseline gets what the daily work leaves of the chunk only when that is at least this many calls
ADAPTIVE_RISE_LIMIT = 6               # hourly runs in a row with a larger carried count before Rick is told
BACKOFF_SECONDS   = 5400              # after a rate limit the next slot is skipped: no run starts until this long has passed
SKIPPED           = "skipped"
ALL_FAILED_CALLS  = 20                # a run that made this many calls and judged none is a broken run, not a quiet one
ROW_SCAN_LIMIT    = 50000             # rows the store count reads before it gives up and reports nothing
TERMINAL          = ( "done", "dropped", "wont_fix" )
BASELINE_SCHEDULE = "7 11 * * *"      # 11:07, an hour after the daily run and 30 minutes before the 11:37 shadow audit drain; a morning slot, never after last call
RISE_LIMIT        = 3                 # daily runs in a row with a larger carried count before Rick is told
INSTALLED_LINES   = ( 2, 3 )          # the daily slot and the reboot line, with the baseline line when it was asked for
BASELINE          = "baseline.json"
BASELINE_DONE     = "complete"
BASELINE_OPEN     = "in_progress"
BOOT_DELAY        = 300               # seconds the host waits after a boot before the reboot line runs
LOG_NAME          = "daily.log"
LOCK_OWNER        = "duplicate-check-daily"
STALE_DAYS        = 3                 # a pinned branch whose tip is this old, with a newer branch beside it, is refused
STALE_BRANCH      = "stale_branch"
MISSING_BRANCH    = "missing_branch"
BRANCH_CHANGED    = "branch_changed"      # the recorded progress belongs to another branch than the one chosen now
COMMIT_NOT_ON_BRANCH = "commit_not_on_branch"
CONTINUITY        = ( BRANCH_CHANGED, COMMIT_NOT_ON_BRANCH )
STAGE_GUARD       = "branch_guard"
STAGE_SETUP       = "setup"           # the stage named in a result file when the configuration, the window or the worktree failed
REFUSED_EXIT      = 3                 # distinct from 0 ok, 1 failed and argparse's 2
UNREACHED         = ( "window", "judged", "carried", "advanced_to", "clusters", "findings", "unreadable", "owed", "usage", "rate_limited", "backoff_until" )     # keys a run that stopped early never measured; filing and audit stay absent without a hook
CARRIED           = behaviour.CARRIED     # names copied into the cron lines from the installer's environment


class Counting:
    """A judge backend that counts the calls made through it."""

    def __init__( self, backend ):
        self.backend, self.calls, self.limited = backend, 0, 0
        self.server_label                      = backend.server_label

    async def complete( self, model, system_prompt, user_prompt ):
        """
        Count the call and return the backend's answer.

        Ensures:
            - a call the service refuses for a rate or usage limit is counted in limited and raised again
            - every later call of the run raises at once without reaching the service
        """
        if self.limited: raise model_transport.ModelRateLimited( "the service rate-limited an earlier call of this run; no further call is made" )
        self.calls += 1
        try: return await self.backend.complete( model, system_prompt, user_prompt )
        except model_transport.ModelRateLimited:
            self.limited += 1
            raise


def git( root, *args ):
    """
    Run one git command in root.

    Ensures:
        - returns the stripped stdout

    Raises:
        - RuntimeError naming the command when git fails
    """
    out = label_prep._git( root, *args )
    if out is None: raise RuntimeError( f"git {' '.join( args )} failed in {root}" )
    return out


def read_last_success( folder ):
    """Ensures: returns the parsed last-success.json of the folder, or None when there is none."""
    path = pathlib.Path( folder ) / LAST_SUCCESS
    return json.loads( path.read_text( encoding="utf-8" ) ) if path.exists() else None


def resolve_branch( root, name ):
    """
    Turn the --branch argument into a branch name.

    Ensures:
        - returns name unchanged unless it is auto
        - for auto returns the local branch matching the working glob whose tip commit is newest, ties by name, else main
    """
    if name != BRANCH_AUTO: return name
    listed = git( root, "for-each-ref", "--format=%(refname:short) %(committerdate:unix)", f"refs/heads/{WORKING_GLOB}" )
    rows   = sorted( ( ( line.split()[ 0 ], int( line.split()[ 1 ] ) ) for line in listed.splitlines() ), key=lambda row: ( -row[ 1 ], row[ 0 ] ) )
    return rows[ 0 ][ 0 ] if rows else BRANCH


def backoff_until( folder, now ):
    """
    Say whether a rate limit still holds the check back.

    Ensures:
        - looks at the newest run that was not itself skipped
        - returns its backoff_until, an ISO time, when that is later than now; None otherwise or with no history
    """
    for line in reversed( history.read_lines( folder ) ):
        if line[ "status" ] == SKIPPED: continue
        until = line.get( "backoff_until" )
        return until if until is not None and datetime.datetime.fromisoformat( until ) > now else None
    return None


def usage_since( before, after, calls=0 ):
    """
    Work out what the calls between two usage tallies used.

    Ensures:
        - returns the difference of the tallies, the cost rounded to 4 places
        - returns None when calls were made and the SDK reported none of them, as under the agy transport: the tokens are unknown, not zero
    """
    used = { k: round( after[ k ] - before[ k ], 4 ) if k == "cost_usd" else after[ k ] - before[ k ] for k in after }
    return None if calls and not used[ "calls" ] else used


def window_of( root, last, now, branch=BRANCH, hours=WINDOW_HOURS ):
    """
    Choose the commits a run judges.

    Requires:
        - last is read_last_success's answer; now is a timezone-aware datetime
    Ensures:
        - returns { start, end, commits }: end is the tip of the branch, start the last good commit or, with none, the newest commit older than hours before now
        - with no commit that old, start is the first commit of the branch
        - commits are those after start up to end on the first-parent line, oldest first
    """
    end   = git( root, "rev-parse", branch )
    start = last[ "commit" ] if last is not None else git( root, "rev-list", "-1", f"--before={( now - datetime.timedelta( hours=hours ) ).isoformat()}", branch )
    if not start: start = git( root, "rev-list", "--max-parents=0", branch ).split()[ -1 ]
    listed = git( root, "rev-list", "--reverse", "--first-parent", f"{start}..{end}" )
    return { "start": start, "end": end, "commits": listed.split() if listed else [] }


def changes( root, window ):
    """
    Read what the window added, changed or renamed.

    Requires:
        - window is window_of's answer
    Ensures:
        - returns [ ( old path, new path ) ] for every added, modified or renamed file; old path is None for an added file and equals the new path for a modified one
        - a rename is what git detects (`-M`, the default similarity), so a file renamed and edited maps to the path it had at the window's start
        - a deleted file is not listed
    """
    out = git( root, "diff", "-z", "--name-status", "-M", "--diff-filter=AMR", window[ "start" ], window[ "end" ] ).split( "\0" )
    pairs, i = [], 0
    while i < len( out ) and out[ i ]:
        status = out[ i ][ 0 ]
        if status == "R": pairs.append( ( out[ i + 1 ], out[ i + 2 ] ) ); i += 3
        else: pairs.append( ( None if status == "A" else out[ i + 1 ], out[ i + 1 ] ) ); i += 2
    return pairs


def changed_files( root, window ):
    """
    List the Python and script files the window added, changed or renamed.

    Ensures:
        - returns the sorted new paths
    """
    return sorted( new for old, new in changes( root, window ) if new.endswith( extract.PY_SUFFIXES + extract.SCRIPT_SUFFIXES ) )


def old_paths( root, window ):
    """
    Map each renamed file to the path it had at the window's start.

    Ensures:
        - returns { new path: old path }
        - a file that kept its path is not in it
    """
    return { new: old for old, new in changes( root, window ) if old is not None and old != new }


def definitions_held_at_start( root, window, files, start_sha, path, key ):
    """
    List the definitions of the changed files that an earlier commit already held.

    Requires:
        - files are the window's changed files at its end; path is a free place for a detached worktree at start_sha
        - key( file, definition ) gives the part of a definition the caller compares: the file is the one it has now

    Ensures:
        - returns the set of key( file, definition ) over the definitions found at start_sha
        - a renamed file is read under the path it had at start_sha, and a file absent there lists nothing
        - the worktree is removed whether the read ends or fails
    """
    was  = old_paths( root, window )
    back = { was.get( f, f ): f for f in files }
    old  = source_at.ensure_worktree( root, start_sha, path )
    try: return { key( back[ d[ "file" ] ], d ) for d in extract.extract_tree( old, [ pathlib.Path( old ) / o for o in back if ( pathlib.Path( old ) / o ).exists() ], "new" )[ "definitions" ] }
    finally: release( root, old )


def new_definitions( tree, root, window ):
    """
    List the definitions the window added or changed, oldest commit first.

    Requires:
        - tree is a worktree at the window's end commit
    Ensures:
        - returns { defs, commit_of }: new-origin definitions of the changed files, in the order of the first-parent commit that last touched their file, then file and line
        - commit_of maps a definition id to that commit
        - a definition whose file, name and text the window's start already held is left out, so only a function that changed or is new is judged
        - a renamed file is compared with the path it had at the start, so a rename alone leaves its functions out
    """
    files = changed_files( root, window )
    found = extract.extract_tree( tree, [ pathlib.Path( tree ) / f for f in files ], "new" )[ "definitions" ] if files else []
    held  = definitions_held_at_start( root, window, files, window[ "start" ], pathlib.Path( tree ).parent / f"{pathlib.Path( tree ).name}-start", lambda f, d: ( f, d[ "name" ], d[ "text" ] ) ) if files else set()
    rank  = { c: i for i, c in enumerate( window[ "commits" ] ) }
    touch = { f: git( root, "log", "-1", "--first-parent", "--format=%H", f"{window[ 'start' ]}..{window[ 'end' ]}", "--", f ) for f in files }
    fresh = [ d for d in found if ( d[ "file" ], d[ "name" ], d[ "text" ] ) not in held ]
    fresh.sort( key=lambda d: ( rank.get( touch[ d[ "file" ] ], len( rank ) ), d[ "file" ], d[ "line" ] ) )
    return { "defs": fresh, "commit_of": { d[ "id" ]: touch[ d[ "file" ] ] for d in fresh } }


def release( root, tree ):
    """Ensures: the detached worktree is unlocked and removed, and nothing is raised."""
    source_at.unlock( root, tree )
    subprocess.run( [ "git", "-C", str( root ), "worktree", "remove", "--force", str( tree ) ], capture_output=True, text=True )


def pool_without_earlier_versions( tree, fresh ):
    """
    Build the server pool of a tree without the earlier versions of the new definitions.

    Ensures:
        - returns the tree's server and client definitions, less every one whose file and name a new definition shares
        - so no new definition can be paired with its own earlier version
    """
    parts = label_prep.tree_definitions( tree )
    taken = { ( d[ "file" ], d[ "name" ] ) for d in fresh }
    return [ d for d in [ *parts[ "server_defs" ], *parts[ "client_defs" ] ] if ( d[ "file" ], d[ "name" ] ) not in taken ]


def progress( defs, commit_of, unjudged, window ):
    """
    Say how far the window was judged.

    Requires:
        - defs are in commit order; unjudged is judge_run's list
    Ensures:
        - returns { advanced_to, carried }: advanced_to is the last commit before the first one that has a carried definition, the window's start when that is the first commit or a commit the window does not list
        - a definition left unjudged by the cap or a failed call is carried; an unreadable reply was ledgered and is not carried
        - with nothing carried, advanced_to is the window's end
    """
    carried = sorted( u[ "id" ] for u in unjudged if u[ "code" ] in CARRIED_CODES )
    if not carried: return { "advanced_to": window[ "end" ], "carried": [] }
    rank    = { c: i for i, c in enumerate( window[ "commits" ] ) }
    first   = min( rank.get( commit_of[ i ], -1 ) for i in carried )
    return { "advanced_to": window[ "start" ] if first <= 0 else window[ "commits" ][ first - 1 ], "carried": carried }


def baseline_window( root, branch=BRANCH ):
    """
    Choose the whole tree as a run's window.

    Requires:
        - branch names a branch of the checkout at root
    Ensures:
        - returns { start, end, commits }: end is the tip of the branch, start its first commit, commits an empty list
    """
    return { "start": git( root, "rev-list", "--max-parents=0", branch ).split()[ -1 ], "end": git( root, "rev-parse", branch ), "commits": [] }


def baseline_definitions( tree, window ):
    """
    List every definition of the files the pool is built from.

    Requires:
        - tree is a worktree at the window's end commit
    Ensures:
        - returns { defs, commit_of } like new_definitions: new-origin definitions in file and line order, each mapped to the window's end commit
        - the files are those label_prep.tree_definitions reads for the pool, so a file the pool cannot read is not asked for
    """
    parts = label_prep.tree_definitions( tree )
    files = sorted( { d[ "file" ] for d in [ *parts[ "server_defs" ], *parts[ "client_defs" ] ] } )
    found = extract.extract_tree( tree, [ pathlib.Path( tree ) / f for f in files ], "new" )[ "definitions" ] if files else []
    found.sort( key=lambda d: ( d[ "file" ], d[ "line" ] ) )
    return { "defs": found, "commit_of": { d[ "id" ]: window[ "end" ] for d in found } }


def read_baseline( folder ):
    """Ensures: returns the parsed baseline.json of the folder, or None when there is none."""
    path = pathlib.Path( folder ) / BASELINE
    return json.loads( path.read_text( encoding="utf-8" ) ) if path.exists() else None


def rising_guard( folder, doc, now, runs, notifier ):
    """
    Tell Rick when the carried count has risen on several daily runs in a row.

    Requires:
        - doc is the finished result document of a daily run; notifier takes ( spoken, abstract ) and returns whether it was sent, or is None
    Ensures:
        - returns None unless this run's carried count, with the history's, rose on each of the last runs measured daily runs
        - otherwise returns { runs, series, notified }; a notifier that is missing or raises gives notified False
        - alerts on the first run that crosses the line only: while the count keeps rising, the later runs return repeat True and notified False, until a fall resets it
    """
    past   = history.read_lines( folder )
    probe  = history.line_of( { **doc, "started_at": now.isoformat() }, "" )
    rising = history.rising_run( [ *past, probe ], runs )
    if rising is None: return None
    if history.rising_run( past, runs ) is not None: return { **rising, "notified": False, "repeat": True }
    shown  = ", ".join( str( n ) for n in rising[ "series" ] )
    sent   = False
    if notifier is not None:
        try: sent = notifier( f"The daily duplicate check is falling behind: its carried count rose on {runs} runs in a row, to {rising[ 'series' ][ -1 ]}.",
                              f"Carried definitions, oldest run first: {shown}. Raise the ceiling or add a slot; the history is `python -m lupin_mcp.duplicate_check_history`." )
        except Exception: sent = False       # a broken notifier must not stop the run from advancing
    return { **rising, "notified": sent }


def write_json( path, doc ):
    """Ensures: writes the document to the path, making the folder, and returns the path."""
    path = pathlib.Path( path )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( doc, indent=2, sort_keys=True ), encoding="utf-8" )
    return path


def record( folder, stem, doc, now ):
    """
    Write a run's result file and append its line to the run history.

    Requires:
        - doc is the result document; stem is the file name without its extension; now is the run's start time
    Ensures:
        - the document gains schema_version and started_at, and None for each measure the run did not reach, so a failed run has the keys of a successful one
        - writes <folder>/<stem>.json, appends one line to runs.jsonl
        - returns the document
    """
    doc.update( schema_version=history.SCHEMA_VERSION, started_at=now.isoformat() )
    for key in UNREACHED: doc.setdefault( key, None )
    write_json( folder / f"{stem}.json", doc )
    history.append_line( folder, history.line_of( doc, f"{stem}.json" ) )
    return doc


def findings_of( groups, fresh, pool, window, parts, commit_of=None ):
    """
    Turn the duplicate clusters into one finding per cluster that holds a new definition.

    Requires:
        - groups are the clusters of more than one definition; fresh and pool are the definitions of the run
        - parts may hold session_of, a function from a definition to the writing seat's session id or None
        - commit_of, when given, maps a definition id to the commit that added it
    Ensures:
        - returns { id, name, file, line, text, session_id, commit, others, window } for each cluster that holds a new definition, in the order of the groups
        - the finding is the cluster's new definition with the lowest id, whichever side the judge ruled from, so a pair of new definitions that repeat each other is one finding
        - others is the rest of the cluster, the other new definitions included
        - without session_of the session is None, so the finding is unresolved to a seat
    """
    by_id  = { d[ "id" ]: d for d in [ *fresh, *pool ] }
    new    = { d[ "id" ] for d in fresh }
    return [ { "id": i, "name": by_id[ i ][ "name" ], "file": by_id[ i ][ "file" ], "line": by_id[ i ][ "line" ], "text": by_id[ i ][ "text" ],
               "session_id": parts[ "session_of" ]( by_id[ i ] ) if "session_of" in parts else None, "commit": commit_of[ i ] if commit_of is not None else None, "window": window,
               "others": [ { "id": o, "name": by_id[ o ][ "name" ], "file": by_id[ o ][ "file" ] } for o in g if o != i ] }
             for g in groups for i in [ min( [ m for m in g if m in new ], default=None ) ] if i is not None ]


def failed_prerequisite( client, cli_path, verify, version_fn ):
    """
    Check the three prerequisites in order.

    Ensures:
        - returns None when all hold, else { prerequisite, detail } for the first that does not: the embedding endpoint answers, the binary reports a version, the frozen configuration matches the live one
    """
    try: client.info()
    except Exception as e: return { "prerequisite": PREREQ_EMBEDDINGS, "detail": f"{type( e ).__name__}: {e}" }
    version = version_fn( cli_path )
    if cli_path is None or version in ( None, UNREADABLE ): return { "prerequisite": PREREQ_BINARY, "detail": f"the binary {cli_path!r} reports no version" }
    try: verify()
    except err.DuplicateCheckError as e: return { "prerequisite": PREREQ_FROZEN, "detail": f"{e.code}: {e.detail}" }
    return None


def other_branches( root, branch ):
    """
    List the local branches the guard compares the pinned one with.

    Ensures:
        - returns [ ( name, tip commit time as epoch seconds ) ] for every ref under refs/heads except main and the pinned branch, newest first, ties by name
    """
    listed = git( root, "for-each-ref", "--format=%(refname:short) %(committerdate:unix)", "refs/heads" )
    rows   = [ line.split() for line in listed.splitlines() ]
    return sorted( ( ( name, int( at ) ) for name, at in rows if name not in ( BRANCH, branch ) ), key=lambda row: ( -row[ 1 ], row[ 0 ] ) )


def branch_guard( root, branch, now, days=STALE_DAYS ):
    """
    Refuse a pinned branch that work has left, so a branch change never fails silently.

    Requires:
        - now is a timezone-aware datetime
    Ensures:
        - returns None when the pinned branch resolves and is either younger than days or has no newer local branch beside it
        - returns { refusal: stale_branch, branch, idle_days, newest, newest_at } when its tip is days old or older and another local branch has a newer commit
        - returns { refusal: missing_branch, branch, newest, newest_at } when the pinned name resolves to no commit; newest is the newest other local branch, or None when there is none
        - main is never the newest branch named
    """
    try: tip = int( git( root, "log", "-1", "--format=%ct", f"{branch}^{{commit}}" ) )
    except RuntimeError: tip = None
    newer = [ row for row in other_branches( root, branch ) if tip is None or row[ 1 ] > tip ]
    where = { "newest": newer[ 0 ][ 0 ], "newest_at": datetime.datetime.fromtimestamp( newer[ 0 ][ 1 ], datetime.timezone.utc ).isoformat() } if newer else { "newest": None, "newest_at": None }
    if tip is None: return { "refusal": MISSING_BRANCH, "branch": branch, **where }
    idle = now.timestamp() - tip
    if newer and idle >= days * 86400: return { "refusal": STALE_BRANCH, "branch": branch, "idle_days": round( idle / 86400, 1 ), **where }
    return None


def continuity_guard( root, branch, previous, commit ):
    """
    Refuse a run that would carry another branch's progress onto this one.

    Requires:
        - previous is the branch the last run recorded, or None for a record written before branches were kept; commit is the last judged commit, or None
    Ensures:
        - returns None when there is no record, or the branch is the recorded one and the commit is an ancestor of its tip
        - returns { refusal: branch_changed, branch, previous, newest: None } when the recorded branch differs from this one
        - returns { refusal: commit_not_on_branch, branch, previous, newest: None } when the commit is not an ancestor of the branch tip
    """
    if previous is not None and previous != branch: return { "refusal": BRANCH_CHANGED, "branch": branch, "previous": previous, "newest": None }
    if commit is None: return None
    try: git( root, "merge-base", "--is-ancestor", commit, branch )
    except RuntimeError: return { "refusal": COMMIT_NOT_ON_BRANCH, "branch": branch, "previous": previous, "newest": None }
    return None


def limit_flag( cap, ceiling ):
    """Ensures: returns --ceiling and its number when a ceiling is given, else --cap and the cap."""
    return f"--ceiling {ceiling}" if ceiling is not None else f"--cap {cap}"


def reinstall_command( root, python, cap, cli_path, branch, ceiling=None, with_baseline=False ):
    """Ensures: returns the reinstall command, keeping the branch, limit and baseline line."""
    more = " --with-baseline" if with_baseline else ""
    return f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {python} -m lupin_mcp.duplicate_check_daily --install {limit_flag( cap, ceiling )} --claude-cli-path {cli_path} --branch {shlex.quote( branch )}{more}"


def refusal_message( refusal, command ):
    """
    Say what a refusal means and what to run.

    Ensures:
        - returns ( spoken, abstract ): spoken is short and holds no path; abstract names the branch and carries the reinstall command, or says no other branch exists
    """
    name = refusal[ "branch" ]
    if refusal[ "refusal" ] in CONTINUITY:
        what = f"it last judged `{refusal['previous']}` and now chooses `{name}`" if refusal[ "refusal" ] == BRANCH_CHANGED else f"its last judged commit is not on `{name}`"
        return ( f"The duplicate check refused to run: {what.replace('`', '')}.",
                 f"Progress is recorded per branch, and {what}.\n\nTo keep going on the old branch, reinstall with `--branch {refusal['previous']}`. To start `{name}` fresh, delete last-success.json and baseline.json in the check's folder." )
    if refusal[ "refusal" ] == STALE_BRANCH: spoken, why = f"The daily duplicate check refused to run: its branch {name} has been idle {refusal[ 'idle_days' ]} days.", f"Pinned branch `{name}` has not moved in {refusal[ 'idle_days' ]} days and `{refusal[ 'newest' ]}` has a newer commit ({refusal[ 'newest_at' ]})."
    else:                                      spoken, why = f"The daily duplicate check refused to run: its branch {name} no longer exists.", f"Pinned branch `{name}` does not resolve to a commit."
    fix = f"Reinstall for the newest branch:\n\n    {command}" if command is not None else "No other local branch exists, so there is nothing to reinstall for; restore the branch or pin another."
    return spoken, f"{why}\n\n{fix}"


def baseline_installed( cmd=None ):
    """
    Say whether the crontab holds this job's baseline line.

    Requires:
        - cmd is the crontab command as a list, or None for the DUPLICATE_CHECK_DAILY_CRONTAB variable or crontab
    Ensures:
        - returns True when a line ending with CRON_TAG runs with --baseline
        - returns False when there is no crontab or the command cannot run
    """
    try: read = subprocess.run( [ *( cmd or [ os.environ.get( "DUPLICATE_CHECK_DAILY_CRONTAB", "crontab" ) ] ), "-l" ], capture_output=True, text=True )
    except OSError: return False
    return read.returncode == 0 and any( line.rstrip().endswith( CRON_TAG ) and " --baseline" in line for line in read.stdout.splitlines() )


def live_notifier( message, abstract, environ=None, query=None, api_key=None, target_of=None, priority="high", kind="alert" ):
    """
    Send Rick one notification, a high-priority alert unless told otherwise.

    Requires:
        - query is a callable ( base, key, path, params ) returning ( status, text ), or None for the live one; api_key and target_of likewise
    Ensures:
        - returns True when the server answered 200
        - never raises: no key, no recipient or a failed post returns False
    """
    from cosa.utils import hook_link_tick as hlt
    environ = os.environ if environ is None else environ
    base    = environ.get( "LUPIN_API_BASE", lt.DEFAULT_API_BASE ).rstrip( "/" )
    try: key, target = ( api_key or hlt._api_key )(), ( target_of or hlt._notify_target )( environ )
    except Exception: return False
    if not target: return False
    status, _ = ( query or hlt.post_query )( base, key, "/api/notify", { "message": message, "type": kind, "priority": priority, "target_user": target, "abstract": abstract,
                                                                         "sender_id": "claude.code@lupin.deepily.ai#duplicate-check-daily", "idempotency_key": str( uuid.uuid4() ) } )
    return status == 200


def live_urgent( message, abstract, **kwargs ):
    """Ensures: sends the message as an urgent alert, with live_notifier's answer."""
    return live_notifier( message, abstract, priority="urgent", **kwargs )


def live_noter( message, abstract, **kwargs ):
    """Ensures: sends the message as a low-priority progress note, with live_notifier's answer."""
    return live_notifier( message, abstract, priority="low", kind="progress", **kwargs )


def run( root, now, trigger, cap, cli_path, parts, branch=BRANCH, parallel=proof_cli.DEFAULT_PARALLEL, clock=time.monotonic, ceiling=None, baseline=False, rise_limit=RISE_LIMIT ):
    """
    Run the daily check once.

    Requires:
        - root is the main checkout; now is a timezone-aware datetime; trigger is cron, reboot or hand; cap is a whole number of judge calls, at least 0, or None when ceiling is given
        - ceiling, when given, is the most judge calls a run may make; the run's cap is then the number of definitions it has to judge, up to the ceiling
        - baseline judges every definition of the tree instead of the window's new ones; rise_limit is the number of rising daily runs that raises the alarm
        - parts holds client, backend, structural ( a function taking the tree and the frozen configuration and giving judge_all's structural_pairs ), verify, version_fn and data_dir
    Ensures:
        - writes <data_dir>/duplicate-check-daily/<date>-<time>-<trigger>.json: the verdicts' clusters, the window, the judge calls and elapsed_seconds
        - a judge ledger written under another Claude Code version is renamed aside first and a new one started; the result holds ledger_rotated { from, to, old_version, new_version }
        - before anything else, continuity_guard refuses a branch other than the one last-success.json or baseline.json recorded, or a recorded commit that is not on the branch: that file gets status failed, stage branch_guard and the refusal, and the urgent hook is told
        - a continuity refusal that repeats the previous run's is recorded with repeat true and sends no second alert, until a run ends differently
        - then branch_guard runs: a pinned branch that is stale or gone writes that file with status failed, stage branch_guard, the refusal, the reinstall command and notified (the notifier hook's answer, False without one); nothing else changes and last-success does not move
        - a failed prerequisite writes that file with status failed, the prerequisite named, and changes nothing else
        - an exception while building the pool, embedding or judging writes that file with status failed, stage judging and the error, and last-success does not move
        - an exception while reading the frozen configuration, choosing the window or making the worktree writes that file with status failed, stage setup and the error, removes a worktree it began, and moves nothing
        - last-success.json advances to the last commit fully judged; definitions the cap left are carried to the next run
        - a baseline run leaves last-success alone and writes baseline.json: status complete when nothing is carried, else in_progress; once complete, a baseline run judges nothing
        - a daily run whose carried count, with the history's, rose on the last rise_limit measured daily runs records that as rising and alerts through the notifier
        - a filer that raises is caught: the result holds filing { error } and the run ends as if it had filed nothing
        - the same holds for an auditor, whose answer is kept as audit
        - the detached worktrees are removed whether the run ends or fails
        - returns the result document
    Raises:
        - ValueError for a trigger that is not cron, reboot or hand
    """
    if trigger not in TRIGGERS: raise ValueError( f"trigger must be one of {TRIGGERS}, got {trigger!r}" )
    started = clock()
    folder  = pathlib.Path( parts[ "data_dir" ] ).joinpath( *FOLDER )
    stem    = f"{now.date().isoformat()}-{now.strftime( '%H%M%S' )}-{trigger}"
    base    = { "date": now.date().isoformat(), "trigger": trigger, "cap": cap, "ceiling": ceiling, "mode": history.MODE_BASELINE if baseline else history.MODE_DAILY, "branch": branch }
    last    = read_last_success( folder )
    marked  = read_baseline( folder ) if baseline else None
    refused = branch_guard( root, branch, now ) or ( continuity_guard( root, branch, marked.get( "branch" ), None ) if marked else continuity_guard( root, branch, last.get( "branch" ), last[ "commit" ] ) if last and not baseline else None )
    if refused is not None:
        again   = baseline or ( "cron_has_baseline" in parts and parts[ "cron_has_baseline" ]() )       # the reinstall replaces every tagged line, so it must name the baseline line
        command = reinstall_command( root, sys.executable, cap, cli_path, refused[ "newest" ], ceiling, again ) if refused[ "newest" ] is not None else None
        sent    = False
        hook    = "urgent" if refused[ "refusal" ] in CONTINUITY else "notifier"
        before  = ( history.read_lines( folder ) or [ { "failure": None } ] )[ -1 ][ "failure" ]
        repeated = refused[ "refusal" ] in CONTINUITY and before == f"{STAGE_GUARD}: {refused[ 'refusal' ]}"       # the same refusal as the last slot's: Rick was told then
        if hook in parts and not repeated:
            try: sent = parts[ hook ]( *refusal_message( refused, command ) )
            except Exception: sent = False       # a broken notifier must not hide the refusal: the file and the exit code still say it
        doc = { **base, "status": "failed", "stage": STAGE_GUARD, **refused, "reinstall": command, "notified": sent, "repeat": repeated, "judge_calls": 0, "elapsed_seconds": round( clock() - started, 3 ) }
        return record( folder, stem, doc, now )
    if baseline and ( read_baseline( folder ) or { } ).get( "status" ) == BASELINE_DONE:
        return record( folder, stem, { **base, "status": "ok", "note": "baseline complete", "judged": 0, "judge_calls": 0, "carried": [], "elapsed_seconds": round( clock() - started, 3 ) }, now )
    until    = backoff_until( folder, now )
    if until is not None:
        return record( folder, stem, { **base, "status": SKIPPED, "note": f"backing off after a rate limit until {until}", "judge_calls": 0, "elapsed_seconds": round( clock() - started, 3 ) }, now )
    miss    = failed_prerequisite( parts[ "client" ], cli_path, parts[ "verify" ], parts[ "version_fn" ] )
    if miss is not None:
        doc = { **base, "status": "failed", **miss, "judge_calls": 0, "elapsed_seconds": round( clock() - started, 3 ) }
        return record( folder, stem, doc, now )
    doc, target = base, None
    try:
        cfg    = parts[ "verify" ]()
        window = baseline_window( root, branch ) if baseline else window_of( root, last, now, branch )
        doc    = { **base, "window": { "start": window[ "start" ], "end": window[ "end" ], "commits": len( window[ "commits" ] ) } }
        target = pathlib.Path( root ) / source_at.WORKTREES / f"{WORKTREE_PREFIX}{window[ 'end' ][ :9 ]}"
        tree   = source_at.ensure_worktree( root, window[ "end" ], target )
    except Exception as exc:               # the frozen configuration, the window or the worktree failed: leave a record and change nothing else
        if target is not None: release( root, target )
        doc = { **doc, "status": "failed", "stage": STAGE_SETUP, "error": f"{type( exc ).__name__}: {exc}", "judge_calls": 0, "elapsed_seconds": round( clock() - started, 3 ) }
        return record( folder, stem, doc, now )
    count = Counting( parts[ "backend" ] )
    spend = parts.get( "usage", model_transport.claude_usage_summary )
    used0 = spend()
    try:
        fresh = baseline_definitions( tree, window ) if baseline else new_definitions( tree, root, window )
        doc[ "owed" ] = len( fresh[ "defs" ] )
        pool  = pool_without_earlier_versions( tree, fresh[ "defs" ] )
        if ceiling is not None: cap = min( ceiling, len( fresh[ "defs" ] ) )
        out   = { "verdicts": [], "unjudged": [], "dropped": { "count": 0, "ids": [] } }
        if fresh[ "defs" ]:
            rotated = proof_cli.rotate_ledger_for_new_cli( parts[ "data_dir" ], cli_path, parts[ "backend" ], FOLDER )
            if rotated is not None: doc[ "ledger_rotated" ] = rotated
            ledger = proof_cli.proof_ledger( parts[ "data_dir" ], cli_path, parts[ "backend" ], FOLDER )
            wiring = { **proof_cli.base_wiring( folder / VECTORS_DIR, parts[ "structural" ]( tree, cfg ), parallel, parts[ "client" ] ), "backend": count, "ledger": ledger }
            out    = pipeline.judge_all( fresh[ "defs" ], [ *fresh[ "defs" ], *pool ], cfg, wiring, 0, max_calls=cap, skip_breaching=True )
    except Exception as exc:               # the pool build, the embeddings or the judge failed: leave a record and change nothing else
        doc.update( status="failed", stage=STAGE_JUDGING, error=f"{type( exc ).__name__}: {exc}", judge_calls=count.calls, usage=usage_since( used0, spend(), count.calls ), rate_limited=count.limited, elapsed_seconds=round( clock() - started, 3 ) )
        return record( folder, stem, doc, now )
    finally:
        release( root, tree )
    ids    = [ d[ "id" ] for d in [ *fresh[ "defs" ], *pool ] if d[ "id" ] not in set( out[ "dropped" ][ "ids" ] ) ]
    groups = [ g for g in cluster.clusters( ids, cluster.join_pairs( out[ "verdicts" ] ) ) if len( g ) > 1 ]
    moved  = progress( fresh[ "defs" ], fresh[ "commit_of" ], out[ "unjudged" ], window )
    doc.update( usage=usage_since( used0, spend(), count.calls ), rate_limited=count.limited, backoff_until=( now + datetime.timedelta( seconds=BACKOFF_SECONDS ) ).isoformat() if count.limited else None )
    doc.update( status="carried" if moved[ "carried" ] else "ok", judged=len( fresh[ "defs" ] ) - len( moved[ "carried" ] ), judge_calls=count.calls,
                carried=moved[ "carried" ], advanced_to=moved[ "advanced_to" ], clusters=groups, unreadable=[ u for u in out[ "unjudged" ] if u[ "code" ] not in CARRIED_CODES ],
                elapsed_seconds=round( clock() - started, 3 ) )
    found = findings_of( groups, fresh[ "defs" ], pool, doc[ "window" ], parts, fresh[ "commit_of" ] )
    try: settled = behaviour.settled_keys( folder )                    # a finding the triage seat already ruled on stays out of the record and the row until its code changes
    except ValueError as e: settled, doc[ "settled_error" ] = set(), str( e )       # a damaged verdicts file must not lose the judged run, so nothing is left out and the record says why
    found   = [ { **f, "day": doc[ "date" ], "run_file": f"{stem}.json" } for f in found if filing.correlation_key( f[ "id" ], f[ "text" ] ) not in settled ]       # the row names the run's day and the file that lists every finding
    doc[ "findings" ] = [ filing.for_record( f ) for f in found ]       # kept on every run, filer or not: the weekly page counts them, and duplicate_check_refile files them again after a filing error
    for hook, key in ( ( "filer", "filing" ), ( "auditor", "audit" ) ):
        if hook not in parts: continue
        try: doc[ key ] = parts[ hook ]( found, folder )
        except Exception as e: doc[ key ] = { "error": f"{type( e ).__name__}: {e}" }       # a broken store client or config must not stop last-success, or the next run re-judges and re-spends the cap
    if baseline: write_json( folder / BASELINE, { "status": BASELINE_OPEN if moved[ "carried" ] else BASELINE_DONE, "end": window[ "end" ], "carried": len( moved[ "carried" ] ), "at": now.isoformat(), "branch": branch } )
    else:
        write_json( folder / LAST_SUCCESS, { "commit": moved[ "advanced_to" ], "at": now.isoformat(), "branch": branch } )
        rising = rising_guard( folder, doc, now, rise_limit, parts.get( "notifier" ) )
        if rising is not None: doc[ "rising" ] = rising
    doc[ "cap" ] = cap
    return record( folder, stem, doc, now )


def chunk_for( folder, ceiling, fill=HOUR_FILL ):
    """
    Size one hourly run's judge calls.

    Requires:
        - ceiling is the most calls a run may make, at least 1
    Ensures:
        - returns the number of calls that fill fill of an hour at the seconds a call took on the latest sizeable runs (SECONDS_PER_CALL without such a run), at least 1 and at most ceiling
    """
    per = status_mod.median_seconds_per_call( history.read_lines( folder ) ) or SECONDS_PER_CALL
    return max( 1, min( ceiling, int( HOUR_SECONDS * fill / per ) ) )


def announce( parts, folder, docs, now, zero_before ):
    """
    Tell Rick what the hourly run did.

    Requires:
        - docs are the result documents the run wrote; zero_before is the projected zero date before the run, or None
    Ensures:
        - a failed run gets one urgent alert naming its failure, unless the branch guard already sent its own
        - a run that hit the rate limit, or made twenty calls and judged none, gets an urgent alert; a skipped slot's note says it is backing off and until when
        - a projected zero date that moved later by more than a day gets one urgent alert
        - a run that did something, or left a backlog, gets one low-priority note; a quiet run gets none
        - a missing hook sends nothing and a hook that raises is ignored, so a broken notifier never changes a run's outcome
    """
    snap = status_mod.snapshot( folder, now )
    send = lambda hook, spoken, abstract: parts[ hook ]( spoken, abstract ) if hook in parts else None
    link = f"[Open the status page](/app/duplicate-check)\n\n{snap[ 'backlog' ][ 'total' ]} definitions left; health {snap[ 'health' ]}."
    todo = []
    for doc in docs:
        line = history.line_of( doc, "" )
        if line[ "failure" ] is not None and "refusal" not in doc: todo.append( ( "urgent", f"The duplicate check {line[ 'mode' ]} run failed: {line[ 'failure' ]}.", link ) )
        if line[ "rate_limited" ]: todo.append( ( "urgent", f"The duplicate check {line[ 'mode' ]} run hit the rate limit; it is backing off until {datetime.datetime.fromisoformat( line[ 'backoff_until' ] ).strftime( '%H:%M' )}.", link ) )
        elif ( line[ "judge_calls" ] or 0 ) >= ALL_FAILED_CALLS and not line[ "judged" ]: todo.append( ( "urgent", f"The duplicate check {line[ 'mode' ]} run made {line[ 'judge_calls' ]} calls and judged none.", link ) )
        note = f"Duplicate check slot skipped: {doc[ 'note' ]}." if line[ "status" ] == SKIPPED else status_mod.note_of( line, snap )
        if note is not None: todo.append( ( "noter", note, link ) )
    if status_mod.slipped( zero_before, snap[ "projected_zero" ] ): todo.append( ( "urgent", f"The duplicate check backlog now reaches zero on {snap[ 'projected_zero' ]}, after {zero_before}.", link ) )
    for hook, spoken, abstract in todo:
        try: send( hook, spoken, abstract )
        except Exception: pass       # a broken notifier must not change what the run recorded


def adaptive_run( root, now, trigger, cli_path, parts, branch, parallel, ceiling, rise_limit=ADAPTIVE_RISE_LIMIT, clock=time.monotonic ):
    """
    Run one hourly slot, the day's owed work first and then the baseline.

    Requires:
        - ceiling is the most judge calls the slot may make, at least 1; the other arguments are run's
    Ensures:
        - the chunk is chunk_for( ceiling ): what fits in the hour at the measured speed
        - a daily run takes the chunk; when it finishes everything owed (status ok) and the baseline is not complete, a baseline run takes what the daily run left, if at least MIN_BASELINE_CALLS
        - with nothing owed the daily run exits in seconds without a judge call
        - a daily run that was backed off, failed or carried definitions is not followed by a baseline run
        - announce is called once, after both runs
        - returns the result documents, daily first
    """
    folder = pathlib.Path( parts[ "data_dir" ] ).joinpath( *FOLDER )
    before = status_mod.snapshot( folder, now )[ "projected_zero" ]
    chunk  = chunk_for( folder, ceiling )
    docs   = [ run( root, now, trigger, None, cli_path, parts, branch, parallel, clock, ceiling=chunk, rise_limit=rise_limit ) ]
    left   = chunk - ( docs[ 0 ][ "judge_calls" ] or 0 )
    if docs[ 0 ][ "status" ] == "ok" and left >= MIN_BASELINE_CALLS and ( read_baseline( folder ) or { } ).get( "status" ) != BASELINE_DONE:
        later = now + datetime.timedelta( seconds=max( 1, math.ceil( docs[ 0 ][ "elapsed_seconds" ] ) ) )       # a distinct second, so the two result files have distinct names
        docs.append( run( root, later, trigger, None, cli_path, parts, branch, parallel, clock, ceiling=left, baseline=True ) )
    announce( parts, folder, docs, now + datetime.timedelta( seconds=1 ), before )
    return docs


def live_rows_by_mark( settings=None, api_key=None, client=None, max_rows=ROW_SCAN_LIMIT ):
    """
    Count the rows in the store that carry the job's mark.

    Requires:
        - the mark is a correlation_key starting with the filer's KEY_PREFIX; the creator is "<persona> (duplicate-check-daily)"
    Ensures:
        - returns { found, open }: found counts every row the mark names, held ones included; open those not done, dropped or wont_fix
        - returns None when the store cannot be read in full: any failed read or a board longer than max_rows is no answer, never a short count
    """
    try:
        from lupin_cli.claude_code.hooks.lib import task_store_client as client_mod, task_store_settings
        client   = client or client_mod
        settings = settings or task_store_settings.load_task_store_settings()
        token    = client.read_api_key() if api_key is None else api_key
        board, cut = client.fetch_board( settings, token, max_rows )
        held, offset = [], 0
        while True:
            ok, status, page = client.query_tasks( settings, token, { "status": "not_approved", "project": filing.PROJECT, "limit": 500, "offset": offset } )
            if not ok: return None
            held.extend( page[ "tasks" ] )
            offset += len( page[ "tasks" ] )
            if not page.get( "has_more" ) or not page[ "tasks" ]: break
    except Exception: return None
    if cut: return None
    mine = { r[ "id" ]: r for r in [ *board, *held ] if ( r[ "correlation_key" ] or "" ).startswith( filing.KEY_PREFIX ) }
    return { "found": len( mine ), "open": sum( 1 for r in mine.values() if r[ "status" ] not in TERMINAL ) }


def finish( parts, folder, now ):
    """
    Rewrite the job summary after a run.

    Ensures:
        - the rows hook, when parts has one, supplies the store count; a hook that raises gives no count
        - a failed write is printed and changes nothing, so a summary problem never fails the job
    """
    try: rows = parts[ "rows_by_mark" ]() if "rows_by_mark" in parts else None
    except Exception: rows = None
    try: status_mod.write_job_summary( folder, now, rows )
    except Exception as exc: print( f"duplicate-check-daily: the job summary was not written: {type( exc ).__name__}: {exc}", file=sys.stderr )


def exit_code( docs ):
    """Ensures: returns 3 for a refusal, else 1 when any run failed, else 0."""
    return REFUSED_EXIT if any( "refusal" in d for d in docs ) else 1 if any( d[ "status" ] == "failed" for d in docs ) else 0


def cron_lines( root, python, log_path, cap, cli_path, carried=None, branch=BRANCH, ceiling=None, baseline=False, adaptive=False ):
    """
    Build the cron lines of the daily check.

    Requires:
        - root is the main checkout path; python is the interpreter path; cli_path is the Claude Code binary
        - cap is a whole number of judge calls, or None when ceiling is given
        - carried maps environment names to values, copied into every line and shell-quoted
        - branch is the branch the check judges
    Ensures:
        - returns [ daily line, reboot line ], plus a baseline line before the reboot line when baseline is set; each ends with CRON_TAG
        - with adaptive, returns [ hourly line, reboot line ] only: both run with --adaptive, the hourly one at HOURLY_SCHEDULE, and the baseline drains inside the slots, so baseline adds nothing
        - the daily line runs at CRON_SCHEDULE (10:00, every day) with trigger cron, the baseline line at BASELINE_SCHEDULE (11:07) with --baseline, the reboot line BOOT_DELAY seconds after a boot with trigger reboot; no line runs after last call
        - the reboot line is the catch-up: it reads the window from the last successful run, so a day the host was off is covered at the next boot
        - every line runs from root with LUPIN_ROOT and PYTHONPATH set, appends to log_path, and carries the limit (--cap, or --ceiling when given) and the binary
        - a branch other than the default is added as --branch, shell-quoted, after the trigger; the default adds nothing
    """
    extra = "".join( f"{name}={shlex.quote( value )} " for name, value in ( carried or {} ).items() )
    named = "" if branch == BRANCH else f" --branch {shlex.quote( branch )}"

    def run( trigger, more="" ):
        """Ensures: returns the shell command of one line, its trigger named."""
        return ( f"cd {root} && LUPIN_ROOT={root} PYTHONPATH={root}/src {extra}{python} -m lupin_mcp.duplicate_check_daily "
                 f"{limit_flag( cap, ceiling )} --claude-cli-path {cli_path} --trigger {trigger}{more}{named} >> {log_path} 2>&1 {CRON_TAG}" )

    if adaptive: return [ lt.cron_lines_for( run( "cron", " --adaptive" ), HOURLY_SCHEDULE, BOOT_DELAY )[ 0 ], lt.cron_lines_for( run( "reboot", " --adaptive" ), HOURLY_SCHEDULE, BOOT_DELAY )[ 1 ] ]
    lines = [ lt.cron_lines_for( run( "cron" ), CRON_SCHEDULE, BOOT_DELAY )[ 0 ] ]
    if baseline: lines.append( lt.cron_lines_for( run( "cron", " --baseline" ), BASELINE_SCHEDULE, BOOT_DELAY )[ 0 ] )
    return [ *lines, lt.cron_lines_for( run( "reboot" ), CRON_SCHEDULE, BOOT_DELAY )[ 1 ] ]


def install_mode( args, environ, now, out, err, crontab_cmd ):
    """
    Print, install, remove or report the cron lines.

    Requires:
        - args holds the parsed flags; exactly one of print_install, install, uninstall or status is set; out and err take one line of text
    Ensures:
        - --print-install prints the lines and changes nothing; --install and --uninstall go through the librarian's locked crontab editor with this job's tag and owner
        - --status says whether the lines are present
        - returns 0, or 1 with the reason on err when the install is refused or the crontab call fails
    """
    root    = args.root or environ.get( "LUPIN_ROOT" ) or str( pathlib.Path.cwd() )
    log_dir = f"{root}{proof_cli.DATA_RELATIVE}/{FOLDER[ 0 ]}"
    cmd     = crontab_cmd or [ environ.get( "DUPLICATE_CHECK_DAILY_CRONTAB", "crontab" ) ]
    try:
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            out( lt.status_text( read.stdout if read.returncode == 0 else "", CRON_TAG, INSTALLED_LINES ) )
            return 0
        if args.uninstall:
            lt.edit_crontab( [], environ, cmd, f"{log_dir}/crontab-backups", now, tag=CRON_TAG, owner=LOCK_OWNER )
            out( "uninstalled" )
            return 0
        lines = cron_lines( root, args.python, f"{log_dir}/{LOG_NAME}", args.cap, args.claude_cli_path, { n: environ[ n ] for n in CARRIED if environ.get( n ) }, args.branch, args.ceiling, args.with_baseline, args.adaptive )
        if args.print_install:
            out( "\n".join( lines ) )
            return 0
        lt.edit_crontab( lines, environ, cmd, f"{log_dir}/crontab-backups", now, tag=CRON_TAG, owner=LOCK_OWNER )
        out( f"installed: {len( lines )} lines" )
        return 0
    except ( lt.InstallRefused, RuntimeError ) as e:
        err( f"duplicate-check-daily: {e}" )
        return 1


def live_parts():
    """
    Build the parts a real run uses.

    Ensures:
        - returns the embedding client, the Claude Code backend, the staged structural source, verify_frozen over the live file, cli_version, the data root and the filer
        - the filer files the run's one triage row over HTTP; it builds its store client, reads the roster and the configured manager only when it is called
        - the auditor queues known-miss audits in the lookup tool's data folder, reading it only when it is called
        - the notifier sends the branch guard's alert, urgent the failure and slip alerts and noter the note after a run, each only when it is called
        - cron_has_baseline reads the crontab, only when a branch guard refusal needs the reinstall command
        - writes nothing and makes no call
    """
    base = proof_cli.base_wiring( ".", lambda defs: [], 1, vector_build.EndpointClient() )
    return { "client": base[ "client" ], "backend": base[ "backend" ], "data_dir": base[ "data_dir" ], "version_fn": model_transport.cli_version,
             "verify": lambda: cfg_mod.verify_frozen( base[ "frozen_path" ], base[ "live" ] ),
             "structural": lambda tree, cfg: proof_cli.structural_source( tree, {}, cfg ), "filer": live_filer, "auditor": live_auditor, "notifier": live_notifier,
             "urgent": live_urgent, "noter": live_noter, "rows_by_mark": live_rows_by_mark, "cron_has_baseline": baseline_installed }


def live_filer( findings, folder ):
    """
    File the run's one triage row in the live store.

    Requires:
        - the environment holds LUPIN_ROOT, the configuration manager's argument and the project's declared manager roster
    Ensures:
        - returns file_findings' answer, made with the HTTP store, the configured manager on duty and the roster
    Raises:
        - NoTriageOwner when there are findings and the roster is empty; run records that as the filer's error
    """
    from cosa.rest.voice_persona_helpers import pick_declared_managers_from_env
    from cosa.config.configuration_manager import ConfigurationManager
    declared = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get( "arbiter manager on duty", default="manager-on-duty" ) or "manager-on-duty"
    return filing.file_findings( findings, folder, filing.LiveStore(), declared, pick_declared_managers_from_env( filing.PROJECT ) )


def live_auditor( findings, folder ):
    """
    Queue a known-miss audit for each finding that ties to a lookup receipt.

    Requires:
        - the environment is the lookup tool's: its data folder holds the receipts, the call log and refusals.jsonl
    Ensures:
        - returns queue_audits' answer, made with find_tie over the refusal pairs and the merged call logs
        - the audit queue and the receipts are read from and written to the lookup tool's own data folder
        - makes no model call
    """
    ctx = rt.context_from_environment()
    records, _bad = eg.merge_call_logs( ctx.data / "call-log" )
    rows = behaviour.read_refusals( ctx.data )
    tie  = lambda finding: tie_mod.find_tie( finding[ "id" ], rows, records, ctx.root, finding[ "commit" ] )
    return audit.queue_audits( findings, tie, lambda rid: rt.load_receipt( ctx, rid ), ctx.data, datetime.date.today().isoformat() )


@contextlib.contextmanager
def run_lock( data_dir ):
    """
    Hold the run lock for the length of one run, or say another run holds it.

    Requires:
        - data_dir is the fleet data folder the result files go under

    Ensures:
        - yields True when this process took an exclusive lock on RUN_LOCK in the check's folder, and keeps it until the block ends
        - yields False at once, waiting for nothing, when another live process holds it
        - the operating system drops the lock when its holder ends, so a run that was killed leaves nothing behind
        - the lock file is never removed, which keeps two processes from locking two different files
    """
    folder = pathlib.Path( data_dir ).joinpath( *FOLDER )
    folder.mkdir( parents=True, exist_ok=True )
    with open( folder / RUN_LOCK, "a" ) as handle:
        try: fcntl.flock( handle, fcntl.LOCK_EX | fcntl.LOCK_NB )
        except BlockingIOError:
            yield False
            return
        try: yield True
        finally: fcntl.flock( handle, fcntl.LOCK_UN )


def main( argv=None, parts=None, now=None, out=print, environ=None, err=None, crontab_cmd=None ):
    """
    Run the daily check from the command line.

    Requires:
        - argv holds one of --cap ( a fixed number of judge calls ) and --ceiling ( the most judge calls an adaptive run may make ), neither with a default, needed to run or to print or install the cron lines
        - --adaptive ( with --ceiling ) runs the hourly slot: the day's owed definitions, then the baseline with the rest of the chunk, then a note to Rick
        - --branch auto judges the newest local wip-* branch
        - argv also holds --claude-cli-path, and optionally --root, --trigger ( default hand ), --branch, --parallel, --baseline ( judge every definition of the tree ), --rise-limit ( default RISE_LIMIT ) and, with the cron modes, --with-baseline ( add the baseline line )
        - one of --print-install, --install, --uninstall or --status, with --python, works on the cron lines instead of running
    Ensures:
        - prints the result document as JSON (a list of them, daily first, with --adaptive) and returns 0, REFUSED_EXIT (3) when the branch guard refused, or 1 when anything else failed
        - the cron modes never run the check
        - after a run the job summary is rewritten beside the ledger, with the count of store rows that carry the job's mark
        - a run takes run_lock first; when another run holds it, prints a skipped document and returns 0 without running anything, so a boot near 10:00 that starts the cron line and the reboot line together runs the check once
    """
    ap = argparse.ArgumentParser( description="Judge the day's new definitions for duplicates." )
    limit = ap.add_mutually_exclusive_group()
    limit.add_argument( "--cap", type=int, default=None )
    limit.add_argument( "--ceiling", type=int, default=None )
    ap.add_argument( "--baseline", action="store_true" )
    ap.add_argument( "--with-baseline", action="store_true" )
    ap.add_argument( "--adaptive", action="store_true" )
    ap.add_argument( "--rise-limit", type=int, default=None )
    ap.add_argument( "--claude-cli-path", default=None )
    ap.add_argument( "--root", default=None )
    ap.add_argument( "--trigger", default="hand", choices=TRIGGERS )
    ap.add_argument( "--branch", default=BRANCH )
    ap.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    ap.add_argument( "--python", default=sys.executable )
    mode = ap.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    args = ap.parse_args( argv )
    cron = args.install or args.uninstall or args.status or args.print_install
    if args.adaptive and ( args.ceiling is None or args.baseline ) and not ( args.uninstall or args.status ): ap.error( "--adaptive needs --ceiling and cannot be combined with --baseline: the slot drains the baseline itself" )
    if args.cap is None and args.ceiling is None and not ( args.uninstall or args.status ): ap.error( "--cap or --ceiling is required: the daily check has no default limit" )
    if cron: return install_mode( args, os.environ if environ is None else environ, now or datetime.datetime.now(), out, err or ( lambda line: print( line, file=sys.stderr ) ), crontab_cmd )
    model_transport.configure( args.claude_cli_path )
    root = args.root or git( ".", "rev-parse", "--show-toplevel" )
    with contextlib.redirect_stdout( sys.stderr ):
        parts = parts or live_parts()
        with run_lock( parts[ "data_dir" ] ) as held:
            if not held:
                out( json.dumps( { "status": "skipped", "trigger": args.trigger, "note": "another run holds the run lock" }, indent=2, sort_keys=True ) )
                return 0
            branch = resolve_branch( root, args.branch )
            when   = now or datetime.datetime.now().astimezone()
            if args.adaptive: docs = adaptive_run( root, when, args.trigger, args.claude_cli_path, parts, branch, args.parallel, args.ceiling, ADAPTIVE_RISE_LIMIT if args.rise_limit is None else args.rise_limit )
            else:             docs = [ run( root, when, args.trigger, args.cap, args.claude_cli_path, parts, branch, args.parallel, ceiling=args.ceiling, baseline=args.baseline, rise_limit=RISE_LIMIT if args.rise_limit is None else args.rise_limit ) ]
    finish( parts, pathlib.Path( parts[ "data_dir" ] ).joinpath( *FOLDER ), when )
    out( json.dumps( docs if args.adaptive else docs[ 0 ], indent=2, sort_keys=True ) )
    return exit_code( docs )


if __name__ == "__main__":  # pragma: no cover - the entry only calls main
    raise SystemExit( main() )
