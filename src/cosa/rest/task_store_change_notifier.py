"""
Task-store change notifier.

Turns "a database session committed having appended TaskEvent rows" into one
`task_store_changed` invalidation event for the web panes. The event carries no
delta: the client re-reads. A missed frame therefore costs a late refresh, never
a wrong board, and the 60-second poll stays as the safety net.

How it works:
    - `TaskRepository._append_event` calls `record_appended_event( session, event )`,
      which parks a small summary of the event on `session.info`.
    - Session-class listeners (registered once, at import) read that list:
      `after_commit` emits one event for the whole commit, `after_rollback`
      throws the list away so a rolled-back session emits nothing.
    - The emit goes through a module-level sink. The `:7999` server installs
      one that calls `websocket_manager.emit`; every other process (the `:8001`
      arbiter, scripts, tests) leaves it unset and the emit is a silent no-op.

Known reach limit: a writer in a process that never installs the sink cannot
push. The arbiter's straggler-ticket and follow-through writes are that case;
their rows appear on the next poll.

Savepoints are unsupported (measured on Postgres 16).
Session `after_commit` / `after_rollback` also fire for a savepoint (begin_nested):
    - a savepoint rollback discards every parked event on the session, including ones
      that go on to commit with the outer transaction -> a missed push;
    - a savepoint release fires `after_commit` early -> the push can reach a client
      before the outer commit is durable, and an outer rollback after it still emitted.
The outcome is a missed or early invalidation, never a wrong board (the poll stays).
No non-test code takes a savepoint today. The first code that does must first key the
listeners on `session.in_nested_transaction()` (via `after_soft_rollback`).
Also: a Session closed without commit keeps its parked list; reuse of one Session
object across commits would count that event. `get_db` makes a fresh Session per use.
"""

from sqlalchemy import event
from sqlalchemy.orm import Session

import cosa.utils.util as du


TASK_STORE_CHANGED_EVENT = "task_store_changed"
_INFO_KEY                = "task_store_appended_events"

_sink = None


def set_sink( sink ) -> None:
    """
    Install (or clear) the function that delivers a payload to the websocket layer.

    Requires:
        - sink is a callable taking one dict, or None to clear it

    Ensures:
        - later commits that appended task events call sink( payload ) once each
    """
    global _sink
    _sink = sink


def get_sink():
    """Return the installed sink, or None."""
    return _sink


def install_websocket_sink( websocket_manager ) -> None:
    """
    Make commits push task_store_changed to every connected session.

    Requires:
        - websocket_manager has a thread-safe emit( event, data ) (WebSocketManager does)

    Ensures:
        - the installed sink calls websocket_manager.emit( "task_store_changed", payload )
    """
    set_sink( lambda payload: websocket_manager.emit( TASK_STORE_CHANGED_EVENT, payload ) )


def to_status_of( transition ):
    """
    The destination status named by a "from->to" transition label.

    Ensures:
        - returns the text after the last "->" when it is non-empty
        - returns None for a label without one ("patched", "amended", "chased")
    """
    if "->" not in transition: return None
    return transition.rsplit( "->", 1 )[ 1 ] or None


def record_appended_event( session, task_event ) -> None:
    """
    Park a summary of one appended TaskEvent on the session until it commits.

    Requires:
        - task_event has been flushed (id and ts populated by the caller's flush)

    Ensures:
        - session.info carries the summary, in append order
    """
    session.info.setdefault( _INFO_KEY, [] ).append( {
        "event_id"   : task_event.id,
        "item_id"    : str( task_event.item_id ),
        "transition" : task_event.transition,
        "to_status"  : to_status_of( task_event.transition ),
        "ts"         : task_event.ts.isoformat() if task_event.ts is not None else None,
    } )


def build_payload( appended ) -> dict:
    """
    One payload for a commit: the last event's identity plus how many there were.

    Requires:
        - appended is a non-empty list of summaries from record_appended_event
    """
    payload          = dict( appended[ -1 ] )
    payload[ "count" ] = len( appended )
    return payload


def _on_after_commit( session ) -> None:
    """Emit once for a session that committed after appending task events."""
    appended = session.info.pop( _INFO_KEY, None )
    if not appended or _sink is None: return
    try:
        _sink( build_payload( appended ) )
    except Exception as e:
        du.print_banner( f"task_store_changed emit failed (commit unaffected): {e!r}", prepend_nl=True )


def _on_after_rollback( session ) -> None:
    """Forget the parked events: the rows they describe no longer exist."""
    session.info.pop( _INFO_KEY, None )


event.listen( Session, "after_commit",   _on_after_commit )
event.listen( Session, "after_rollback", _on_after_rollback )
