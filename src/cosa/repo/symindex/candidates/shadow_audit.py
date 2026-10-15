"""
The shadow audit: a full sweep on a small share of lookups, compared with the shortlist.

A lookup is sampled by a hash of its need and the vector-set generation, so the same lookup is always in or out.
A sampled lookup is queued, and a scheduled run drains the queue through a transport that does the full sweep.
Each audit leaves a receipt of its own kind in the same data folder, and the receipts give a bound on missed matches.
Nothing here makes a live call: the transport is passed in.
"""
import hashlib
import json
import math
import os
import pathlib

from cosa.repo.symindex.candidates.errors import CandidateError

AUDIT_COUNTS_INVALID  = "AUDIT_COUNTS_INVALID"
AUDIT_RECEIPT_CORRUPT = "AUDIT_RECEIPT_CORRUPT"
AUDIT_RATE_INVALID    = "AUDIT_RATE_INVALID"

KIND           = "shadow_audit"
SAMPLE_RATE    = 0.01
SAMPLE_BUCKETS = 10000
Z_ONE_SIDED_95 = 1.6448536269514722
CONFIDENCE     = 0.95
MATCHING       = ( "REUSE", "EXTEND" )
OUTCOMES       = ( "miss", "ok", "inconclusive" )
ITEM_FIELDS    = ( "id", "need", "language", "generation", "index_sha", "live", "queued_on", "attempts" )
TEMP_PREFIX    = ".tmp-"
RECEIPT_FIELDS = ( "kind", "id", "need_hash", "language", "generation", "index_sha", "live_verdict", "full_verdict",
                   "candidate_count", "causal_ids", "outcome", "missed_ids", "audited_on" )


def audit_bound( misses, n ):
    """
    Give the 95% upper bound on the share of lookups whose true match the stage missed.

    Requires:
        - n is a whole number of audits and misses is a whole number from 0 to n

    Ensures:
        - returns 1.0 when n is 0, because no audit says nothing
        - returns the exact one-sided bound, 1 - 0.05 ** ( 1 / n ), when misses is 0, which is never above the rule of three, 3 / n
        - a miss never lowers the bound: for every n the bound at one miss is above the bound at none
        - otherwise returns the one-sided Wilson upper bound
        - the result is never above 1.0

    Raises:
        - CandidateError AUDIT_COUNTS_INVALID when a count is not a whole number or misses is outside 0 to n
    """
    if not all( isinstance( v, int ) and not isinstance( v, bool ) for v in ( misses, n ) ) or n < 0 or misses < 0 or misses > n:
        raise CandidateError( AUDIT_COUNTS_INVALID, f"misses {misses!r} of n {n!r}" )
    if n == 0: return 1.0
    if misses == 0: return 1.0 - ( 1.0 - CONFIDENCE ) ** ( 1.0 / n )
    p, z2 = misses / n, Z_ONE_SIDED_95 ** 2
    centre = p + z2 / ( 2 * n )
    spread = Z_ONE_SIDED_95 * math.sqrt( p * ( 1 - p ) / n + z2 / ( 4 * n * n ) )
    return min( 1.0, ( centre + spread ) / ( 1 + z2 / n ) )


def need_hash( need ):
    """Return the sha256 of a need's text, so a receipt names a need without keeping its words."""
    return hashlib.sha256( need.encode( "utf-8" ) ).hexdigest()


def is_sampled( need, generation, rate=SAMPLE_RATE ):
    """
    Decide whether a lookup is in the audit sample.

    Requires:
        - rate is from 0 to 1

    Ensures:
        - the same need and generation always give the same answer
        - about rate of the lookups are in, and a rate of 0 takes none and a rate of 1 takes all

    Raises:
        - CandidateError AUDIT_RATE_INVALID when rate is outside 0 to 1
    """
    if not 0 <= rate <= 1: raise CandidateError( AUDIT_RATE_INVALID, repr( rate ) )
    digest = hashlib.sha256( f"{generation}\n{need}".encode( "utf-8" ) ).hexdigest()
    return int( digest[ :8 ], 16 ) % SAMPLE_BUCKETS < round( rate * SAMPLE_BUCKETS )


def compare( live_verdict, full_verdict, causal_ids, candidate_ids ):
    """
    Compare the full sweep with the shortlist the stage kept.

    Requires:
        - causal_ids is the full sweep's ids that made it a reuse or an extend, empty for any other verdict
        - candidate_ids is every id the stage kept

    Ensures:
        - returns "inconclusive" when the full sweep could not decide, so the audit is not counted
        - returns "inconclusive" when the full sweep matched but named no causal id, since that answer is malformed
        - returns "miss" when the full sweep matched and none of its causal ids was kept
        - returns "ok" otherwise, including when the judge disagreed with itself about a kept id
        - live_verdict does not change the outcome: the stage is judged on what it kept
    """
    if full_verdict not in MATCHING and full_verdict != "NEW": return "inconclusive"
    if full_verdict in MATCHING and not causal_ids: return "inconclusive"
    if full_verdict in MATCHING and not set( causal_ids ) & set( candidate_ids ): return "miss"
    return "ok"


