"""
Open one store row per worktree refused for over a day; close it when the tree is gone.

A refusal notify is a card, and a card scrolls away. A straggler refused for 24 hours becomes a row with an owner,
so the pile is somebody's owed work instead of nobody's surprise.

  * owner / accountable manager: a seat tree `seat-cc-<role>-<manager>-<n>` records its spawning manager
    in its name (session_spawner builds it from the manager's persona slug), and the seat's own persona
    is gone once the seat is reaped. So both fields name that manager.
    A branch or tree is resolved by resolve_creator, in this order.
    First the manager stamped on the branch at reap (git config `branch.<name>.lupin-manager`).
    Then a seat tree's own name. Then the spawn registry, for a name that begins with a worker persona. A name none of them resolves goes to NO_CREATOR_OWNER,
    who triages it, and the body lists the lookups that were tried.
  * dedupe: correlation key `worktree:<absolute tree path>`, one row per tree.
  * door: a direct repository write, not /api/tasks. The router would mint the row into the holding area,
    where the arbiter can never move it out again, so it could never close its own tickets.
    The throughput counter excludes the `worktree:` lane (task_repository.count_created_and_closed)
    so these rows, which close as `dropped`, never count against anyone else's creates.
  * close: `dropped`, reason "tree absent at <ts>". A system actor has no honest receipt for `done`.

The clock: `first_refused_at` lives in a sidecar beside the refusal ledger. A tree seen refused for the first time
gets an estimate, capped at now. The estimate is the moment its newest file went idle plus the janitor's own
idle threshold, the earliest a sweep could have refused it. The row body says the time is estimated.
"""

import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from cosa.utils.atomic_json import load_json_section

STRAGGLER_KEY_PREFIX  = "worktree:"
STRAGGLER_AGE_HOURS   = 24.0
NO_CREATOR_OWNER      = "maria"
ARBITER_ACTOR         = "heartbeat-arbiter@lupin.deepily.ai"
STRAGGLER_PRIORITY    = "P3"
SANDBOX_SEGMENT       = "/.claude/worktrees/"
SEAT_TREE_RE          = re.compile( r"^seat-cc-(?P<role>[a-z]+)-(?P<manager>[a-z0-9-]+?)-(?P<n>\d+)$" )
MAX_BODY_BLOCKERS     = 10


def straggler_key( path: str ) -> str:
    """
    The dedupe key for one tree.

    Ensures:
        - returns "worktree:" + the absolute, normalized path — one key per tree
    """
    return STRAGGLER_KEY_PREFIX + os.path.abspath( path )


MANAGER_STAMP_KEY = "branch.{branch}.lupin-manager"


def _plain_run( argv, cwd=None, timeout=60 ):
    """Run argv with subprocess; the default git runner of the stamp helpers."""
    return subprocess.run( argv, cwd=cwd, capture_output=True, text=True, timeout=timeout )


def _manager_words( name: str ) -> str:
    """Return a persona in the store's key shape: "Mr. Radio" gives "mr radio"."""
    from lupin_mcp.persona_normalization import canonical_persona_key
    return canonical_persona_key( name.replace( "-", " " ) )


def read_stamp( project_root: str, branch: str, run: Optional[ Callable ] = None ) -> Optional[ str ]:
    """
    Read the manager stamped on a branch.

    Requires:
        - project_root is a repository root; run is None or a runner taking ( argv, cwd=, timeout= )

    Ensures:
        - returns the value of git config `branch.<branch>.lupin-manager` in that repo, or None when it is
          unset, blank, or git could not be run; never raises
    """
    run = run if run is not None else _plain_run
    try:
        done = run( [ "git", "config", "--get", MANAGER_STAMP_KEY.format( branch=branch ) ], cwd=project_root, timeout=60 )
    except Exception:
        return None
    value = ( done.stdout or "" ).strip() if done.returncode == 0 else ""
    return value or None


def write_stamp( project_root: str, branch: str, manager: str, run: Optional[ Callable ] = None ) -> bool:
    """
    Stamp a branch with the manager that owns it.

    Ensures:
        - sets git config `branch.<branch>.lupin-manager` to manager; returns True on success
        - returns False, changing nothing, when git fails; never raises
        - the stamp is repo config, so it outlives the worktree and the branch's move to refs/archive
    """
    run = run if run is not None else _plain_run
    try:
        done = run( [ "git", "config", MANAGER_STAMP_KEY.format( branch=branch ), manager ], cwd=project_root, timeout=60 )
    except Exception:
        return False
    return done.returncode == 0


