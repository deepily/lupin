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
import statistics
import sys
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

# The mark whose offset from the anchor is "latency to first useful response".
FIRST_USEFUL_MARK = "t_first_useful"

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


def response_similarity( record: Dict[ str, Any ] ) -> Optional[ float ]:
    """The §8 `similarity` (best score) for a record, or None when absent/failed."""
    if not record[ "ok" ]:
        return None
    value = record[ "payload" ].get( "similarity" )
    return None if value is None else float( value )


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


def compute_metrics( records: List[ Dict[ str, Any ] ] ) -> Dict[ str, Any ]:
    """
    The full metric set for one pass over the corpus.

    Requires:
        - records is a list of per-request dicts, each {utterance, expected_command,
          ok, status_code, payload}.

    Ensures:
        - returns a dict of counts, rates (None when the denominator is 0), latency
          percentiles, routing accuracy, the would-be-wrong count, and by_path counts.
        - a rate's denominator is the count of 200-returning requests, so a failed
          HTTP call can never inflate a numerator.
    """
    n        = len( records )
    ok       = [ r for r in records if r[ "ok" ] ]
    n_ok     = len( ok )

    cache_hits      = [ r for r in ok if response_path( r ) == PATH_REPLAY ]
    cache_candidates = [ r for r in ok if response_similarity( r ) is not None ]
    replay_failures = [ r for r in ok if response_route_reason( r ) == ROUTE_REPLAY_ERROR ]
    router_errors   = [ r for r in ok if response_route_reason( r ) == ROUTE_ROUTER_ERROR ]
    extract_errors  = [ r for r in ok if response_route_reason( r ) == ROUTE_EXTRACT_ERROR ]
    agent_errors    = [ r for r in ok if response_route_reason( r ) == ROUTE_AGENT_ERROR ]

    latencies = [ v for v in ( first_useful_ms( r ) for r in ok ) if v is not None ]

    routed_right = [ r for r in ok if route_matches( matched_command( r ), r[ "expected_command" ] ) ]

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
        "cache_hit_rate"      : _rate( len( cache_hits ),       n_ok ),
        "cache_candidate_rate": _rate( len( cache_candidates ), n_ok ),
        "replay_failure_rate" : _rate( len( replay_failures ),  n_ok ),
        "router_error_rate"   : _rate( len( router_errors ),    n_ok ),
        "extract_error_rate"  : _rate( len( extract_errors ),   n_ok ),
        "agent_error_rate"    : _rate( len( agent_errors ),     n_ok ),
        "routing_accuracy"    : _rate( len( routed_right ),     n_ok ),
        "p50_first_useful_ms" : percentile( latencies, 50 ),
        "p95_first_useful_ms" : percentile( latencies, 95 ),
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

    http_errors = [ r for r in records if not r[ "ok" ] ]
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
        timeout      : float                     = 120.0,
    ) -> None:
        self.base_url     = base_url.rstrip( "/" )
        self.bearer       = bearer
        self.websocket_id = websocket_id
        self.post_fn      = post_fn
        self.timeout      = timeout

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
            - returns {utterance, ok, status_code, payload}; ok is (status_code == 200).
        """
        url     = self.base_url + "/api/v2/ask"
        headers = { "Authorization": f"Bearer {self.bearer}" }
        body    = {
            "question"     : question,
            "websocket_id" : self.websocket_id,
            "speak"        : False,
            "interactive"  : False,
        }
        reply   = self._post( url, body, headers )
        ok      = ( reply.status_code == 200 )
        payload = reply.json() if ok else {}
        return {
            "utterance"   : question,
            "ok"          : ok,
            "status_code" : reply.status_code,
            "payload"     : payload,
        }


def run_pass(
    corpus    : List[ Tuple[ str, str ] ],
    ask       : Callable[ [ str ], Dict[ str, Any ] ],
    pass_kind : str,
    fail_fast : bool = False,
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

    Raises:
        - EvalIntegrityError if fail_fast and the first request is not ok.
    """
    records : List[ Dict[ str, Any ] ] = []
    for index, ( utterance, expected ) in enumerate( corpus ):
        record = ask( utterance )
        record[ "expected_command" ] = expected
        record[ "pass_kind" ]        = pass_kind
        records.append( record )
        if fail_fast and index == 0 and not record[ "ok" ]:
            raise EvalIntegrityError(
                f"fail-fast: first {pass_kind} request returned "
                f"{record[ 'status_code' ]}, not 200 — aborting before spending the corpus"
            )
    return records


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def _fmt( value: Optional[ float ] ) -> str:
    """A metric cell: 'n/a' for None, else the value as-is."""
    return "n/a" if value is None else str( value )


