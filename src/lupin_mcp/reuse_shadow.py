"""
Live wiring of the reuse shadow audit: queue sampled lookups and drain them.

The audit itself (sampling, receipts, the miss bound) is cosa.repo.symindex.candidates.shadow_audit.
This module connects it to the live lookup and gives the drain a command line and a cron job.

Five INI keys control it, and all are read fresh on every use.
`reuse shadow audit enabled` switches queueing and draining on. It ships false.
`reuse shadow audit max tokens per drain` is the most tokens one drain may spend. It has no default:
a drain refuses to start while the key is missing, blank or not a positive whole number.
`reuse shadow audit weekly cap` is the most audits one week may hold. It has no default and no constant.
`reuse shadow audit budgets enabled` is true or false, with no default.
When true, the lifetime limit and the weekly cap are enforced. When false, neither is read or checked, and the drain logs one line saying so.
The per-drain ceiling is enforced either way.
A missing, blank or garbled switch refuses with AUDIT_BUDGETS_SWITCH. It is never read as false.
`reuse shadow audit lifetime token limit` is the most all shadow audits together may ever spend.
It has no default and no constant. A drain refuses to start while the key is bad.
It also refuses when the ledger's total for the `shadow-audit-` runs plus this drain's ceiling would pass the limit.

Exit 0 means the drain ran. Exit 1 means it could not finish, or an install was refused.
Exit 2 means a named error stopped it. Exit 3 means the job is switched off.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

from cosa.repo.symindex import librarian_tick as lt
from cosa.repo.symindex.candidates import shadow_audit as sa
from cosa.repo.symindex.candidates.errors import CandidateError
from lupin_mcp import reuse_ledger

AUDIT_CEILING_UNSET     = "AUDIT_CEILING_UNSET"
AUDIT_NEEDS_PACKED      = "AUDIT_NEEDS_PACKED"
AUDIT_SWEEP_REFUSED     = "AUDIT_SWEEP_REFUSED"
AUDIT_LIFETIME_UNSET    = "AUDIT_LIFETIME_UNSET"
AUDIT_LIFETIME_REACHED  = "AUDIT_LIFETIME_REACHED"
AUDIT_LEDGER_UNREADABLE = "AUDIT_LEDGER_UNREADABLE"
AUDIT_WEEKLY_CAP_UNSET  = "AUDIT_WEEKLY_CAP_UNSET"
AUDIT_BUDGETS_SWITCH    = "AUDIT_BUDGETS_SWITCH"
SWEEP_RUN_PREFIX        = "shadow-audit"
ENABLED_KEY             = "reuse shadow audit enabled"
CEILING_KEY             = "reuse shadow audit max tokens per drain"
LIFETIME_KEY            = "reuse shadow audit lifetime token limit"
WEEKLY_CAP_KEY         = "reuse shadow audit weekly cap"
BUDGETS_KEY             = "reuse shadow audit budgets enabled"
LEDGER_RUN_PREFIX       = SWEEP_RUN_PREFIX + "-"
CRON_TAG                = "# reuse-shadow-audit"
CRON_SCHEDULE           = "37 11 * * *"
SCRIPT_NAME             = "reuse-shadow-audit.sh"
LOG_NAME                = "shadow-audit.log"
LOCK_OWNER              = "reuse-shadow-audit"
EXIT_OK                 = 0
EXIT_FAILED             = 1
EXIT_NAMED              = 2
EXIT_DISABLED           = 3


def _read_positive( key, code, reader ):
    """
    Read one INI key that must hold a positive whole number.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns the positive whole number the key holds

    Raises:
        - CandidateError with the given code when the key is absent, blank, unreadable, not a whole number, or below 1
    """
    errors = []
    raw    = ( lt.read_value( key, reader, errors ) or "" ).strip()
    if not raw.isdigit() or int( raw ) < 1:
        raise CandidateError( code, f"{key} must be a positive whole number, got {raw!r}" + ( f" ({errors[ 0 ]})" if errors else "" ) )
    return int( raw )


def read_ceiling( reader=None ):
    """
    Read the token ceiling of one drain.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns the positive whole number the key holds
        - there is no default: the shipped file holds the key blank

    Raises:
        - CandidateError AUDIT_CEILING_UNSET when the key is absent, blank, unreadable, not a whole number, or below 1
    """
    return _read_positive( CEILING_KEY, AUDIT_CEILING_UNSET, reader )


def read_lifetime_limit( reader=None ):
    """
    Read the most tokens all shadow audits together may ever spend.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns the positive whole number the key holds, read fresh
        - there is no default and no constant: the INI file is the only source

    Raises:
        - CandidateError AUDIT_LIFETIME_UNSET when the key is absent, blank, unreadable, not a whole number, or below 1
    """
    return _read_positive( LIFETIME_KEY, AUDIT_LIFETIME_UNSET, reader )


def read_budgets_enabled( reader=None ):
    """
    Read the switch that applies the lifetime limit and the weekly cap.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns True for "true" and False for "false", in any letter case and ignoring spaces
        - read fresh, with no default

    Raises:
        - CandidateError AUDIT_BUDGETS_SWITCH when the key is absent, blank, unreadable or anything but true or false
    """
    errors = []
    raw    = ( lt.read_value( BUDGETS_KEY, reader, errors ) or "" ).strip().lower()
    if raw not in ( "true", "false" ):
        raise CandidateError( AUDIT_BUDGETS_SWITCH, f"{BUDGETS_KEY} must be true or false, got {raw!r}" + ( f" ({errors[ 0 ]})" if errors else "" ) )
    return raw == "true"


def read_weekly_cap( reader=None ):
    """
    Read the most audits one week may hold.

    Requires:
        - reader is a callable ( key ) returning a string or None, or None for the live disk reader

    Ensures:
        - returns the positive whole number the key holds, read fresh
        - there is no default and no constant: the INI file is the only source

    Raises:
        - CandidateError AUDIT_WEEKLY_CAP_UNSET when the key is absent, blank, unreadable, not a whole number, or below 1
    """
    return _read_positive( WEEKLY_CAP_KEY, AUDIT_WEEKLY_CAP_UNSET, reader )


def live_capacity( ledger, headroom_settings=None, reader=None ):
    """
    Work out run capacity with the audit numbers the drain reads.

    Requires:
        - ledger is an AccountLedger; headroom_settings is a dict of reuse_ledger.capacity keyword arguments, or None

    Ensures:
        - returns reuse_ledger.account_capacity's answer, with the audit ceiling and weekly cap read fresh from the INI
        - so the headroom arithmetic and the drain cannot drift apart

    Raises:
        - CandidateError AUDIT_CEILING_UNSET or AUDIT_WEEKLY_CAP_UNSET when either key is bad
    """
    return reuse_ledger.account_capacity( ledger, read_ceiling( reader ), read_weekly_cap( reader ), **( headroom_settings or { } ) )


def check_lifetime_limit( ledger, limit, ceiling ):
    """
    Refuse a drain whose ceiling could carry the lifetime audit spend past the limit.

    Requires:
        - ledger is an AccountLedger; limit and ceiling are positive whole numbers

    Ensures:
        - returns the tokens the shadow-audit runs hold now, when that total plus the ceiling does not pass the limit
        - a closed run counts at its spend and an open one at the larger of its ceiling and its spend

    Raises:
        - CandidateError AUDIT_LIFETIME_REACHED when the total plus the ceiling would pass the limit
        - CandidateError AUDIT_LEDGER_UNREADABLE when the ledger cannot be read
    """
    try: spent = ledger.held_by_prefix( LEDGER_RUN_PREFIX )
    except reuse_ledger.LedgerUnreadable as error: raise CandidateError( AUDIT_LEDGER_UNREADABLE, f"{error}" ) from error
    if spent + ceiling > limit:
        raise CandidateError( AUDIT_LIFETIME_REACHED, f"{spent} tokens already held by shadow audits plus a drain ceiling of {ceiling} passes the lifetime limit of {limit} ({LIFETIME_KEY})" )
    return spent


def queue_lookup( data_dir, receipt, today, reader=None ):
    """
    Queue a served lookup for audit when the audit is on and the lookup is in the sample.

    Requires:
        - receipt is the stored receipt of a check_exists question
        - today is an ISO date string

    Ensures:
        - returns the queue id, or None when the audit is off, the lookup is not sampled, or the lookup is not a shortlist answer
        - the need queued is the receipt's query, which the redactor has already cleaned
        - a sweep-only, test-including, pair or exclusion lookup is never queued: they are measurement runs, not live answers
        - a lookup whose candidate stage failed is never queued, because there is no shortlist to compare
        - the daily lookup count only goes up while the audit is on

    Raises:
        - CandidateError or OSError from the queue write
    """
    if not lt.read_enabled( reader=reader, key=ENABLED_KEY ): return None
    inputs = audit_inputs( receipt )
    return None if inputs is None else sa.enqueue_if_sampled( data_dir, *inputs, today )


def audit_inputs( receipt ):
    """
    Read the fields the audit queue needs from a stored lookup receipt.

    Requires:
        - receipt is a stored receipt dict

    Ensures:
        - returns ( need, language, generation, index_sha, live ), the arguments the queue writes take after data_dir, or None
        - None for a receipt that is not a shortlist answer of check_exists: a sweep-only, test-including, pair or exclusion lookup, or one whose candidate stage failed or is absent
        - the need is the receipt's query, which the redactor has already cleaned
    """
    if receipt[ "tool" ] != "check_exists" or any( key in receipt for key in ( "sweep_only", "include_tests", "question", "exclude_id" ) ): return None
    stage = receipt[ "candidate_stage" ] if "candidate_stage" in receipt else None
    if stage is None or "error" in stage: return None
    return receipt[ "query" ], receipt[ "language" ], stage[ "manifest_hash" ], receipt[ "index_sha" ], { "verdict": receipt[ "verdict" ], "candidate_ids": stage[ "ids" ] }


def sweep_of( ctx_factory, ask ):
    """
    Build the drain's sweep function.

    Requires:
        - ctx_factory is a function ( run_name ) returning a fresh packed ReuseContext, one per sweep because a packed context is single use
        - ask is reuse_tools.unstored_need_impl or a stand-in with its signature

    Ensures:
        - returns a function ( need, language, exclude_id=None ) giving { verdict, causal_ids, tokens } and the cause when the verdict is uncertain
        - causal_ids are the ids of the full sweep's shortlist
        - tokens are the sweep's tokens in plus tokens out
        - every sweep gets its own run name, from reuse_ledger.make_run_name

    Raises:
        - CandidateError AUDIT_SWEEP_REFUSED from the returned function when the sweep answers an error
    """
    def sweep( need, language, exclude_id=None ):
        """Ensures: returns the audit's view of one full sweep, leaving out exclude_id if given."""
        result = ask( need, exclude_id, ctx_factory( reuse_ledger.make_run_name( SWEEP_RUN_PREFIX ) ), language=language )
        if result[ "status" ] != "ok": raise CandidateError( AUDIT_SWEEP_REFUSED, f"{result[ 'error' ]}" )
        out = { "verdict": result[ "verdict" ], "causal_ids": [ row[ "id" ] for row in result[ "shortlist" ] ],
                "tokens": result[ "stats" ][ "tokens_in" ] + result[ "stats" ][ "tokens_out" ] }
        if result[ "verdict" ] == "UNCERTAIN_READ_SOURCE": out[ "cause" ] = result[ "cause" ]
        return out

    return sweep


