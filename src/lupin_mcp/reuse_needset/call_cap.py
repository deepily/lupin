"""
One shared cap on model calls, over a single ledger file.

Set B's first-thousand run may make 1,314 model calls in all. The first attempt spent 686, and Rick raised the budget by about 1,000 on 1 November.
Fable need-drafting, the checker's judge and the agent probe are all calls, and all of them are counted here, whichever stage makes them.
Call 1,315 is refused by name before any model is contacted. A stage may also have a budget of its own, so one stage cannot spend the others' calls.
"""
import contextlib
import contextvars
import datetime
import fcntl
import json
import os

from cosa.repo.doc_lint import jev_transport, model_transport
from lupin_mcp.reuse_needset import errors as er

CALL_LIMIT = 1314
NO_STAGE   = "unstaged"
_STAGE     = contextvars.ContextVar( "needset_call_stage", default=NO_STAGE )


@contextlib.contextmanager
def stage( name ):
    """
    Name the stage that makes the calls inside the block.

    Requires:
        - name is a non-empty string

    Ensures:
        - every call charged inside the block carries the name in its ledger row
        - the earlier name comes back when the block ends, even by an error

    Raises:
        - ValueError for an empty name
    """
    if not name: raise ValueError( "a stage needs a name" )
    token = _STAGE.set( name )
    try:
        yield name
    finally:
        _STAGE.reset( token )


