"""
CJ Flow paired v1-vs-v2 go/no-go LATENCY verdict — the provenance-gated caller AND the
paired median-Δ gate itself (design §6, 2026.08.14-v2-paired-go-no-go-harness-design.md).

WHY THIS MODULE OWNS THE GATE. The median-Δ latency verdict is inherently CROSS-ARM: it
pairs v1's and v2's per-utterance spans and compares them. It was originally drafted inside
v2_eval.py as `median(v2_spans) − median(v1_spans)` — a difference of INDEPENDENT medians
over two flat, identity-less lists, which is a DIFFERENT statistic from the spec's
median-of-per-utterance-deltas and carried no ≥20% PASS/FAIL (Tiffany's B2,
2026.08.16-v2-eval-adversarial-review.md). The gate lives HERE now, rebuilt to §6, because
this is the one place that sees BOTH arms; v2_eval and v1_eval_arm each measure one arm and
emit `spans_by_utterance`, and this module aligns them.

THE §6 COMPUTATION (design lines 121-126), exactly:
    - both arms measured the SAME sampled utterances (proven by the provenance check below);
    - per shared utterance u:  Δ(u) = v1_span(u) − v2_span(u)  — POSITIVE ⇒ v2 is faster;
    - a pair is DROPPED when either arm has no usable span for u, and the drop count is RECORDED;
    - GATE = median(Δ), and it PASSES iff median(Δ) ≥ 20% of the v1 median (v2 is ≥20% faster);
    - p95 is REPORTED, never GATING (at n=60 one tail outlier moves it — design §1.5).

Median-of-deltas is NOT the same as difference-of-medians (median is not linear): on paired
data the two can give opposite verdicts. That separation is what the gate's regression test
pins — a fixture where the two disagree, so reverting to the old statistic goes red.

THE PROVENANCE CHECK (review fix #1). The gate is meaningless unless both arms measured the
SAME sample. Before it fires, `paired_provenance_check` refuses unless both provenance stamps
agree on corpus + seed + n_per_command + a SIGNATURE of the exact (utterance, command) pairs.
A mismatch names every disagreeing field and emits NO number.

THE INSTRUMENT RESIDUAL (review fix #2, Cheech's ruling). The verdict names the FULL latency
asymmetry IN the string that prints in the table — not in prose a reader skips: v1's span
includes its whole FIFO queue-dwell, v2's has no queue. Legitimate for an end-to-end UX
verdict; the risk is only that delta_ms is misread as compute-only, so the caveat rides WITH
the number.

WHAT IT IS NOT. This is the LATENCY row of the §1.5 go/no-go table plus its provenance gate —
not the whole table (the human replay-correctness floor, the vetoes, the INVEST/STOP/SPLIT
roll-up are the eval's larger definition of done). And the LIVE combined run (v1 arm against
its pinned worktree, v2 against main) is a separate scheduled step; this consumes the two
artifacts those runs produce.

VENUE. PURE — reads two on-disk artifacts and does arithmetic. Unit tests are :7999,
AI-discretionary, no server, no inference. The runs that PRODUCE the artifacts are the
:8000-scheduled arm runs.

Design: 2026.08.14-v2-paired-go-no-go-harness-design.md §6; 2026.08.14-cj-flow-v2-phases-2-3-
and-evaluation.md §1.3-§1.5; review: 2026.08.16-v2-eval-adversarial-review.md (B2, B3, fixes #1/#2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: src AND src/scripts on path so `import cosa...` resolves. Resolves
# through LUPIN_ROOT when a run wrapper points it at a specific tree.
# ---------------------------------------------------------------------------
_root        = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_src_path    = os.path.join( _root, "src" )
_scripts_dir = os.path.join( _src_path, "scripts" )
for _p in ( _src_path, _scripts_dir ):
    if _p not in sys.path:               # pragma: no cover - bootstrap path guard (already present under test)
        sys.path.insert( 0, _p )

import cosa.utils.util as du   # noqa: E402


# The provenance-stamp fields every arm artifact must carry. `sample_signature` is the
# load-bearing one: two arms measured the same utterances IFF their signatures match.
PROVENANCE_FIELDS = ( "arm", "corpus", "seed", "n_per_command", "sample_signature", "sampled_n" )

# The §6 gate bar: v2 must be at least this fraction faster than v1 (median-Δ ≥ 20% of the
# v1 median). Named so the threshold is one edit, never a magic literal in the arithmetic.
PASS_FRACTION = 0.20

# The instrument string that PRINTS IN THE VERDICT TABLE (fix #2). It names the full
# asymmetry — v1's FIFO queue-dwell is INSIDE its span, v2 has no queue — so a reader can
# never take delta_ms for a compute-only difference.
INSTRUMENT = (
    "client_send end-to-end UX span, PAIRED per utterance (Δ = v1 − v2; positive ⇒ v2 faster). "
    "v1's span INCLUDES its full FIFO queue-dwell (POST /api/push, then block until the completed "
    "WS event) plus network + serialization; v2 is one synchronous round-trip with NO queue. "
    "Legitimate for an end-to-end UX-latency verdict — delta_ms is NOT a compute-only difference."
)


# ---------------------------------------------------------------------------
# The sample signature — what actually binds two arms to one measured sample.
# ---------------------------------------------------------------------------
def compute_sample_signature( pairs: Sequence[ Tuple[ str, str ] ] ) -> str:
    """
    A deterministic, order-independent fingerprint of the (utterance, command) pairs.

    Requires:
        - pairs is a sequence of (utterance, expected_command) 2-tuples.

    Ensures:
        - returns the sha256 hex of the SORTED, DEDUPED pair set, so two arms that
          measured the same utterances (in any order) produce the same signature and
          two arms that measured different utterances cannot collide.
        - binds BOTH the utterance text AND its expected command (a unit separator
          between the two keeps "a","bc" distinct from "ab","c").
    """
    encoded = sorted( { f"{utterance}\x1f{command}" for utterance, command in pairs } )
    joined  = "\x1e".join( encoded )
    return hashlib.sha256( joined.encode( "utf-8" ) ).hexdigest()


def make_provenance(
    arm           : str,
    corpus        : str,
    seed          : Optional[ int ],
    n_per_command : Optional[ int ],
    sampled_pairs : Sequence[ Tuple[ str, str ] ],
) -> Dict[ str, Any ]:
    """
    Build the provenance stamp an arm attaches to its serialized result.

    Requires:
        - arm is "v1" or "v2"; corpus is the corpus name both arms load.
        - seed / n_per_command describe the sampler (None on a limit-based run that
          did not sample — such an arm can never pair with a seeded one, by design).
        - sampled_pairs is the exact (utterance, expected_command) set the arm measured.

    Ensures:
        - returns a dict carrying exactly PROVENANCE_FIELDS, with sample_signature
          computed from sampled_pairs and sampled_n = len( sampled_pairs ).
    """
    return {
        "arm"              : arm,
        "corpus"           : corpus,
        "seed"             : seed,
        "n_per_command"    : n_per_command,
        "sample_signature" : compute_sample_signature( sampled_pairs ),
        "sampled_n"        : len( sampled_pairs ),
    }


# ---------------------------------------------------------------------------
# The provenance check — fix #1. Runs BEFORE the gate; refuses to let it fire on
# two arms that did not measure the same thing.
# ---------------------------------------------------------------------------
def _missing_provenance_fields( provenance: Dict[ str, Any ] ) -> List[ str ]:
    """The PROVENANCE_FIELDS absent from `provenance` (a malformed stamp names itself)."""
    return [ field for field in PROVENANCE_FIELDS if field not in provenance ]


def paired_provenance_check(
    v1_provenance : Dict[ str, Any ],
    v2_provenance : Dict[ str, Any ],
) -> Optional[ str ]:
    """
    None iff the two arms provably measured the SAME paired sample; else a reason
    string naming EVERY disagreement. Never raises.

    Ensures:
        - returns a reason string when either stamp is missing a PROVENANCE_FIELD,
          when either reports sampled_n == 0 (an empty arm cannot be paired), or when
          corpus / seed / n_per_command / sample_signature disagree — every failing
          check contributes its own clause so the refusal is auditable, not a bare "no".
        - returns None only when all fields are present, both samples are non-empty,
          and all four binding fields agree (the signature being the authoritative one).
    """
    reasons : List[ str ] = []

    v1_missing = _missing_provenance_fields( v1_provenance )
    v2_missing = _missing_provenance_fields( v2_provenance )
    if v1_missing:
        reasons.append( f"v1 provenance is missing field(s): {', '.join( v1_missing )}" )
    if v2_missing:
        reasons.append( f"v2 provenance is missing field(s): {', '.join( v2_missing )}" )
    if reasons:
        return "; ".join( reasons )   # a malformed stamp cannot be compared field-by-field

    if v1_provenance[ "sampled_n" ] == 0:
        reasons.append( "v1 measured 0 utterances (an empty arm cannot be paired)" )
    if v2_provenance[ "sampled_n" ] == 0:
        reasons.append( "v2 measured 0 utterances (an empty arm cannot be paired)" )

    for field in ( "corpus", "seed", "n_per_command", "sample_signature" ):
        if v1_provenance[ field ] != v2_provenance[ field ]:
            reasons.append( f"{field} differs (v1={v1_provenance[ field ]!r}, v2={v2_provenance[ field ]!r})" )

    if reasons:
        return "; ".join( reasons )
    return None


# ---------------------------------------------------------------------------
# The §6 paired median-Δ gate — the correct statistic (median OF per-utterance
# deltas), with the ≥20% PASS/FAIL threshold. Reads each arm's spans_by_utterance.
# ---------------------------------------------------------------------------
def _spans_by_utterance( metrics: Dict[ str, Any ] ) -> Optional[ Dict[ str, float ] ]:
    """The arm's {utterance: client_span_ms} map, or None when absent/empty/not-a-dict."""
    spans = metrics.get( "spans_by_utterance" )
    if not isinstance( spans, dict ) or len( spans ) == 0:
        return None
    return spans


