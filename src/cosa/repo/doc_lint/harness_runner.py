"""
The runner of the judge harness (plan 1, section 5, "Throughput and scheduling").

For each before/after pair it draws several independent claim lists from the extractor and
freezes each list. It then runs the judge three times over each list. Every finished model
call is written to a ledger the moment it returns, so a killed run resumes without repeating
a call. The ledger key carries the hash of the old text, the hash of the new text, the prompt
version and the model id. A changed prompt or model can therefore never resume a stale verdict.
"""

import hashlib
import json
import os
from collections import namedtuple

from . import claim_extractor, claim_judge

HarnessConfig = namedtuple( "HarnessConfig", [
    "extractor_model", "judge_model", "escalation_model", "writer_model", "extractor_lists", "judge_runs"
], defaults=( 2, 3 ) )


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
        - ValueError naming the missing id, or the judge role that equals the writer
    """
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


class Ledger:
    """
    An append-only file of finished model calls, one JSON object per line.

    Requires:
        - path is writable

    Ensures:
        - every put is on disk before it returns, so a kill loses at most the call in flight
        - a torn last line from a kill during a write is ignored on load
    """

    def __init__( self, path ):
        self.path    = path
        self.entries = {}
        if os.path.exists( path ):
            with open( path, encoding="utf-8" ) as f:
                for line in f:
                    try:
                        record = json.loads( line )
                    except ValueError:
                        continue
                    self.entries[ record[ "key" ] ] = record[ "value" ]

    def _ends_with_newline( self ):
        """Say whether the ledger file's last byte is a newline."""
        with open( self.path, "rb" ) as f:
            f.seek( -1, os.SEEK_END )
            return f.read( 1 ) == b"\n"

    def get( self, key ):
        """Return the stored value for key, or None when that call has not finished."""
        return self.entries.get( key )

    def put( self, key, value ):
        """Store a finished call durably before returning."""
        torn = os.path.exists( self.path ) and os.path.getsize( self.path ) > 0 and not self._ends_with_newline()
        with open( self.path, "a", encoding="utf-8" ) as f:
            if torn: f.write( "\n" )
            f.write( json.dumps( { "key": key, "value": value } ) + "\n" )
            f.flush()
            os.fsync( f.fileno() )
        self.entries[ key ] = value


async def run_pair( pair, config, ledger, query_fn=None, judge_backend=None ):
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
          discarded claims, the uncovered fraction of the old text, and one verdict row per
          judge run
        - the claim list of each extractor slot is frozen in the ledger before any judging
        - a finished call is never made again

    Raises:
        - ValueError if config fails check_models
        - whatever the extractor or judge raises for a failed call; finished calls stay in the ledger
    """
    check_models( config )
    lists = []
    for slot in range( config.extractor_lists ):
        key    = ledger_key( "extract", pair, claim_extractor.PROMPT_VERSION, config.extractor_model, slot )
        frozen = ledger.get( key )
        if frozen is None:
            result = await claim_extractor.extract_claims( pair[ "old" ], config.extractor_model, query_fn=query_fn )
            frozen = { "claims": [ c._asdict() for c in result.claims ], "discarded": len( result.discarded ),
                       "uncovered": result.uncovered_fraction,
                       "longest_quote": result.longest_quote_share }
            ledger.put( key, frozen )
        claims = [ claim_extractor.Claim( **c ) for c in frozen[ "claims" ] ]
        runs   = []
        for run in range( config.judge_runs ):
            version = claim_judge.PROMPT_VERSION if judge_backend is None else judge_backend.prompt_version
            model   = config.judge_model + "+" + config.escalation_model if judge_backend is None else judge_backend.key_id
            jkey    = ledger_key( "judge", pair, version, model,
                                  f"{slot}.{run}.{text_hash( json.dumps( frozen[ 'claims' ], sort_keys=True ) )}" )
            rows = ledger.get( jkey )
            if rows is None:
                if judge_backend is None:
                    judged = await claim_judge.judge_claims( claims, pair[ "new" ], pair.get( "design" ),
                                                             config.judge_model, config.escalation_model, query_fn=query_fn )
                else:
                    judged = await judge_backend.judge( claims, pair[ "new" ], pair.get( "design" ), query_fn )
                rows   = [ { "verdict": j.verdict, "escalated": j.escalated, "reason": j.reason, "noul": j.noul } for j in judged ]
                if judge_backend is None or judge_backend.complete( judged ): ledger.put( jkey, rows )
            runs.append( rows )
        lists.append( { "claims": frozen[ "claims" ], "discarded": frozen[ "discarded" ],
                        "uncovered": frozen[ "uncovered" ], "longest_quote": frozen[ "longest_quote" ], "runs": runs } )
    return { "id": pair[ "id" ], "seed_span": pair.get( "seed_span" ), "lists": lists }


async def run_all( pairs, config, ledger, query_fn=None, judge_backend=None ):
    """
    Run every pair in order and return their results.

    Requires:
        - pairs is a list of run_pair inputs

    Ensures:
        - results are in the order of pairs; pairs run one at a time, so the ledger has a single writer
    """
    return [ await run_pair( pair, config, ledger, query_fn=query_fn, judge_backend=judge_backend ) for pair in pairs ]
