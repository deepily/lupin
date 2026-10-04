"""
The runner of the judge harness (plan 1, section 5, "Throughput and scheduling").

For each before/after pair it draws several independent claim lists from the extractor and
freezes each list. It then runs the judge three times over each list. Every finished model
call is written to a ledger the moment it returns, so a killed run resumes without repeating
a call. The ledger key carries the hash of the old text, the hash of the new text, the prompt
version and the model id. A changed prompt or model can therefore never resume a stale verdict.
"""

import asyncio
import hashlib
import json
import os
from collections import namedtuple

from . import claim_extractor, claim_judge, model_transport

HarnessConfig = namedtuple( "HarnessConfig", [
    "extractor_model", "judge_model", "escalation_model", "writer_model", "extractor_lists", "judge_runs", "judge_thinking"
], defaults=( 2, 3, "default" ) )


def check_models( config ):
    """
    Refuse a configuration in which a judge could be grading its own writing.

    Requires:
        - config is a HarnessConfig

    Ensures:
        - returns None when every model id is set and neither the judge nor the escalation model
          is the writer model
        - the extractor may equal the writer: it only lists claims, it does not grade a rewrite
        - ids are compared as exact pinned ids, ignoring case and surrounding space; an alias of
          the writer's model that is spelled differently is not detected, so use pinned ids

    Raises:
        - ValueError naming the missing id, or the judge role that equals the writer, or a judge_thinking that
          is not one of model_transport.THINKING_SETTINGS
    """
    if config.judge_thinking not in model_transport.THINKING_SETTINGS:
        raise ValueError( f"judge_thinking must be one of {model_transport.THINKING_SETTINGS}, got {config.judge_thinking!r}" )
    for name in ( "extractor_model", "judge_model", "escalation_model", "writer_model" ):
        if not getattr( config, name ): raise ValueError( f"{name} is required: the harness has no default model" )
    for name in ( "judge_model", "escalation_model" ):
        if getattr( config, name ).strip().lower() == config.writer_model.strip().lower():
            raise ValueError( f"{name} equals the writer model {config.writer_model!r}: a model must not grade its own rewrite" )


def text_hash( text ):
    """Return a short stable hash of a text, for ledger keys."""
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()[ :16 ]


def ledger_key( stage, pair, prompt_version, model_id, slot ):
    """
    Build the ledger key for one model call.

    Requires:
        - stage is a short name; pair has "old", "new" and optionally "design"
        - slot identifies the call within its stage, such as the extractor list and judge run

    Ensures:
        - the key holds the hash of the old text, the hash of the new text with its design doc,
          the prompt version and the model id, so changing any of them is a different key
    """
    new_side = pair[ "new" ] + "\0" + ( pair.get( "design" ) or "" )
    return "|".join( [ stage, text_hash( pair[ "old" ] ), text_hash( new_side ), prompt_version, model_id, str( slot ) ] )


class LedgerBindingError( ValueError ):
    """A ledger was written under a different Claude Code binary than the run now asking to resume it."""


class Ledger:
    """
    An append-only file of finished model calls, one JSON object per line.

    Requires:
        - path is writable
        - binding is None, or a string naming the Claude Code binary and version the calls run under

    Ensures:
        - a binding is written as the file's first record, and a ledger holding calls or a binding
          that differs from this one is refused (LedgerBindingError), so a resume never mixes binaries
        - every put is on disk before it returns, so a kill loses at most the call in flight
        - a torn last line from a kill during a write is ignored on load
        - a put may carry the call time of the row, written in the same line, so a row and its time are
          on disk together or not at all; timing is no part of the key, and a row written without it reads as None
    """

    def __init__( self, path, binding=None ):
        self.path     = path
        self.entries  = {}
        self.timings  = {}
        self.recorded = None
        if os.path.exists( path ):
            with open( path, encoding="utf-8" ) as f:
                for line in f:
                    try:
                        record = json.loads( line )
                    except ValueError:
                        continue
                    if "binding" in record:
                        self.recorded = record[ "binding" ]
                    else:
                        self.entries[ record[ "key" ] ] = record[ "value" ]
                        if "timing" in record: self.timings[ record[ "key" ] ] = record[ "timing" ]
        if binding is not None:
            if ( self.entries or self.recorded is not None ) and self.recorded != binding:
                raise LedgerBindingError( f"ledger {path} was written under {self.recorded!r} and this run is {binding!r}: use a new ledger" )
            if self.recorded is None:
                self._append( { "binding": binding } )
                self.recorded = binding

    def _ends_with_newline( self ):
        """Say whether the ledger file's last byte is a newline."""
        with open( self.path, "rb" ) as f:
            f.seek( -1, os.SEEK_END )
            return f.read( 1 ) == b"\n"

    def get( self, key ):
        """Return the stored value for key, or None when that call has not finished."""
        return self.entries.get( key )

    def _append( self, record ):
        """Append one record to the file and force it to disk."""
        torn = os.path.exists( self.path ) and os.path.getsize( self.path ) > 0 and not self._ends_with_newline()
        with open( self.path, "a", encoding="utf-8" ) as f:
            if torn: f.write( "\n" )
            f.write( json.dumps( record ) + "\n" )
            f.flush()
            os.fsync( f.fileno() )

    def timing( self, key ):
        """Return the recorded { stage: { "seconds", "calls" } } of a finished row, or None when it was written without one."""
        return self.timings.get( key )

    def put( self, key, value, timing=None ):
        """Store a finished call durably before returning; timing, when given, is stored in the same line."""
        record = { "key": key, "value": value }
        if timing is not None: record[ "timing" ] = timing
        self._append( record )
        self.entries[ key ] = value
        if timing is not None: self.timings[ key ] = timing