def _arm_instrument_reason( metrics: Dict[ str, Any ], arm: str ) -> Optional[ str ]:
    """None iff `metrics` carries a non-empty per-utterance client-span map; else a reason."""
    if _spans_by_utterance( metrics ) is None:
        return f"{arm} arm did not report per-utterance client spans (missing/empty spans_by_utterance)"
    return None


def paired_median_delta_gate(
    v1_metrics : Dict[ str, Any ],
    v2_metrics : Dict[ str, Any ],
) -> Dict[ str, Any ]:
    """
    The §6 paired median-Δ latency gate: median of per-utterance deltas, ≥20% PASS/FAIL.

    Requires:
        - each metrics dict carries `spans_by_utterance` ({utterance: client_span_ms}
          for that arm's OK records) and optionally `client_p95_ms` (informational).

    Ensures:
        - DECLINES with {"fired": False, "reason": ...} — naming every cause — when
          either arm lacks per-utterance spans, when NO utterance was measured by both
          (0 shared pairs), or when the v1 median over the shared set is non-positive
          (no 20% threshold can be formed). No verdict number is emitted.
        - otherwise returns {"fired": True, "verdict": "PASS"|"FAIL", ...} with:
            Δ(u) = v1_span(u) − v2_span(u) over the SHARED utterances (positive ⇒ v2
            faster); median_delta_ms = median(Δ); v1_median_ms = median of v1's shared
            spans; threshold_ms = 20% of v1_median_ms; PASS iff median_delta_ms ≥
            threshold_ms; n_shared, n_dropped (+ v1_only / v2_only breakdown, RECORDED
            per §6); faster_arm from the sign of median_delta_ms; and the p95s carried
            as INFORMATIONAL (never gating).
        - never raises.
    """
    reasons = [
        r for r in (
            _arm_instrument_reason( v1_metrics, "v1" ),
            _arm_instrument_reason( v2_metrics, "v2" ),
        ) if r is not None
    ]
    if reasons:
        return { "fired": False, "reason": "paired latency gate DECLINED — " + "; ".join( reasons ) }

    v1_spans = _spans_by_utterance( v1_metrics )
    v2_spans = _spans_by_utterance( v2_metrics )
    shared   = sorted( set( v1_spans ) & set( v2_spans ) )
    v1_only  = sorted( set( v1_spans ) - set( v2_spans ) )
    v2_only  = sorted( set( v2_spans ) - set( v1_spans ) )

    if not shared:
        return {
            "fired"  : False,
            "reason" : ( "paired latency gate DECLINED — no utterance was measured by BOTH arms "
                         f"(0 shared pairs; v1-only {len( v1_only )}, v2-only {len( v2_only )})" ),
        }

    deltas    = [ v1_spans[ u ] - v2_spans[ u ] for u in shared ]
    v1_shared = [ v1_spans[ u ] for u in shared ]
    v1_median = round( statistics.median( v1_shared ), 3 )
    if v1_median <= 0:
        return {
            "fired"  : False,
            "reason" : ( f"paired latency gate DECLINED — v1 median span is non-positive ({v1_median} ms); "
                         "cannot form the 20% threshold" ),
        }

    median_delta = round( statistics.median( deltas ), 3 )
    threshold    = round( PASS_FRACTION * v1_median, 3 )
    passed       = median_delta >= threshold
    if   median_delta > 0: faster = "v2"
    elif median_delta < 0: faster = "v1"
    else:                  faster = "tie"

    return {
        "fired"           : True,
        "verdict"         : "PASS" if passed else "FAIL",
        "pass"            : passed,
        "instrument"      : INSTRUMENT,
        "n_shared"        : len( shared ),
        "n_dropped"       : len( v1_only ) + len( v2_only ),
        "dropped_v1_only" : len( v1_only ),
        "dropped_v2_only" : len( v2_only ),
        "v1_median_ms"    : v1_median,
        "median_delta_ms" : median_delta,
        "threshold_ms"    : threshold,
        "pass_fraction"   : PASS_FRACTION,
        "faster_arm"      : faster,
        # p95 is INFORMATIONAL (never gating) — design §1.5, one tail outlier moves it at n=60.
        "v1_p95_ms"       : v1_metrics.get( "client_p95_ms" ),
        "v2_p95_ms"       : v2_metrics.get( "client_p95_ms" ),
    }