class CallCap:
    """
    A count of model calls kept in a ledger file that outlives the process.

    Requires:
        - path is a file in an existing directory; the file may not exist yet
        - limit is an int of zero or more
        - stage_limits is None, or maps a stage name to an int of zero or more calls that stage may make

    Ensures:
        - a call is counted before it is made, so a call that crashes still counts
        - the count is read and the row written under one exclusive file lock, so two processes cannot both take the last call
        - a new CallCap over the same file starts from the calls already there, so a resumed run keeps the count
    """

    def __init__( self, path, limit=CALL_LIMIT, stage_limits=None ):
        """
        Hold the ledger path, the limit and the stage limits.

        Raises:
            - ValueError for a limit or a stage limit that is not an int of zero or more, or a directory that does not exist
        """
        if isinstance( limit, bool ) or not isinstance( limit, int ) or limit < 0: raise ValueError( f"limit must be an int of zero or more, got {limit!r}" )
        stage_limits = {} if stage_limits is None else dict( stage_limits )
        for name, each in stage_limits.items():
            if isinstance( each, bool ) or not isinstance( each, int ) or each < 0: raise ValueError( f"the limit of stage {name!r} must be an int of zero or more, got {each!r}" )
        if not os.path.isdir( os.path.dirname( os.path.abspath( path ) ) ): raise ValueError( f"ledger directory for {path!r} does not exist" )
        self.path  = str( path )
        self.limit = limit
        self.stage_limits = stage_limits

    def rows( self ):
        """
        Read the counted calls.

        Ensures:
            - returns the readable rows in file order; a torn last line is skipped
            - a missing file gives an empty list
        """
        if not os.path.exists( self.path ): return []
        out = []
        with open( self.path, encoding="utf-8", errors="replace" ) as f:
            for line in f:
                try: out.append( json.loads( line ) )
                except ValueError: continue
        return out

    def used( self ):
        """Ensures: returns how many calls the ledger holds."""
        return len( self.rows() )

    def by_stage( self ):
        """Ensures: returns { stage name: calls charged to it }, sorted by name."""
        counts = {}
        for row in self.rows(): counts[ row[ "stage" ] ] = counts.get( row[ "stage" ], 0 ) + 1
        return dict( sorted( counts.items() ) )

    def charge( self, model ):
        """
        Count one call or refuse it.

        Requires:
            - model is a non-empty model id

        Ensures:
            - writes one row, flushed to disk, holding the call number, the stage, the model and the time
            - a call past the limit writes nothing and contacts nothing
            - a call past the budget of the stage that asks writes nothing and contacts nothing, while the other stages keep their own calls
            - a ledger whose last line was cut off is closed with a newline first, so the fragment cannot hide the new row

        Raises:
            - NeedsetError CALL_CAP_REACHED naming the count, the limit and the stage that asked
            - NeedsetError STAGE_BUDGET_REACHED naming the stage, its calls and its budget, when the whole limit still has room
            - ValueError for an empty model id
        """
        if not model: raise ValueError( "a charged call needs a model id" )
        with open( self.path, "a+", encoding="utf-8" ) as f:
            fcntl.flock( f, fcntl.LOCK_EX )
            rows    = self.rows()
            used    = len( rows )
            name    = _STAGE.get()
            spent   = sum( 1 for r in rows if r[ "stage" ] == name )
            allowed = used < self.limit
            over    = allowed and name in self.stage_limits and spent >= self.stage_limits[ name ]
            if allowed and not over:
                size = os.fstat( f.fileno() ).st_size
                if size > 0 and os.pread( f.fileno(), 1, size - 1 ) != b"\n": f.write( "\n" )
                f.write( json.dumps( { "n": used + 1, "stage": name, "model": model, "ts": datetime.datetime.now( datetime.timezone.utc ).isoformat() } ) + "\n" )
                f.flush()
                os.fsync( f.fileno() )
        if not allowed: raise er.NeedsetError( er.CALL_CAP_REACHED, f"{used} of {self.limit} calls used; the {name} stage asked for another, and no model was contacted" )
        if over: raise er.NeedsetError( er.STAGE_BUDGET_REACHED, f"the {name} stage used {spent} of its {self.stage_limits[ name ]} calls and asked for another; no model was contacted" )

    @contextlib.contextmanager
    def installed( self ):
        """
        Make every complete call and every Jev attempt in the process pass through this cap.

        Ensures:
            - inside the block each model_transport call is charged here before the model is contacted
            - each HTTP attempt to Jev, retries included, is charged here before the request is sent
            - both hooks that were set before come back when the block ends, even by an error
        """
        before      = model_transport.CHARGE_HOOK
        jev_before  = jev_transport.CHARGE_HOOK
        model_transport.set_charge_hook( self.charge )
        jev_transport.set_charge_hook( self.charge )
        try:
            yield self
        finally:
            model_transport.set_charge_hook( before )
            jev_transport.set_charge_hook( jev_before )

    def guard( self, call, model ):
        """
        Wrap an async call that reaches a model by another door than model_transport.

        Requires:
            - call is an async function; model is the model id the call uses

        Ensures:
            - returns an async function with the same arguments that charges one call first and then awaits the original
            - a refused call never starts the original
        """
        async def guarded( *args, **kwargs ):
            """Ensures: charges one call, then returns what the wrapped call returns."""
            self.charge( model )
            return await call( *args, **kwargs )
        return guarded


def charge_attempt( model ):
    """
    Count one model call that is made outside model_transport.complete.

    Requires:
        - model is the model id the call will use

    Ensures:
        - with a cap installed, charges the call to it before the model is contacted
        - with no cap installed and no stage running, does nothing, so a use outside a stage run is unchanged
        - a caller that wraps itself in CallCap.guard must not also call this, or one call counts twice

    Raises:
        - NeedsetError CAP_NOT_INSTALLED when a stage is running and no cap is installed, so no caller can go uncounted
        - NeedsetError CALL_CAP_REACHED from the cap at the call past its limit
        - NeedsetError STAGE_BUDGET_REACHED from the cap at the call past the running stage's budget
    """
    hook = model_transport.CHARGE_HOOK
    if hook is None:
        if _STAGE.get() != NO_STAGE: raise er.NeedsetError( er.CAP_NOT_INSTALLED, f"the {_STAGE.get()} stage reached a model with no cap installed" )
        return
    hook( model )