def audit_receipt( need, language, generation, index_sha, live, sweep, today ):
    """
    Build the receipt of one audit.

    Requires:
        - live holds verdict and candidate_ids of the lookup that was served
        - sweep holds verdict and causal_ids of the full sweep
        - today is an ISO date string

    Ensures:
        - returns a dict whose keys are RECEIPT_FIELDS
        - the id is a 16 character hash of the need hash, generation and index sha, so a repeat is one receipt
        - the need's words are not kept, only its hash
    """
    candidates = set( live[ "candidate_ids" ] )
    outcome    = compare( live[ "verdict" ], sweep[ "verdict" ], sweep[ "causal_ids" ], candidates )
    digest     = need_hash( need )
    rid        = hashlib.sha256( f"{digest}\n{generation}\n{index_sha}".encode( "utf-8" ) ).hexdigest()[ :16 ]
    missed     = sorted( set( sweep[ "causal_ids" ] ) - candidates ) if outcome == "miss" else []
    return { "kind": KIND, "id": rid, "need_hash": digest, "language": language, "generation": generation, "index_sha": index_sha,
             "live_verdict": live[ "verdict" ], "full_verdict": sweep[ "verdict" ], "candidate_count": len( candidates ),
             "causal_ids": sorted( sweep[ "causal_ids" ] ), "outcome": outcome, "missed_ids": missed, "audited_on": today }


def _folder( data_dir, name ):
    """Return one subfolder of the data folder, made if it is missing."""
    path = pathlib.Path( data_dir ) / name
    path.mkdir( parents=True, exist_ok=True )
    return path


def _temp_name( path ):
    """Name a write's temporary file so no *.json listing sees it."""
    return path.with_name( f"{TEMP_PREFIX}{os.getpid()}-{path.name}.part" )


def _item_ok( item ):
    """Return True when a queue file holds every queue field."""
    return isinstance( item, dict ) and all( key in item for key in ITEM_FIELDS ) and isinstance( item[ "attempts" ], int ) \
           and isinstance( item[ "live" ], dict )


def _write_once( path, text ):
    """
    Put a file in place whole, or leave an existing one alone.

    Ensures:
        - the text is written to a temporary name in the same folder and linked to path, so path is whole or absent
        - an existing path is never replaced, and the temporary name is gone afterwards
        - returns True when this call created the file
    """
    temp = _temp_name( path )
    temp.write_text( text, encoding="utf-8" )
    try:
        os.link( temp, path )
        return True
    except FileExistsError:
        return False
    finally:
        os.remove( temp )


def store_receipt( data_dir, receipt ):
    """
    Write a receipt once.

    Ensures:
        - the file receipts/shadow-<id>.json exists afterwards, whole
        - an existing receipt is kept and returned, so a repeat audit never rewrites history

    Raises:
        - CandidateError AUDIT_RECEIPT_CORRUPT when the file already there is not JSON
    """
    path = _folder( data_dir, "receipts" ) / f"shadow-{receipt[ 'id' ]}.json"
    _write_once( path, json.dumps( receipt, sort_keys=True ) + "\n" )
    try: return json.loads( path.read_text( encoding="utf-8" ) )
    except ValueError as exc: raise CandidateError( AUDIT_RECEIPT_CORRUPT, f"{path.name}: {exc}" ) from exc


def load_receipts( data_dir ):
    """
    Read every audit receipt in the data folder.

    Ensures:
        - returns the receipts of kind shadow_audit, sorted by id
        - other receipts in the folder are not read

    Raises:
        - CandidateError AUDIT_RECEIPT_CORRUPT naming a file that is not JSON, lacks a key, or holds an unknown outcome
    """
    out = []
    for path in sorted( ( pathlib.Path( data_dir ) / "receipts" ).glob( "shadow-*.json" ) ):
        try: receipt = json.loads( path.read_text( encoding="utf-8" ) )
        except ValueError as exc: raise CandidateError( AUDIT_RECEIPT_CORRUPT, f"{path.name}: {exc}" ) from exc
        if not isinstance( receipt, dict ) or any( key not in receipt for key in RECEIPT_FIELDS ) or receipt[ "outcome" ] not in OUTCOMES:
            raise CandidateError( AUDIT_RECEIPT_CORRUPT, f"{path.name}: wrong shape" )
        out.append( receipt )
    return out


def tally( receipts, language, generation ):
    """
    Count audits for one language and one vector-set generation.

    Ensures:
        - returns { audits, misses, inconclusive, bound, generation, language }
        - audits counts conclusive audits only, and the bound is audit_bound( misses, audits )
        - a receipt of another language or generation is not counted
    """
    held         = [ r for r in receipts if r[ "language" ] == language and r[ "generation" ] == generation ]
    inconclusive = sum( 1 for r in held if r[ "outcome" ] == "inconclusive" )
    misses       = sum( 1 for r in held if r[ "outcome" ] == "miss" )
    audits       = len( held ) - inconclusive
    return { "audits": audits, "misses": misses, "inconclusive": inconclusive, "bound": audit_bound( misses, audits ),
             "generation": generation, "language": language }