# ---------------------------------------------------------------------------
# The wiring: provenance-check -> gate. The executable path the gate was missing.
# ---------------------------------------------------------------------------
def build_paired_verdict(
    v1_artifact : Dict[ str, Any ],
    v2_artifact : Dict[ str, Any ],
) -> Dict[ str, Any ]:
    """
    Produce the paired latency verdict from the two arms' artifacts.

    Requires:
        - each artifact is {"metrics": <arm metrics dict>, "provenance": <stamp>}.

    Ensures:
        - runs paired_provenance_check FIRST; on any mismatch returns
          {"fired": False, "provenance_ok": False, "reason": ...} and the gate is NEVER
          called — no latency number is emitted for an unbound pair.
        - on matching provenance, returns paired_median_delta_gate(v1_metrics,
          v2_metrics) with "provenance_ok": True added (the gate may still DECLINE on a
          missing instrument or zero shared pairs).
        - never raises on well-formed artifacts.
    """
    provenance_reason = paired_provenance_check( v1_artifact[ "provenance" ], v2_artifact[ "provenance" ] )
    if provenance_reason is not None:
        return {
            "fired"         : False,
            "provenance_ok" : False,
            "reason"        : "paired gate DECLINED (provenance) — " + provenance_reason,
        }

    gate = paired_median_delta_gate( v1_artifact[ "metrics" ], v2_artifact[ "metrics" ] )
    gate[ "provenance_ok" ] = True
    return gate