def drain( data_dir, ctx_factory, ask, today, ceiling, weekly_cap, on_failure=None ):
    """
    Drain the audit queue under a token ceiling.

    Requires:
        - ceiling is a positive whole number of tokens; weekly_cap is a positive whole number of audits, or None for no weekly cap

    Ensures:
        - returns run_pending's result with spent_tokens and stopped_by
        - the run stops before a sweep that could pass the ceiling, and the rest of the queue waits for the next drain
        - the run also stops when the audits of the last seven days reach weekly_cap, which main reads from the INI (None when the budgets are switched off)
        - on_failure, when given, is called with the item id and the exception of each failed item
    """
    return sa.run_pending( data_dir, sweep_of( ctx_factory, ask ), today, max_tokens=ceiling, pass_language=True, weekly_cap=weekly_cap, on_failure=on_failure )


def cron_lines( root, python, log_path, carried=None ):
    """
    Build the two cron lines.

    Requires:
        - root is the main checkout path; python is the interpreter path

    Ensures:
        - returns [ daily line, reboot line ], each ending with CRON_TAG
        - each line runs the wrapper script and sets every name in carried to its value
    """
    extra = "".join( f"{name}={value} " for name, value in ( carried or {} ).items() )
    run   = f"cd {root} && LUPIN_ROOT={root} {extra}REUSE_SHADOW_AUDIT_PYTHON={python} {root}/src/scripts/{SCRIPT_NAME} >> {log_path} 2>&1 {CRON_TAG}"
    return lt.cron_lines_for( run, CRON_SCHEDULE, 300 )


