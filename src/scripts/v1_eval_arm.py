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

THE LATENCY-PARITY RULE (design §3, the load-bearing decision): measure the
SAME span in both arms — work-start → completion — and EXCLUDE v1 queue dwell.
So the v1 span is `RUNNING_ts → COMPLETED_ts` (from the transition events),
NEVER `push_received → COMPLETED` (which would include the wait in the todo
queue and flatter v2 for being synchronous — measuring the transport, not the
redesign). The completion metadata also carries `started_at`/`completed_at`, a
cross-check on the same span.

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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

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


# ─────────────────────────────────────────────────────────── record shape

@dataclass
class V1Record:
    """
    One utterance's v1-arm outcome. `ok` is True only when both transition
    timestamps were observed and a span could be computed; a failed job (no
    RUNNING/COMPLETED pair) is `ok=False` with `failure` naming why — it drops
    out of latency + is counted in the failure rate, never silently discarded.
    """
    utterance        : str
    expected_command : str
    job_id           : Optional[str]           = None
    actual_command   : Optional[str]           = None
    is_cache_hit     : bool                     = False
    queued_ts        : Optional[float]          = None   # QUEUED transition (≈ request received), epoch seconds
    running_ts       : Optional[float]          = None   # RUNNING transition (work-start), epoch seconds
    completed_ts     : Optional[float]          = None   # COMPLETED transition, epoch seconds
    span_ms          : Optional[float]          = None   # COMPUTE span: completed_ts - running_ts (EXCLUDES queue dwell)
    wall_clock_ms    : Optional[float]          = None   # WALL-CLOCK: completed_ts - queued_ts (what the user waits, dwell INCLUDED)
    ok               : bool                     = False
    failure          : Optional[str]            = None
    degradation      : Optional[str]            = None   # which DEGRADATION_PATH this job exercised, if any


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
                        transitions: Dict[str, Any], class_to_command: Dict[str, str] ) -> V1Record:
    """
    Build one V1Record from a push response + the transition observations for it.

    Requires:
        - push_result carries `job_id` (str) on success, or is falsy/`error` on a
          push failure
        - transitions is a dict with keys `running_ts`, `completed_ts` (epoch
          seconds or None) and `metadata` (the RUNNING→COMPLETED metadata dict,
          or None if the job never completed)
        - class_to_command maps agent_type → routing command

    Ensures:
        - a push that returned no job_id ⇒ ok=False, failure="push_failed"
        - a job that never reached COMPLETED (no completed_ts / no metadata) ⇒
          ok=False, failure="no_completion"; still records running_ts if seen
        - a completed job ⇒ ok iff a non-negative span was computable; records
          actual_command (mapped), is_cache_hit, span_ms, and any degradation tag
        - never raises
    """
    rec = V1Record( utterance=utterance, expected_command=expected_command )

    job_id = push_result.get( "job_id" ) if isinstance( push_result, dict ) else None
    if not job_id:
        rec.failure = "push_failed"
        return rec
    rec.job_id     = job_id
    rec.queued_ts  = transitions.get( "queued_ts" )
    rec.running_ts = transitions.get( "running_ts" )

    metadata = transitions.get( "metadata" )
    completed_ts = transitions.get( "completed_ts" )
    if not metadata or completed_ts is None:
        rec.failure = "no_completion"
        return rec

    rec.completed_ts   = completed_ts
    rec.is_cache_hit   = bool( metadata.get( "is_cache_hit" ) )
    rec.actual_command = resolve_command( metadata.get( "agent_type" ), class_to_command )
    rec.degradation    = _classify_degradation( metadata )
    # Two spans answering two questions (Cheech, design §3 + wall-clock addendum):
    #   COMPUTE (comparable across arms): RUNNING → COMPLETED, dwell EXCLUDED.
    #   WALL-CLOCK (what the v1 user feels): QUEUED → COMPLETED, dwell INCLUDED.
    # `ok` is gated on the COMPUTE span (the comparable number); wall-clock is
    # informational and may be None when queued_ts was not observed.
    rec.span_ms       = span_ms_between( rec.running_ts, rec.completed_ts )
    rec.wall_clock_ms = span_ms_between( rec.queued_ts, rec.completed_ts )
    rec.ok            = rec.span_ms is not None
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
                 class_to_command: Dict[str, str] ) -> List[V1Record]:
    """
    Drive each (utterance, expected_command) pair through the v1 arm, in order.

    Requires:
        - push_fn( utterance ) → the /api/push response dict (carries job_id)
        - collect_fn( job_id ) → { queued_ts, running_ts, completed_ts, metadata }
          observed from the job's transition events (both seams injected in tests)
        - the pairs are already sampled/ordered by the caller (pairing preserved
          across arms — design §6)

    Ensures:
        - returns one V1Record per pair, in the same order (pairing preserved)
        - a push failure short-circuits collection for that pair (no job to watch)
        - never raises on a seam that returns cleanly
    """
    records: List[V1Record] = []
    for utterance, expected_command in pairs:
        push_result = push_fn( utterance )
        job_id      = push_result.get( "job_id" ) if isinstance( push_result, dict ) else None
        transitions = collect_fn( job_id ) if job_id else {}
        records.append(
            assemble_v1_record( utterance, expected_command, push_result, transitions, class_to_command )
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

    routed_right = sum( 1 for r in ok if route_matches( r.actual_command, r.expected_command ) )
    cache_hits   = sum( 1 for r in ok if r.is_cache_hit )
    spans        = [ r.span_ms for r in ok if r.span_ms is not None ]
    wall_spans   = [ r.wall_clock_ms for r in ok if r.wall_clock_ms is not None ]
    seen_paths   = sorted( { r.degradation for r in records if r.degradation } )

    return {
        "n"                      : n,
        "ok_n"                   : ok_n,
        "failure_rate"           : _rate( n - ok_n, n ),
        "routing_accuracy"       : _rate( routed_right, ok_n ),
        "cache_hit_rate"         : _rate( cache_hits, ok_n ),
        # COMPUTE span — comparable across arms (dwell excluded); the paired gate.
        "compute_p50_ms"         : percentile( spans, 50.0 ),
        "compute_p95_ms"         : percentile( spans, 95.0 ),
        # WALL-CLOCK — what the v1 user actually waits (dwell included); a DIFFERENT
        # question, reported so v1 is never quoted as faster than anyone experiences.
        "wall_clock_p50_ms"      : percentile( wall_spans, 50.0 ),
        "wall_clock_p95_ms"      : percentile( wall_spans, 95.0 ),
        "degradation_paths_seen" : seen_paths,
        "spans"                  : spans,             # raw COMPUTE spans (for the paired median-Δ gate)
        "wall_clock_spans"       : wall_spans,        # raw WALL-CLOCK spans (informational)
    }


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
        f"compute    : RUNNING->COMPLETED (queue dwell EXCLUDED — comparable across arms, design §3)\n"
        f"wall-clock : QUEUED->COMPLETED (queue dwell INCLUDED — what the v1 user waits)\n"
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
    rows   = [
        header,
        f"utterances        : {metrics['n']} (ok {metrics['ok_n']})",
        f"failure_rate      : {_fmt( None if fail is None else fail * 100 )}%",
        f"routing_accuracy  : {_fmt( None if acc is None else acc * 100 )}%  (command-match LOWER BOUND, R-C2)",
        f"cache_hit_rate    : {_fmt( None if chr_ is None else chr_ * 100 )}%",
        "-- COMPUTE span (comparable across arms; dwell EXCLUDED; the paired gate) --",
        f"compute_p50_ms    : {_fmt( metrics['compute_p50_ms'] )}",
        f"compute_p95_ms    : {_fmt( metrics['compute_p95_ms'] )}  (INFORMATIONAL, n too small to gate)",
        "-- WALL-CLOCK to answer (what the v1 user WAITS; dwell INCLUDED; a DIFFERENT question) --",
        f"wall_clock_p50_ms : {_fmt( metrics['wall_clock_p50_ms'] )}",
        f"wall_clock_p95_ms : {_fmt( metrics['wall_clock_p95_ms'] )}",
        f"degradation_seen  : {', '.join( metrics['degradation_paths_seen'] ) or '(none)'}",
    ]
    return "\n".join( rows )


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