# ---------------------------------------------------------------------------
# Rendering + artifact IO
# ---------------------------------------------------------------------------
def render_paired_verdict( verdict: Dict[ str, Any ] ) -> str:
    """
    Render the paired median-Δ verdict as a markdown block.

    Ensures:
        - a DECLINED verdict (provenance OR instrument OR zero-shared) renders its refusal
          reason verbatim and NO latency number.
        - a fired verdict renders PASS/FAIL, the ≥20% bar, both medians, the paired
          median Δ, the drop counts (§6 record), the faster arm, the instrument residual,
          and the p95s labelled INFORMATIONAL.
    """
    lines : List[ str ] = [ "## Paired median-Δ latency gate (v1 vs v2)", "" ]
    if not verdict[ "fired" ]:
        lines.append( f"**DECLINED — no number emitted.** {verdict[ 'reason' ]}" )
        return "\n".join( lines )
    lines.append( f"**VERDICT: {verdict[ 'verdict' ]}** — bar: v2 ≥ {int( verdict[ 'pass_fraction' ] * 100 )}% faster than v1." )
    lines.append( "" )
    lines.append( f"- instrument: {verdict[ 'instrument' ]}" )
    lines.append( f"- paired median Δ (v1 − v2): {verdict[ 'median_delta_ms' ]} ms — faster arm: {verdict[ 'faster_arm' ]}" )
    lines.append( f"- v1 median: {verdict[ 'v1_median_ms' ]} ms · pass threshold: ≥ {verdict[ 'threshold_ms' ]} ms" )
    lines.append( f"- paired over {verdict[ 'n_shared' ]} shared utterances · dropped {verdict[ 'n_dropped' ]} "
                  f"(v1-only {verdict[ 'dropped_v1_only' ]}, v2-only {verdict[ 'dropped_v2_only' ]})" )
    lines.append( f"- p95 (INFORMATIONAL, n too small to gate): v1 {verdict[ 'v1_p95_ms' ]} ms · v2 {verdict[ 'v2_p95_ms' ]} ms" )
    return "\n".join( lines )