def _context_factory( root, environ, ceiling ):
    """
    Build the per-sweep context factory of the live drain.

    Requires:
        - environ names a pack size, as the live server's does

    Ensures:
        - each context is packed, single use, and carries the drain ceiling as its own spend limit

    Raises:
        - CandidateError AUDIT_NEEDS_PACKED when the pack size variable is unset
    """
    from lupin_mcp import reuse_tools
    if not environ.get( reuse_tools.PACK_SIZE_VARIABLE ):
        raise CandidateError( AUDIT_NEEDS_PACKED, f"{reuse_tools.PACK_SIZE_VARIABLE} must be set: the audit sweeps on the packed path" )

    def factory( run_name ):
        """Ensures: returns a fresh packed context for one sweep."""
        env = dict( environ, **{ reuse_tools.CEILING_VARIABLE: str( ceiling ), reuse_tools.RUN_NAME_VARIABLE: run_name } )
        old = os.environ.copy()
        os.environ.update( env )
        try: return reuse_tools.context_from_environment( root )
        finally:
            os.environ.clear()
            os.environ.update( old )

    return factory


def main( argv=None, environ=None, now=None, out=None, err=None, crontab_cmd=None, factory=None, ask=None, reader=None, ledger=None ):
    """
    Run the command line.

    Requires:
        - argv is a list of arguments, or None for sys.argv

    Ensures:
        - with no mode flag, drains the queue once under the INI ceiling and returns its exit code
        - a switched-off job logs one line and returns EXIT_DISABLED before anything is read or swept
        - a missing ceiling, budgets switch, weekly cap or lifetime limit, or a drain that would pass the lifetime limit, prints the named error as JSON and returns EXIT_NAMED, before any sweep
        - ledger is an AccountLedger, or None for the fleet's ledger
        - --print-install prints the cron lines and changes nothing
        - --install, --uninstall and --status go through the librarian's locked crontab editor with this job's tag
    """
    environ = os.environ if environ is None else environ
    now     = now or datetime.datetime.now()
    out     = sys.stdout if out is None else out                                # looked up per call, so a test that swaps stdout is heard
    err     = sys.stderr if err is None else err
    parser  = argparse.ArgumentParser( prog="python -m lupin_mcp.reuse_shadow", description=__doc__.split( "\n\n" )[ 0 ] )
    mode    = parser.add_mutually_exclusive_group()
    for flag in ( "--install", "--uninstall", "--status", "--print-install" ): mode.add_argument( flag, action="store_true" )
    parser.add_argument( "--root" )
    parser.add_argument( "--python", default=sys.executable )
    args    = parser.parse_args( argv )
    root    = args.root or environ.get( "LUPIN_ROOT" ) or os.getcwd()
    from lupin_mcp import reuse_tools
    data    = reuse_tools.data_dir( root )
    log_dir = os.path.join( str( data ), "shadow-audit" )
    lines   = cron_lines( root, args.python, os.path.join( log_dir, LOG_NAME ), { name: environ[ name ] for name in ( "DEEPILY_DATA_DIR", reuse_tools.PACK_SIZE_VARIABLE ) if environ.get( name ) } )
    cmd     = crontab_cmd or [ environ.get( "REUSE_SHADOW_AUDIT_CRONTAB", "crontab" ) ]
    if args.print_install:
        print( "\n".join( lines ), file=out )
        return EXIT_OK
    try:
        if args.install or args.uninstall:
            lt.edit_crontab( [] if args.uninstall else lines, environ, cmd, os.path.join( log_dir, "crontab-backups" ), now, tag=CRON_TAG, owner=LOCK_OWNER )
            print( "uninstalled" if args.uninstall else "installed: 2 lines", file=out )
            return EXIT_OK
        if args.status:
            read = subprocess.run( [ *cmd, "-l" ], capture_output=True, text=True )
            print( lt.status_text( read.stdout if read.returncode == 0 else "", CRON_TAG ), file=out )
            return EXIT_OK
    except ( lt.InstallRefused, RuntimeError ) as error:
        print( f"reuse-shadow-audit: {error}", file=err )
        return EXIT_FAILED
    log = lt.make_logger( os.path.join( log_dir, LOG_NAME ) )
    if not lt.read_enabled( reader=reader, key=ENABLED_KEY ):
        log( f"drain is switched off: {ENABLED_KEY} is not true" )
        print( json.dumps( { "ran": False, "reason": "switched off" }, sort_keys=True ), file=out )
        return EXIT_DISABLED
    try:
        ceiling = read_ceiling( reader )
        budgets = read_budgets_enabled( reader )
        weekly  = read_weekly_cap( reader ) if budgets else None
        if budgets: check_lifetime_limit( ledger or reuse_ledger.AccountLedger( reuse_ledger.ledger_path( root ) ), read_lifetime_limit( reader ), ceiling )
        else: log( f"budgets are off: {BUDGETS_KEY} is false, so the lifetime limit and the weekly cap are not applied; the per-drain ceiling of {ceiling} still is" )
        result  = drain( data, factory or _context_factory( root, environ, ceiling ), ask or reuse_tools.unstored_need_impl, now.date().isoformat(), ceiling, weekly, lambda item_id, exc: log( f"item {item_id} failed: {type( exc ).__name__}: {exc}" ) )
    except CandidateError as error:
        log( f"drain refused: {error}" )
        print( json.dumps( { "error": error.code, "detail": error.detail } ), file=out )
        return EXIT_NAMED
    summary = { key: result[ key ] for key in ( "audited", "failed", "corrupt", "dropped", "spent_tokens", "stopped_by" ) }
    log( f"drain done: {json.dumps( summary, sort_keys=True )}" )
    print( json.dumps( summary, sort_keys=True ), file=out )
    return EXIT_FAILED if result[ "failed" ] and not result[ "audited" ] else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit( main() )
