"""
Server-side call log for the reuse tools: a FastMCP middleware that appends one JSON line per
call to the per-session log, so coverage does not depend on callers logging themselves.

Each seat runs its own STDIO server, so each server writes its own file
(<data>/call-log/<session id>.jsonl); a reader merges the files. The middleware never raises and
never changes a tool result.
"""
import datetime

from fastmcp.server.middleware import Middleware

REUSE_TOOLS = ( "check_exists", "fetch_similar", "read_capability", "replay" )
MAX_ARGS    = 300


def _receipt_id( result ):
    """Ensures: returns the receipt_id of a tool result (structured content first, then a JSON text block), else None."""
    sc = result.structured_content
    if isinstance( sc, dict ): return sc.get( "receipt_id" )
    return None


class ReuseCallLogMiddleware( Middleware ):
    """
    Log every reuse-tool call.

    Requires:
        - identity is a callable returning the caller's "<persona> <session id>" string
        - session_id names this server's log file
    Ensures:
        - after a reuse tool returns, one line { ts, tool, caller, session, receipt_id, error, args }
          is appended; a tool that raises is logged with its error and the exception is re-raised
        - other tools pass through untouched
        - a failure to log is swallowed: the tool result is returned unchanged
    """

    def __init__( self, identity, session_id, context_factory=None ):
        self.identity, self.session_id, self.context_factory = identity, session_id, context_factory

    def _log( self, tool, args, receipt_id, error ):
        try:
            from lupin_mcp import reuse_tools
            ctx = ( self.context_factory or reuse_tools.context_from_environment )()
            reuse_tools.append_call_log( ctx, self.session_id, {
                "ts": datetime.datetime.now( datetime.timezone.utc ).isoformat(), "tool": tool, "caller": self.identity(),
                "session": self.session_id, "receipt_id": receipt_id, "error": error, "args": repr( args )[ :MAX_ARGS ] } )
        except Exception:                                                     # logging must never break a tool call
            pass

    async def on_call_tool( self, context, call_next ):
        """
        Ensures:
            - returns the next handler's result unchanged
        """
        name = context.message.name
        if name not in REUSE_TOOLS: return await call_next( context )
        try:
            result = await call_next( context )
        except Exception as e:
            self._log( name, context.message.arguments, None, f"{type( e ).__name__}: {e}" )
            raise
        sc = result.structured_content
        self._log( name, context.message.arguments, _receipt_id( result ), sc.get( "error" ) if isinstance( sc, dict ) else None )
        return result