def render_provenance_block(
    v1_provenance : Dict[ str, Any ],
    v2_provenance : Dict[ str, Any ],
) -> str:
    """
    The provenance stamp block prefacing the verdict, so a reader sees WHAT the two arms
    measured (and whether they agree) beside the number.

    Ensures:
        - returns a markdown block naming each arm's corpus / seed / n_per_command /
          sampled_n / short signature, and a one-line MATCH or MISMATCH verdict.
    """
    def _short( provenance: Dict[ str, Any ] ) -> str:
        signature = provenance.get( "sample_signature" )
        return signature[ :12 ] if isinstance( signature, str ) else str( signature )

    matched = paired_provenance_check( v1_provenance, v2_provenance ) is None
    lines   = [
        "## Sample provenance",
        "",
        "| field | v1 | v2 |",
        "|---|---|---|",
        f"| corpus | {v1_provenance.get( 'corpus' )} | {v2_provenance.get( 'corpus' )} |",
        f"| seed | {v1_provenance.get( 'seed' )} | {v2_provenance.get( 'seed' )} |",
        f"| n_per_command | {v1_provenance.get( 'n_per_command' )} | {v2_provenance.get( 'n_per_command' )} |",
        f"| sampled_n | {v1_provenance.get( 'sampled_n' )} | {v2_provenance.get( 'sampled_n' )} |",
        f"| signature | {_short( v1_provenance )} | {_short( v2_provenance )} |",
        "",
        f"**Provenance: {'MATCH — arms measured the same sample.' if matched else 'MISMATCH — the paired gate is declined below.'}**",
    ]
    return "\n".join( lines )


