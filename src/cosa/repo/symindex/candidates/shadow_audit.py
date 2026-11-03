"""
The shadow audit: a full sweep on a small share of lookups, compared with the shortlist.

A lookup is sampled by a hash of its need and the vector-set generation, so the same lookup is always in or out.
A sampled lookup is queued, and a scheduled run drains the queue through a transport that does the full sweep.
Each audit leaves a receipt of its own kind in the same data folder, and the receipts give a bound on missed matches.
Nothing here makes a live call: the transport is passed in.
"""
import datetime
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
NO_MATCH       = "NO_MATCH"
OUTCOMES       = ( "miss", "ok", "inconclusive" )
ITEM_FIELDS    = ( "id", "need", "language", "generation", "index_sha", "live", "queued_on", "attempts", "known_miss", "exclude_id", "tie" )
TEMP_PREFIX    = ".tmp-"
RECEIPT_FIELDS = ( "kind", "id", "need_hash", "language", "generation", "index_sha", "live_verdict", "full_verdict",
                   "candidate_count", "causal_ids", "outcome", "missed_ids", "audited_on", "known_miss", "exclude_id", "tie" )
NEW_FIELD            = "known_miss"                                  # added after the first files were written; a file without it reads as False
LATER_FIELDS         = { "exclude_id": None, "tie": None }           # added after known_miss; a file without one reads as the default shown
OLD_ITEM_FIELDS      = tuple( f for f in ITEM_FIELDS if f != NEW_FIELD and f not in LATER_FIELDS )
OLD_RECEIPT_FIELDS   = tuple( f for f in RECEIPT_FIELDS if f != NEW_FIELD and f not in LATER_FIELDS )
TIES                 = ( "ruling", "heuristic" )
UNKNOWN_ENTRY        = "UNKNOWN_ENTRY"                               # the code a sweep refusal carries when the index lacks the excluded id
UNKNOWN_ENTRY_TRIES  = 3                                             # failed attempts after which an item that keeps answering it is dropped
WEEK_DAYS            = 7


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


def compare( live_verdict, full_verdict, causal_ids, candidate_ids, full_cause=None ):
    """
    Compare the full sweep with the shortlist the stage kept.

    Requires:
        - causal_ids is the full sweep's ids that made it a reuse or an extend, empty for any other verdict
        - candidate_ids is every id the stage kept
        - full_cause is the cause the full sweep reported, or None; the cause `NO_MATCH` is how the shipped policy says nothing matched

    Ensures:
        - returns "inconclusive" when the full sweep could not decide, so the audit is not counted; a sweep that found no match is decided, whether it says `NEW` (a policy before `no_new`) or `UNCERTAIN_READ_SOURCE` with the cause `NO_MATCH`
        - returns "inconclusive" when the full sweep matched but named no causal id, since that answer is malformed
        - returns "miss" when the full sweep matched and none of its causal ids was kept
        - returns "ok" otherwise, including when the judge disagreed with itself about a kept id
        - live_verdict does not change the outcome: the stage is judged on what it kept
    """
    no_match = full_verdict == "NEW" or ( full_verdict == "UNCERTAIN_READ_SOURCE" and full_cause == NO_MATCH )
    if full_verdict not in MATCHING and not no_match: return "inconclusive"
    if full_verdict in MATCHING and not causal_ids: return "inconclusive"
    if full_verdict in MATCHING and not set( causal_ids ) & set( candidate_ids ): return "miss"
    return "ok"


def _receipt_id( digest, generation, index_sha, exclude_id=None ):
    """Return the 16 character receipt id of a need, generation, index sha and excluded id."""
    text = f"{digest}\n{generation}\n{index_sha}" + ( f"\n{exclude_id}" if exclude_id is not None else "" )
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()[ :16 ]


def _receipt_shape_ok( receipt ):
    """Return True when a parsed receipt holds every receipt field and a known outcome."""
    return isinstance( receipt, dict ) and all( key in receipt for key in OLD_RECEIPT_FIELDS ) and receipt[ "outcome" ] in OUTCOMES


