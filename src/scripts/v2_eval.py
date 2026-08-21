"""
CJ Flow v2 eval harness — the two-pass run that produces the plan's headline metrics.

EXECUTOR: AI
    This harness is NOT Rick's to run. Its definition of done is "a report from a
    two-pass run nobody had to babysit" (plan §DoD, cascade ruling R-D9), so leaving
    it to a human to type the CLI defeats the acceptance criterion in the same
    document. It is owned by the AI and submitted on a schedule.

VENUE: :8000, SCHEDULED, post-midnight off-peak (12 AM - 9 AM EDT)
    It spends real inference and needs a live server, so it runs on the test server
    via `POST /api/test-suite/submit` in the off-peak window — NEVER on :7999, NEVER
    via curl, NEVER side-door injected (cascade ruling R-D5, Lupin venue rules).

What it does (plan §9, §7, §6a):
    Two passes over the same corpus. COLD measures router accuracy + first-response
    latency against the existing cache; WARM, run immediately after, measures the
    cache-hit rate and the cold->warm latency delta. A single pass cannot produce the
    cache-hit number. Each request runs `speak=false, interactive=false` so the whole
    flow executes with TTS dispatch skipped and nothing ever blocks.

    The corpus (`src/conf/training/agent-router-simple-commands.json`) maps each
    command to a file of one-utterance-per-line data; the JSON key is the expected
    command, so intent-routing accuracy comes out for free.

Metrics (from the §8 response payloads, cross-checked against the authoritative
`io/v2-flow/trace-YYYY-MM-DD.jsonl`): cache_hit_rate, cache_candidate_rate,
replay_failure_rate, router_error_rate, extract_error_rate, agent_error_rate,
p50/p95 first-useful latency, routing accuracy, the would-be-wrong oracle (R-C2),
and the §6a cache-hit-rate-vs-threshold table.

Dependency: the live path needs Unit D (`routers/v2_ask.py`, `flow.py`) landed. This
module is written to the §8 endpoint contract and unit-tested against it now; the
live wiring is a matter of the server answering `POST /api/v2/ask` per that contract.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: this script may run before `cosa` is importable, so resolve the
# project root from LUPIN_ROOT and put src/ on the path before importing cosa.
# ---------------------------------------------------------------------------
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if _LUPIN_ROOT is None:                    # pragma: no cover - bootstrap guard; LUPIN_ROOT is set in every runtime and test
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
_SRC_PATH = os.path.join( _LUPIN_ROOT, "src" )
if _SRC_PATH not in sys.path:              # pragma: no cover - bootstrap: src-path state depends on import order
    sys.path.insert( 0, _SRC_PATH )

import cosa.utils.util as du   # noqa: E402
from cosa.rest.v2.registry import resolve   # noqa: E402  — the table the CRUD exclusion reads

# The provenance-stamp contract lives in paired_eval (the paired orchestrator, which imports
# neither arm, so there is no cycle). v2's main stamps make_provenance over the sample it
# measured, so the paired gate can bind this arm to the v1 arm by signature.
from paired_eval import make_provenance   # noqa: E402

# The snapshot-isolation guard is the neutral home both arms reach acyclically (it imports
# neither arm). v2's per-arm clean-step composes its config cross-check + measurement-db
# assertion; v2 -> guard is safe (v1 -> v2 -> guard is acyclic).
from eval_isolation_guard import (   # noqa: E402
    assert_measurement_db,
    require_config_table_matches_write_target,
)


# ---------------------------------------------------------------------------
# Contract vocabulary — the §8 `path` and `route_reason` strings this harness
# reads. Kept as named constants so wiring to Unit D is a single edit if the
# server reports a value under a different spelling.
# ---------------------------------------------------------------------------
PATH_REPLAY       = "replay"
PATH_AGENT        = "agent"
PATH_RECEPTIONIST = "receptionist"
PATH_NEEDS_INPUT  = "needs_input"

ROUTE_AGENT_ERROR   = "agent_error"
ROUTE_ROUTER_ERROR  = "router_error"
ROUTE_EXTRACT_ERROR = "extract_error"
ROUTE_REPLAY_ERROR  = "replay_error"

# The four route reasons that mean the work did NOT complete. A 200 carrying one of these
# is a REPORTED FAILURE, not a success — see is_completed_ok below.
ROUTE_ERROR_REASONS = frozenset( {
    ROUTE_AGENT_ERROR, ROUTE_ROUTER_ERROR, ROUTE_EXTRACT_ERROR, ROUTE_REPLAY_ERROR,
} )


def is_completed_ok( status_code, payload ):
    """
    Did this call COMPLETE the work — the same question v1's arm is made to answer.

    🔴 WHY THIS EXISTS (row d8d019f6, 2026-08-20). `ok` was `status_code == 200` and the
    payload was never inspected, while v1_eval_arm.py:314 required a job_id, an OBSERVED
    terminal completion, a completed_ts, and a computable span. So v2 was graded on "did
    the server answer" and v1 on "did the work finish end to end" — two different questions
    whose failure rates were then compared as though they were one. A v2 response of 200
    carrying route_reason="agent_error" counted as a SUCCESS.

    Requires:
        - status_code is the HTTP status; payload is the decoded body (or falsy)

    Ensures:
        - False unless the status is 200 (unchanged)
        - False when the body reports one of ROUTE_ERROR_REASONS — the server answered,
          and what it said was that the work failed
        - True otherwise, INCLUDING a body with no route_reason at all: absence of a
          reported error is not evidence of one, and this predicate must not invent
          failures v1 would not have counted either
    """
    if status_code != 200: return False
    if not isinstance( payload, dict ): return False
    return payload.get( "route_reason" ) not in ROUTE_ERROR_REASONS


# The mark whose offset from the anchor is "latency to first useful response".
FIRST_USEFUL_MARK = "t_first_useful"

# Read budget for one POST /api/v2/ask. The v2 arm's ask is a SYNCHRONOUS full Phi-4
# inference — ~22s typical, 34-67s observed, and past 120s late in a long run when the
# model server is under contention. The n=60 closer ts-1686ce29 ran 3h02m and then died
# on a ReadTimeoutError at the old 120s limit, BEFORE either arm's artifact was dumped,
# so the whole run was unrecoverable. 300s is the budget; LUPIN_V2_ASK_TIMEOUT_SECONDS
# raises or lowers it for a run without a code edit. (Row d8d019f6.)
ASK_READ_TIMEOUT_SECONDS = 300.0

# §6a: the decision floors the threshold table reports, choosing the floor from
# data rather than re-running the corpus once per candidate value.
THRESHOLD_FLOORS = ( 100.0, 98.0, 95.0, 90.0 )

# This harness measures ONE arm (v2). It has no v1 baseline, so it CANNOT produce
# the §1 go/no-go verdict (INVEST / STOP / SPLIT) — that is the paired v1-vs-v2
# harness. This banner is printed at the top of every report so a v2-only cache-hit
# or latency number is never mistaken for the decision it is a down-payment on.
# (Cheech, 2026-08-14, thread 4fb7f475.)
NOT_GONOGO_BANNER = (
    "> ⚠️ **v2-only — NOT the go/no-go decision table.** No v1 baseline runs here, so "
    "these numbers report v2's own cache-hit rate and latency distribution and DO NOT "
    "decide INVEST / STOP / SPLIT (§1). The paired v1-vs-v2 harness produces that verdict."
)

# The would-be-wrong caveat, kept VERBATIM (cascade ruling R-C2): command-match
# is a lower bound — same command at a different location still scores "right" —
# so this column under-counts. A semantic oracle is phase 2.
WOULD_BE_WRONG_CAVEAT = (
    "Command-match is a LOWER BOUND (same command, different location still "
    "scores right), so it under-counts; a semantic oracle is phase 2."
)

# Named corpora. "simple" is manifest-driven; "weather" is the two-utterance
# argument-chain case that proves extract-and-park on every pass.
_CORPUS_MANIFESTS = {
    "simple" : "/src/conf/training/agent-router-simple-commands.json",
}
_WEATHER_COMMAND = "agent router go to weather"
_WEATHER_PAIRS   = (
    ( "what's the weather in Tokyo", _WEATHER_COMMAND ),
    ( "what's the weather",          _WEATHER_COMMAND ),
)


class EvalIntegrityError( RuntimeError ):
    """Raised when a run's own integrity properties fail — a lying run, not a low score.

    A metric harness that reports over responses whose traces never landed, or over a
    run where the router was dead, is worse than useless: it manufactures a confident
    green. This is raised loudly so such a run stops instead of publishing a number.
    """


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------
def is_utterance_line( line: str ) -> bool:
    """
    True iff `line` carries an utterance rather than a comment or blank.

    Requires:
        - line is a string.

    Ensures:
        - returns False for a line that is empty/whitespace-only or begins
          (after stripping) with '#'.
        - returns True otherwise.
    """
    stripped = line.strip()
    if stripped == "":         return False
    if stripped.startswith( "#" ): return False
    return True


def load_corpus(
    name         : str,
    project_root : Optional[ str ] = None,
    limit        : Optional[ int ] = None,
) -> List[ Tuple[ str, str ] ]:
    """
    Load a named corpus as (utterance, expected_command) pairs.

    Requires:
        - name is a registered corpus ("simple" or "weather").
        - limit, when given, is a positive integer bounding utterances PER command.

    Ensures:
        - "weather" returns the two-utterance argument-chain pairs.
        - "simple" reads the JSON manifest, then each command's data file, keeping
          only utterance lines (is_utterance_line), pairing each with its JSON key.
        - returns a non-empty list.

    Raises:
        - ValueError if name is unknown or the loaded corpus is empty.
    """
    if name == "weather":
        pairs = list( _WEATHER_PAIRS )
        return _apply_limit( pairs, limit )

    if name not in _CORPUS_MANIFESTS:
        raise ValueError( f"unknown corpus '{name}' — known: {sorted( _CORPUS_MANIFESTS )} + 'weather'" )

    root         = project_root if project_root is not None else du.get_project_root()
    manifest_path = root + _CORPUS_MANIFESTS[ name ]
    with open( manifest_path ) as handle:
        manifest = json.load( handle )

    pairs: List[ Tuple[ str, str ] ] = []
    for command, rel_path in manifest.items():
        data_path = root + rel_path
        with open( data_path ) as handle:
            lines = [ line.strip() for line in handle if is_utterance_line( line ) ]
        if limit is not None:
            lines = lines[ :limit ]
        for utterance in lines:
            pairs.append( ( utterance, command ) )

    if not pairs:
        raise ValueError( f"corpus '{name}' loaded zero utterances — refusing to run on an empty corpus" )
    return pairs


def _apply_limit(
    pairs : List[ Tuple[ str, str ] ],
    limit : Optional[ int ],
) -> List[ Tuple[ str, str ] ]:
    """Return the first `limit` pairs per command, or all pairs when limit is None."""
    if limit is None:
        return pairs
    seen : Dict[ str, int ] = {}
    kept : List[ Tuple[ str, str ] ] = []
    for utterance, command in pairs:
        count = seen.get( command, 0 )
        if count < limit:
            kept.append( ( utterance, command ) )
            seen[ command ] = count + 1
    return kept


def stratified_sample(
    pairs         : List[ Tuple[ str, str ] ],
    n_per_command : int,
    seed          : int,
) -> Tuple[ List[ Tuple[ str, str ] ], Dict[ str, Any ] ]:
    """
    A seeded, per-command random sample of the corpus (the paired-harness sampler).

    Unlike `_apply_limit` (first-N per command — order-dependent, no randomness), this
    draws a REPRODUCIBLE random sample of `n_per_command` utterances per command so the
    biggest command cannot dominate a "system-wide" number and the smallest ones are not
    starved (plan §5, §1.4a). The sample is a pure function of (utterance set, n, seed):
    each command's utterances are sorted before sampling, so the source file's line order
    does not change which utterances are chosen.

    Requires:
        - pairs is a non-empty list of (utterance, expected_command).
        - n_per_command is a positive integer (the target per-command sample size).
        - seed is an integer, recorded in the report so the exact sample reproduces.

    Ensures:
        - each command contributes min( n_per_command, available ) utterances, chosen with
          a `random.Random( seed )` draw over that command's sorted utterance set.
        - commands appear in first-appearance order; a command with fewer than
          n_per_command utterances contributes all of them and is listed in
          manifest["under_quota"] so the report names what fell short (never a silent cap).
        - returns ( sampled_pairs, manifest ); manifest carries seed, n_per_command,
          per-command {kept, available}, the under_quota command list, and total_kept.

    Raises:
        - ValueError if pairs is empty or n_per_command < 1.
    """
    if not pairs:
        raise ValueError( "stratified_sample: refusing to sample an empty corpus" )
    if n_per_command < 1:
        raise ValueError( "stratified_sample: n_per_command must be >= 1" )

    order   : List[ str ]              = []
    grouped : Dict[ str, List[ str ] ] = {}
    for utterance, command in pairs:
        if command not in grouped:
            grouped[ command ] = []
            order.append( command )
        grouped[ command ].append( utterance )

    rng         = random.Random( seed )
    sampled     : List[ Tuple[ str, str ] ]      = []
    per_command : Dict[ str, Dict[ str, int ] ]  = {}
    under_quota : List[ str ]                     = []
    for command in order:
        utterances = sorted( grouped[ command ] )          # order-independent sample base
        available  = len( utterances )
        keep       = min( n_per_command, available )
        chosen     = rng.sample( utterances, keep )        # seeded, reproducible
        for utterance in chosen:
            sampled.append( ( utterance, command ) )
        per_command[ command ] = { "kept": keep, "available": available }
        if available < n_per_command:
            under_quota.append( command )

    manifest = {
        "seed"          : seed,
        "n_per_command" : n_per_command,
        "per_command"   : per_command,
        "under_quota"   : under_quota,
        "total_kept"    : len( sampled ),
    }
    return sampled, manifest


# ---------------------------------------------------------------------------
# Per-request field accessors — one seam each, so a contract-field rename is a
# single edit rather than a scatter of `.get()` calls across the metrics.
# ---------------------------------------------------------------------------
def response_path( record: Dict[ str, Any ] ) -> Optional[ str ]:
    """The §8 `path` for a record, or None when the request did not return 200."""
    if not record[ "ok" ]:
        return None
    return record[ "payload" ].get( "path" )


def response_route_reason( record: Dict[ str, Any ] ) -> Optional[ str ]:
    """The §8 `route_reason` for a record, or None when the request did not return 200."""
    if not record[ "ok" ]:
        return None
    return record[ "payload" ].get( "route_reason" )


def reported_route_reason( record: Dict[ str, Any ] ) -> Optional[ str ]:
    """
    The `route_reason` a 200 CARRIES, whether or not the work completed.

    🔴 THE SECOND LAYER OF THE STRUCTURAL ZERO (row d8d019f6, 2026-08-20). Moving the error
    rates onto an `answered` denominator was not enough, because response_route_reason
    GATES ON `ok` and returns None for exactly the records that carry an error. Once
    is_completed_ok made `ok` mean "the work completed", the accessor stopped being able to
    read the errored records at all — so the rates still came out 0.0 with a correct
    denominator. The instrument refused to look at its own evidence at two independent
    layers, and either one alone was enough to silence it.

    response_route_reason keeps its ok-gated meaning for the cache/candidate views, which
    legitimately describe completed work only. This is its peer for the error views.

    Ensures:
        - returns the body's route_reason for any request that returned 200, errored or not
        - returns None for a non-200 (no body was answered) or an unparseable payload
    """
    if record.get( "status_code" ) != 200:
        return None
    payload = record.get( "payload" )
    return payload.get( "route_reason" ) if isinstance( payload, dict ) else None


def response_similarity( record: Dict[ str, Any ] ) -> Optional[ float ]:
    """The §8 `similarity` (best score) for a record, or None when absent/failed."""
    if not record[ "ok" ]:
        return None
    value = record[ "payload" ].get( "similarity" )
    return None if value is None else float( value )


def _crud_agents_enabled() -> bool:
    """
    The live value of `crud for dataframes agents enabled` (lupin-app.ini:1915).

    Read, not asserted. The reader used to pass crud_enabled=True into resolve(),
    which is the CONFIGURED value today and not the same statement — with the flag
    off, calendar and todo do not fork, they ARE snapshotable, and excluding them
    would drop real cache misses out of the denominator and report a rate that
    flatters the cache.

    Same key and same missing-means-enabled default the v1 queue uses
    (todo_fifo_queue._crud_agents_enabled) and the flow's construction site reads,
    so all three surfaces cannot disagree about which agents ran.

    A missing or unreadable config answers True, matching that default rather than
    inventing a quieter one.
    """
    try:
        from cosa.config.configuration_manager import ConfigurationManager
        value = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
            "crud for dataframes agents enabled", default="true"
        )
    except Exception:
        return True
    return str( value ).strip().lower() == "true"


def _is_cacheable_command( command: Optional[ str ], crud_enabled: Optional[ bool ]=None ) -> bool:
    """
    Could a request that routed to `command` ever have been a cache hit?

    Asks the registry, not a hand-list: a command whose spec says snapshotable=False
    is never written back, so it can never replay. With the CRUD flag ON that is the
    forked calendar and todo pair plus weather; with it OFF it is weather alone.

    An unknown or non-conversational command answers True — it is not excluded by
    THIS rule, and silently dropping it here would hide it from the denominator for
    a reason that has nothing to do with caching.

    crud_enabled is read from config when not supplied; the parameter exists so a
    test can state the flag instead of depending on the machine's INI.
    """
    if command is None:
        return True
    if crud_enabled is None:
        crud_enabled = _crud_agents_enabled()
    spec = resolve( command, crud_enabled=crud_enabled )
    if spec is None:
        return True
    return spec.snapshotable


def matched_command( record: Dict[ str, Any ] ) -> Optional[ str ]:
    """
    The command attributed to a replayed snapshot (the §8 `command` on a replay).

    Seam for the R-C2 would-be-wrong oracle. On the replay path no router runs, so
    `command` reports the matched snapshot's routing command; if Unit D surfaces it
    under a different field, this is the one line to change.
    """
    if not record[ "ok" ]:
        return None
    return record[ "payload" ].get( "command" )


def first_useful_ms( record: Dict[ str, Any ] ) -> Optional[ float ]:
    """The latency to first useful response in ms, or None when unstamped/failed."""
    if not record[ "ok" ]:
        return None
    timings = record[ "payload" ].get( "timings_ms" ) or {}
    value   = timings.get( FIRST_USEFUL_MARK )
    return None if value is None else float( value )


def response_trace_id( record: Dict[ str, Any ] ) -> Optional[ str ]:
    """The §8 `trace_id` for a record, or None when the request did not return 200."""
    if not record[ "ok" ]:
        return None
    return record[ "payload" ].get( "trace_id" )


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------
def percentile( values: Sequence[ float ], pct: float ) -> Optional[ float ]:
    """
    The linear-interpolated percentile of `values`.

    Requires:
        - values is a sequence of numbers; 0 <= pct <= 100.

    Ensures:
        - returns None for an empty sequence.
        - returns the single value (as float) when len == 1.
        - otherwise interpolates between the two ranks bracketing pct.
    """
    if not values:
        return None
    ordered = sorted( values )
    if len( ordered ) == 1:
        return round( float( ordered[ 0 ] ), 3 )
    rank = ( pct / 100.0 ) * ( len( ordered ) - 1 )
    low  = int( rank )
    high = min( low + 1, len( ordered ) - 1 )
    frac = rank - low
    return round( ordered[ low ] + ( ordered[ high ] - ordered[ low ] ) * frac, 3 )


def _rate( numerator: int, denominator: int ) -> Optional[ float ]:
    """The fraction numerator/denominator rounded to 4 places, or None when denominator is 0."""
    if denominator == 0:
        return None
    return round( numerator / denominator, 4 )


def route_matches( actual: Optional[ str ], expected: str ) -> bool:
    """
    True iff the router's chosen command matches the utterance's expected command.

    Requires:
        - expected is the corpus JSON key for the utterance.

    Ensures:
        - returns False when actual is None.
        - compares case-insensitively after stripping surrounding whitespace.
    """
    if actual is None:
        return False
    return actual.strip().lower() == expected.strip().lower()


def compute_metrics( records: List[ Dict[ str, Any ] ],
                     mappable_commands: Optional[ Sequence[ str ] ] = None ) -> Dict[ str, Any ]:
    """
    The full metric set for one pass over the corpus.

    Requires:
        - records is a list of per-request dicts, each {utterance, expected_command,
          ok, status_code, payload}.
        - mappable_commands is the set of routing commands the arms CAN score — the
          same set v1_eval_arm.compute_v1_metrics excludes on. None means no
          restriction (every utterance eligible), which is the pre-2026-08-20
          behaviour and is retained only for callers that do not score routing.

    Ensures:
        - returns a dict of counts, rates (None when the denominator is 0), latency
          percentiles, routing accuracy, the would-be-wrong count, and by_path counts.
        - a rate's denominator is the count of completed requests, so a failed
          call can never inflate a numerator.
        - routing_accuracy is scored over ELIGIBLE ok records only, and the exclusion
          is published as routing_eligible_n / routing_excluded_n /
          routing_excluded_share so it is auditable rather than silent.

    🔴 WHY mappable_commands EXISTS (row d8d019f6, 2026-08-20). v1_eval_arm.py:440 says
    in as many words "The v2 arm must exclude the SAME utterances", and this module had
    ZERO occurrences of the word "eligible". v1 excluded 40% of the corpus from its
    routing denominator as unmappable; v2 excluded nothing and scored those same
    utterances as routing misses. The two routing-accuracy numbers were then printed
    side by side as though they answered one question.
    """
    n        = len( records )
    ok       = [ r for r in records if r[ "ok" ] ]
    n_ok     = len( ok )

    cache_hits      = [ r for r in ok if response_path( r ) == PATH_REPLAY ]
    cache_candidates = [ r for r in ok if response_similarity( r ) is not None ]

    # THE CRUD EXCLUSION LIVES HERE NOW, not in the routing table (step 2b, Rick
    # 2026-08-21). It used to be enforced by pinning resolve() to the non-CRUD class
    # so forked calendar and todo traffic never reached a CRUD agent — a REPORTING
    # constraint shaping what every request routed through. The fork moved into
    # resolve(); this is the reader that has to know about it.
    #
    # The rule is the honest one: the denominator is requests that COULD have been a
    # cache hit. A command the writer refuses to serialize can never replay, so
    # counting it as a miss reports a cache failure that did not happen. That covers
    # CRUD-forked calendar and todo AND weather, which was never snapshotable either
    # — same reason, stated once.
    # ⚠️ A RECORD THAT ACTUALLY REPLAYED IS CACHEABLE BY DEMONSTRATION, whatever the
    # table says. Excluding on the table alone dropped weather replays out of the
    # DENOMINATOR while they stayed in the numerator, so cache_hit_rate went None on a
    # weather-only run — and guard_cold_start, which raises when a "cold" pass reports
    # any replay at all, stopped seeing a pre-warmed store. Caught by
    # test_main_cold_guard_raises_on_warm_cold, not by reasoning about the rule.
    #
    # `snapshotable` says what the WRITER will write from here on. It cannot say what
    # the store already holds.
    crud_enabled = _crud_agents_enabled()     # read ONCE per run, not once per record
    cacheable = [
        r for r in ok
        if response_path( r ) == PATH_REPLAY or _is_cacheable_command( matched_command( r ), crud_enabled )
    ]

    # ERROR RATES ARE COUNTED OVER EVERY ANSWERED REQUEST, NOT OVER `ok` (row d8d019f6,
    # 2026-08-20). They used to read `ok`, which was harmless while `ok` meant "the server
    # answered" - an errored 200 was still in that set, so it could still be counted. The
    # moment is_completed_ok made `ok` mean "the work completed", every errored record left
    # the set these rates measure over, and all four went STRUCTURALLY ZERO: they could no
    # longer report the thing they are named for.
    #
    # ts-e0311090 is the receipt. The artifact published replay_failure_rate 0.0 while the
    # raw records show 42 of 100 warm responses returning replay_error and 5 agent_error -
    # every one an HTTP 200. A rate of 0.0 read as "replay is healthy" while replay was
    # failing 42% of the time.
    #
    # `answered` is the right denominator: every request the server responded to, whether or
    # not the work completed. On a clean run it equals the old set exactly, so nothing that
    # used to report correctly changes.
    answered        = [ r for r in records if r[ "status_code" ] == 200 ]
    n_answered      = len( answered )
    replay_failures = [ r for r in answered if reported_route_reason( r ) == ROUTE_REPLAY_ERROR ]
    router_errors   = [ r for r in answered if reported_route_reason( r ) == ROUTE_ROUTER_ERROR ]
    extract_errors  = [ r for r in answered if reported_route_reason( r ) == ROUTE_EXTRACT_ERROR ]
    agent_errors    = [ r for r in answered if reported_route_reason( r ) == ROUTE_AGENT_ERROR ]

    latencies = [ v for v in ( first_useful_ms( r ) for r in ok ) if v is not None ]

    # F1 client-send instrument (additive): the comparable-across-arms span. Server-stamped
    # first_useful stays exactly as-is above; this is a SECOND, client-clock number measured
    # the same way the v1 arm measures around /api/push, so the paired gate has one instrument.
    client_spans = [ r[ "client_span_ms" ] for r in ok if r.get( "client_span_ms" ) is not None ]
    # The paired median-Δ gate (paired_eval) needs per-utterance identity, not a flat list —
    # it pairs v2's span for utterance u against v1's span for the SAME u. Key by utterance so
    # the two arms can be aligned; provenance guarantees both measured the same utterance set.
    spans_by_utterance = { r[ "utterance" ]: r[ "client_span_ms" ] for r in ok if r.get( "client_span_ms" ) is not None }

    # F2 parity with the v1 arm: routing is scored ONLY over utterances whose expected
    # command is mappable. An unmappable utterance is EXCLUDED from the denominator, never
    # counted as a forced miss.
    mappable     = set( mappable_commands ) if mappable_commands is not None else None
    def _eligible( record ):
        return mappable is None or record[ "expected_command" ] in mappable
    eligible     = [ r for r in ok if _eligible( r ) ]
    excluded_n   = sum( 1 for r in records if not _eligible( r ) )
    routed_right = [ r for r in eligible if route_matches( matched_command( r ), r[ "expected_command" ] ) ]

    would_be_wrong = [
        r for r in cache_hits
        if not route_matches( matched_command( r ), r[ "expected_command" ] )
    ]

    by_path : Dict[ str, int ] = {}
    for r in ok:
        key = response_path( r )
        label = key if key is not None else "unknown"
        by_path[ label ] = by_path.get( label, 0 ) + 1

    return {
        "n"                   : n,
        "n_ok"                : n_ok,
        "n_http_error"        : n - n_ok,
        "n_answered"          : n_answered,   # the four error rates are over THIS, not n_ok
        "cache_hit_rate"      : _rate( len( cache_hits ),       len( cacheable ) ),
        "cache_hit_denominator": len( cacheable ),   # NOT n_ok — see _is_cacheable_command
        "cache_excluded_n"    : n_ok - len( cacheable ),
        "cache_candidate_rate": _rate( len( cache_candidates ), n_ok ),
        "replay_failure_rate" : _rate( len( replay_failures ),  n_answered ),
        "router_error_rate"   : _rate( len( router_errors ),    n_answered ),
        "extract_error_rate"  : _rate( len( extract_errors ),   n_answered ),
        "agent_error_rate"    : _rate( len( agent_errors ),     n_answered ),
        "routing_eligible_n"  : len( eligible ),
        "routing_excluded_n"  : excluded_n,
        "routing_excluded_share" : _rate( excluded_n, n ),
        "routing_accuracy"    : _rate( len( routed_right ),     len( eligible ) ),
        "p50_first_useful_ms" : percentile( latencies, 50 ),
        "p95_first_useful_ms" : percentile( latencies, 95 ),
        # F1 client-send instrument. `client_p50_ms`/`client_p95_ms` are the arm's
        # own percentiles; `spans_by_utterance` is the paired gate's input — the same
        # per-utterance shape v1's compute_v1_metrics emits. An arm with an empty
        # spans_by_utterance (a pre-F1 or zero-200 run) makes the paired gate
        # refuse-with-reason rather than emit a number.
        "client_p50_ms"       : percentile( client_spans, 50 ),
        "client_p95_ms"       : percentile( client_spans, 95 ),
        "spans_by_utterance"  : spans_by_utterance,
        "would_be_wrong"      : len( would_be_wrong ),
        "cache_hits"          : len( cache_hits ),
        "by_path"             : by_path,
    }


def threshold_table(
    records : List[ Dict[ str, Any ] ],
    floors  : Sequence[ float ] = THRESHOLD_FLOORS,
) -> List[ Dict[ str, Any ] ]:
    """
    The §6a cache-hit-rate-vs-threshold table, computed post-hoc from recorded scores.

    Requires:
        - records carry each request's best similarity (or None) via the §8 payload.

    Ensures:
        - returns one row per floor: {floor, hit_rate, hits, would_be_wrong}, where
          hit_rate is the fraction of 200-returning requests whose best similarity is
          at or above the floor, and would_be_wrong counts those whose matched command
          differs from the expected command (the R-C2 lower-bound oracle).
        - hit_rate is None only when there are zero 200-returning requests.
    """
    ok   = [ r for r in records if r[ "ok" ] ]
    n_ok = len( ok )
    rows : List[ Dict[ str, Any ] ] = []
    for floor in floors:
        at_floor = [
            r for r in ok
            if response_similarity( r ) is not None and response_similarity( r ) >= floor
        ]
        wrong = [
            r for r in at_floor
            if not route_matches( matched_command( r ), r[ "expected_command" ] )
        ]
        rows.append( {
            "floor"          : floor,
            "hit_rate"       : _rate( len( at_floor ), n_ok ),
            "hits"           : len( at_floor ),
            "would_be_wrong" : len( wrong ),
        } )
    return rows


def latency_delta( cold: Dict[ str, Any ], warm: Dict[ str, Any ] ) -> Dict[ str, Optional[ float ] ]:
    """
    The cold->warm latency change for p50 and p95.

    Ensures:
        - returns {p50_delta_ms, p95_delta_ms}; a delta is None when either pass
          lacks that percentile (an empty latency set).
    """
    def _delta( key: str ) -> Optional[ float ]:
        c = cold[ key ]
        w = warm[ key ]
        if c is None or w is None:
            return None
        return round( w - c, 3 )
    return {
        "p50_delta_ms": _delta( "p50_first_useful_ms" ),
        "p95_delta_ms": _delta( "p95_first_useful_ms" ),
    }


# ---------------------------------------------------------------------------
# The paired median-Δ gate MOVED to src/scripts/paired_eval.py (row d8d019f6).
#
# It is a CROSS-ARM concern — it pairs v2's and v1's per-utterance client spans and
# computes the design-§6 median-OF-deltas with a ≥20% PASS/FAIL. The version that once
# lived here computed difference-OF-medians over a flat `spans` list, a different
# statistic with no threshold (Tiffany's B2, 2026.08.16-v2-eval-adversarial-review.md),
# so it was deleted rather than left importable. v2's compute_metrics now emits
# `spans_by_utterance`; paired_eval aligns it against the v1 arm's and fires the gate.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Run-integrity guard — the control that MUST be able to fail. It asserts three
# PROPERTIES of a run (never walks a list of expected values): every response
# was 200, every landed trace is in the authoritative JSONL, and the router was
# alive. A run failing any of these is lying, so it raises rather than reports.
# ---------------------------------------------------------------------------
def guard_run_integrity(
    records            : List[ Dict[ str, Any ] ],
    jsonl_trace_ids    : Sequence[ str ],
    max_router_error_rate : float = 0.20,
) -> None:
    """
    Raise EvalIntegrityError unless the run's integrity properties all hold.

    Requires:
        - records is a completed pass; jsonl_trace_ids are the trace ids present in
          the day's authoritative trace file; 0 <= max_router_error_rate <= 1.

    Ensures:
        - returns None when ALL THREE properties hold:
            (1) http-all-ok      — no record failed to return 200;
            (2) trace-parity     — every 200 record's trace_id is in jsonl_trace_ids;
            (3) router-liveness  — router_error_rate <= max_router_error_rate.
        - raises EvalIntegrityError naming EVERY violated property otherwise.

    Raises:
        - EvalIntegrityError when any property fails.
    """
    violations : List[ str ] = []

    # TRANSPORT, not completion. `ok` now means "the work completed" (is_completed_ok),
    # so reading it here would abort the whole run on the very route errors this eval
    # exists to COUNT — and abort it with a message claiming a non-200 that never
    # happened. This check owns one question only: did the server answer at all.
    http_errors = [ r for r in records if r[ "status_code" ] != 200 ]
    if http_errors:
        violations.append(
            f"http-all-ok: {len( http_errors )} of {len( records )} requests did not return 200"
        )

    landed  = set( jsonl_trace_ids )
    ok      = [ r for r in records if r[ "ok" ] ]
    missing = [ response_trace_id( r ) for r in ok if response_trace_id( r ) not in landed ]
    if missing:
        violations.append(
            f"trace-parity: {len( missing )} of {len( ok )} traces are absent from the authoritative JSONL"
        )

    metrics = compute_metrics( records )
    rate    = metrics[ "router_error_rate" ]
    if rate is not None and rate > max_router_error_rate:
        violations.append(
            f"router-liveness: router_error_rate {rate} exceeds ceiling {max_router_error_rate} "
            f"(a dead model server masquerades as receptionist success)"
        )

    if violations:
        raise EvalIntegrityError( "run integrity failed — " + "; ".join( violations ) )


def guard_cold_start( cold_metrics: Dict[ str, Any ] ) -> None:
    """
    Raise EvalIntegrityError when the COLD pass was not actually cold (F3).

    The review's F3: `guard_run_integrity` runs on the WARM pass only, so a store
    pre-warmed by a prior run — or by the other arm — makes the "cold" pass read
    cache hits, understating cold latency and contaminating the cold→warm delta.
    A cold pass with any cache hit is a contaminated baseline reported as clean.

    Requires:
        - cold_metrics is the compute_metrics dict for the cold pass.

    Ensures:
        - returns None when cold cache_hit_rate is None (no 200s) or 0.0 (truly cold).
        - raises EvalIntegrityError when cold cache_hit_rate > 0 — a pre-warmed store.

    Raises:
        - EvalIntegrityError on a warm cold pass.
    """
    rate = cold_metrics[ "cache_hit_rate" ]
    if rate is not None and rate > 0:
        raise EvalIntegrityError(
            f"cold-start integrity failed — cold pass cache_hit_rate {rate} > 0: the store was "
            f"pre-warmed (prior run or the other arm), so this cold baseline is contaminated"
        )


def read_jsonl_trace_ids( trace_path: str ) -> List[ str ]:
    """
    The trace ids recorded in one JSONL trace file.

    Requires:
        - trace_path names a file (may be absent).

    Ensures:
        - returns [] when the file does not exist.
        - otherwise returns the `trace_id` of every non-blank JSON line.
    """
    if not os.path.exists( trace_path ):
        return []
    ids : List[ str ] = []
    with open( trace_path ) as handle:
        for line in handle:
            if line.strip() == "":
                continue
            ids.append( json.loads( line )[ "trace_id" ] )
    return ids


def neighbouring_trace_paths( trace_path: str ) -> List[ str ]:
    """
    The trace file named, plus the day either side of it.

    🔴 WHY (row d8d019f6, 2026-08-20). The 3-hour run `ts-23613e7d` died at the verdict
    step with "trace-parity: 100 of 100 traces are absent from the authoritative JSONL",
    and the traces were not absent — they were in the NEXT DAY'S FILE. Two causes, either
    one fatal on its own:

      1. TWO CLOCKS. The writer (cosa/rest/v2/trace.py:161) names the file from
         `datetime.now()`, which inside the container is UTC. The reader named it from
         `du.get_current_datetime_raw()`, which is US/Eastern. Every run started after
         8 PM EDT therefore read a file the writer was not writing — a guaranteed
         100%-missing verdict, every night, forever.
      2. MIDNIGHT. Even on one clock, a multi-hour run that crosses the writer's midnight
         has its traces split across two files, so reading any single day is short.

    Reading the neighbours removes both. A trace id is a 32-hex random, so widening the
    haystack cannot manufacture a false match; it can only stop inventing false misses.

    Requires:
        - trace_path ends in "trace-YYYY-MM-DD.jsonl"

    Ensures:
        - returns [ path ] unchanged when the name does not carry a parseable date —
          a rename must degrade to the old single-file behaviour, never crash a run
        - otherwise returns the previous day, the named day, and the next day, in order
    """
    directory = os.path.dirname( trace_path )
    name      = os.path.basename( trace_path )
    prefix, suffix = "trace-", ".jsonl"
    if not ( name.startswith( prefix ) and name.endswith( suffix ) ):
        return [ trace_path ]
    try:
        day = datetime.strptime( name[ len( prefix ) : -len( suffix ) ], "%Y-%m-%d" )
    except ValueError:
        return [ trace_path ]
    return [
        os.path.join( directory, f"{prefix}{( day + timedelta( days=offset ) ).strftime( '%Y-%m-%d' )}{suffix}" )
        for offset in ( -1, 0, 1 )
    ]


def read_trace_ids_around( trace_path: str ) -> List[ str ]:
    """
    Every trace id in the named day's file and the day either side.

    Ensures:
        - returns the concatenated ids of whichever of those files exist (absent files
          contribute nothing, exactly as read_jsonl_trace_ids already allows)
    """
    ids : List[ str ] = []
    for path in neighbouring_trace_paths( trace_path ):
        ids.extend( read_jsonl_trace_ids( path ) )
    return ids


# ---------------------------------------------------------------------------
# Per-arm clean-step (design §4, decision B). The v2 peer of v1_eval_arm.truncate_snapshots.
#
# NOT YET WIRED — this is a BRIDGE-COMPOSABLE PRIMITIVE with NO caller outside its own tests.
# Under decision B (Mr Radio, 2026-08-16) isolation is on the DATABASE axis: both arms write
# the same table NAME (solution_snapshots) but on their own measurement db (v1 -> lupin_db_v1baseline,
# v2 -> lupin_db_test). Sam's paired integration bridge (row d212f54b, currently blocked) is the
# REAL caller; the paired run MUST NOT proceed until that bridge calls this AND a test proves the
# call happens. Do not claim it "wired" on a green unit suite — that is the exact orphan defect
# (row d8d019f6 / require_arms_distinct_and_clean) this row is closing, and it must not recur here.
# ---------------------------------------------------------------------------
SYNONYM_TABLE = "canonical_synonyms"   # tier-1 lookup table — the other half of the cache


def clean_v2_snapshot_store( connection: Any, config_mgr: Any ) -> str:
    """
    Empty v2's snapshot table so the cold pass starts genuinely cold — TWO guards fire first.

    Ordering is the safety property. Both guards run and can RAISE before connection.execute is
    ever reached, so a wrong config or a wrong db never reaches a TRUNCATE:
      1. CONFIG cross-check (require_config_table_matches_write_target) — the declared
         `v2 snapshot table` equals the ORM write target; the TRUNCATE identifier is then the
         RESOLVED __tablename__ it returns, never the raw config string (no injection surface).
      2. DB assertion (assert_measurement_db) — the connection's OWN db (read off
         connection.engine.url, never a decoupled arg) is a measurement db, never dev/prod.

    Requires:
        - connection is the live DB connection the TRUNCATE will run on; it exposes
          `.engine.url` and `.execute( sql )`. Under decision B its db is v2's own measurement
          db (lupin_db_test), which assert_measurement_db verifies.
        - config_mgr exposes .get( key, default, return_type ).

    Ensures:
        - runs the config cross-check FIRST (raises ConfigTableMismatch on drift), then the db
          assertion (raises NotAMeasurementDatabase on a wrong db) — connection.execute is
          NEVER called if either raises.
        - on a measurement db with a matching config, TRUNCATEs the ORM write target (the value
          the cross-check returned) **together with the tier-1 synonym table** in one statement,
          and returns the snapshot table's name.

    🔴 WHY THE SYNONYM TABLE GOES TOO (row d8d019f6, 2026-08-20). Emptying snapshots alone
    leaves every synonym from every prior run pointing at a row that is gone. Tier 1 matches
    one of those ghosts by verbatim text, dereferences it to nothing and reports a MISS, so
    the cache cannot hit however well replay works. Measured on lupin_db_test after
    ts-23613e7d: 124 snapshots against 1,021 v2-written synonyms, 897 dangling, and every
    synonym matching a live question resolving to a ghost — v2 was graded at a 0% hit rate
    with a 65% candidate rate. The two tables are one cache.

    Raises:
        - ConfigTableMismatch when the declared table does not equal the ORM write target.
        - NotAMeasurementDatabase when the connection's db is not a measurement db.
    """
    from sqlalchemy import text   # SQLAlchemy 2.x rejects a raw string here — statements must be executable

    target = require_config_table_matches_write_target( config_mgr )   # raises on config drift
    assert_measurement_db( str( connection.engine.url ) )              # raises on a wrong db
    # identifiers: the resolved __tablename__ + a module constant — neither caller-supplied
    connection.execute( text( f"TRUNCATE TABLE {target}, {SYNONYM_TABLE}" ) )
    connection.commit()   # SQLAlchemy 2.x is commit-as-you-go: without this the TRUNCATE rolls back on close (the store stays dirty)
    return target


# ---------------------------------------------------------------------------
# The live client seam — a POST-to-server ask, with the transport injected so
# the whole flow is exercisable without a live server (and covered).
# ---------------------------------------------------------------------------
class HttpAskClient:
    """A `POST /api/v2/ask` client for the scheduled :8000 run (§8 contract).

    Requires:
        - base_url points at a server answering the §8 endpoint contract.
        - post_fn(url, json, headers, timeout) returns an object with .status_code
          and .json(); it defaults to requests.post at call time.
        - bearer is a JWT for get_current_user (from /auth/login; mock tokens are
          legacy).

    Ensures:
        - ask(question) POSTs {question, websocket_id, speak:false, interactive:false}
          and returns {utterance, ok, status_code, payload}.
    """

    def __init__(
        self,
        base_url     : str,
        bearer       : str,
        websocket_id : str                       = "v2-eval",
        post_fn      : Optional[ Callable ]      = None,
        timeout      : float                     = ASK_READ_TIMEOUT_SECONDS,
        clock        : Callable[ [], float ]     = time.monotonic,
        relogin_fn   : Optional[ Callable[ [], str ] ] = None,
        attempt_log_fn : Optional[ Callable[ [ Dict[ str, Any ] ], None ] ] = None,
        wall_clock   : Callable[ [], float ]     = time.time,
    ) -> None:
        self.base_url     = base_url.rstrip( "/" )
        self.bearer       = bearer
        self.websocket_id = websocket_id
        self.post_fn      = post_fn
        self.timeout      = timeout
        self.clock        = clock                # injected monotonic clock — the F1 client-send stopwatch
        self.relogin_fn   = relogin_fn           # re-mint a fresh bearer on 401 (token-expiry refresh, row d8d019f6)
        self.attempt_log_fn = attempt_log_fn     # start/end/error rows so a HANG names itself (see _log_attempt)
        self.wall_clock   = wall_clock           # wall time for the log rows (monotonic is meaningless in a file)
        self._attempt_seq = 0

    def _log_attempt( self, **fields: Any ) -> None:
        """
        Record one attempt-lifecycle row, if a sink is wired.

        WHY THIS EXISTS (María, row d8d019f6). The v2 flow trace writes a row only at
        COMPLETION, so the one call you most need to see — the one that hung — is the only one
        guaranteed to leave no evidence. 983 calls survived the last run and the single request
        that blew the read wall left nothing, which is why the timeout is sized at 4x
        worst-OBSERVED rather than to a known worst case. A row at START fixes that: a hang
        leaves a dangling start with no matching end, and that dangling row names the utterance.

        Ensures:
            - never raises. An instrument that can kill the run it is measuring is worse than
              no instrument, so a sink failure is swallowed deliberately.
        """
        if self.attempt_log_fn is None:
            return
        try:
            self.attempt_log_fn( { "wall_ts": self.wall_clock(), **fields } )
        except Exception:   # pragma: no cover - defensive: the instrument must never break the run
            pass

    def _post( self, url: str, payload: Dict[ str, Any ], headers: Dict[ str, str ] ) -> Any:
        """POST via the injected transport, defaulting to requests.post."""
        if self.post_fn is not None:
            return self.post_fn( url, json=payload, headers=headers, timeout=self.timeout )
        import requests
        return requests.post( url, json=payload, headers=headers, timeout=self.timeout )

    def ask( self, question: str ) -> Dict[ str, Any ]:
        """
        Submit one utterance and normalize the reply to a record.

        Ensures:
            - runs speak=false, interactive=false (the flow executes, TTS is skipped,
              nothing blocks).
            - returns {utterance, ok, status_code, payload, client_span_ms}; ok is
              (status_code == 200).
            - client_span_ms is the CLIENT-SEND span (F1): monotonic clock from the
              instant just before the POST to the instant the reply is in hand. It
              encloses ALL of v2's server-side work (routing + extract + cache lookup +
              replay), so it is the SAME kind of measurement the v1 arm takes around
              /api/push — the one number the paired median-Δ gate may compare. It is a
              proxy (it also carries network + serialization), NOT v2's precise
              server-stamped first_useful; both are reported, and the report says which
              is which.
        """
        url     = self.base_url + "/api/v2/ask"
        headers = { "Authorization": f"Bearer {self.bearer}" }
        body    = {
            "question"     : question,
            "websocket_id" : self.websocket_id,
            "speak"        : False,
            "interactive"  : False,
        }
        self._attempt_seq += 1
        seq      = self._attempt_seq
        send_ts  = self.clock()
        # START row BEFORE the POST. A call that never returns leaves this row with no matching
        # "end", so the hang identifies itself instead of vanishing (María, row d8d019f6).
        self._log_attempt( phase="start", seq=seq, attempt=1, utterance=question, timeout_s=self.timeout )
        try:
            reply = self._post( url, body, headers )
        except BaseException as failure:
            # A read timeout is the exact failure this instrument exists for: name the utterance
            # and how long we waited, then re-raise unchanged so behaviour is untouched.
            self._log_attempt( phase="error", seq=seq, attempt=1, utterance=question,
                               timeout_s=self.timeout, waited_s=self.clock() - send_ts,
                               error=type( failure ).__name__, detail=str( failure ) )
            raise
        recv_ts = self.clock()
        # Token-refresh on expiry (row d8d019f6): a long paired run outlives the JWT (~30min), so
        # late requests 401. On a 401, re-login for a fresh bearer and retry ONCE, resetting the
        # stopwatch so the recorded client_span_ms is the SUCCESSFUL retry — never the 401+relogin.
        # Without this a >30min run fails http-all-ok and the integrity guard refuses (ts-d0f50349:
        # 4 of 50 late requests 401'd, no median-Δ).
        if reply.status_code == 401 and self.relogin_fn is not None:
            self.bearer = self.relogin_fn()
            headers     = { "Authorization": f"Bearer {self.bearer}" }
            send_ts     = self.clock()
            self._log_attempt( phase="start", seq=seq, attempt=2, utterance=question,
                               timeout_s=self.timeout, note="retry after 401 + relogin" )
            try:
                reply = self._post( url, body, headers )
            except BaseException as failure:
                self._log_attempt( phase="error", seq=seq, attempt=2, utterance=question,
                                   timeout_s=self.timeout, waited_s=self.clock() - send_ts,
                                   error=type( failure ).__name__, detail=str( failure ) )
                raise
            recv_ts     = self.clock()
        # ALIGNED WITH v1's BAR (row d8d019f6): a 200 whose body reports a route error is a
        # failure here, exactly as an errored job is a failure in the v1 arm. Parse first,
        # then judge — the old order could not inspect a body it had already discarded.
        payload = reply.json() if reply.status_code == 200 else {}
        ok      = is_completed_ok( reply.status_code, payload )
        span_ms = ( recv_ts - send_ts ) * 1000.0                 # F1 client-send instrument
        self._log_attempt( phase="end", seq=seq, utterance=question, ok=ok,
                           status_code=reply.status_code, client_span_ms=span_ms )
        return {
            "utterance"      : question,
            "ok"             : ok,
            "status_code"    : reply.status_code,
            "payload"        : payload,
            "client_span_ms" : span_ms,
        }


def read_running_server_sha( base_url: str ) -> str:   # pragma: no cover - live HTTP boundary
    """
    Ask the RUNNING v2 server what sha it booted from, so this arm's numbers are auditable
    back to the tree that produced them (row c9b43538).

    Read from GET /api/code-identity, whose JSON body carries `git_sha` at the TOP LEVEL.
    NOT /health — that returns only {status, timestamp}, so reading it yields "" against a
    perfectly healthy server. The v1 arm's twin (v1_eval_arm.read_running_server_sha) carries
    the long form of that warning; this is a deliberate duplicate rather than an import,
    because v1_eval_arm imports v2_eval and reaching back would make the cycle.

    Ensures:
        - returns the reported sha, or "" when the key is absent — "" is a REFUSAL upstream,
          never a value that reaches a report.
    """
    import json, urllib.request
    req  = urllib.request.Request( base_url.rstrip( "/" ) + "/api/code-identity" )
    data = json.loads( urllib.request.urlopen( req, timeout=10 ).read().decode() )
    return data.get( "git_sha", "" )


def load_mappable_commands() -> Optional[ List[ str ] ]:
    """
    The routing commands both arms can score, from the live v1 registry.

    Ensures:
        - returns the class_to_command VALUES (the same list v1_eval_arm hands its own
          assemble step), or None when the registry cannot be read
        - a None return is announced on stdout, never silent: an unrestricted denominator
          is the very asymmetry this exists to close, so a reader must see it happened
        - never raises
    """
    try:
        from v1_eval_arm import load_v1_class_to_command      # lazy: v1 imports v2
        class_to_command, _ambiguous = load_v1_class_to_command()
        return list( class_to_command.values() )
    except Exception as failure:                              # pragma: no cover - live-registry seam
        print( f"[v2-eval] WARNING: could not read the v1 routing registry ({type( failure ).__name__}: "
               f"{failure}) — routing accuracy will be scored over the FULL corpus, which is NOT "
               f"comparable to the v1 arm's eligible-only denominator." )
        return None


def run_pass(
    corpus          : List[ Tuple[ str, str ] ],
    ask             : Callable[ [ str ], Dict[ str, Any ] ],
    pass_kind       : str,
    fail_fast       : bool = False,
    allow_warm_cold : bool = False,
) -> List[ Dict[ str, Any ] ]:
    """
    Run one pass over the corpus, attaching the expected command to each record.

    Requires:
        - corpus is a non-empty list of (utterance, expected_command) pairs.
        - ask(question) returns a record dict {utterance, ok, status_code, payload}.
        - pass_kind is "cold" or "warm".

    Ensures:
        - returns one record per corpus pair, each carrying expected_command and
          pass_kind alongside the ask() result.
        - when fail_fast is True and the FIRST request does not return 200, raises
          immediately — a broken endpoint costs one request, not the whole corpus
          (Cheech, thread 4fb7f475). The first real utterance doubles as the smoke,
          so no extra probe request is spent.
        - on a COLD pass, raises at the FIRST replayed answer — a pre-warmed store
          costs the calls made so far, not the whole corpus (row a77a7906).
        - when allow_warm_cold is True that abort is SUPPRESSED, matching the
          --allow-warm-cold escape hatch that already suppresses guard_cold_start.
          One flag, one meaning, both ends of the run.

    Raises:
        - EvalIntegrityError if fail_fast and the first request is not ok.
        - EvalIntegrityError on the first cold-pass cache hit, unless allow_warm_cold.
    """
    records : List[ Dict[ str, Any ] ] = []
    for index, ( utterance, expected ) in enumerate( corpus ):
        record = ask( utterance )
        record[ "expected_command" ] = expected
        record[ "pass_kind" ]        = pass_kind
        records.append( record )
        # Same split as guard_run_integrity: fail-fast owns "is the endpoint broken",
        # which is a transport question. A first utterance that returns 200 and reports
        # agent_error is a result to record, not a reason to abandon the corpus.
        if fail_fast and index == 0 and record[ "status_code" ] != 200:
            raise EvalIntegrityError(
                f"fail-fast: first {pass_kind} request returned "
                f"{record[ 'status_code' ]}, not 200 — aborting before spending the corpus"
            )
        # COLD-STORE FAIL-FAST (row a77a7906). guard_cold_start already refuses a
        # contaminated baseline, but it runs AFTER the whole corpus, so on 2026-08-21
        # a warm store would have cost two hours of inference before saying so. This
        # is the SAME predicate evaluated incrementally: guard_cold_start raises when
        # cold cache_hit_rate > 0, which is true exactly when at least one cold record
        # replays. Detecting it here changes WHEN we learn, never WHAT counts.
        #
        # It reads the store THROUGH THE EVAL'S OWN CALLS — the reply the flow just
        # sent — so it cannot drift onto a different database, and it cannot read
        # empty while the server's in-memory cache is warm. A row count queried
        # anywhere else could do both (Mr Radio's refutation bar, 2026-08-21).
        #
        # NOT a replacement for guard_cold_start: a store warm only for utterances
        # this pass never reaches is invisible here and is still caught at the end.
        if ( pass_kind == "cold" and not allow_warm_cold
             and record[ "ok" ] and response_path( record ) == PATH_REPLAY ):
            raise EvalIntegrityError(
                f"cold-start integrity failed at request {index + 1} of {len( corpus )}: "
                f"the store was already warm — {record[ 'utterance' ]!r} came back as a "
                f"REPLAY, so this pass is not a cold baseline. Aborting rather than "
                f"spending the rest of the corpus. The store must be cleared before a "
                f"cold pass, and v2_eval cannot clear it: that is the step-13 cache dump, "
                f"legal only after 9a and 9b merge. Do NOT hand-truncate the test DB."
            )
    return records


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def _fmt( value: Optional[ float ] ) -> str:
    """A metric cell: 'n/a' for None, else the value as-is."""
    return "n/a" if value is None else str( value )


def render_report(
    cold_metrics  : Dict[ str, Any ],
    warm_metrics  : Dict[ str, Any ],
    warm_table    : List[ Dict[ str, Any ] ],
    delta         : Dict[ str, Optional[ float ] ],
    corpus_name   : str,
    timestamp     : str,
    seed          : int,
    n_per_command : int,
) -> str:
    """
    The markdown report for a two-pass run.

    Ensures:
        - returns a markdown string carrying the metric table (cold vs warm), the
          cold->warm latency delta, the §6a threshold table (from the warm pass), and
          the R-C2 would-be-wrong caveat verbatim.
        - STAMPS the sample seed + n_per_command (B3) so the v2 report is reproducible
          and its stratified sample is auditable — the same reproducibility facts the
          v1 arm's header carries.
    """
    lines : List[ str ] = []
    lines.append( f"# CJ Flow v2 eval — corpus `{corpus_name}` — {timestamp}" )
    lines.append( "" )
    lines.append( NOT_GONOGO_BANNER )
    lines.append( "" )
    lines.append( "**EXECUTOR: AI** · venue :8000 scheduled (post-midnight off-peak) · `speak=false, interactive=false`" )
    lines.append( f"**sample**: stratified, seed `{seed}`, n_per_command `{n_per_command}` (reproducible — same seed, same sample)" )
    lines.append( "" )
    lines.append( "## Headline metrics (cold vs warm)" )
    lines.append( "" )
    lines.append( "| metric | cold | warm |" )
    lines.append( "|---|---|---|" )
    rows = [
        ( "requests (n)",          "n" ),
        ( "HTTP errors",           "n_http_error" ),
        ( "cache-hit rate",        "cache_hit_rate" ),
        ( "cache-candidate rate",  "cache_candidate_rate" ),
        ( "replay-failure rate",   "replay_failure_rate" ),
        ( "router-error rate",     "router_error_rate" ),
        ( "extract-error rate",    "extract_error_rate" ),
        ( "agent-error rate",      "agent_error_rate" ),
        ( "routing accuracy",      "routing_accuracy" ),
        ( "routing eligible (n)",  "routing_eligible_n" ),
        ( "routing excluded (n)",  "routing_excluded_n" ),
        ( "p50 first-useful (ms)", "p50_first_useful_ms" ),
        ( "p95 first-useful (ms)", "p95_first_useful_ms" ),
        ( "p50 client-send (ms)",  "client_p50_ms" ),
        ( "p95 client-send (ms)",  "client_p95_ms" ),
        ( "would-be-wrong (count)","would_be_wrong" ),
    ]
    for label, key in rows:
        lines.append( f"| {label} | {_fmt( cold_metrics[ key ] )} | {_fmt( warm_metrics[ key ] )} |" )
    lines.append( "" )
    lines.append(
        "> **routing accuracy is scored over the ELIGIBLE rows only** — utterances whose "
        "expected command is not mappable are EXCLUDED from the denominator, not counted "
        "as misses, and the excluded count is in the table above. This is the same "
        "exclusion the v1 arm applies, so the two arms' routing numbers answer one question."
    )
    lines.append( "" )
    lines.append(
        "> instruments: **first-useful** is v2's server-stamped mark (routing→answer, "
        "server-precise). **client-send** is the F1 cross-arm span — the client stopwatch "
        "from just-before-POST to reply-in-hand — the ONLY number comparable to the v1 arm. "
        "It is a proxy: it also carries network + serialization, so it is close to, but not "
        "the same instrument as, the server-stamped mark. The paired median-Δ gate uses "
        "client-send; first-useful is v2-internal detail."
    )
    lines.append( "" )
    lines.append( "## Cold → warm latency delta" )
    lines.append( "" )
    lines.append( f"- p50: {_fmt( delta[ 'p50_delta_ms' ] )} ms" )
    lines.append( f"- p95: {_fmt( delta[ 'p95_delta_ms' ] )} ms" )
    lines.append( "" )
    lines.append( "## Cache-hit rate vs threshold (§6a, warm pass)" )
    lines.append( "" )
    lines.append( "| floor | hit-rate | hits | would-be-wrong |" )
    lines.append( "|---|---|---|---|" )
    for row in warm_table:
        lines.append(
            f"| {row[ 'floor' ]} | {_fmt( row[ 'hit_rate' ] )} | {row[ 'hits' ]} | {row[ 'would_be_wrong' ]} |"
        )
    lines.append( "" )
    lines.append( f"> would-be-wrong caveat: {WOULD_BE_WRONG_CAVEAT}" )
    lines.append( "" )
    lines.append( "## Route distribution (warm pass)" )
    lines.append( "" )
    for label in sorted( warm_metrics[ "by_path" ] ):
        lines.append( f"- `{label}`: {warm_metrics[ 'by_path' ][ label ]}" )
    lines.append( "" )
    return "\n".join( lines )


def dump_records_early( out_dir: str, cold_records: List[ Dict[ str, Any ] ],
                        warm_records: List[ Dict[ str, Any ] ] ) -> Optional[ str ]:
    """
    Persist the raw records the moment both passes return, BEFORE anything may refuse.

    🔴 WHY (row d8d019f6, 2026-08-20). `guard_run_integrity` fires before `write_outputs`,
    so when ts-23613e7d raised on trace-parity it destroyed the v2 arm's ENTIRE run — three
    hours of records that had already been collected never reached disk, and no eval-<stamp>
    directory was written at all. The v1 arm has carried this insurance since attempt 11
    (_dump_paired_artifacts fires the moment the v1 arm returns); the v2 arm never got it.
    A downstream refusal should cost the VERDICT, never the DATA.

    Ensures:
        - writes records.jsonl into out_dir and returns its path
        - BEST-EFFORT: a dump failure is reported and swallowed, never allowed to mask the
          real run outcome — insurance that can itself kill the run is not insurance
    """
    try:
        os.makedirs( out_dir, exist_ok=True )
        path = os.path.join( out_dir, "records.jsonl" )
        with open( path, "w" ) as handle:
            for record in list( cold_records ) + list( warm_records ):
                handle.write( json.dumps( record ) + "\n" )
        print( f"[v2-eval] early record dump: {len( cold_records ) + len( warm_records )} records -> {path}" )
        return path
    except Exception as failure:
        print( f"[v2-eval] WARNING: early record dump failed ({type( failure ).__name__}: {failure}) — "
               f"the run continues, but a refusal past this point will cost the records." )
        return None


def write_outputs(
    out_dir      : str,
    report_md    : str,
    cold_records : List[ Dict[ str, Any ] ],
    warm_records : List[ Dict[ str, Any ] ],
) -> Dict[ str, str ]:
    """
    Write the markdown report and the raw records to `out_dir`.

    Ensures:
        - creates out_dir (and parents) if absent.
        - writes report.md and records.jsonl (one JSON object per record, both passes).
        - returns {report, records} — the two paths written.
    """
    os.makedirs( out_dir, exist_ok=True )
    report_path  = os.path.join( out_dir, "report.md" )
    records_path = os.path.join( out_dir, "records.jsonl" )
    with open( report_path, "w" ) as handle:
        handle.write( report_md )
    with open( records_path, "w" ) as handle:
        for record in list( cold_records ) + list( warm_records ):
            handle.write( json.dumps( record ) + "\n" )
    return { "report": report_path, "records": records_path }


# ---------------------------------------------------------------------------
# CLI entry point. The live run needs an authenticated client; the client is
# injected so main() is fully exercisable without a server.
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    """The CLI parser: --corpus, --passes, --base-url, --limit, --max-router-error-rate."""
    parser = argparse.ArgumentParser( description="CJ Flow v2 two-pass eval harness (EXECUTOR: AI)" )
    parser.add_argument( "--corpus",  default="simple", help="corpus name (simple|weather)" )
    parser.add_argument( "--passes",  type=int, default=2, help="number of passes (must be 2 for cache-hit)" )
    parser.add_argument( "--base-url", default="http://localhost:8000", help="server base url (:8000 scheduled)" )
    parser.add_argument( "--limit",   type=int, default=None, help="cap utterances per command (pre-sample)" )
    parser.add_argument( "--seed",    type=int, default=1024,
                         help="stratified-sample seed (stamped in the report; reproducibility, design §5)" )
    parser.add_argument( "--n-per-command", type=int, default=60,
                         help="stratified sample size per command (PER ARM, design §5)" )
    parser.add_argument( "--max-router-error-rate", type=float, default=0.20,
                         help="run-integrity ceiling on router_error_rate" )
    parser.add_argument( "--allow-warm-cold", action="store_true",
                         help="skip the F3 cold-start guard (use only when the store is deliberately pre-warmed)" )
    return parser


def main(
    argv           : Optional[ List[ str ] ] = None,
    client_factory : Optional[ Callable[ [ str ], Any ] ] = None,
    project_root   : Optional[ str ] = None,
    timestamp      : Optional[ str ] = None,
    read_sha_fn    : Optional[ Callable[ [ str ], str ] ] = None,
    probe_models_fn: Optional[ Callable[ [ str ], None ] ] = None,
) -> Dict[ str, Any ]:
    """
    Run the two-pass eval and write the report.

    Requires:
        - argv are CLI args (defaults to sys.argv[1:]).
        - client_factory(base_url) returns an object with .ask(question); when None,
          an HttpAskClient is built from LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* credentials.
        - passes must be 2 — a single pass cannot produce the cache-hit number.

    Ensures:
        - loads the corpus, STRATIFIED-SAMPLES it (seed + n_per_command, design §5 —
          the same sampler + seed the v1 arm uses, so the two arms measure the same
          population and the v2 report is reproducible), runs cold then warm, guards
          run integrity on the warm pass, guards cold-start integrity on the cold pass
          (F3; unless --allow-warm-cold), renders the seed-stamped report, and writes it
          under io/v2-flow/eval-<timestamp>/.
        - stamps a v2 provenance record (make_provenance over the sampled set) and writes
          a v2-arm-artifact.json = {metrics: warm, provenance} — the input paired_eval
          consumes to fire the paired median-Δ gate against the v1 arm.
        - returns {out_dir, paths, cold, warm, provenance}.

    Raises:
        - ValueError if passes != 2.
        - EvalIntegrityError if the warm pass fails an integrity property, or (unless
          --allow-warm-cold) the cold pass shows cache hits (a pre-warmed store).
    """
    args   = build_arg_parser().parse_args( argv )
    if args.passes != 2:
        raise ValueError( "the two-pass design is required — a single pass cannot produce cache-hit rate" )

    root   = project_root if project_root is not None else du.get_project_root()
    stamp  = timestamp if timestamp is not None else du.get_current_datetime_raw().strftime( "%Y-%m-%d-%H-%M-%S" )
    pairs  = load_corpus( args.corpus, project_root=root, limit=args.limit )
    # B3: stratified + seeded PER ARM (design §5) — same sampler as v1, so the arms measure
    # the same population; a flat first-N would let the biggest command dominate.
    corpus, _sample_manifest = stratified_sample( pairs, args.n_per_command, args.seed )
    # WHICH TREE served the v2 numbers (row c9b43538). The v1 arm has always read its sha back
    # from the running server; v2 had no equivalent, so even a forced check covered half the
    # comparison. There is no pin to assert against here — v2 runs whatever is deployed — so
    # this RECORDS rather than asserts. Reading it before the passes means a server that cannot
    # identify itself stops the run before it spends hours, not after.
    read_sha    = read_sha_fn if read_sha_fn is not None else read_running_server_sha
    v2_git_sha  = read_sha( args.base_url )
    if not isinstance( v2_git_sha, str ) or v2_git_sha.strip() == "":
        raise EvalIntegrityError(
            f"the v2 server at {args.base_url} did not report a git sha (got {v2_git_sha!r}); "
            f"refusing to measure numbers that could not be traced back to a tree"
        )
    provenance = make_provenance( "v2", args.corpus, args.seed, args.n_per_command, corpus,
                                  git_sha=v2_git_sha )

    factory = client_factory if client_factory is not None else _default_client_factory
    client  = factory( args.base_url )

    # The model server is a dependency this run cannot see fail. Probe EVERY port the
    # configuration names BEFORE a single question is asked, and refuse naming the one that
    # did not answer — a half-alive box (one port up, one down) reads as alive to any check
    # that probes a single port, which is how the last outage stayed invisible until a
    # three-hour job died on it (row b9604f8c).
    probe = probe_models_fn if probe_models_fn is not None else _default_model_probe
    probe( "before the cold pass" )

    cold_records = run_pass( corpus, client.ask, "cold", fail_fast=True,
                             allow_warm_cold=args.allow_warm_cold )
    # AGAIN between the passes. A long run can OUTLIVE its dependency: the box can die at
    # minute ten as easily as before minute zero, and the warm pass is the expensive half.
    # The pass boundary is the cheapest point where a mid-run death is still catchable.
    probe( "between the cold and warm passes" )
    warm_records = run_pass( corpus, client.ask, "warm" )

    # INSURANCE BEFORE ANY REFUSAL (row d8d019f6): both passes are done and the records are
    # in memory only. guard_run_integrity below CAN raise, and when it did on ts-23613e7d it
    # took three hours of already-collected v2 records with it. Land them first.
    out_dir = os.path.join( root, "io", "v2-flow", f"eval-{stamp}" )
    dump_records_early( out_dir, cold_records, warm_records )

    trace_path = os.path.join( root, "io", "v2-flow", f"trace-{stamp[ :10 ]}.jsonl" )
    # The day either side too — the writer's clock is the container's (UTC) and this
    # process's is US/Eastern, and a long run crosses midnight anyway. See
    # neighbouring_trace_paths for the run this cost.
    landed     = read_trace_ids_around( trace_path )
    guard_run_integrity( warm_records, landed, max_router_error_rate=args.max_router_error_rate )

    # The routing denominator must be the SAME set of utterances the v1 arm scores on
    # (row d8d019f6). Derived from the LIVE registry here, exactly as the v1 arm derives
    # it, and imported lazily because v1_eval_arm imports THIS module — a module-level
    # import would close the cycle.
    mappable = load_mappable_commands()
    cold_metrics = compute_metrics( cold_records, mappable_commands=mappable )
    warm_metrics = compute_metrics( warm_records, mappable_commands=mappable )
    if not args.allow_warm_cold:
        guard_cold_start( cold_metrics )          # F3: a contaminated cold baseline raises, never reports clean
    warm_table   = threshold_table( warm_records )
    delta        = latency_delta( cold_metrics, warm_metrics )
    report_md    = render_report( cold_metrics, warm_metrics, warm_table, delta,
                                  args.corpus, stamp, args.seed, args.n_per_command )

    paths   = write_outputs( out_dir, report_md, cold_records, warm_records )   # out_dir set above, before the guard

    # The paired step (paired_eval) consumes {metrics, provenance}; write the v2 arm artifact.
    artifact_path = os.path.join( out_dir, "v2-arm-artifact.json" )
    with open( artifact_path, "w" ) as handle:
        json.dump( { "metrics": warm_metrics, "provenance": provenance }, handle )
    paths[ "artifact" ] = artifact_path

    return { "out_dir": out_dir, "paths": paths, "cold": cold_metrics, "warm": warm_metrics, "provenance": provenance }


def _default_model_probe( context: str ) -> None:   # pragma: no cover - live socket boundary
    """
    Refuse the run unless EVERY configured vLLM endpoint answers.

    WHY IT IS HERE. On 2026-08-17 the router at :3000 went down while :3001 stayed up. The
    box read as alive to any check that probed one port, and the outage surfaced only when
    a THREE-HOUR job died on it, with an API error three layers from the cause (row
    b9604f8c). Probing every configured endpoint before the first question turns those
    hours into a refusal at second one that names the port.

    Injected as `probe_models_fn` in tests, so the unit tier never opens a socket.
    """
    from cosa.config.configuration_manager import ConfigurationManager
    from cosa.utils.model_server_liveness import require_live
    require_live( config_mgr=ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ),
                  context=context )


def _default_client_factory( base_url: str ) -> HttpAskClient:
    """
    Build an authenticated HttpAskClient from the standard test credentials.

    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD are set; a bearer JWT
          is obtained from /auth/login (mock tokens are legacy).

    Ensures:
        - returns an HttpAskClient pointed at base_url with a bearer token.
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise ValueError(
            "set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD"
        )
    import requests
    def _login() -> str:
        reply = requests.post( base_url.rstrip( "/" ) + "/auth/login",
                               json={ "email": email, "password": password }, timeout=30.0 )
        reply.raise_for_status()
        return reply.json()[ "tokens" ][ "access_token" ]   # /auth/login nests the token under "tokens" (B1)
    # relogin_fn = the SAME login, re-minted on 401 so a >30min paired run survives JWT expiry (d8d019f6).
    # timeout: ASK_READ_TIMEOUT_SECONDS unless a run overrides it — a read wall must never again be
    # the thing that destroys 3 hours of unwritten arm data (ts-1686ce29, row d8d019f6).
    ask_timeout = float( os.environ.get( "LUPIN_V2_ASK_TIMEOUT_SECONDS", ASK_READ_TIMEOUT_SECONDS ) )
    return HttpAskClient( base_url, bearer=_login(), relogin_fn=_login, timeout=ask_timeout,
                          attempt_log_fn=make_attempt_logger() )