async def run_pair( pair, config, ledger, query_fn=None, judge_backend=None, on_unreadable=None ):
    """
    Run the extractor and judge over one pair, skipping every call the ledger already holds.

    Requires:
        - pair has "id", "old", "new"; optionally "design" and "seed_span" ( start, end ) in old
        - config passes check_models
        - judge_backend, when given, has .prompt_version, .key_id (names the model and every setting
          that changes a verdict, such as thresholds), .complete( judged ) and an async .judge( claims,
          new, design, query_fn ) returning Judgements; without one the Claude judge runs

    Ensures:
        - the judge ledger key carries the backend's key_id and prompt version, so a Jev run can
          never resume a Claude verdict or a run with other thresholds
        - a backend's verdicts are ledgered only when its .complete( judged ) is True, so a run in
          which the backend failed to answer is asked again on resume instead of replayed
        - returns { "id", "seed_span", "lists" }; each list holds its claims, the count of
          discarded claims, one { code, words, start, end } per discard (no quote text), the runs
          flagged for a person and their word counts, the extra extractor calls made, the uncovered fraction of the old text, and one verdict row per
          judge run
        - the claim list of each extractor slot is frozen in the ledger before any judging
        - a list whose first reply was unreadable twice is frozen with parse_failed True (the retry is not
          repeated on resume), no claims, and its whole old text flagged; on_unreadable, when given, is called
          with ( pair id, slot, attempt, raw reply, error ) for each unreadable reply
        - a frozen entry written before row ed2f9b4e has no discards, flags, reextract_calls, parse_failed or
          retry_calls; it reads as none of them, so judge_comparison can still rebuild a report from an old ledger
        - a finished call is never made again
        - with judge_thinking "off" the judge key carries "|thinking=off", so a verdict judged with thinking
          on is never reused for thinking off or the other way round; a ledger of the other setting is not
          refused, its judge rows simply miss and the judge calls run again (extractor lists are shared)
        - "timing" holds { "stages": { stage: { "seconds", "calls" } }, "untimed_rows" }, summed over every
          row of the pair, fresh or resumed (a resumed row reports its recorded time); a row ledgered before
          timing existed counts in untimed_rows; timing is never part of a ledger key

    Raises:
        - ValueError if config fails check_models
        - whatever the extractor or judge raises for a failed call; finished calls stay in the ledger
    """
    check_models( config )
    lists   = []
    timing  = {}
    untimed = 0

    def tally( recorded ):
        """Add one finished row's recorded timing to the pair's totals; a row with none counts as untimed."""
        nonlocal untimed
        if recorded is None:
            untimed += 1
            return
        for stage, entry in recorded.items():
            total = timing.setdefault( stage, { "seconds": 0.0, "calls": 0 } )
            total[ "seconds" ] += entry[ "seconds" ]
            total[ "calls" ]   += entry[ "calls" ]

    for slot in range( config.extractor_lists ):
        key    = ledger_key( "extract", pair, claim_extractor.PROMPT_VERSION, config.extractor_model, slot )
        frozen = ledger.get( key )
        if frozen is None:
            sink   = None if on_unreadable is None else ( lambda attempt, raw, error, slot=slot: on_unreadable( pair[ "id" ], slot, attempt, raw, error ) )
            with model_transport.record_calls( ( ( "extractor", "default" ), ) ) as calls:
                result = await claim_extractor.extract_claims( pair[ "old" ], config.extractor_model, query_fn=query_fn, on_unreadable=sink )
            recorded = summarize_calls( calls )
            frozen = { "claims": [ c._asdict() for c in result.claims ], "discarded": len( result.discarded ),
                       "discards": list( result.discards ), "flags": [ list( f ) for f in result.flags ], "flag_words": list( result.flag_words ),
                       "parse_failed": result.parse_failed, "retry_calls": result.retry_calls,
                       "reextract_calls": result.reextract_calls,
                       "uncovered": result.uncovered_fraction,
                       "longest_quote": result.longest_quote_share }
            ledger.put( key, frozen, timing=recorded )
        else:
            recorded = ledger.timing( key )
        tally( recorded )
        claims = [ claim_extractor.Claim( **c ) for c in frozen[ "claims" ] ]
        runs   = []
        for run in range( config.judge_runs ):
            version = claim_judge.PROMPT_VERSION if judge_backend is None else judge_backend.prompt_version
            model   = config.judge_model + "+" + config.escalation_model if judge_backend is None else judge_backend.key_id
            if judge_backend is None and config.judge_thinking != "default": model += "|thinking=" + config.judge_thinking
            jkey    = ledger_key( "judge", pair, version, model,
                                  f"{slot}.{run}.{text_hash( json.dumps( frozen[ 'claims' ], sort_keys=True ) )}" )
            rows = ledger.get( jkey )
            if rows is None:
                plan = ( ( "judge", config.judge_thinking ), ( "escalation", "default" ) ) if judge_backend is None else ( ( "escalation", "default" ), )
                with model_transport.record_calls( plan ) as calls:
                    if judge_backend is None:
                        judged = await claim_judge.judge_claims( claims, pair[ "new" ], pair.get( "design" ),
                                                                 config.judge_model, config.escalation_model, query_fn=query_fn )
                    else:
                        judged = await judge_backend.judge( claims, pair[ "new" ], pair.get( "design" ), query_fn )
                rows     = [ { "verdict": j.verdict, "escalated": j.escalated, "reason": j.reason, "noul": j.noul } for j in judged ]
                recorded = summarize_calls( calls )
                if judge_backend is None or judge_backend.complete( judged ): ledger.put( jkey, rows, timing=recorded )
            else:
                recorded = ledger.timing( jkey )
            tally( recorded )
            runs.append( rows )
        lists.append( { "claims": frozen[ "claims" ], "discarded": frozen[ "discarded" ],
                        "discards": frozen.get( "discards", [] ), "flags": frozen.get( "flags", [] ),
                        "reextract_calls": frozen.get( "reextract_calls", 0 ), "flag_words": frozen.get( "flag_words", [] ),
                        "parse_failed": frozen.get( "parse_failed", False ), "retry_calls": frozen.get( "retry_calls", 0 ),
                        "uncovered": frozen[ "uncovered" ], "longest_quote": frozen[ "longest_quote" ], "runs": runs } )
    return { "id": pair[ "id" ], "seed_span": pair.get( "seed_span" ), "lists": lists, "timing": { "stages": timing, "untimed_rows": untimed } }