def bound_for_verdict( data_dir, language, generation ):
    """
    Give the figures a write-new verdict reports.

    Ensures:
        - returns tally( ... ) over the receipts in data_dir for that language and generation
    """
    return tally( load_receipts( data_dir ), language, generation )


def count_lookup( data_dir, today ):
    """
    Add one lookup to the day's count.

    Ensures:
        - appends one line to receipts/shadow-lookups-<today>.log and returns that day's count so far
    """
    path = _folder( data_dir, "receipts" ) / f"shadow-lookups-{today}.log"
    with open( path, "a", encoding="utf-8" ) as handle: handle.write( "1\n" )
    return len( path.read_text( encoding="utf-8" ).splitlines() )


def enqueue_if_sampled( data_dir, need, language, generation, index_sha, live, today, rate=SAMPLE_RATE ):
    """
    Count a served lookup and queue it for audit when it is in the sample.

    Requires:
        - live holds verdict and candidate_ids of the lookup that was served
        - need is the redacted need, because the queue file keeps its words so the sweep can read them

    Ensures:
        - the day's lookup count goes up by one, sampled or not
        - returns the queue id of a sampled lookup, or None
        - a sampled lookup is a file in shadow-pending/, and the same lookup queues once

    Raises:
        - CandidateError AUDIT_RATE_INVALID from is_sampled
    """
    count_lookup( data_dir, today )
    if not is_sampled( need, generation, rate ): return None
    key  = hashlib.sha256( f"{need_hash( need )}\n{generation}\n{index_sha}".encode( "utf-8" ) ).hexdigest()[ :16 ]
    item = { "id": key, "need": need, "language": language, "generation": generation, "index_sha": index_sha, "live": live, "queued_on": today,
             "attempts": 0 }
    _write_once( _folder( data_dir, "shadow-pending" ) / f"{key}.json", json.dumps( item, sort_keys=True ) + "\n" )
    return key


def run_pending( data_dir, sweep_fn, today, limit=None ):
    """
    Drain the audit queue through the full-sweep transport.

    Requires:
        - sweep_fn takes a need and returns { verdict, causal_ids }

    Ensures:
        - returns { audited, failed, corrupt, receipts }
        - each audited item leaves a receipt and its queue file is removed
        - an item whose sweep raises stays queued with its attempt count up by one, and counts as failed
        - a queue file that is not JSON, or lacks a queue field, is renamed to <name>.corrupt and counted, and the run goes on
        - a sweep answer that lacks verdict or causal_ids counts as a failure of that item, like a raised error
        - a temporary file of a write in progress is never read
        - at most limit items are taken, fewest attempts first, then oldest queued date, then queue id
    """
    queued, corrupt = [], 0
    for path in sorted( p for p in _folder( data_dir, "shadow-pending" ).glob( "*.json" ) if not p.name.startswith( TEMP_PREFIX ) ):
        try: item = json.loads( path.read_text( encoding="utf-8" ) )
        except ValueError: item = None
        if not _item_ok( item ):
            path.rename( path.with_name( path.name + ".corrupt" ) )
            corrupt += 1
            continue
        queued.append( ( item, path ) )
    queued.sort( key=lambda pair: ( pair[ 0 ][ "attempts" ], pair[ 0 ][ "queued_on" ], pair[ 0 ][ "id" ] ) )
    if limit is not None: queued = queued[ :limit ]
    receipts, failed = [], 0
    for item, path in queued:
        try:
            sweep   = sweep_fn( item[ "need" ] )
            receipt = audit_receipt( item[ "need" ], item[ "language" ], item[ "generation" ], item[ "index_sha" ], item[ "live" ], sweep, today )
        except Exception:                      # a transport failure or a malformed answer leaves the item queued, behind the fresh ones
            failed += 1
            temp = _temp_name( path )
            temp.write_text( json.dumps( dict( item, attempts=item[ "attempts" ] + 1 ), sort_keys=True ) + "\n", encoding="utf-8" )
            os.replace( temp, path )
            continue
        receipts.append( store_receipt( data_dir, receipt ) )
        os.remove( path )
    return { "audited": len( receipts ), "failed": failed, "corrupt": corrupt, "receipts": receipts }


def daily_volume( data_dir ):
    """
    Report the lookups counted per day and the audits stored per day.

    Ensures:
        - returns { date: { lookups, audits } } for every day that has a count or a receipt
    """
    days = {}
    for path in ( pathlib.Path( data_dir ) / "receipts" ).glob( "shadow-lookups-*.log" ):
        day = path.stem.removeprefix( "shadow-lookups-" )
        days.setdefault( day, { "lookups": 0, "audits": 0 } )[ "lookups" ] = len( path.read_text( encoding="utf-8" ).splitlines() )
    for receipt in load_receipts( data_dir ):
        days.setdefault( receipt[ "audited_on" ], { "lookups": 0, "audits": 0 } )[ "audits" ] += 1
    return days