def audit_receipt( need, language, generation, index_sha, live, sweep, today, known_miss=False, exclude_id=None, tie=None ):
    """
    Build the receipt of one audit.

    Requires:
        - live holds verdict and candidate_ids of the lookup that was served
        - sweep holds verdict and causal_ids of the full sweep, and the cause when it has one
        - today is an ISO date string
        - known_miss is True for an audit of a lookup behind a found duplicate, False for a random-sample audit
        - exclude_id is the id the sweep left out, or None; tie is "ruling" or "heuristic" for a known-miss audit, else None

    Ensures:
        - returns a dict whose keys are RECEIPT_FIELDS, with known_miss, exclude_id and tie as given
        - the id is a 16 character hash of the need hash, generation, index sha and excluded id, so a repeat is one receipt
        - the need's words are not kept, only its hash
    """
    candidates = set( live[ "candidate_ids" ] )
    outcome    = compare( live[ "verdict" ], sweep[ "verdict" ], sweep[ "causal_ids" ], candidates, sweep[ "cause" ] if "cause" in sweep else None )
    digest     = need_hash( need )
    rid        = _receipt_id( digest, generation, index_sha, exclude_id )
    missed     = sorted( set( sweep[ "causal_ids" ] ) - candidates ) if outcome == "miss" else []
    return { "kind": KIND, "id": rid, "need_hash": digest, "language": language, "generation": generation, "index_sha": index_sha,
             "live_verdict": live[ "verdict" ], "full_verdict": sweep[ "verdict" ], "candidate_count": len( candidates ),
             "causal_ids": sorted( sweep[ "causal_ids" ] ), "outcome": outcome, "missed_ids": missed, "audited_on": today, "known_miss": known_miss, "exclude_id": exclude_id, "tie": tie }


def _folder( data_dir, name ):
    """Return one subfolder of the data folder, made if it is missing."""
    path = pathlib.Path( data_dir ) / name
    path.mkdir( parents=True, exist_ok=True )
    return path


def _temp_name( path ):
    """Name a write's temporary file so no *.json listing sees it."""
    return path.with_name( f"{TEMP_PREFIX}{os.getpid()}-{path.name}.part" )