def summarize_calls( calls ):
    """
    Fold ( stage, seconds ) call records into { stage: { "seconds", "calls" } }.

    Requires:
        - calls is a list of ( stage, seconds ) as record_calls() yields

    Ensures:
        - one entry per stage seen; seconds is the sum of that stage's wall-clock seconds, calls their count
    """
    totals = {}
    for stage, seconds in calls:
        entry = totals.setdefault( stage, { "seconds": 0.0, "calls": 0 } )
        entry[ "seconds" ] += seconds
        entry[ "calls" ]   += 1
    return totals


def unquotable_seeds( pairs ):
    """
    Return the ids of seeded pairs whose seeded span cannot itself be quoted.

    Requires:
        - pairs is a list of run_pair inputs

    Ensures:
        - a pair with a seed_span is listed when locate_quote refuses the text of that span in the old
          text: too short, ambiguous, or too much of the text; the instrument cannot express such a removal
        - unseeded pairs are never listed; ids only, never text
    """
    return [ p[ "id" ] for p in pairs
             if p.get( "seed_span" ) is not None and claim_extractor.locate_quote( p[ "old" ][ p[ "seed_span" ][ 0 ]:p[ "seed_span" ][ 1 ] ], p[ "old" ] ) is None ]


async def run_all( pairs, config, ledger, query_fn=None, judge_backend=None, on_unreadable=None, parallel=1 ):
    """
    Run every pair and return their results in input order.

    Requires:
        - pairs is a list of run_pair inputs
        - parallel is an int of 1 or more

    Ensures:
        - with parallel 1 the pairs run one at a time, as before
        - with parallel N above 1, up to N pairs are in flight at once; the ledger and the call budget are
          written without an await between check and write, so lines stay whole and a cap is never passed
        - pairs with the same old text, new text and design run one after another, so a resumed or repeated
          pair never makes a call a twin has finished
        - once one pair fails, pairs not yet started are skipped, every pair in flight finishes (its ledger
          rows are kept), and then the failure of the earliest pair in input order is raised

    Raises:
        - ValueError if parallel is below 1
        - whatever run_pair raises
    """
    if parallel < 1: raise ValueError( f"parallel must be 1 or more, got {parallel}" )
    if parallel == 1:
        return [ await run_pair( pair, config, ledger, query_fn=query_fn, judge_backend=judge_backend, on_unreadable=on_unreadable ) for pair in pairs ]
    slots  = asyncio.Semaphore( parallel )
    twins  = {}
    errors = {}

    async def one( index, pair ):
        """Run one pair under its twin lock and a slot; record, rather than raise, its failure."""
        lock = twins.setdefault( ( pair[ "old" ], pair[ "new" ], pair.get( "design" ) ), asyncio.Lock() )
        outcome = None
        async with lock, slots:
            if not errors:
                try:
                    outcome = await run_pair( pair, config, ledger, query_fn=query_fn, judge_backend=judge_backend, on_unreadable=on_unreadable )
                except Exception as e:
                    errors[ index ] = e
        return outcome

    results = await asyncio.gather( *[ one( i, pair ) for i, pair in enumerate( pairs ) ] )
    if errors: raise errors[ min( errors ) ]
    return list( results )
