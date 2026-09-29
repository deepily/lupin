"""
One store row per worktree the janitor has refused for more than a day — opened once,
closed by the janitor when the tree is gone.

Rick's ruling, 2026-09-29 (broadcast 0457564c, relayed by María; the ticket "door" by his
own keypress): a refusal notify is a card, and a card scrolls away. A straggler that has
sat refused for 24 hours becomes a ROW with an owner, so the pile is somebody's owed work
instead of nobody's surprise.

  * owner / accountable manager — a seat tree `seat-cc-<role>-<manager>-<n>` records its
    SPAWNING MANAGER in its name (session_spawner builds it from the manager's persona slug),
    and the seat's own persona is gone once the seat is reaped. So both fields name that
    manager. A tree that records no creator goes to NO_CREATOR_OWNER, who triages it
    (María's ruling), and the body says "no creator recorded".
  * dedupe — correlation key `worktree:<absolute tree path>`, one row per tree.
  * door — a DIRECT repository write, not /api/tasks (Rick's keypress, 2026-09-29). The
    router would mint the row into the holding area, where the arbiter can never move it
    out again, so it could never close its own tickets. The throughput counter excludes the
    `worktree:` lane (task_repository.count_created_and_closed) so these rows, which close
    as `dropped`, never count against anyone else's creates.
  * close — `dropped`, reason "tree absent at <ts>". A system actor has no honest receipt
    for `done`.

The clock: `first_refused_at` lives in a sidecar beside the refusal ledger. A tree seen
refused for the first time gets an ESTIMATE — the moment its newest file went idle plus the
janitor's own idle threshold, the earliest a sweep could have refused it — capped at now,
and the row body says the time is estimated.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

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


def owner_for_tree( path: str ) -> dict:
    """
    Who owns the straggler row for a tree.

    Requires:
        - path is a worktree path (its basename is the tree's name)

    Ensures:
        - a seat tree `seat-cc-<role>-<manager-slug>-<n>` → owner and accountable are the
          manager slug with hyphens as spaces (the store's canonical key shape, e.g.
          "mr-radio" → "mr radio"), creator_recorded True
        - anything else → both NO_CREATOR_OWNER, creator_recorded False
        - returns { owner, accountable, creator_recorded }; never raises
    """
    m = SEAT_TREE_RE.match( os.path.basename( os.path.normpath( path ) ) )
    if m:
        manager = m.group( "manager" ).replace( "-", " " )
        return { "owner": manager, "accountable": manager, "creator_recorded": True }
    return { "owner": NO_CREATOR_OWNER, "accountable": NO_CREATOR_OWNER, "creator_recorded": False }


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
    try:
        with open( state_path, "r", encoding="utf-8" ) as fh:
            data = json.load( fh )
        trees = data.get( "trees" ) if isinstance( data, dict ) else None
        return trees if isinstance( trees, dict ) else {}
    except ( OSError, ValueError ):
        return {}


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
                       f"assigned to {NO_CREATOR_OWNER} for triage." ]
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
    Open a row for every tree refused longer than `age_hours`; drop the row of every tree
    that is gone.

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

    Rick's keypress (2026-09-29) chose this door over /api/tasks; see the module docstring.
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
