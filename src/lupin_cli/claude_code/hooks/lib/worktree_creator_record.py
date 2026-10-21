"""
Records which manager a worker's worktree belongs to, at the moment the worker makes it.

A worker creates its own review tree with `git worktree add .claude/worktrees/<name>`.
The janitor retires that tree hours later, after the worker's bridge is gone.
The archive row then has only the branch name to go on.

This hook runs before the Bash call and writes one ledger entry: tree path, branch and spawning manager.
The manager comes from COSA_VOICE_SPAWNED_BY_PERSONA, which the seat already carries.
A seat spawned before that variable existed has only COSA_VOICE_SPAWNED_BY, the manager's session id.
Its manager is then read from that session's bridge.

The ledger is <fleet data root>/worktree-creators.json, so every seat of one repo shares it.
A reap never deletes it. A seat that no manager spawned records nothing.

Text matching reads the ordinary spellings of the command.
These are `git worktree add`, `git -C dir worktree add` and `cd dir && ...`.
A path to git and the options -b, -B, --detach and --force are read too.
It fails open: any error records nothing and never blocks the call.
The threat model is accident, as in stash_guard.
"""
import fcntl
import json
import os
import re
import shlex
import subprocess
import time
from typing import List, Optional

from lupin_cli.claude_code.hooks.lib.heartbeat_hold import fleet_data_root

LEDGER_NAME      = "worktree-creators.json"
SPAWNED_BY_ENV   = "COSA_VOICE_SPAWNED_BY_PERSONA"
SPAWNER_ID_ENV   = "COSA_VOICE_SPAWNED_BY"
SANDBOX_SEGMENT  = "/.claude/worktrees/"
RETENTION_DAYS   = 60
_SEGMENT_SPLIT   = re.compile( r"&&|\|\||[;|\n]" )
_OPTS_WITH_VALUE = ( "-b", "-B", "--reason" )
_GIT_OPTS_VALUE  = ( "-C", "-c", "--git-dir", "--work-tree" )


def ledger_path( repo_root: str ) -> str:
    """
    Return the creator ledger file of a repository.

    Requires:
        - repo_root is the main checkout or any worktree of the repo

    Ensures:
        - returns <fleet data root of that repo>/worktree-creators.json; a worktree resolves to its parent
    """
    return os.path.join( str( fleet_data_root( repo_root ) ), LEDGER_NAME )


def _is_git( token: str ) -> bool:
    """Ensures: returns True for `git` however the path to it is spelled."""
    return os.path.basename( token ) == "git"


def parse_worktree_adds( command: str, cwd: str ) -> List[ dict ]:
    """
    List the `git worktree add` calls in a shell command.

    Requires:
        - command is the Bash tool's command text; cwd is the directory it runs in

    Ensures:
        - returns [ { path, branch } ] in command order: path is absolute, branch is the -b/-B name or None
        - a leading `cd <dir>` and git's `-C <dir>` move the base a relative path resolves against
        - a segment that cannot be tokenized, or has no path after `add`, is skipped; never raises
    """
    out, base = [], cwd
    for segment in _SEGMENT_SPLIT.split( command ):
        try:
            tokens = shlex.split( segment )
        except ValueError:
            continue
        if len( tokens ) >= 2 and tokens[ 0 ] == "cd":
            base = os.path.normpath( os.path.join( base, os.path.expanduser( tokens[ 1 ] ) ) )
            continue
        git_at = next( ( i for i, t in enumerate( tokens ) if _is_git( t ) ), None )
        if git_at is None: continue
        i, here = git_at + 1, base
        while i < len( tokens ) and tokens[ i ].startswith( "-" ):
            if tokens[ i ] == "-C" and i + 1 < len( tokens ): here = os.path.normpath( os.path.join( here, tokens[ i + 1 ] ) )
            i += 2 if tokens[ i ] in _GIT_OPTS_VALUE else 1
        if tokens[ i : i + 2 ] != [ "worktree", "add" ]: continue
        branch, path, j = None, None, i + 2
        while j < len( tokens ):
            if tokens[ j ] in ( "-b", "-B" ) and j + 1 < len( tokens ): branch = tokens[ j + 1 ]; j += 2
            elif tokens[ j ] in _OPTS_WITH_VALUE: j += 2
            elif tokens[ j ].startswith( "-" ): j += 1
            else:
                path = path or tokens[ j ]; j += 1                    # the first positional is the path, a later one the commit-ish
        if path: out.append( { "path": os.path.normpath( os.path.join( here, os.path.expanduser( path ) ) ), "branch": branch } )
    return out