def render_report(
    cold_metrics : Dict[ str, Any ],
    warm_metrics : Dict[ str, Any ],
    warm_table   : List[ Dict[ str, Any ] ],
    delta        : Dict[ str, Optional[ float ] ],
    corpus_name  : str,
    timestamp    : str,
) -> str:
    """
    The markdown report for a two-pass run.

    Ensures:
        - returns a markdown string carrying the metric table (cold vs warm), the
          cold->warm latency delta, the §6a threshold table (from the warm pass), and
          the R-C2 would-be-wrong caveat verbatim.
    """
    lines : List[ str ] = []
    lines.append( f"# CJ Flow v2 eval — corpus `{corpus_name}` — {timestamp}" )
    lines.append( "" )
    lines.append( NOT_GONOGO_BANNER )
    lines.append( "" )
    lines.append( "**EXECUTOR: AI** · venue :8000 scheduled (post-midnight off-peak) · `speak=false, interactive=false`" )
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
        ( "p50 first-useful (ms)", "p50_first_useful_ms" ),
        ( "p95 first-useful (ms)", "p95_first_useful_ms" ),
        ( "would-be-wrong (count)","would_be_wrong" ),
    ]
    for label, key in rows:
        lines.append( f"| {label} | {_fmt( cold_metrics[ key ] )} | {_fmt( warm_metrics[ key ] )} |" )
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
    parser.add_argument( "--limit",   type=int, default=None, help="cap utterances per command" )
    parser.add_argument( "--max-router-error-rate", type=float, default=0.20,
                         help="run-integrity ceiling on router_error_rate" )
    return parser


def main(
    argv           : Optional[ List[ str ] ] = None,
    client_factory : Optional[ Callable[ [ str ], Any ] ] = None,
    project_root   : Optional[ str ] = None,
    timestamp      : Optional[ str ] = None,
) -> Dict[ str, Any ]:
    """
    Run the two-pass eval and write the report.

    Requires:
        - argv are CLI args (defaults to sys.argv[1:]).
        - client_factory(base_url) returns an object with .ask(question); when None,
          an HttpAskClient is built from LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* credentials.
        - passes must be 2 — a single pass cannot produce the cache-hit number.

    Ensures:
        - loads the corpus, runs cold then warm, guards run integrity on the warm pass,
          renders the report, and writes it under io/v2-flow/eval-<timestamp>/.
        - returns {out_dir, paths, cold, warm}.

    Raises:
        - ValueError if passes != 2.
        - EvalIntegrityError if the warm pass fails an integrity property.
    """
    args   = build_arg_parser().parse_args( argv )
    if args.passes != 2:
        raise ValueError( "the two-pass design is required — a single pass cannot produce cache-hit rate" )

    root   = project_root if project_root is not None else du.get_project_root()
    stamp  = timestamp if timestamp is not None else du.get_current_datetime_raw().strftime( "%Y-%m-%d-%H-%M-%S" )
    corpus = load_corpus( args.corpus, project_root=root, limit=args.limit )

    factory = client_factory if client_factory is not None else _default_client_factory
    client  = factory( args.base_url )

    cold_records = run_pass( corpus, client.ask, "cold", fail_fast=True )
    warm_records = run_pass( corpus, client.ask, "warm" )

    trace_path = os.path.join( root, "io", "v2-flow", f"trace-{stamp[ :10 ]}.jsonl" )
    landed     = read_jsonl_trace_ids( trace_path )
    guard_run_integrity( warm_records, landed, max_router_error_rate=args.max_router_error_rate )

    cold_metrics = compute_metrics( cold_records )
    warm_metrics = compute_metrics( warm_records )
    warm_table   = threshold_table( warm_records )
    delta        = latency_delta( cold_metrics, warm_metrics )
    report_md    = render_report( cold_metrics, warm_metrics, warm_table, delta, args.corpus, stamp )

    out_dir = os.path.join( root, "io", "v2-flow", f"eval-{stamp}" )
    paths   = write_outputs( out_dir, report_md, cold_records, warm_records )

    return { "out_dir": out_dir, "paths": paths, "cold": cold_metrics, "warm": warm_metrics }


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
    reply = requests.post( base_url.rstrip( "/" ) + "/auth/login",
                           json={ "email": email, "password": password }, timeout=30.0 )
    reply.raise_for_status()
    bearer = reply.json()[ "access_token" ]
    return HttpAskClient( base_url, bearer=bearer )


if __name__ == "__main__":                    # pragma: no cover - CLI wrapper, exercised by the scheduled :8000 run
    result = main()
    print( f"wrote {result[ 'paths' ][ 'report' ]}" )
