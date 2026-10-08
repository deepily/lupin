"""
The measurement driver: each arm is its own run and writes a results file.

The three-way question is asked in arms that must not share answers. There are single runs, a canary,
packs of 10, 50 and 200, the page arms, and six probe arms. The ledger holds the stage's token total,
counted over the runs named s1-*, so it survives a restart. A human approves the canary before any
arm but the first single run is paid for. The driver sends nothing itself: the transport is a factory.
"""
import collections
import contextlib
import fcntl
import json
import os
import pathlib
import time

from cosa.repo.doc_lint import jev_transport as jt
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_tools as rt

STAGE_TOKENS     = rl.STAGE1_CEILING_TOKENS
RUN_PREFIX       = "s1-"
FORMAT           = "stage1-arm-1"
CANARY_FORMAT    = "stage1-canary-1"
QUESTIONS        = ( 1, 2, 3, 4 )
CANARY_SIZE      = 10
MAX_ATTEMPTS     = 3                                             # an arm may be run, and run again twice
RETRY_INDEX      = { 2: 15, 3: 16 }                              # the canary's reruns: their run index is free of every arm's, so they read no earlier answer
OUTPUT_LIMIT     = rc.OUTPUT_TOKENS_PER_ENTRY
UNGATED          = ( "single1", "canary" )                       # the arms that may run before a canary is approved
PLACEMENTS       = ( "first", "middle", "last" )
NEIGHBOURS       = { "random": "random", "near": "near_duplicate" }
PROBE_KEYS       = frozenset( ( "id", "placement", "neighbours" ) )
ARMS             = { "single1": ( 1, 1 ), "single2": ( 2, 1 ), "canary": ( 3, CANARY_SIZE ), "pack10": ( 3, 10 ), "pack50": ( 4, 50 ), "pack200": ( 5, 200 ),
                     "page-single1": ( 6, 1 ), "page-single2": ( 7, 1 ), "page-pack": ( 8, 200 ) }
ARMS.update( { f"probe-{place}-{near}": ( 9 + 3 * ( near == "near" ) + PLACEMENTS.index( place ), 200 ) for near in NEIGHBOURS for place in PLACEMENTS } )

_OTHER_ARMS = sorted( arm for arm in ARMS if arm != "canary" )


def retry_index( arm, attempt ):
    """
    Give an arm's attempt the run index its cache keys use.

    Ensures:
        - returns the arm's own run index for attempt 1
        - returns, for a rerun, an index no other arm or attempt uses, so a rerun reads none of the answers before it
        - the canary keeps the indexes it has run under, 15 and 16; every other arm's reruns follow from 17
    """
    if attempt == 1: return ARMS[ arm ][ 0 ]
    if arm == "canary": return RETRY_INDEX[ attempt ]
    return 17 + 2 * _OTHER_ARMS.index( arm ) + attempt - 2



class StageRefused( Exception ):
    """An arm asked for more tokens than the stage has left."""


class CanaryNotApproved( Exception ):
    """An arm was asked for before its question's canary was read and approved."""


class CanaryTripped( Exception ):
    """A canary crossed one of its stop numbers and cannot be approved."""


class DriverRefused( ValueError ):
    """The driver refused a step before spending: no ledger run opened, no name used."""


class KeyMissing( Exception ):
    """The live transport has no key, so the arm was refused before it opened a ledger run."""


class Stage1Env:
    """
    Everything the driver needs from outside, injectable for tests.

    Requires:
        - ledger is an AccountLedger that already exists
        - transport_factory takes an arm's TokenBudget and returns a transport; the default is the live one
    Ensures:
        - results go to <data>/stage1-results/
        - entries_in_index is written into every results file, as the run tree's sendable-entry count
    """

    def __init__( self, root, data, ledger, transport_factory=None, entries_in_index=None, workers=rp.WORKERS_DEFAULT, model=rt.JEV_MODEL, clock=None ):
        self.root, self.data, self.ledger  = pathlib.Path( root ), pathlib.Path( data ), ledger
        self.transport_factory             = transport_factory or ( lambda budget: rt.LiveJevTransport( budget=budget, transient=True ) )
        self.live                          = transport_factory is None
        self.entries_in_index              = entries_in_index
        self.workers, self.model           = workers, model
        self.clock                         = clock or ( lambda: time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) )

    @property
    def results_dir( self ):
        """Ensures: returns the directory every arm's results file goes in."""
        return self.data / "stage1-results"


def run_name( question, arm, attempt=1 ):
    """Ensures: returns s1-q<question>-<arm>, plus -a<attempt> for a retry."""
    return f"{RUN_PREFIX}q{question}-{arm}" + ( f"-a{attempt}" if attempt > 1 else "" )