def _repo_of( path: str, cwd: str ) -> str:
    """
    Return the repo a new tree belongs to.

    This is the folder above its sandbox segment, else the git toplevel of cwd.
    """
    if SANDBOX_SEGMENT in path: return path.split( SANDBOX_SEGMENT )[ 0 ]
    top = subprocess.run( [ "git", "rev-parse", "--show-toplevel" ], cwd=cwd, capture_output=True, text=True, timeout=10 )
    return top.stdout.strip() if top.returncode == 0 and top.stdout.strip() else cwd


def _store_words( persona: str ) -> str:
    """Return a persona in the store's key shape ("Mr. Radio" gives "mr radio")."""
    from lupin_cli.claude_code.hooks.lib.session_bridge import canonical_persona_key
    return canonical_persona_key( persona )


def spawning_manager( env: dict ) -> Optional[ str ]:
    """
    Name the manager that spawned this seat, from the seat's environment.

    Ensures:
        - returns the store-shaped persona in COSA_VOICE_SPAWNED_BY_PERSONA when it is set
        - otherwise returns the voice persona of the manager session named by COSA_VOICE_SPAWNED_BY, read from
          that session's bridge: a seat spawned before the persona variable existed carries only the id
        - returns None for a seat no manager spawned, or when neither source answers; never raises
    """
    persona = env.get( SPAWNED_BY_ENV, "" ).strip()
    if persona: return _store_words( persona )
    manager_id = env.get( SPAWNER_ID_ENV, "" ).strip()
    if not manager_id: return None
    from lupin_cli.claude_code.hooks.lib.session_bridge import get_voice_persona
    voice = get_voice_persona( manager_id )
    name  = voice.get( "name" ) if isinstance( voice, dict ) else None
    return _store_words( name ) if isinstance( name, str ) and name.strip() else None


def write_entries( ledger: str, adds: List[ dict ], manager: str, now: Optional[ float ] = None ) -> None:
    """
    Add entries to the ledger under a file lock.

    Ensures:
        - entries older than the retention window are dropped
        - trees[ path ] and branches[ branch ] each name the manager; an entry already there is overwritten
        - the write is atomic (temp file then rename) and serialized across processes by a lock file
    Raises:
        - OSError when the ledger folder cannot be written; the caller swallows it
    """
    now = now if now is not None else time.time()
    os.makedirs( os.path.dirname( ledger ), exist_ok=True )
    with open( ledger + ".lock", "w" ) as lock:
        fcntl.flock( lock, fcntl.LOCK_EX )
        try:
            with open( ledger ) as f: data = json.load( f )
        except ( OSError, ValueError ):
            data = {}
        trees    = { p: e for p, e in data.get( "trees", {} ).items() if now - e.get( "ts", 0 ) < RETENTION_DAYS * 86400 }
        branches = { b: e for b, e in data.get( "branches", {} ).items() if now - e.get( "ts", 0 ) < RETENTION_DAYS * 86400 }
        for add in adds:
            trees[ add[ "path" ] ] = { "manager": manager, "branch": add[ "branch" ], "ts": now }
            if add[ "branch" ]: branches[ add[ "branch" ] ] = { "manager": manager, "path": add[ "path" ], "ts": now }
        tmp = f"{ledger}.{os.getpid()}.tmp"
        with open( tmp, "w" ) as f: json.dump( { "trees": trees, "branches": branches }, f, indent=1, sort_keys=True )
        os.replace( tmp, ledger )


def record_worktree_creator( tool_name: str, tool_input: dict, cwd: str, environ: Optional[ dict ] = None,
                             now: Optional[ float ] = None ) -> List[ str ]:
    """
    Record the spawning manager for each worktree a Bash command is about to create.

    Requires:
        - tool_name and tool_input are the hook payload's fields; cwd is the payload's cwd

    Ensures:
        - does nothing unless tool_name is Bash, the command holds a `git worktree add`, and spawning_manager
          names the manager of this seat
        - returns the tree paths recorded; a failure of any kind returns [] and never raises or blocks the call
    """
    try:
        env = environ if environ is not None else os.environ
        if tool_name != "Bash" or not isinstance( tool_input, dict ): return []
        command = tool_input.get( "command" )
        if not isinstance( command, str ) or "worktree" not in command: return []
        adds = parse_worktree_adds( command, cwd or os.getcwd() )
        if not adds: return []
        manager = spawning_manager( env )
        if not manager: return []
        write_entries( ledger_path( _repo_of( adds[ 0 ][ "path" ], cwd or os.getcwd() ) ), adds, manager, now=now )
        return [ a[ "path" ] for a in adds ]
    except Exception:
        return []