def render_paired_report(
    verdict       : Dict[ str, Any ],
    v1_provenance : Dict[ str, Any ],
    v2_provenance : Dict[ str, Any ],
    timestamp     : str,
) -> str:
    """
    The full paired-verdict markdown: title, provenance block, then the gate verdict.

    Ensures:
        - returns a markdown string that ALWAYS carries the provenance block and the
          verdict rendered by render_paired_verdict (fired or DECLINED).
    """
    return "\n".join( [
        f"# CJ Flow paired v1-vs-v2 latency verdict — {timestamp}",
        "",
        render_provenance_block( v1_provenance, v2_provenance ),
        "",
        render_paired_verdict( verdict ),
        "",
    ] )


def load_arm_artifact( path: str ) -> Dict[ str, Any ]:
    """
    Read one arm artifact from a JSON file and prove it carries what the verdict needs.

    Ensures:
        - returns the parsed dict when both "metrics" and "provenance" keys are present.

    Raises:
        - ValueError when the top-level object lacks "metrics" or "provenance" — a
          malformed artifact fails loudly here, never as a mysterious KeyError later.
    """
    with open( path ) as handle:
        artifact = json.load( handle )
    missing = [ key for key in ( "metrics", "provenance" ) if key not in artifact ]
    if missing:
        raise ValueError( f"arm artifact {path!r} is missing top-level key(s): {', '.join( missing )}" )
    return artifact


def build_arg_parser() -> argparse.ArgumentParser:
    """The CLI: --v1-artifact, --v2-artifact, --out (all paths)."""
    parser = argparse.ArgumentParser(
        description="CJ Flow paired v1-vs-v2 latency verdict (provenance-gated §6 median-Δ gate)"
    )
    parser.add_argument( "--v1-artifact", required=True, help="path to the v1 arm's {metrics, provenance} JSON" )
    parser.add_argument( "--v2-artifact", required=True, help="path to the v2 arm's {metrics, provenance} JSON" )
    parser.add_argument( "--out", default=None, help="output markdown path (default: io/v2-flow/paired-verdict-<ts>.md)" )
    return parser


def main(
    argv         : Optional[ List[ str ] ] = None,
    load_fn      : Callable[ [ str ], Dict[ str, Any ] ] = load_arm_artifact,
    project_root : Optional[ str ] = None,
    timestamp    : Optional[ str ] = None,
) -> Dict[ str, Any ]:
    """
    Load both arm artifacts, build the provenance-gated verdict, and write the report.

    Requires:
        - argv carry --v1-artifact and --v2-artifact (defaults to sys.argv[1:]).
        - load_fn(path) returns an {metrics, provenance} dict (injected in tests).

    Ensures:
        - builds the verdict via build_paired_verdict (provenance-check -> gate) and
          writes the rendered report to --out (or io/v2-flow/paired-verdict-<ts>.md).
        - returns {"verdict": <dict>, "report": <str>, "out_path": <str>}.
    """
    args = build_arg_parser().parse_args( argv )

    root  = project_root if project_root is not None else du.get_project_root()
    stamp = timestamp if timestamp is not None else du.get_current_datetime_raw().strftime( "%Y-%m-%d-%H-%M-%S" )

    v1_artifact = load_fn( args.v1_artifact )
    v2_artifact = load_fn( args.v2_artifact )

    verdict = build_paired_verdict( v1_artifact, v2_artifact )
    report  = render_paired_report( verdict, v1_artifact[ "provenance" ], v2_artifact[ "provenance" ], stamp )

    out_path = args.out if args.out is not None else os.path.join(
        root, "io", "v2-flow", f"paired-verdict-{stamp}.md"
    )
    os.makedirs( os.path.dirname( out_path ), exist_ok=True )
    with open( out_path, "w" ) as handle:
        handle.write( report )

    return { "verdict": verdict, "report": report, "out_path": out_path }


if __name__ == "__main__":                    # pragma: no cover - CLI wrapper, exercised by the scheduled paired run
    result = main()
    print( f"wrote {result[ 'out_path' ]}" )
