"""
CJ Flow v1-arm eval client — the v1 half of the paired v1-vs-v2 go/no-go harness.

WHY THIS EXISTS (cascade ruling R-D9 / phase-4 note): the shipped `v2_eval.py`
measures ONE arm (v2, cold→warm) and says so at its own line 83 — it cannot
produce the INVEST / STOP / SPLIT verdict, which is a PAIRED v1-vs-v2 judgment.
This module is the v1 arm: it drives the v1 queue pipeline and emits the same
metric shape (routing accuracy, cache-hit rate, work-span latency) so the two
arms can be compared on one instrument.

THE TRANSPORT DIFFERENCE THAT DRIVES THE DESIGN (design §2):
    v2 arm — `POST /api/v2/ask` (synchronous; result inline).
    v1 arm — `POST /api/push` (queues.py) → the job runs through the v1 FIFO
             pipeline → its result is observed via the `job_state_transition`
             WebSocket events (QUEUED→RUNNING, RUNNING→COMPLETED).

THE LATENCY-PARITY RULE (design §3, as CORRECTED by review F1, 2026-08-15): the
ONLY cross-arm-comparable latency is measured from a CLIENT-SIDE send timestamp —
the instant just before the client POSTs → the moment the client observes
completion. No server-side boundary is trusted, so THIS arm's PRE-QUEUE
routing+embedding+cache-lookup (which `push_job` runs synchronously inside
`/api/push`, BEFORE the QUEUED/RUNNING transitions) is inside the measured span.
The earlier `RUNNING → COMPLETED` framing was WRONG — it silently dropped v1's
pre-queue work. The server-side spans (`RUNNING→COMPLETED`, `QUEUED→COMPLETED`)
are kept as INFORMATIONAL sub-spans only (the queue-dwell breakdown), NOT the
cross-arm comparison.

⚠️ HALF DONE — DO NOT DIFF THE ARMS' LATENCY YET. This client-side anchor is
implemented in the v1 arm (HERE) ONLY. The v2 arm (`v2_eval.py`) still measures
`first_useful_ms` from SERVER-SIDE request receipt (v2_eval.py:409) — it has no
send_ts / client_span. Until v2_eval.py is switched to the SAME client-side
anchor, the two arms measure DIFFERENT spans and their latency is NOT comparable
(the exact defect F1 exists to kill, just on the other arm). The paired median-Δ
gate must not be computed until both arms match.

RUN CONTEXT (design §2a — enforced by the RUN wrapper, not this pure module):
    • The v1 pipeline is EXPIRING CODE; run this against a WORKTREE PINNED at
      sha `b0735467` (the last sha carrying `todo_fifo_queue.py` +
      `routers/queues.py`), with `LUPIN_ROOT` exported to that worktree so
      config + corpus resolve from v1, not the dirty main tree
      (auto-memory `reference_worktree_testing_needs_lupin_root_override`).
    • The report header stamps the pin sha AND the sample seed — the two facts
      a reader needs to reproduce the exact baseline.

THE OPEN SEAM, KEPT HONEST (design §1 step-1 note / R-A1): the v1 done metadata
exposes `agent_type` = the agent CLASS name (job_type), NOT the routing command
the corpus keys on. Routing accuracy therefore needs an agent-class → command
map, which this module takes as an INJECTED seam (`class_to_command`). An
unmapped class resolves to actual_command=None and counts as a routing MISS —
never a fabricated hit. Command-match is a LOWER BOUND on correctness (R-C2):
same command from a different location still scores right, so it under-counts.

PURITY: every side-effecting seam (the push POST, the WS-transition collection)
is injectable, so the whole record-assembly + metric tree is unit-provable with
fakes and no server. Import-time side effects: none.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit


class EvalIntegrityError( RuntimeError ):
    """A precondition for a trustworthy measurement was violated (e.g. the COLD
    pass was not actually cold, F3) — the run is failed LOUDLY rather than
    reporting a contaminated baseline as if it were clean."""

# Bootstrap: src AND src/scripts on path (resolves through LUPIN_ROOT when the RUN
# wrapper points it at the pinned worktree; falls back to cwd for a plain unit run
# on main). src/scripts is added so `v2_eval` imports under the SAME module
# identity the shipped `test_v2_eval` uses — never a second `scripts.v2_eval` copy.
_root        = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_src_path    = os.path.join( _root, "src" )
_scripts_dir = os.path.join( _src_path, "scripts" )
for _p in ( _src_path, _scripts_dir ):
    if _p not in sys.path:               # pragma: no cover - bootstrap path guard (already present under test)
        sys.path.insert( 0, _p )

# Reuse the shipped corpus loader, seeded stratified sampler, and math helpers —
# same corpus + same statistics as the v2 arm (design §5, §6).
from v2_eval import (            # noqa: E402
    load_corpus,
    stratified_sample,
    percentile,
    _rate,
    route_matches,
)

# The v1 pin sha this arm is measured against (design §2a). Stamped in the report
# header so the baseline is non-expiring and the comparison reproducible.
V1_PIN_SHA = "b0735467"

# The six degradation paths that must all be present + distinct (design §7 floor).
# v1 surfaces failures through the completion metadata's `error` / status; a v1
# baseline reports which of these it actually exercised (it need not hit all six —
# that floor gates v2's redesign, not v1's baseline — but the column is printed).
DEGRADATION_PATHS = (
    "router_error", "extract_error", "replay_error",
    "agent_error", "queue_error", "timeout_error",
)


# ───────────────────────── the measured-sha stamp (root-cause countermeasure)
# ROOT CAUSE, one line across three layers (subprocess / worktree tests / container
# mount): code that resolves a path at runtime does not know which tree it was meant
# to measure, and every wrong answer arrives as a plausible number rather than an
# error. The countermeasure: read the sha back from the RUNNING process and ASSERT
# it — so a wrong tree fails LOUD instead of stamping a false baseline.

def _sha_matches( observed: str, expected: str ) -> bool:
    """
    True iff `observed` agrees with `expected` on `expected`'s length — so a full
    40-char sha reported by the running server matches the short pin. Both must be
    non-empty (an 8-hex-char prefix is collision-safe for this use).
    """
    return bool( observed ) and bool( expected ) and observed[ :len( expected ) ] == expected


def assert_measured_sha( observed_sha: Any, expected: str = V1_PIN_SHA ) -> str:
    """
    Assert the sha READ BACK FROM THE RUNNING SERVER is the pinned v1 sha — never
    trust the launcher's config/env for this. This turns the report's sha from a
    LABEL into an ASSERTION: on mismatch the run fails LOUD rather than recording a
    baseline measured against the wrong tree (the root cause named above).

    Requires:
        - observed_sha is the sha the LIVE process reports it booted from
          (container: the build-baked value it serves; bare host: git rev-parse of
          the process's actual code path) — NOT the launcher's intended sha

    Ensures:
        - returns the observed sha (str) when it matches `expected` on the pin length
        - raises EvalIntegrityError for a non-string / empty / mismatched observed
          sha, quoting both values — the caller must NOT record the baseline
    """
    if not isinstance( observed_sha, str ) or not _sha_matches( observed_sha, expected ):
        raise EvalIntegrityError(
            f"refusing to record the baseline: the RUNNING server reports sha "
            f"{observed_sha!r}, not the pinned v1 sha {expected!r}. The measured tree is "
            f"not the tree we meant to measure — fail loud, never stamp a false baseline."
        )
    return observed_sha


def read_running_server_sha( base_url: str ) -> str:   # pragma: no cover - live HTTP boundary
    """
    Ask the RUNNING server what sha it booted from — a value the v1 container BAKES
    at build (`git rev-parse HEAD` → served on /health), NOT the launcher's env.
    Paired with assert_measured_sha so a mismatch fails the run. (Live boundary; the
    pure, tested assertion is assert_measured_sha. The /health `git_sha` field is
    provided by the container build — design constraint: the stamp.)
    """
    import json, urllib.request
    req  = urllib.request.Request( base_url + "/health" )
    data = json.loads( urllib.request.urlopen( req, timeout=10 ).read().decode() )
    return data.get( "git_sha", "" )   # missing -> "" -> assert_measured_sha RAISES (fail-loud, not hidden)


# ─────────────────────────────────────────────────────────── record shape

@dataclass
class V1Record:
    """
    One utterance's v1-arm outcome. `ok` is True only when both transition
    timestamps were observed and a span could be computed; a failed job (no
    RUNNING/COMPLETED pair) is `ok=False` with `failure` naming why — it drops
    out of latency + is counted in the failure rate, never silently discarded.
    """
    utterance         : str
    expected_command  : str
    job_id            : Optional[str]           = None
    actual_command    : Optional[str]           = None
    is_cache_hit      : bool                     = False
    routing_eligible  : bool                     = False  # expected_command is mappable (F2) — else EXCLUDED from routing
    # Client-side clock (F1): the ONLY cross-arm-comparable span. Anchored just
    # before the POST and at the moment the client observes completion, so it
    # encloses v1's pre-queue routing+embedding+cache-lookup exactly as v2's
    # first_useful encloses its inline routing+extract+replay. No clock skew
    # (both ends are the client's clock), no trusted server boundary.
    send_ts           : Optional[float]          = None
    recv_ts           : Optional[float]          = None
    client_span_ms    : Optional[float]          = None  # (recv_ts - send_ts) — THE comparable span
    # Server-side sub-spans — INFORMATIONAL ONLY, never the cross-arm comparison
    # (F1): they show the queue-dwell breakdown but omit the pre-queue work.
    queued_ts         : Optional[float]          = None
    running_ts        : Optional[float]          = None
    completed_ts      : Optional[float]          = None
    server_compute_ms : Optional[float]          = None  # completed_ts - running_ts (queue dwell excluded)
    server_wall_ms    : Optional[float]          = None  # completed_ts - queued_ts  (queue dwell included)
    ok                : bool                     = False
    failure           : Optional[str]            = None
    degradation       : Optional[str]            = None


# ─────────────────────────────────────────────────── pure record assembly

def resolve_command( agent_type: Optional[str], class_to_command: Dict[str, str] ) -> Optional[str]:
    """
    Map a v1 job's `agent_type` (agent CLASS name) to its routing command.

    Ensures:
        - returns class_to_command[ agent_type ] when present
        - returns None for a missing/blank agent_type OR an unmapped class —
          an unmapped class is a routing MISS, never a fabricated match (R-A1)
        - never raises
    """
    if not agent_type:
        return None
    return class_to_command.get( agent_type )


def span_ms_between( running_ts: Optional[float], completed_ts: Optional[float] ) -> Optional[float]:
    """
    Ensures:
        - returns (completed_ts - running_ts) * 1000, the WORK span in ms, when
          both are present AND completed_ts >= running_ts
        - returns None when either is missing OR the pair is out of order (a
          negative span is corrupt, not a measurement) — never raises
    """
    if running_ts is None or completed_ts is None:
        return None
    delta = ( completed_ts - running_ts ) * 1000.0
    if delta < 0:
        return None
    return delta


def assemble_v1_record( utterance: str, expected_command: str, push_result: Dict[str, Any],
                        transitions: Dict[str, Any], class_to_command: Dict[str, str],
                        *, send_ts: Optional[float] = None, recv_ts: Optional[float] = None,
                        mappable_commands: Optional[Sequence[str]] = None ) -> V1Record:
    """
    Build one V1Record from a push response + the transition observations for it.

    Requires:
        - push_result carries `job_id` (str) on success, or is falsy/`error` on a
          push failure
        - transitions is a dict with `queued_ts`, `running_ts`, `completed_ts`
          (epoch seconds or None) and `metadata` (the COMPLETED metadata, or None
          if the job never terminally completed). BLOCKING CONTRACT (F4): a
          non-terminal `collect_fn` return — one WITHOUT a completed_ts+metadata
          pair — is treated as a FAILURE (no_completion), never a completion, so a
          still-running cold job can never masquerade as done.
        - send_ts / recv_ts are the CLIENT-side send and completion-observed
          timestamps (F1); their difference is the ONLY comparable span
        - mappable_commands is the set of routing commands v1 CAN score (the
          class_to_command values); an expected_command outside it is EXCLUDED
          from routing (F2), never a forced miss. Defaults to the map's own values.

    Ensures:
        - no job_id ⇒ ok=False, failure="push_failed"
        - no terminal completion ⇒ ok=False, failure="no_completion"
        - a completed job ⇒ ok iff the client span (recv-send) is computable;
          records actual_command, is_cache_hit, routing_eligible, the comparable
          client_span_ms, the informational server sub-spans, and any degradation
        - never raises
    """
    rec = V1Record( utterance=utterance, expected_command=expected_command,
                    send_ts=send_ts, recv_ts=recv_ts )
    mappable = set( mappable_commands ) if mappable_commands is not None else set( class_to_command.values() )
    rec.routing_eligible = expected_command in mappable          # F2: only mappable utterances score routing

    job_id = push_result.get( "job_id" ) if isinstance( push_result, dict ) else None
    if not job_id:
        rec.failure = "push_failed"
        return rec
    rec.job_id     = job_id
    rec.queued_ts  = transitions.get( "queued_ts" )
    rec.running_ts = transitions.get( "running_ts" )

    metadata = transitions.get( "metadata" )
    completed_ts = transitions.get( "completed_ts" )
    if not metadata or completed_ts is None:                     # F4: partial return ⇒ NOT a completion
        rec.failure = "no_completion"
        return rec

    rec.completed_ts   = completed_ts
    rec.is_cache_hit   = bool( metadata.get( "is_cache_hit" ) )
    rec.actual_command = resolve_command( metadata.get( "agent_type" ), class_to_command )
    rec.degradation    = _classify_degradation( metadata )
    # F1 — the ONLY comparable span is client-side send→observed-completion.
    rec.client_span_ms = span_ms_between( rec.send_ts, rec.recv_ts )
    # Informational server sub-spans (NOT the cross-arm comparison): they omit the
    # pre-queue routing+embedding+cache-lookup /api/push runs synchronously.
    rec.server_compute_ms = span_ms_between( rec.running_ts, rec.completed_ts )
    rec.server_wall_ms    = span_ms_between( rec.queued_ts, rec.completed_ts )
    rec.ok                = rec.client_span_ms is not None
    if not rec.ok:
        rec.failure = "bad_span"
    return rec


def _classify_degradation( metadata: Dict[str, Any] ) -> Optional[str]:
    """
    Ensures:
        - returns the metadata's explicit `degradation_path` when it names one of
          DEGRADATION_PATHS
        - else returns "agent_error" when the metadata carries a non-empty `error`
          (a failed job exercised the generic agent-error path)
        - else None (a clean completion exercised no degradation path)
        - never raises
    """
    named = metadata.get( "degradation_path" )
    if named in DEGRADATION_PATHS:
        return named
    if metadata.get( "error" ):
        return "agent_error"
    return None


# ─────────────────────────────────────────────────────────── pass driver

def run_v1_pass( pairs: Sequence[Tuple[str, str]], *, push_fn: Callable[[str], Dict[str, Any]],
                 collect_fn: Callable[[str], Dict[str, Any]],
                 class_to_command: Dict[str, str],
                 clock: Callable[[], float] = time.monotonic ) -> List[V1Record]:
    """
    Drive each (utterance, expected_command) pair through the v1 arm, in order.

    Requires:
        - push_fn( utterance ) → the /api/push response dict (carries job_id)
        - collect_fn( job_id ) → { queued_ts, running_ts, completed_ts, metadata },
          and it MUST BLOCK until the job terminally completes (F4) — a partial
          return is scored as a failure, never a completion, by assemble
        - clock() → the CLIENT monotonic clock; stamped just before push (send_ts)
          and just after collect returns (recv_ts) so the comparable span (F1) is
          purely client-side. Injected in tests.
        - the pairs are already sampled/ordered by the caller (pairing preserved)

    Ensures:
        - returns one V1Record per pair, in the same order (pairing preserved)
        - a push failure short-circuits collection for that pair (no job to watch)
        - every record shares ONE mappable-command set (F2), computed once
        - never raises on a seam that returns cleanly
    """
    mappable = list( class_to_command.values() )
    records: List[V1Record] = []
    for utterance, expected_command in pairs:
        send_ts     = clock()
        push_result = push_fn( utterance )
        job_id      = push_result.get( "job_id" ) if isinstance( push_result, dict ) else None
        if job_id:
            transitions = collect_fn( job_id )     # BLOCKS until terminal (F4)
            recv_ts     = clock()
        else:
            transitions, recv_ts = {}, None
        records.append(
            assemble_v1_record( utterance, expected_command, push_result, transitions, class_to_command,
                                send_ts=send_ts, recv_ts=recv_ts, mappable_commands=mappable )
        )
    return records


# ──────────────────────────────────────────────────────── metric compute

def compute_v1_metrics( records: List[V1Record] ) -> Dict[str, Any]:
    """
    Compute the v1-arm metric row (the shape the paired table consumes).

    Ensures:
        - returns a dict with: n, ok_n, failure_rate, routing_accuracy (over OK
          records, command-match LOWER BOUND R-C2), cache_hit_rate (over OK
          records), latency_p50_ms / latency_p95_ms (over OK spans),
          degradation_paths_seen (sorted list), spans (the raw OK span list, for
          the paired median-Δ gate)
        - rates are None when their denominator is 0 (never a divide-by-zero, never
          a fabricated 0.0) — see _rate
        - never raises
    """
    n     = len( records )
    ok    = [ r for r in records if r.ok ]
    ok_n  = len( ok )

    # F2 — routing is scored ONLY over routing-eligible ok records (mappable,
    # non-agentic); ineligible utterances are EXCLUDED from the denominator (not
    # forced misses) and their count + corpus share are reported so the exclusion
    # is auditable, never silent. The v2 arm must exclude the SAME utterances.
    eligible     = [ r for r in ok if r.routing_eligible ]
    excluded_n   = sum( 1 for r in records if not r.routing_eligible )
    routed_right = sum( 1 for r in eligible if route_matches( r.actual_command, r.expected_command ) )

    cache_hits    = sum( 1 for r in ok if r.is_cache_hit )
    client_spans  = [ r.client_span_ms    for r in ok if r.client_span_ms    is not None ]
    compute_spans = [ r.server_compute_ms for r in ok if r.server_compute_ms is not None ]
    wall_spans    = [ r.server_wall_ms    for r in ok if r.server_wall_ms    is not None ]
    seen_paths    = sorted( { r.degradation for r in records if r.degradation } )

    return {
        "n"                      : n,
        "ok_n"                   : ok_n,
        "failure_rate"           : _rate( n - ok_n, n ),
        # F2 routing over eligible only, with the exclusion made visible.
        "routing_eligible_n"     : len( eligible ),
        "routing_excluded_n"     : excluded_n,
        "routing_excluded_share" : _rate( excluded_n, n ),
        "routing_accuracy"       : _rate( routed_right, len( eligible ) ),
        "cache_hit_rate"         : _rate( cache_hits, ok_n ),
        # F1 — the CROSS-ARM COMPARABLE span: client send → observed completion.
        "client_p50_ms"          : percentile( client_spans, 50.0 ),
        "client_p95_ms"          : percentile( client_spans, 95.0 ),
        "spans"                  : client_spans,      # raw COMPARABLE spans (the paired median-Δ gate)
        # INFORMATIONAL server sub-spans (NOT the comparison): the dwell breakdown.
        "server_compute_p50_ms"  : percentile( compute_spans, 50.0 ),
        "server_wall_p50_ms"     : percentile( wall_spans, 50.0 ),
        "degradation_paths_seen" : seen_paths,
    }


# ─────────────────────────────── transition-event parsing (collector core)

# The v1 JobState string values (job_state.py) the WS events carry in `to_state`.
_ST_QUEUED    = "queued"
_ST_RUNNING   = "running"
_ST_COMPLETED = "completed"


def _iso_to_epoch( iso: Any ) -> Optional[float]:
    """
    Ensures:
        - parses an ISO-8601 string (the event `timestamp`, aware) to epoch seconds
        - returns None for None / non-string / unparseable — never raises, so one
          malformed stamp cannot crash a whole pass
    """
    import datetime
    if not isinstance( iso, str ):
        return None
    try:
        return datetime.datetime.fromisoformat( iso ).timestamp()
    except ValueError:
        return None


def parse_transitions( events: Sequence[Dict[str, Any]] ) -> Dict[str, Any]:
    """
    Reduce ONE job's `job_state_transition` events into the transitions dict
    assemble_v1_record consumes.

    Requires:
        - events is the list of job_state_transition payloads for a SINGLE job
          (each { to_state, timestamp (ISO), metadata? }), already job-filtered

    Ensures:
        - returns { queued_ts, running_ts, completed_ts, metadata }, timestamps in
          epoch seconds (QUEUED/RUNNING/COMPLETED transitions); metadata is the
          COMPLETED event's metadata (the completion payload), else None
        - a terminal FAILURE (failed/cancelled/…) leaves completed_ts + metadata
          None ⇒ the record reads no_completion (honest: no usable span), never a
          fabricated completion
        - never raises (a malformed timestamp becomes None via _iso_to_epoch)
    """
    out: Dict[str, Any] = { "queued_ts": None, "running_ts": None, "completed_ts": None, "metadata": None }
    for ev in events:
        to = ev.get( "to_state" )
        ts = _iso_to_epoch( ev.get( "timestamp" ) )
        if to == _ST_QUEUED:
            out[ "queued_ts" ] = ts
        elif to == _ST_RUNNING:
            out[ "running_ts" ] = ts
        elif to == _ST_COMPLETED:
            out[ "completed_ts" ] = ts
            out[ "metadata" ]     = ev.get( "metadata" )
    return out


# ──────────────────────────────────── routing-command map (R-A1 seam)

DEFAULT_COMMAND_TEMPLATE = "agent router go to {mode}"


def build_class_to_command( mode_to_agent: Dict[str, Any],
                            template: str = DEFAULT_COMMAND_TEMPLATE ) -> Tuple[Dict[str, str], List[str]]:
    """
    Invert v1's MODE_TO_AGENT ({mode: AgentClass}) into {agent_class_name: command},
    the map `resolve_command` needs (the v1 done metadata carries the CLASS name,
    not the command — R-A1).

    Requires:
        - mode_to_agent maps a mode string → an agent class (has `__name__`)
        - template formats a mode into its routing command ("...go to {mode}")

    Ensures:
        - returns ( class_to_command, ambiguous ) where class_to_command maps each
          agent class name to its command
        - AMBIGUITY IS EXCLUDED, NOT GUESSED: if one class is reachable from >1
          mode (⇒ >1 command), it is DROPPED from the map and named in `ambiguous`
          — resolve_command then returns None for it (a routing MISS), never a
          coin-flip between two commands (honest under-count, R-A1 lower bound)
        - never raises

    KNOWN GAP (named, not hidden): agentic modes route via AGENTIC_MODE_MAP with
    full command strings, NOT through MODE_TO_AGENT, so they are absent here and
    their utterances score as misses — the command-match lower bound (R-C2), made
    explicit rather than papered over.
    """
    by_class: Dict[str, str] = {}
    ambiguous: set = set()
    for mode, agent_cls in mode_to_agent.items():
        name    = getattr( agent_cls, "__name__", str( agent_cls ) )
        command = template.format( mode=mode )
        if name in by_class and by_class[ name ] != command:
            ambiguous.add( name )
        else:
            by_class[ name ] = command
    for name in ambiguous:
        by_class.pop( name, None )
    return by_class, sorted( ambiguous )


# ─────────────────────────────────────────── cold/warm two-pass driver

def run_two_pass( pairs: Sequence[Tuple[str, str]], *, push_fn: Callable[[str], Dict[str, Any]],
                  collect_fn: Callable[[str], Dict[str, Any]],
                  class_to_command: Dict[str, str],
                  clock: Callable[[], float] = time.monotonic,
                  assert_cold: bool = True ) -> Dict[str, Any]:
    """
    Run the corpus twice (COLD then WARM) — the pair a single pass cannot produce
    (design §6): COLD measures routing + first-response against an empty cache;
    WARM, immediately after, measures the cache-hit rate the warm pass generates.

    Requires:
        - pairs already sampled + ordered (identical list both passes, pairing
          preserved); the seams populate/serve the cache between passes
        - push_fn / collect_fn / class_to_command / clock as for run_v1_pass

    Ensures:
        - returns { "cold": <metrics>, "warm": <metrics> }
        - F3 COLD-START GUARD: when assert_cold, a cold pass whose cache_hit_rate
          is > 0 means the store was pre-warmed (a prior run or the other arm) —
          the baseline is contaminated, so this RAISES EvalIntegrityError rather
          than reporting a flattering cold number as clean. (A per-run table tag
          is the cheaper fix when available; this assertion is the floor that
          fails the run loudly when it is not.)
        - never raises on clean seams EXCEPT the cold-start guard above
    """
    cold = compute_v1_metrics( run_v1_pass( pairs, push_fn=push_fn, collect_fn=collect_fn,
                                            class_to_command=class_to_command, clock=clock ) )
    if assert_cold and cold[ "cache_hit_rate" ] is not None and cold[ "cache_hit_rate" ] > 0:
        raise EvalIntegrityError(
            f"COLD pass was not cold: cache_hit_rate={cold['cache_hit_rate']} > 0 — the snapshot store "
            f"was pre-warmed (prior run or the other arm). Scope a per-run table or empty the store "
            f"before the cold pass; refusing to report a contaminated baseline (F3)."
        )
    warm = compute_v1_metrics( run_v1_pass( pairs, push_fn=push_fn, collect_fn=collect_fn,
                                            class_to_command=class_to_command, clock=clock ) )
    return { "cold": cold, "warm": warm }


# ───────────────────────────────────────────────────────────── reporting

def build_report_header( *, seed: int, corpus: str, n_per_command: int, base_url: str ) -> str:
    """
    Ensures:
        - returns the report header stamping the v1 PIN SHA and the sample SEED
          (design §2a/§5 — the two reproducibility facts), plus corpus + arm
    """
    return (
        f"# CJ Flow v1-arm baseline\n"
        f"v1_pin_sha : {V1_PIN_SHA}   (measured against the pinned worktree)\n"
        f"seed       : {seed}\n"
        f"corpus     : {corpus}   n_per_command={n_per_command}\n"
        f"base_url   : {base_url}\n"
        f"comparable : CLIENT send -> observed completion (F1). ⚠️ v1 arm ONLY so far — v2_eval.py still\n"
        f"             measures server-side first_useful; DO NOT diff arm latency until v2 matches.\n"
        f"server sub-spans (informational): RUNNING->COMPLETED (dwell excl), QUEUED->COMPLETED (dwell incl)\n"
    )


def _fmt( value: Optional[float] ) -> str:
    """Ensures: '<n/a>' for None, else the value at 1 decimal."""
    return "<n/a>" if value is None else f"{value:.1f}"


def render_v1_report( metrics: Dict[str, Any], *, seed: int, corpus: str,
                      n_per_command: int, base_url: str ) -> str:
    """
    Ensures:
        - returns the full v1-arm report: header (with pin sha + seed) + the
          metric rows, rates rendered '<n/a>' when their denominator was 0
    """
    header = build_report_header( seed=seed, corpus=corpus, n_per_command=n_per_command, base_url=base_url )
    acc    = metrics[ "routing_accuracy" ]
    chr_   = metrics[ "cache_hit_rate" ]
    fail   = metrics[ "failure_rate" ]
    excl   = metrics[ "routing_excluded_share" ]
    rows   = [
        header,
        f"utterances            : {metrics['n']} (ok {metrics['ok_n']})",
        f"failure_rate          : {_fmt( None if fail is None else fail * 100 )}%",
        "-- ROUTING (scored over MAPPABLE utterances only; same exclusion both arms, F2) --",
        f"routing_accuracy      : {_fmt( None if acc is None else acc * 100 )}%  "
        f"(over {metrics['routing_eligible_n']} eligible; command-match LOWER BOUND, R-C2)",
        f"routing_excluded      : {metrics['routing_excluded_n']} utterances "
        f"({_fmt( None if excl is None else excl * 100 )}% of corpus — unmappable/agentic, EXCLUDED not missed)",
        f"cache_hit_rate        : {_fmt( None if chr_ is None else chr_ * 100 )}%",
        "-- LATENCY: the CROSS-ARM COMPARABLE span is client send -> observed completion (F1) --",
        f"client_p50_ms         : {_fmt( metrics['client_p50_ms'] )}",
        f"client_p95_ms         : {_fmt( metrics['client_p95_ms'] )}  (INFORMATIONAL, n too small to gate)",
        "-- server sub-spans below are INFORMATIONAL ONLY — NOT the cross-arm comparison (they omit "
        "the pre-queue routing/embedding/cache work /api/push does synchronously) --",
        f"server_compute_p50_ms : {_fmt( metrics['server_compute_p50_ms'] )}  (RUNNING->COMPLETED, dwell excluded)",
        f"server_wall_p50_ms    : {_fmt( metrics['server_wall_p50_ms'] )}  (QUEUED->COMPLETED, dwell included)",
        f"degradation_seen      : {', '.join( metrics['degradation_paths_seen'] ) or '(none)'}",
    ]
    return "\n".join( rows )


# ─────────────────────────────────────────────────── run orchestrator

def run_v1_baseline( *, corpus: str = "simple", seed: int = 1024, n_per_command: int = 60,
                     base_url: str = "http://localhost:8000",
                     push_fn: Callable[[str], Dict[str, Any]],
                     collect_fn: Callable[[str], Dict[str, Any]],
                     class_to_command: Dict[str, str], limit: Optional[int] = None,
                     clock: Callable[[], float] = time.monotonic, assert_cold: bool = True,
                     load_corpus_fn: Callable[..., Any] = load_corpus,
                     sample_fn: Callable[..., Any] = stratified_sample ) -> Dict[str, Any]:
    """
    Compose the full v1 baseline: load the corpus → seeded stratified sample →
    COLD/WARM two-pass → metrics → rendered report (warm pass is the headline).

    Requires:
        - push_fn / collect_fn drive the LIVE v1 server (injected; the RUN wrapper
          supplies the real WS-listening seams against the pinned-worktree server)
        - class_to_command is the R-A1 map (build_class_to_command output)
        - load_corpus_fn / sample_fn default to the shipped v2_eval helpers (same
          corpus + same seeded stratified sampler as the v2 arm — pairing preserved)

    Ensures:
        - returns { cold, warm, manifest, report, sampled_n }; the report header
          stamps the v1 pin sha + the seed (reproducibility, design §2a/§5) and
          both span boundaries (compute vs wall-clock)
        - the SAME sampled utterance list runs both passes (cache warms between
          them); never raises on seams that return cleanly
    """
    pairs             = load_corpus_fn( corpus, limit=limit )
    sampled, manifest = sample_fn( pairs, n_per_command, seed )
    passes            = run_two_pass( sampled, push_fn=push_fn, collect_fn=collect_fn,
                                      class_to_command=class_to_command, clock=clock,
                                      assert_cold=assert_cold )
    report            = render_v1_report( passes[ "warm" ], seed=seed, corpus=corpus,
                                          n_per_command=n_per_command, base_url=base_url )
    return {
        "cold"      : passes[ "cold" ],
        "warm"      : passes[ "warm" ],
        "manifest"  : manifest,
        "report"    : report,
        "sampled_n" : len( sampled ),
    }


# ───────────────────────── cold-start truncation (F3, :8000-guarded)

SNAPSHOT_TABLE = "solution_snapshots"   # the fixed Postgres snapshot table (ORM __tablename__)

# The measurement databases the destructive cold-truncate MAY target — exactly
# these two, matched on the url's db NAME (not a substring), so dev/prod/unparented
# are refused even when they share a prefix. The v1 baseline server runs on its OWN
# db (lupin_db_v1baseline), never the shared :8000 test db, so a cold TRUNCATE can
# never wipe a live :8000 run; lupin_db_test stays allowed for the v2 arm's own runs
# (design src/rnd/v0.2.0/2026.08.15-v1-baseline-standalone-server-design.md, constraint A).
MEASUREMENT_DB_NAMES = frozenset( { "lupin_db_test", "lupin_db_v1baseline" } )


def _db_name( db_url: str ) -> str:
    """
    The database name = the PATH component of the url, minus its leading '/'.
    Parsed with urlsplit so a query ('?...') or fragment ('#...') — either of
    which can contain a '/' — can NEVER be mistaken for the db name.

    This closes the de9c32d0 hole (Cheech): a naive rsplit('/') picked up a
    '/lupin_db_test' smuggled into the query/fragment and would have TRUNCATEd the
    real db in the path, e.g.
      'postgresql://u:p@h/lupin_db_dev?options=-c search_path=/lupin_db_test'
      'postgresql://u:p@h/lupin_db_dev#/lupin_db_test'
    both now resolve to 'lupin_db_dev' (refused). 'postgresql://.../lupin_db_test?
    sslmode=require' -> 'lupin_db_test'; a path-less url yields ''. Ensures: a str.
    """
    return urlsplit( db_url ).path.lstrip( "/" )


def assert_test_db( db_url: Any ) -> None:
    """
    Refuse to proceed unless the connection targets a MEASUREMENT database — the
    shared :8000 test db (lupin_db_test) OR the dedicated v1-baseline db
    (lupin_db_v1baseline). Never the dev db, never prod, never an unparented url.

    The truncation MAKES the cold pass cold (the stronger guarantee that pairs
    with the assert-cold floor). But a TRUNCATE is irreversible, so this is the
    hard precondition (Cheech): fire LOUD and never proceed on an unexpected
    target. The v1 baseline uses its OWN db, so this can never wipe a live :8000
    run; widening to an allow-list did NOT weaken the dev/prod refusal — the db
    NAME must match the set EXACTLY (a substring check would let 'lupin_db_test'
    smuggle in a 'lupin_db_test_shadow'; exact-name closes that).

    Ensures:
        - returns None when db_url is a string whose db name is in MEASUREMENT_DB_NAMES
        - raises EvalIntegrityError for any other / missing / non-string target,
          with the offending value quoted — the caller must not TRUNCATE
    """
    if not isinstance( db_url, str ) or _db_name( db_url ) not in MEASUREMENT_DB_NAMES:
        raise EvalIntegrityError(
            f"refusing to TRUNCATE: the DB target is not a measurement database "
            f"(allowed db names: {sorted( MEASUREMENT_DB_NAMES )}); got {db_url!r}. "
            f"Fail loud, never proceed."
        )


def _connection_url( connection: Any ) -> str:
    """
    Derive the DB url FROM the connection that will execute (SQLAlchemy
    `connection.engine.url`). Single source of truth: the url we CHECK is the url
    that will RUN — a separate db_url argument could name the test DB while the
    connection points elsewhere (the mismatch Cheech flagged). Ensures: str url.
    """
    return str( connection.engine.url )


def truncate_snapshots( connection: Any ) -> str:
    """
    Empty the snapshot table so the cold pass starts genuinely cold — but ONLY
    after proving, from the connection ITSELF, that the target is the :8000 test DB.

    Requires:
        - connection is the live DB connection the TRUNCATE will run on; its url is
          read off `connection.engine.url` (not a separate, possibly-mismatched arg)
          and it exposes `.execute( sql )`

    Ensures:
        - the guard url is DERIVED from `connection` (no decoupled db_url can lie
          about the target); assert_test_db runs FIRST — on a wrong target it
          RAISES and connection.execute is NEVER called (no TRUNCATE on the wrong DB)
        - on the test DB, truncates the FIXED SNAPSHOT_TABLE (a constant, never a
          caller-supplied identifier → no injection surface) and returns its name
    """
    assert_test_db( _connection_url( connection ) )   # url derived from the executing connection
    connection.execute( f"TRUNCATE TABLE {SNAPSHOT_TABLE}" )
    return SNAPSHOT_TABLE


# ────────────────────────────────────────── live IO seams (injected away)

def _default_push_fn( base_url: str, websocket_id: str,
                      token: str ) -> Callable[[str], Dict[str, Any]]:   # pragma: no cover - live HTTP boundary
    """Build a push_fn that POSTs one utterance to /api/push on the v1 server."""
    import json, urllib.request
    def _push( utterance: str ) -> Dict[str, Any]:
        body = json.dumps( { "question": utterance, "websocket_id": websocket_id } ).encode()
        req  = urllib.request.Request(
            base_url + "/api/push", data=body,
            headers={ "Authorization": f"Bearer {token}", "Content-Type": "application/json" }, method="POST" )
        try:
            return json.loads( urllib.request.urlopen( req, timeout=30 ).read().decode() )
        except Exception as e:
            return { "error": str( e ) }
    return _push


def _default_collect_fn( ws_recv_events: Callable[[str], Sequence[Dict[str, Any]]] ) -> Callable[[str], Dict[str, Any]]:   # pragma: no cover - live WS boundary
    """
    Build a collect_fn from a raw WS-event source. `ws_recv_events( job_id )` is
    the live boundary — it subscribes to the queue WebSocket and returns that
    job's `job_state_transition` payloads (until COMPLETED or a timeout). The
    REDUCTION of those events into timestamps is the pure, tested parse_transitions
    — so the only unproven surface here is the socket receive itself.
    """
    def _collect( job_id: str ) -> Dict[str, Any]:
        return parse_transitions( ws_recv_events( job_id ) )
    return _collect


def load_v1_class_to_command():   # pragma: no cover - imports the live v1 registry from the pinned worktree
    """
    Build the routing-command map from the LIVE v1 registry (MODE_TO_AGENT),
    resolved through LUPIN_ROOT — so it reads the PINNED WORKTREE's v1 code, not
    the dirty main tree (design §2a). Returns ( class_to_command, ambiguous ).
    The WS-transition collector is deliberately NOT stubbed here: it is built and
    exercised WITH the live run against the worktree server, never shipped as an
    untested boundary that reads as done.
    """
    from cosa.rest.todo_fifo_queue import MODE_TO_AGENT
    return build_class_to_command( MODE_TO_AGENT )


def build_arg_parser() -> argparse.ArgumentParser:
    """The v1-arm CLI (design §5): corpus, seed, per-command n, base url, limit."""
    parser = argparse.ArgumentParser( description="CJ Flow v1-arm eval client (paired go/no-go, v1 half)" )
    parser.add_argument( "--corpus",        default="simple", help="corpus name (simple|weather)" )
    parser.add_argument( "--seed",          type=int, default=1024, help="sampling seed (stamped in report)" )
    parser.add_argument( "--n-per-command", type=int, default=60, help="stratified sample size per command" )
    parser.add_argument( "--base-url",      default="http://localhost:8000", help="v1 server base url (:8000 scheduled)" )
    parser.add_argument( "--limit",         type=int, default=None, help="cap utterances per command (debug)" )
    return parser


if __name__ == "__main__":   # pragma: no cover - CLI entry, exercised via the scheduled RUN wrapper
    print( "v1_eval_arm is the v1 half of the paired harness; run it via the scheduled :8000 wrapper "
           f"against the pinned worktree at {V1_PIN_SHA} with LUPIN_ROOT exported to it." )