def stage_remaining( ledger ):
    """Ensures: returns the stage's tokens less what its runs hold in the ledger."""
    return STAGE_TOKENS - ledger.held_by_prefix( RUN_PREFIX )


def _check_probe( arm, probe, entries ):
    """
    Check a probe against its arm and the pack it sits in.

    Raises:
        - ValueError when a probe arm has no probe, another arm has one, or the probe is malformed,
          is not in the pack, is not at its stated position, or does not match the arm's name
    """
    if not arm.startswith( "probe-" ):
        if probe is not None: raise DriverRefused( f"a probe belongs to a probe arm, not to {arm!r}" )
        return
    if probe is None: raise DriverRefused( f"{arm!r} needs a probe" )
    _, place, near = arm.split( "-" )
    if not isinstance( probe, dict ) or set( probe ) != PROBE_KEYS or not isinstance( probe[ "id" ], str ):
        raise DriverRefused( f"a probe is a mapping with exactly {sorted( PROBE_KEYS )}" )
    if probe[ "placement" ] not in PLACEMENTS or probe[ "neighbours" ] not in NEIGHBOURS.values():
        raise DriverRefused( f"probe placement is one of {PLACEMENTS} and neighbours one of {tuple( NEIGHBOURS.values() )}" )
    if ( probe[ "placement" ], probe[ "neighbours" ] ) != ( place, NEIGHBOURS[ near ] ):
        raise DriverRefused( f"the probe does not match the arm {arm!r}" )
    ids = [ e[ "id" ] for e in entries ]
    if probe[ "id" ] not in ids: raise DriverRefused( f"probe {probe[ 'id' ]!r} is not in the pack" )
    want = { "first": 0, "middle": len( ids ) // 2, "last": len( ids ) - 1 }[ place ]
    if ids.index( probe[ "id" ] ) != want: raise DriverRefused( f"probe is not at the {place} position of the pack" )


def _check_ready( env, entries ):
    """
    Check what a run would otherwise learn only after its ledger run opened.

    Requires:
        - every entry has an id
    Raises:
        - ValueError for a workers value outside the sweep's range, or for an entry id that is repeated
        - KeyMissing when the transport is the live one and the key variable is empty or unset
    """
    workers = env.workers
    if type( workers ) is not int or not rp.WORKERS_MIN <= workers <= rp.WORKERS_MAX:
        raise DriverRefused( f"workers must be an integer from {rp.WORKERS_MIN} to {rp.WORKERS_MAX}, got {workers!r}" )
    counts   = collections.Counter( e[ "id" ] for e in entries )
    repeated = sorted( i for i, n in counts.items() if n > 1 )
    if repeated: raise DriverRefused( f"{len( repeated )} entry id(s) are repeated in the arm, the first is {repeated[ 0 ]!r}" )
    if env.live and not jt.has_key(): raise KeyMissing( f"{jt.KEY_VARIABLE} is not set; no ledger run was opened and no run name was spent" )


def _canary_path( env, question, attempt=1 ):
    return env.results_dir / f"{run_name( question, 'canary', attempt )}.canary.json"


def _canary_reports( env, question ):
    """Ensures: returns ( attempt, path, report ) for each canary file written, oldest first."""
    found = [ ( n, _canary_path( env, question, n ) ) for n in range( 1, MAX_ATTEMPTS + 1 ) ]
    return [ ( n, path, json.loads( path.read_text() ) ) for n, path in found if path.exists() ]


def _require_approved( env, question ):
    """Raises: CanaryNotApproved unless a canary file holds an approval and no trip."""
    if not any( report[ "approved" ] is not None and not report[ "tripped" ] for _, _, report in _canary_reports( env, question ) ):
        raise CanaryNotApproved( f"the canary of question {question} is not approved" )


def _check_attempt( env, question, arm, attempt, reason, entries ):
    """
    Check a rerun against the rules that let a stopped arm run again.

    Raises:
        - ValueError for an attempt outside 1 to MAX_ATTEMPTS, a rerun without a reason or a first attempt with one,
          or a rerun with no attempt before it
        - ValueError for a rerun of an arm with an attempt that completed, or with one that stopped for any reason but its ceiling
        - ValueError for a rerun whose entries are not, id for id and in order, the entries of the attempt before it
        - ValueError for a canary rerun after any attempt was approved, or after an attempt tripped on model_mismatch
    """
    if type( attempt ) is not int or not 1 <= attempt <= MAX_ATTEMPTS: raise DriverRefused( f"attempt must be a whole number from 1 to {MAX_ATTEMPTS}, got {attempt!r}" )
    if attempt == 1:
        if reason is not None: raise DriverRefused( "a first attempt has no reason; only a retry gives one" )
        return
    if not isinstance( reason, str ) or not reason.strip(): raise DriverRefused( "a retry needs a named reason" )
    if not ( env.results_dir / f"{run_name( question, arm, attempt - 1 )}.json" ).exists(): raise DriverRefused( f"attempt {attempt} has no earlier attempt to follow" )
    if arm != "canary":
        before = { n: json.loads( ( env.results_dir / f"{run_name( question, arm, n )}.json" ).read_text() ) for n in range( 1, attempt ) }
        done   = [ n for n, rec in before.items() if rec[ "state" ] == "complete" ]
        if done: raise DriverRefused( f"{arm!r} of question {question} already completed as attempt {done[ 0 ]}; it is not run again" )
        for n, rec in before.items():
            if rec[ "stop_reason" ] != "ceiling": raise DriverRefused( f"{arm!r} of question {question} attempt {n} stopped for {rec[ 'stop_reason' ]}; only an arm stopped by its ceiling is run again" )
        if before[ attempt - 1 ][ "entry_ids" ] != [ e[ "id" ] for e in entries ]: raise DriverRefused( f"the entries of this rerun are not the entries of attempt {attempt - 1} of {arm!r}; a rerun asks the same ones" )
        return
    reports = _canary_reports( env, question )
    if any( report[ "approved" ] is not None for _, _, report in reports ): raise DriverRefused( f"the canary of question {question} is already approved" )
    if any( "model_mismatch" in report[ "tripped" ] for _, _, report in reports ): raise DriverRefused( f"the canary of question {question} tripped on model_mismatch; it is not retried" )


@contextlib.contextmanager
def _stage_lock( env ):
    """Ensures: yields holding a lock beside the ledger, so two drivers cannot admit at once."""
    lock = env.ledger.path.with_name( env.ledger.path.name + ".stage.lock" )
    with lock.open( "a" ) as f:
        fcntl.flock( f, fcntl.LOCK_EX )
        try: yield
        finally: fcntl.flock( f, fcntl.LOCK_UN )


def _write_json( path, record ):
    """Ensures: writes the record whole or not at all, with no temporary file left."""
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp = path.with_name( path.name + ".tmp" )
    tmp.write_text( json.dumps( record, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    os.replace( tmp, path )


def _stop_reason( sweep, budget ):
    """Ensures: returns why the arm stopped early, from the strings the analysis reads, or None."""
    if budget.stop_reason is not None: return "ledger"
    if sweep[ "stopped_by" ]: return sweep[ "stopped_by" ]
    if budget.ceiling_refusals: return "ceiling"
    if sweep[ "not_reached" ]: return "attempts"                              # nothing else stopped it, so the attempts were spent
    return None


def _rows_with_reserve( rows, need, by_id, template, model ):
    """Ensures: returns the rows, each with its own body's reserve, or None if never sent."""
    out = []
    for row in rows:
        if row[ "attempts" ] == 0: reserve = None
        else: reserve = rc.reserve_tokens( rp.pack_request( need, [ by_id[ i ] for i in row[ "ids" ] ], template, model )[ 0 ], len( row[ "ids" ] ) )
        out.append( { **row, "reserve_tokens": reserve } )
    return out


def run_arm( env, question, arm, need, entries, ceiling_tokens, attempt_limit=None, probe=None, attempt=1, reason=None ):
    """
    Run one arm as its own ledger run and write its results file.

    Requires:
        - question is 1 to 4 and arm is one of the arm names
        - entries are symbol dicts; for a probe arm they are one pack with the probe at its position
        - ceiling_tokens is what this arm may spend, and fits in what the stage has left
        - attempt is 1 for a first run; an arm its ceiling stopped may be run again as attempt 2 or 3, with a reason; any other arm may not
    Ensures:
        - nothing is sent and no ledger row is written when any check below refuses
        - the sweep keys its answers by pack size and run index, so no two arms share an answer
        - the run is closed in the ledger however the arm ends, and the results file is written
        - the attempt limit defaults to the arm's cap, and the results file records both as attempt_cap and attempt_limit
        - an arm that runs out of attempts, ceiling or ledger is incomplete with its reason, never raised
        - an entry the response left unasked counts as failed, so it makes the arm incomplete
        - returns the results record
    Raises:
        - ValueError for a question, arm or probe out of range, a run name used before, workers out of range or a repeated entry id
        - KeyMissing for the live transport with no key; this and the ValueErrors above open no ledger run and spend no name
        - ReuseError BAD_BUDGET for an attempt limit above the arm's cap: its entries plus ten percent, never below the 9,000 floor
        - StageRefused when the ceiling passes what the stage has left
        - CanaryNotApproved for any arm but the first single run before the canary is approved
        - LedgerUnreadable or AccountLimitReached from the ledger
    """
    if type( question ) is not int or question not in QUESTIONS: raise DriverRefused( f"question must be one of {QUESTIONS}, got {question!r}" )
    if arm not in ARMS: raise DriverRefused( f"arm must be one of {sorted( ARMS )}, got {arm!r}" )
    _check_attempt( env, question, arm, attempt, reason, entries )
    attempt_cap   = rt.call_budget_cap_for( len( entries ) )
    attempt_limit = attempt_cap if attempt_limit is None else attempt_limit
    if type( attempt_limit ) is not int or not 1 <= attempt_limit <= attempt_cap:
        raise rt.ReuseError( "BAD_BUDGET", f"attempt limit must be an integer from 1 to {attempt_cap}, got {attempt_limit!r}" )
    if arm not in UNGATED: _require_approved( env, question )
    _check_probe( arm, probe, entries )
    _check_ready( env, entries )
    name, ( index, size ) = run_name( question, arm, attempt ), ARMS[ arm ]
    index    = retry_index( arm, attempt )
    template = rt.PAGE_TEMPLATE if arm.startswith( "page-" ) else rt.PROMPT_TEMPLATE
    record   = { "format": FORMAT, "question": question, "need": need, "arm": arm, "run_name": name, "run_index": index, "size": size, "model": env.model,
                 "template_hash": rt.prompt_template_hash( template ), "started_at": env.clock(), "ceiling_tokens": ceiling_tokens, "attempt_cap": attempt_cap, "attempt_limit": attempt_limit,
                 "entry_ids": [ e[ "id" ] for e in entries ], "entries_in_index": env.entries_in_index, "probe": probe,
                 "attempt": attempt, "retry_reason": reason }
    with _stage_lock( env ):                                                      # the check and the admission are one step
        remaining = stage_remaining( env.ledger )
        if type( ceiling_tokens ) is int and ceiling_tokens > remaining:  # pragma: no branch -- the lock never swallows this raise
            raise StageRefused( f"{ceiling_tokens} asked, {remaining} remaining of the stage's {STAGE_TOKENS}" )
        try: budget = rc.TokenBudget( attempt_limit, ceiling_tokens, ledger=env.ledger, run=name )
        except ValueError as e: raise DriverRefused( str( e ) ) from e                    # a run name used before, refused by the ledger
    try:
        ctx   = rt.ReuseContext( env.root, env.data, transport=env.transport_factory( budget ), template=template, model=env.model, call_budget=attempt_limit, call_budget_cap=attempt_cap )
        sweep = rp.sweep_packed( ctx, need, entries, size, workers=env.workers, key_mode="stage1", run_index=index, template=template, model=env.model, budget=budget )
        rows  = _rows_with_reserve( sweep[ "rows" ], need, { e[ "id" ]: e for e in entries }, template, env.model )
        record.update( state="complete" if not ( sweep[ "failed" ] or sweep[ "not_reached" ] ) else "incomplete", stop_reason=_stop_reason( sweep, budget ),
                       answers=sweep[ "answers" ], failed=sweep[ "failed" ], not_reached=sweep[ "not_reached" ], unasked=sweep[ "unasked" ], cache_hits=sweep[ "cache_hits" ],
                       rows=rows, transport_calls=sweep[ "transport_calls" ],
                       totals={ "requests": sweep[ "requests" ], "calls": sweep[ "calls" ], "attempts_answered": sweep[ "attempts_answered" ], "attempts_failed": sweep[ "attempts_failed" ],
                                "tokens_in": sweep[ "tokens_in" ], "tokens_out": sweep[ "tokens_out" ], "usage_missing": sweep[ "usage_missing" ], "refused_422": sweep[ "refused_422" ],
                                "stopped_by": sweep[ "stopped_by" ], "spent_tokens": budget.spent_tokens, "reserved_tokens": budget.reserved_tokens,
                                "ceiling_refusals": budget.ceiling_refusals } )
    except BaseException as e:                                                    # the arm is recorded as an error, then the error goes on
        record.update( state="error", stop_reason=f"error: {type( e ).__name__}", answers=[], failed=[], not_reached=[], unasked=[], cache_hits=0, rows=[], transport_calls=[],
                       totals={ "requests": 0, "calls": 0, "attempts_answered": 0, "attempts_failed": 0, "tokens_in": 0, "tokens_out": 0, "usage_missing": 0, "refused_422": 0,
                                "stopped_by": None, "spent_tokens": budget.spent_tokens, "reserved_tokens": budget.reserved_tokens, "ceiling_refusals": budget.ceiling_refusals } )
        raise
    finally:
        try:
            record[ "ended_at" ] = env.clock()
            _write_json( env.results_dir / f"{name}.json", record )
        finally:
            budget.end()
    return record


def _canary_report( question, out ):
    """Ensures: returns the canary record for one finished canary arm, nothing yet approved."""
    sent     = [ r for r in out[ "rows" ] if r[ "status" ] == "answered" and r[ "tokens_out" ] is not None ]
    usage    = [ { "request_hash": r[ "request_hash" ], "usage": r[ "tokens_in" ] + r[ "tokens_out" ], "reserve": r[ "reserve_tokens" ],
                   "over": r[ "tokens_in" ] + r[ "tokens_out" ] > r[ "reserve_tokens" ] } for r in sent ]
    per      = [ r[ "tokens_out" ] / r[ "size" ] for r in sent ]
    refusals = sum( 1 for r in out[ "rows" ] if r[ "status" ] == "refused" )
    sent_rows = [ r for r in out[ "rows" ] if r[ "attempts" ] ]
    tripped  = [ name for name, hit in ( ( f"output_per_entry_over_{OUTPUT_LIMIT}", any( n > OUTPUT_LIMIT for n in per ) ),
                                         ( "usage_over_reserve", any( u[ "over" ] for u in usage ) ),
                                         ( "refusal", refusals > 0 ),
                                         ( "usage_missing", out[ "totals" ][ "usage_missing" ] > 0 ),
                                         ( "model_mismatch", out[ "stop_reason" ] == "model_mismatch" ),
                                         ( "nothing_measured", not sent_rows ),
                                         ( "incomplete", out[ "state" ] != "complete" ) ) if hit ]
    return { "format": CANARY_FORMAT, "question": question, "run_name": out[ "run_name" ], "attempt": out[ "attempt" ], "retry_reason": out[ "retry_reason" ],
             "output_tokens_per_entry": per, "usage_vs_reserve": usage,
             "refusals": refusals, "attempts_over_one": sum( 1 for c in out[ "transport_calls" ] if c[ "attempts" ] > 1 ), "unasked": len( out[ "unasked" ] ),
             "tripped": tripped, "approved": None }


def run_canary( env, question, need, entries, ceiling_tokens, attempt_limit=None, attempt=1, reason=None ):
    """
    Ask the first pack of ten and write the numbers a human reads before more is paid for.

    Ensures:
        - sends the first CANARY_SIZE entries as one request, under the run s1-q<question>-canary
        - writes the canary file beside the arm file, with `approved` empty
        - returns the canary record; a stop number that was crossed is in `tripped`
        - a retry is attempt 2 or 3 with a reason, runs as s1-q<question>-canary-a<attempt>, and keeps every earlier file
    """
    out    = run_arm( env, question, "canary", need, entries[ :CANARY_SIZE ], ceiling_tokens, attempt_limit, attempt=attempt, reason=reason )
    report = _canary_report( question, out )
    _write_json( _canary_path( env, question, attempt ), report )
    return report


def approve_canary( env, question, by, why, attempt=None ):
    """
    Record that a human read a canary and let the other arms run.

    Ensures:
        - approves the latest attempt that wrote a canary file, or the attempt named
    Raises:
        - ValueError for a missing by or why, or a canary already approved
        - CanaryNotApproved when the question, or the attempt named, has no canary
        - CanaryTripped when that canary crossed a stop number; it is never approved
    """
    if not isinstance( by, str ) or not by or not isinstance( why, str ) or not why: raise DriverRefused( "by and why must say who approved the canary and why" )
    reports = _canary_reports( env, question )
    if not reports: raise CanaryNotApproved( f"no canary was run for question {question}" )
    if any( report[ "approved" ] is not None for _, _, report in reports ): raise DriverRefused( f"the canary of question {question} is already approved" )
    chosen = [ r for r in reports if attempt is None or r[ 0 ] == attempt ]
    if not chosen: raise CanaryNotApproved( f"no canary was run for question {question} attempt {attempt}" )
    _, path, report = chosen[ -1 ]
    if report[ "tripped" ]: raise CanaryTripped( f"the canary tripped: {', '.join( report[ 'tripped' ] )}" )
    report[ "approved" ] = { "by": by, "why": why, "at": env.clock() }
    _write_json( path, report )