def _item_ok( item ):
    """
    Return True when a queue file holds every queue field.

    Ensures:
        - the id and the queued date are text, so the drain can sort on them
        - a file written before known_miss, exclude_id or tie existed is accepted
        - a known_miss that is not True or False, an exclude_id that is not text or None, and a tie that is not ruling, heuristic or None are not
    """
    return isinstance( item, dict ) and all( key in item for key in OLD_ITEM_FIELDS ) and isinstance( item[ "attempts" ], int ) \
           and isinstance( item[ "live" ], dict ) and isinstance( item[ "id" ], str ) and isinstance( item[ "queued_on" ], str ) \
           and isinstance( item.get( NEW_FIELD, False ), bool ) and isinstance( item.get( "exclude_id" ), ( str, type( None ) ) ) and item.get( "tie" ) in ( None, *TIES )


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
        - CandidateError AUDIT_RECEIPT_CORRUPT when the file already there is not JSON or is not a receipt
    """
    path = _folder( data_dir, "receipts" ) / f"shadow-{receipt[ 'id' ]}.json"
    _write_once( path, json.dumps( receipt, sort_keys=True ) + "\n" )
    return _read_receipt_file( path )


def _read_receipt_file( path ):
    """
    Read one receipt file.

    Ensures:
        - a receipt written before known_miss, exclude_id or tie existed comes back with the defaults: False, None, None

    Raises:
        - CandidateError AUDIT_RECEIPT_CORRUPT when the file is not JSON or is not a receipt
    """
    try: receipt = json.loads( path.read_text( encoding="utf-8" ) )
    except ValueError as exc: raise CandidateError( AUDIT_RECEIPT_CORRUPT, f"{path.name}: {exc}" ) from exc
    if not _receipt_shape_ok( receipt ): raise CandidateError( AUDIT_RECEIPT_CORRUPT, f"{path.name}: wrong shape" )
    return { NEW_FIELD: False, **LATER_FIELDS, **receipt }


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
        out.append( _read_receipt_file( path ) )
    return out


def tally( receipts, language, generation, known_miss=False, tie=None ):
    """
    Count audits for one language and one vector-set generation.

    Ensures:
        - returns { audits, misses, inconclusive, bound, generation, language }
        - audits counts conclusive audits only, and the bound is audit_bound( misses, audits )
        - a receipt of another language or generation is not counted
        - only receipts whose known_miss equals the argument are counted, so the random-sample bound is never mixed with the audits of found duplicates
        - with tie given, only known-miss receipts of that tie are counted, so a heuristic tie has its own figures
    """
    held         = [ r for r in receipts if r[ "language" ] == language and r[ "generation" ] == generation and r[ NEW_FIELD ] == known_miss and ( tie is None or r[ "tie" ] == tie ) ]
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


def enqueue_pending( data_dir, need, language, generation, index_sha, live, today, known_miss=False, exclude_id=None, tie=None ):
    """
    Put one lookup in the audit queue, without counting it and without sampling.

    Requires:
        - live holds verdict and candidate_ids of the lookup that was served
        - need is the redacted need, because the queue file keeps its words so the sweep can read them

    Ensures:
        - returns the queue id, a hash of the need, generation and index sha, and of the excluded id when there is one
        - a file in shadow-pending/ holds the item with attempts 0 and the known_miss, exclude_id and tie given, and the same lookup queues once
        - the same lookup queued with and without an excluded id is two items, because the sweeps ask different questions
        - a known-miss call for a lookup already queued as a random-sample item upgrades that item to known-miss, keeping its attempts, so it drains first
        - the day's lookup count does not change
    """
    key  = _receipt_id( need_hash( need ), generation, index_sha, exclude_id )
    item = { "id": key, "need": need, "language": language, "generation": generation, "index_sha": index_sha, "live": live, "queued_on": today,
             "attempts": 0, "known_miss": known_miss, "exclude_id": exclude_id, "tie": tie }
    path = _folder( data_dir, "shadow-pending" ) / f"{key}.json"
    if not _write_once( path, json.dumps( item, sort_keys=True ) + "\n" ) and known_miss: _mark_known_miss( path, tie )
    return key


def _mark_known_miss( path, tie ):
    """
    Raise a queued item to known-miss when a found duplicate points at the same lookup.

    Ensures:
        - an item that is not yet known-miss is rewritten whole with known_miss True and the tie given, its attempts kept
        - an item already known-miss, one that is not JSON, and one that is not an item are left as they are
    """
    try: held = json.loads( path.read_text( encoding="utf-8" ) )
    except ValueError: return
    if not _item_ok( held ) or held.get( NEW_FIELD, False ): return
    temp = _temp_name( path )
    temp.write_text( json.dumps( { **held, NEW_FIELD: True, "tie": tie }, sort_keys=True ) + "\n", encoding="utf-8" )
    os.replace( temp, path )


def enqueue_if_sampled( data_dir, need, language, generation, index_sha, live, today, rate=SAMPLE_RATE ):
    """
    Count a served lookup and queue it for audit when it is in the sample.

    Requires:
        - live holds verdict and candidate_ids of the lookup that was served
        - need is the redacted need, because the queue file keeps its words so the sweep can read them

    Ensures:
        - the day's lookup count goes up by one, sampled or not
        - returns the queue id of a sampled lookup, or None
        - a sampled lookup is a file in shadow-pending/ with known_miss False, and the same lookup queues once

    Raises:
        - CandidateError AUDIT_RATE_INVALID from is_sampled
    """
    count_lookup( data_dir, today )
    if not is_sampled( need, generation, rate ): return None
    return enqueue_pending( data_dir, need, language, generation, index_sha, live, today )


def audits_in_week( data_dir, today ):
    """
    Count the audits stored in the seven days that end on today.

    Requires:
        - today is an ISO date string

    Ensures:
        - returns the number of receipts whose audited_on is from six days before today to today, both included
    """
    end   = datetime.date.fromisoformat( today )
    first = end - datetime.timedelta( days=WEEK_DAYS - 1 )
    return sum( v[ "audits" ] for day, v in daily_volume( data_dir ).items() if first <= datetime.date.fromisoformat( day ) <= end )


def run_pending( data_dir, sweep_fn, today, limit=None, max_tokens=None, pass_language=False, weekly_cap=None ):
    """
    Drain the audit queue through the full-sweep transport.

    Requires:
        - sweep_fn takes a need and returns { verdict, causal_ids }, and the cause when the verdict is uncertain

    Ensures:
        - returns { audited, failed, corrupt, dropped, receipts }
        - each audited item leaves a receipt and its queue file is removed
        - an item whose sweep raises stays queued with its attempt count up by one, and counts as failed
        - a queue file that is not JSON, lacks a queue field, or holds an id or queued date that is not text, is renamed to <name>.corrupt and counted, and the run goes on
        - an item whose receipt file is already there and damaged counts as failed like a raised sweep, stays queued, and the run goes on
        - that check comes before the sweep, so a damaged receipt file never spends a sweep
        - a sweep answer that lacks verdict or causal_ids counts as a failure of that item, like a raised error
        - a temporary file of a write in progress is never read
        - at most limit items are taken, known-miss items first, then fewest attempts, then oldest queued date, then queue id
        - an item whose sweep raises a CandidateError whose detail is exactly UNKNOWN_ENTRY, the code the sweep gives, stays queued like any failure, until its third failed attempt; then its file is removed and it counts as dropped
        - an item queued before known_miss existed is read as known_miss False
        - with weekly_cap, the run stops before the audit that would make the audits stored in the seven days ending today pass the cap; the rest stay queued
        - with pass_language the sweep is called as sweep_fn( need, language ), else as sweep_fn( need )
        - an item with an exclude_id adds the keyword exclude_id=<that id> to the call, so the sweep leaves the duplicate's own definition out; an item without one is called as before
        - with max_tokens, each sweep answer must carry a whole-number tokens count (a sweep without one fails like a raised error), and the run
          stops before a sweep when the tokens spent so far plus the largest sweep seen would pass max_tokens; the rest stay queued
        - with max_tokens or weekly_cap the result also holds stopped_by, "ceiling" or "weekly_cap" when the run stopped for that reason, else None; with max_tokens it also holds spent_tokens
        - without either the result keeps its five keys
    """
    queued, corrupt = [], 0
    for path in sorted( p for p in _folder( data_dir, "shadow-pending" ).glob( "*.json" ) if not p.name.startswith( TEMP_PREFIX ) ):
        try: item = json.loads( path.read_text( encoding="utf-8" ) )
        except ValueError: item = None
        if not _item_ok( item ):
            path.rename( path.with_name( path.name + ".corrupt" ) )
            corrupt += 1
            continue
        queued.append( ( { NEW_FIELD: False, **LATER_FIELDS, **item }, path ) )
    queued.sort( key=lambda pair: ( not pair[ 0 ][ NEW_FIELD ], pair[ 0 ][ "attempts" ], pair[ 0 ][ "queued_on" ], pair[ 0 ][ "id" ] ) )
    if limit is not None: queued = queued[ :limit ]
    receipts, failed, dropped, spent, biggest, stopped = [], 0, 0, 0, 0, None
    room = None if weekly_cap is None else weekly_cap - audits_in_week( data_dir, today )
    for item, path in queued:
        if room is not None and len( receipts ) >= room:
            stopped = "weekly_cap"
            break
        if max_tokens is not None and spent + max( biggest, 1 ) > max_tokens:
            stopped = "ceiling"
            break
        try:
            held = _folder( data_dir, "receipts" ) / f"shadow-{_receipt_id( need_hash( item[ 'need' ] ), item[ 'generation' ], item[ 'index_sha' ], item[ 'exclude_id' ] )}.json"
            if held.exists(): _read_receipt_file( held )                       # a damaged receipt file fails the item before any sweep is spent
            extra   = { "exclude_id": item[ "exclude_id" ] } if item[ "exclude_id" ] is not None else {}
            sweep   = sweep_fn( item[ "need" ], item[ "language" ], **extra ) if pass_language else sweep_fn( item[ "need" ], **extra )
            tokens  = sweep[ "tokens" ] if max_tokens is not None else 0
            if type( tokens ) is not int or tokens < 0: raise ValueError( f"tokens {tokens!r}" )
            receipt = audit_receipt( item[ "need" ], item[ "language" ], item[ "generation" ], item[ "index_sha" ], item[ "live" ], sweep, today, item[ NEW_FIELD ], item[ "exclude_id" ], item[ "tie" ] )
            stored  = store_receipt( data_dir, receipt )
        except Exception as exc:               # a transport failure, a malformed answer or a damaged receipt file leaves the item queued, behind the fresh ones
            failed += 1
            if isinstance( exc, CandidateError ) and exc.detail == UNKNOWN_ENTRY and item[ "attempts" ] + 1 >= UNKNOWN_ENTRY_TRIES:
                os.remove( path )
                dropped += 1
                continue
            temp = _temp_name( path )
            temp.write_text( json.dumps( dict( item, attempts=item[ "attempts" ] + 1 ), sort_keys=True ) + "\n", encoding="utf-8" )
            os.replace( temp, path )
            continue
        receipts.append( stored )
        os.remove( path )
        spent, biggest = spent + tokens, max( biggest, tokens )
    out = { "audited": len( receipts ), "failed": failed, "corrupt": corrupt, "dropped": dropped, "receipts": receipts }
    if max_tokens is not None: out.update( spent_tokens=spent )
    if max_tokens is not None or weekly_cap is not None: out.update( stopped_by=stopped )
    return out


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