def make_attempt_logger( path: Optional[ str ] = None ) -> Callable[ [ Dict[ str, Any ] ], None ]:
    """
    Build the append-a-JSON-line sink for HttpAskClient's start/end/error rows.

    Requires:
        - path, when given, is the file to append to; otherwise LUPIN_V2_ASK_ATTEMPT_LOG,
          otherwise <project root>/io/v2-flow/ask-attempts.jsonl.

    Ensures:
        - returns a callable that opens, appends ONE json line, and closes — per record. The
          open/close per row is the durability property that matters: a row still sitting in a
          buffer when the process dies is a row that does not exist, and that is the failure
          this instrument was built to end. (An explicit flush() would be redundant, since
          closing the file already flushes it — there is none, so none can be misread as
          the control.)
        - creates the parent directory if absent.
    """
    if path is None:
        path = os.environ.get( "LUPIN_V2_ASK_ATTEMPT_LOG" )
    if path is None:
        path = os.path.join( du.get_project_root(), "io", "v2-flow", "ask-attempts.jsonl" )

    def _append( record: Dict[ str, Any ] ) -> None:
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        with open( path, "a" ) as handle:
            handle.write( json.dumps( record ) + "\n" )

    return _append


if __name__ == "__main__":                    # pragma: no cover - CLI entry stub, not unit-testable (login logic covered via _default_client_factory)
    result = main()
    print( f"wrote {result[ 'paths' ][ 'report' ]}" )