def spawn_registry_manager( persona: str ) -> Optional[ str ]:
    """
    Find the manager that spawned a worker persona, from the live session bridges.

    Ensures:
        - returns the store-shaped manager name frozen at spawn (`spawned_by_persona`) on the bridge(s) whose
          voice persona is `persona`, or None when no live bridge carries it
        - returns None when two bridges of that persona name different managers (ambiguous: never guess)
        - never raises
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import iter_live_bridges
        key, found = _manager_words( persona ), set()
        for _, data, _ in iter_live_bridges():
            voice = data.get( "voice_persona" )
            name  = voice.get( "name" ) if isinstance( voice, dict ) else None
            by    = data.get( "spawned_by_persona" )
            if isinstance( name, str ) and isinstance( by, str ) and by.strip() and _manager_words( name ) == key:
                found.add( _manager_words( by ) )
        return found.pop() if len( found ) == 1 else None
    except Exception:
        return None


def resolve_creator( name: str, project_root: Optional[ str ] = None, branch: Optional[ str ] = None,
                     run: Optional[ Callable ] = None, registry_fn: Optional[ Callable ] = None ) -> dict:
    """
    Find the manager a tree or branch belongs to, trying each lookup in order.

    Requires:
        - name is the tree name (or the branch name minus its rescue stamp)
        - branch and project_root, when both are given, enable the stamp lookup
        - registry_fn is None (spawn_registry_manager) or takes a persona and returns a manager or None

    Ensures:
        - tries, in order: the branch stamp, a seat tree's own name, the spawn registry for the name's first segment
        - returns { manager, source, tried } where source is "branch stamp", "seat tree name" or "spawn registry"
          for the lookup that answered, and manager is None with source None when none did
        - tried lists every lookup attempted, so a row can say what was looked up; never raises
    """
    registry_fn = registry_fn if registry_fn is not None else spawn_registry_manager
    tried       = []
    if branch and project_root:
        tried.append( "branch stamp" )
        stamp = read_stamp( project_root, branch, run )
        if stamp: return { "manager": _manager_words( stamp ), "source": "branch stamp", "tried": tried }
    else:
        tried.append( "branch stamp (no branch or repo root given)" )
    tried.append( "seat tree name" )
    m = SEAT_TREE_RE.match( name )
    if m: return { "manager": m.group( "manager" ).replace( "-", " " ), "source": "seat tree name", "tried": tried }
    first = name.split( "-" )[ 0 ]
    tried.append( f"spawn registry for '{first}'" )
    try:
        manager = registry_fn( first ) if first else None
    except Exception:
        manager = None
    if manager: return { "manager": manager, "source": "spawn registry", "tried": tried }
    return { "manager": None, "source": None, "tried": tried }


def _owner_from( found: dict ) -> dict:
    """
    Return the owner dict for a resolve_creator result.

    Ensures:
        - returns { owner, accountable, creator_recorded, source, tried }
    """
    who = found[ "manager" ] if found[ "manager" ] else NO_CREATOR_OWNER
    return { "owner": who, "accountable": who, "creator_recorded": found[ "manager" ] is not None,
             "source": found[ "source" ], "tried": found[ "tried" ] }


def owner_for_tree( path: str, registry_fn: Optional[ Callable ] = None ) -> dict:
    """
    Who owns the straggler row for a tree.

    Requires:
        - path is a worktree path (its basename is the tree's name)

    Ensures:
        - a seat tree `seat-cc-<role>-<manager-slug>-<n>` → owner and accountable are the
          manager slug with hyphens as spaces (the store's canonical key shape, e.g.
          "mr-radio" → "mr radio"), creator_recorded True
        - a name whose first segment is a worker persona with a live spawn record → that worker's
          spawning manager
        - anything else → both NO_CREATOR_OWNER, creator_recorded False
        - returns { owner, accountable, creator_recorded, source, tried }; never raises
    """
    return _owner_from( resolve_creator( os.path.basename( os.path.normpath( path ) ), registry_fn=registry_fn ) )


# ==========================================================================
# Archived branches — one row per unmerged branch that never landed (row aec2319f)
# ==========================================================================
#
# Rick's ruling, 2026-10-02: unmerged rescued work is archived and ticketed, never
# auto-merged. The reaper does the archiving (retire_branch); this opens the row, so the
# work has an owner before the 14-day sweep removes the archive ref.

ARCHIVE_KEY_PREFIX = "archive:"
RESCUE_STAMP_RE    = re.compile( r"-\d{8}T\d{6}Z$" )


def owner_for_branch( branch: str, project_root: Optional[ str ] = None, run: Optional[ Callable ] = None,
                      registry_fn: Optional[ Callable ] = None ) -> dict:
    """
    Who owns the row for an archived branch.

    Requires:
        - project_root, when given, is the repository that holds the branch's config

    Ensures:
        - a manager stamped on the branch (git config `branch.<branch>.lupin-manager`, written when the reaper
          retired the branch's tree) is read first
        - otherwise the last path segment, minus a rescue stamp (`-YYYYMMDDTHHMMSSZ`), is resolved as a
          tree name by resolve_creator: `wt-rescue/seat-cc-author-cheech-2-20261002T135947Z` belongs to cheech,
          and `wt-rescue/arnold-review-ab12cd3-20261019T011500Z` to the manager who spawned arnold
        - any other name has no recorded creator
        - returns { owner, accountable, creator_recorded, source, tried }; never raises
    """
    name = RESCUE_STAMP_RE.sub( "", branch.rsplit( "/", 1 )[ -1 ] )
    return _owner_from( resolve_creator( name, project_root=project_root, branch=branch, run=run, registry_fn=registry_fn ) )


def compose_archive_row( outcome: dict ) -> dict:
    """
    The row fields for one archived branch whose work did not land.

    Requires:
        - outcome is retire_branch's dict with kept_reason "archived", plus repo_root
          (the arbiter adds it) or without it (then the project is "lupin")

    Ensures:
        - returns { title, body, owner, accountable, project, correlation_key }; the key
          is "archive:" + the archive ref, one per archived tip
        - the body names the ref, the sha, the count ahead, what landed means here, the
          restore command and the 14-day deadline
    """
    branch  = outcome[ "branch" ]
    ref     = outcome[ "archive_ref" ]
    root    = outcome.get( "repo_root" )
    who     = owner_for_branch( branch, project_root=root )
    project = os.path.basename( os.path.normpath( root ) ) if root else "lupin"
    ahead   = outcome.get( "commits_ahead" )
    state   = ( "could not be checked for content already on the working branch"
                if outcome.get( "landed" ) is None else "holds commits whose content is not on the working branch" )
    lines = [
        f"The worktree janitor archived branch `{branch}` at `{ref}` (sha `{outcome.get( 'sha' )}`).",
        f"It is {ahead if ahead is not None else 'an unknown number of'} commits ahead of `{outcome.get( 'target' )}` and {state}.",
        "",
        "Nothing was merged and nothing was deleted. The archive ref is removed 14 days after the day in its name.",
        f"Restore it with: `git update-ref refs/heads/{branch} {outcome.get( 'sha' )}`",
        "",
        "Merge what is green and reviewed, or close this row as dropped if the work is not wanted.",
    ]
    if not who[ "creator_recorded" ]:
        lines += [ "", f"No creator recorded: the branch name does not identify a seat, so it is assigned to {NO_CREATOR_OWNER} for triage.",
                   f"Lookups tried, none answered: {'; '.join( who[ 'tried' ] )}." ]
    else:
        lines += [ "", f"Creator: {who[ 'owner' ]}, from the {who[ 'source' ]}." ]
    return {
        "title"           : f"[{project.upper()}] Archived unmerged branch: {branch}"[ :120 ],
        "body"            : "\n".join( lines ),
        "owner"           : who[ "owner" ],
        "accountable"     : who[ "accountable" ],
        "project"         : project,
        "correlation_key" : ARCHIVE_KEY_PREFIX + ref,
    }


def open_archive_tickets( branches_kept: list, store, log_fn: Callable ) -> dict:
    """
    Open one row per branch archived this poll whose work had not landed.

    Requires:
        - branches_kept is the janitor result's list of branch outcomes
        - store has find_open( key ) and create( **compose_archive_row fields )

    Ensures:
        - only an outcome with kept_reason "archived" and landed not True gets a row; a
          branch whose commits were already on the working branch by content gets none
        - an open row already carrying the key is adopted, never duplicated
        - one branch's store failure is logged and listed in errors; the others proceed
        - returns { opened: [ ref ], adopted: [ ref ], errors: [ str ] }; never raises
    """
    out = { "opened": [], "adopted": [], "errors": [] }
    for outcome in branches_kept or []:
        if outcome.get( "kept_reason" ) != "archived" or outcome.get( "landed" ) is True:
            continue
        ref = outcome.get( "archive_ref" )
        try:
            row = compose_archive_row( outcome )
            if store.find_open( row[ "correlation_key" ] ):
                out[ "adopted" ].append( ref )
            else:
                store.create( **row )
                out[ "opened" ].append( ref )
        except Exception as e:
            out[ "errors" ].append( f"{ref}: open failed: {e}" )
            log_fn( "worktree_archive_ticket_failed", archive_ref=ref, error=str( e ) )
    if out[ "opened" ] or out[ "adopted" ]:
        log_fn( "worktree_archive_tickets", opened=out[ "opened" ], adopted=out[ "adopted" ] )
    return out


def project_for_tree( path: str ) -> str:
    """
    The store project a tree belongs to: the basename of the repo that holds it.

    Ensures:
        - ".../lupin-mobile/.claude/worktrees/x" → "lupin-mobile"
        - a path outside any sandbox → "lupin"; never raises
    """
    norm = os.path.abspath( path )
    if SANDBOX_SEGMENT in norm:
        return os.path.basename( norm.split( SANDBOX_SEGMENT )[ 0 ] ) or "lupin"
    return "lupin"


def load_state( state_path: str ) -> dict:
    """
    The sidecar { path: { first_refused_at, estimated, ticket_id } }.

    Ensures:
        - {} when absent, corrupt or unreadable; never raises
    """
    return load_json_section( state_path, "trees" )


def write_state( state_path: str, trees: dict, now: datetime ) -> None:
    """
    Replace the sidecar atomically (temp file + os.replace).

    Raises:
        - OSError when it cannot be written (the caller logs it)
    """
    os.makedirs( os.path.dirname( state_path ), exist_ok=True )
    tmp = f"{state_path}.tmp"
    with open( tmp, "w", encoding="utf-8" ) as fh:
        json.dump( { "updated_at": now.isoformat(), "trees": trees }, fh, indent=2, sort_keys=True )
        fh.write( "\n" )
    os.replace( tmp, state_path )


def compose_row( path: str, blockers: list, first_refused_at: str, estimated: bool ) -> dict:
    """
    The row fields for one straggler.

    Ensures:
        - returns { title, body, owner, accountable, project, correlation_key }
        - the body names the tree, its blocking files (first MAX_BODY_BLOCKERS, the rest
          counted), when it was first refused (marked estimated when it is), and what
          clears it; a tree with no recorded creator says "no creator recorded"
    """
    who   = owner_for_tree( path )
    name  = os.path.basename( os.path.normpath( path ) )
    shown = blockers[ :MAX_BODY_BLOCKERS ]
    lines = [ f"The worktree janitor has refused to remove `{path}` since {first_refused_at}"
              f"{' (estimated from when the tree went idle)' if estimated else ''}.",
              "",
              "Blocking ignored files:" ]
    lines += [ f"- `{b}`" for b in shown ]
    if len( blockers ) > len( shown ):
        lines.append( f"- … and {len( blockers ) - len( shown )} more" )
    lines += [ "",
               "Move any data worth keeping somewhere durable, or delete it; the next janitor poll "
               "then removes the tree and closes this row as dropped." ]
    if not who[ "creator_recorded" ]:
        lines += [ "", "No creator recorded: this tree's name does not identify a seat, so it is "
                       f"assigned to {NO_CREATOR_OWNER} for triage.",
                   f"Lookups tried, none answered: {'; '.join( who[ 'tried' ] )}." ]
    return {
        "title"           : f"[{project_for_tree( path ).upper()}] Refused worktree straggler: {name}",
        "body"            : "\n".join( lines ),
        "owner"           : who[ "owner" ],
        "accountable"     : who[ "accountable" ],
        "project"         : project_for_tree( path ),
        "correlation_key" : straggler_key( path ),
    }


def _iso( dt: datetime ) -> str:
    return dt.astimezone( timezone.utc ).isoformat( timespec="seconds" )


def sync_straggler_tickets(
    refused        : dict,
    state_path     : str,
    store,
    log_fn         : Callable,
    now            : Optional[ datetime ] = None,
    age_hours      : float = STRAGGLER_AGE_HOURS,
    idle_hours_fn  : Optional[ Callable[ [ str ], float ] ] = None,
    janitor_idle_h : float = 6.0,
    exists_fn      : Callable[ [ str ], bool ] = os.path.exists,
) -> dict:
    """
    Open a row per long-refused tree and drop the row of each tree that is gone.

    A tree counts as long-refused once it has been refused for more than `age_hours`.

    Requires:
        - refused is refused_set()'s { path: [ blockers ] } for this poll
        - store has find_open( key ) -> id | None, create( **compose_row fields ) -> id,
          drop( ticket_id, reason ) -> None (each may raise)
        - idle_hours_fn( path ) -> hours since the tree's newest file changed, or None
          (then a first sighting starts its clock at now)

    Ensures:
        - a tree refused for the first time is recorded with first_refused_at: now minus
          ( idle hours - janitor_idle_h ), never later than now, estimated=True when that
          estimate moved it back
        - a tree refused for >= age_hours with no ticket gets exactly one: an open row found
          under its key is adopted, otherwise one is created
        - a recorded tree no longer present on disk has its ticket dropped (reason names the
          time) and leaves the sidecar; a recorded tree still on disk but no longer refused
          keeps its entry, so a flapping tree does not reopen a second row
        - one tree's store failure is logged and recorded in errors; the others proceed
        - the sidecar is rewritten only when it changed
        - returns { opened: [ path ], adopted: [ path ], closed: [ path ], pending: int,
                    errors: [ str ] }; never raises
    """
    now      = now if now is not None else datetime.now( timezone.utc )
    previous = load_state( state_path )
    trees    = { p: dict( v ) for p, v in previous.items() }
    out      = { "opened": [], "adopted": [], "closed": [], "pending": 0, "errors": [] }

    for path, blockers in refused.items():
        entry = trees.get( path )
        if entry is None:
            first, estimated = now, False
            idle = None
            if idle_hours_fn is not None:
                try:
                    idle = idle_hours_fn( path )
                except Exception:
                    idle = None
            if isinstance( idle, ( int, float ) ) and idle != float( "inf" ) and idle > janitor_idle_h:
                first, estimated = now - timedelta( hours=idle - janitor_idle_h ), True
            entry = { "first_refused_at": _iso( first ), "estimated": estimated, "ticket_id": None }
            trees[ path ] = entry
        if entry.get( "ticket_id" ):
            continue
        first_dt = datetime.fromisoformat( entry[ "first_refused_at" ] )
        if now - first_dt < timedelta( hours=age_hours ):
            out[ "pending" ] += 1
            continue
        row = compose_row( path, list( blockers ), entry[ "first_refused_at" ], entry.get( "estimated", False ) )
        try:
            found = store.find_open( row[ "correlation_key" ] )
            if found:
                entry[ "ticket_id" ] = str( found )
                out[ "adopted" ].append( path )
            else:
                entry[ "ticket_id" ] = str( store.create( **row ) )
                out[ "opened" ].append( path )
        except Exception as e:
            out[ "errors" ].append( f"{path}: open failed: {e}" )
            log_fn( "worktree_straggler_open_failed", path=path, error=str( e ) )

    for path in list( trees ):
        if path in refused or exists_fn( path ):
            continue
        ticket_id = trees[ path ].get( "ticket_id" )
        if ticket_id:
            try:
                store.drop( ticket_id, f"worktree {path} absent at {_iso( now )} (janitor poll)" )
                out[ "closed" ].append( path )
            except Exception as e:
                out[ "errors" ].append( f"{path}: close failed: {e}" )
                log_fn( "worktree_straggler_close_failed", path=path, ticket_id=ticket_id, error=str( e ) )
                continue
        del trees[ path ]

    if trees != previous:
        try:
            write_state( state_path, trees, now )
        except OSError as e:
            out[ "errors" ].append( f"state write failed: {e}" )
            log_fn( "worktree_straggler_state_write_failed", error=str( e ) )
    if out[ "opened" ] or out[ "adopted" ] or out[ "closed" ]:
        log_fn( "worktree_straggler_tickets", opened=out[ "opened" ], adopted=out[ "adopted" ],
                closed=out[ "closed" ], pending=out[ "pending" ] )
    return out


class RepositoryStragglerStore:
    """
    The real store: direct TaskRepository writes, one short session per call.

    This door is chosen over /api/tasks; the module docstring says why.
    Canonicalizes personas itself, because it bypasses the router's _canon_persona.
    """

    def find_open( self, key: str ) -> Optional[ str ]:
        """The id of a non-terminal row carrying `key`, or None."""
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.task_repository import TaskRepository
        with get_db() as session:
            rows = TaskRepository( session ).query_tasks( correlation_key=key, limit=1 )
            return str( rows[ 0 ].id ) if rows else None

    def create( self, title, body, owner, accountable, project, correlation_key ) -> str:
        """Mint one queued row; returns its id."""
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.task_repository import TaskRepository
        from lupin_mcp.persona_normalization import canonical_persona_key
        with get_db() as session:
            item = TaskRepository( session ).create_item(
                item_class          = "task",
                title               = title,
                project             = project,
                created_by          = ARBITER_ACTOR,
                authority           = "standing",
                body                = body,
                owner_persona       = canonical_persona_key( owner ) or owner,
                accountable_manager = canonical_persona_key( accountable ) or accountable,
                priority            = STRAGGLER_PRIORITY,
                status              = "queued",
                correlation_key     = correlation_key,
            )
            session.flush()
            return str( item.id )

    def drop( self, ticket_id: str, reason: str ) -> None:
        """Move the row to dropped with `reason`; a row already terminal is left alone."""
        import uuid
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.task_repository import TaskRepository
        with get_db() as session:
            repo = TaskRepository( session )
            item = repo.get_by_id_for_update( uuid.UUID( ticket_id ) )
            if item is None or item.status in ( "done", "dropped" ):
                return
            repo.apply_transition( item, "dropped", actor=ARBITER_ACTOR, authority="standing", reason=reason )


def quick_smoke_test():
    """Exercise the pure paths with an in-memory store; no database, no disk beyond a temp file."""
    import tempfile
    print( "worktree_straggler_tickets smoke test" )

    class _Mem:
        def __init__( self ): self.rows, self.dropped = {}, []
        def find_open( self, key ): return next( ( i for i, r in self.rows.items() if r[ "correlation_key" ] == key ), None )
        def create( self, **row ):
            i = f"id{len( self.rows )}"; self.rows[ i ] = row; return i
        def drop( self, i, reason ): self.dropped.append( ( i, reason ) )

    with tempfile.TemporaryDirectory() as d:
        state = os.path.join( d, "stragglers.json" )
        tree  = "/repo/lupin/.claude/worktrees/seat-cc-author-mr-radio-1"
        mem   = _Mem()
        now   = datetime( 2026, 9, 29, 14, 0, tzinfo=timezone.utc )
        r1 = sync_straggler_tickets( { tree: [ "io/x.md" ] }, state, mem, lambda *a, **k: None, now=now,
                                     idle_hours_fn=lambda p: 40.0, exists_fn=lambda p: True )
        assert r1[ "opened" ] == [ tree ], r1
        assert mem.rows[ "id0" ][ "owner" ] == "mr radio"
        r2 = sync_straggler_tickets( {}, state, mem, lambda *a, **k: None, now=now, exists_fn=lambda p: False )
        assert r2[ "closed" ] == [ tree ] and mem.dropped[ 0 ][ 0 ] == "id0", r2
    print( "✓ open after estimated 24h, owner from seat name, drop when gone" )


if __name__ == "__main__":
    quick_smoke_test()
