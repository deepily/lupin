#!/usr/bin/env python3
"""
measure_visual_flake.py — durable visual-flake triage harness.

Promoted from the ad-hoc scratchpad harness that earned its keep on the Gate D
6b_focus hunt (item f1ebcb9d/7ffa1998): it reproduced the 24px-contiguous-block
anti-masking rejection firsthand and localized the unfrozen-timestamp root
cause. The scratchpad copy was session-scoped and reaped with its author; this
is a clean reconstruction against the same public comparator API.

WHAT IT DOES
    Runs BOTH of Sam's tolerant comparators (from
    src/tests/e2e_ui/visual_height_tolerance.py) on an actual-vs-golden PNG pair
    and emits the decision metrics plus a three-way triage verdict:

      • compare_pngs_content_shift_tolerant → best_dx / best_dy / best_mismatch
      • compare_pngs_aa_scatter_tolerant    → component_count / largest_cluster_area
                                              / erosion_survivors / total_diff_pixels

THE THREE-WAY VERDICT (advisory — the printed metrics let a human override)
    SWAP      A tolerant comparator already forgives the diff outright (a benign
              uniform sub-pixel content shift, OR isolated glyph-AA scatter with
              no contiguity). The cheapest fix: migrate the failing test onto
              that comparator — NO baseline change, NO code hunt.
    RECAPTURE Diffs over the isolated-AA floor but with NO solid contiguous
              block (0 erosion survivors). Cross-run rasterization
              nondeterminism, OR a baseline captured in a bad state (e.g. an
              incomplete emoji glyph — cf. the f0c9907c fonts.ready re-baseline).
              A fresh `--update-snapshots` capture is the safe fix. CAVEAT: a
              LARGE thin cluster could still be a genuine thin-border regression
              — verify the printed cluster metrics before recapturing.
    ESCALATE  A genuine contiguous-regression signal the tolerant comparators
              REFUSE: a size (width/height) mismatch refused before pixel
              analysis, OR a solid block that survived morphological erosion.
              These look like real regressions, not noise — investigate the
              render; do NOT recapture blindly.

The verdict is intentionally grounded in the comparators' OWN semantics (their
matched flags + the erosion-survivor never-false-green tripwire) rather than a
fresh arbitrary pixel threshold, so it inherits their proven discrimination.

USAGE
    PYTHONPATH=src python -m cosa.tests.tools.measure_visual_flake \\
        --actual path/to/actual.png --golden path/to/golden.png [tuning flags]

    Exit code: 0 = SWAP, 1 = RECAPTURE, 2 = ESCALATE (scriptable triage).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                   # pragma: no cover - type-checker-only import; runtime keeps the module PIL/numpy/scipy-free (the comparators are imported lazily in measure()).
    from tests.e2e_ui.visual_height_tolerance import AaScatterResult, ContentShiftResult


# The three triage verdicts. Advisory: always printed alongside the raw metrics
# so a human can override on the ambiguous large-thin-cluster case.
SWAP      = "SWAP"
RECAPTURE = "RECAPTURE"
ESCALATE  = "ESCALATE"

# Verdict → process exit code (scriptable): benign-cheap-fix 0, safe-recapture 1,
# real-regression 2.
_EXIT_CODES = { SWAP: 0, RECAPTURE: 1, ESCALATE: 2 }


@dataclass( frozen=True )
class FlakeVerdict:
    """
    A triage verdict plus the two comparator results it was derived from.

    Attributes:
        verdict:       One of SWAP / RECAPTURE / ESCALATE.
        rationale:     Human-readable justification citing the decisive metric(s).
        aa:            The AaScatterResult (spatial contiguity analysis).
        content_shift: The ContentShiftResult (uniform sub-pixel-shift search).
    """
    verdict       : str
    rationale     : str
    aa            : "AaScatterResult"
    content_shift : "ContentShiftResult"

    @property
    def exit_code( self ) -> int:
        """Process exit code for this verdict (SWAP 0 / RECAPTURE 1 / ESCALATE 2)."""
        return _EXIT_CODES[ self.verdict ]


def classify_visual_flake( aa: "AaScatterResult", cs: "ContentShiftResult" ) -> FlakeVerdict:
    """
    Derive a three-way triage verdict from the two comparator results (PURE).

    This is the harness's decision logic — deliberately dependency-free (reads
    only the duck-typed result attributes) so it is unit-testable without the
    PIL/numpy/scipy image stack.

    Requires:
        - aa exposes .matched, .reason, .total_diff_pixels, .component_count,
          .largest_cluster_area, .erosion_survivors (an AaScatterResult shape)
        - cs exposes .matched, .best_dx, .best_dy (a ContentShiftResult shape)

    Ensures:
        - returns SWAP iff EITHER comparator matched (content-shift preferred in
          the rationale when both match, since it is the stricter forgiveness)
        - returns ESCALATE iff (neither matched) AND EITHER the aa comparison was
          a size refusal (0 counted diff and 0 components ⇒ refused before pixel
          analysis) OR a solid block survived erosion (>0 survivors)
        - returns RECAPTURE otherwise (neither matched, no size refusal, no
          erosion survivor ⇒ over the isolated-AA floor but non-contiguous)
        - the returned FlakeVerdict carries BOTH source results verbatim for the
          caller to print / re-decide on the ambiguous large-thin-cluster case
    """
    # 1) SWAP — content-shift reconciles a uniform <=max_shift px sub-pixel shift
    #    to zero mismatch. Cheapest fix: migrate the test onto this comparator.
    if cs.matched:
        return FlakeVerdict(
            SWAP,
            f"content-shift comparator reconciles a uniform ({cs.best_dx},{cs.best_dy})px "
            f"sub-pixel shift to zero mismatch — migrate the test onto "
            f"compare_pngs_content_shift_tolerant; no baseline change.",
            aa, cs,
        )

    # 2) SWAP — aa-scatter forgives isolated glyph-AA scatter (no contiguity).
    if aa.matched:
        return FlakeVerdict(
            SWAP,
            f"aa-scatter comparator forgives {aa.total_diff_pixels}px of isolated glyph-AA "
            f"scatter across {aa.component_count} cluster(s) (largest {aa.largest_cluster_area}px, "
            f"0 erosion survivors) — migrate the test onto compare_pngs_aa_scatter_tolerant; "
            f"no baseline change.",
            aa, cs,
        )

    # Neither comparator forgave it. Distinguish a real regression from a stale
    # baseline using the aa comparison's OWN never-false-green signals.

    # 3) ESCALATE — a size (width/height) mismatch refused before any pixel
    #    analysis (0 counted diff AND 0 components is uniquely the early-refusal
    #    shape). A size change is structural, not sub-pixel noise.
    size_refused = aa.total_diff_pixels == 0 and aa.component_count == 0
    if size_refused:
        return FlakeVerdict(
            ESCALATE,
            f"size mismatch refused outright ({aa.reason}) — a width/height change is "
            f"structural, not sub-pixel noise; investigate the render, do NOT recapture blindly.",
            aa, cs,
        )

    # 4) ESCALATE — a solid contiguous block survived morphological erosion: the
    #    comparator's never-false-green regression tripwire.
    if aa.erosion_survivors > 0:
        return FlakeVerdict(
            ESCALATE,
            f"{aa.erosion_survivors}px survived erosion (a solid contiguous block; largest "
            f"cluster {aa.largest_cluster_area}px across {aa.component_count} cluster(s)) — "
            f"this is the never-false-green regression signal; investigate, do NOT recapture.",
            aa, cs,
        )

    # 5) RECAPTURE — diffs over the isolated-AA floor but with NO solid block:
    #    cross-run rasterization nondeterminism, or a baseline captured in a bad
    #    state (e.g. an incomplete emoji glyph — cf. the f0c9907c re-baseline).
    return FlakeVerdict(
        RECAPTURE,
        f"{aa.total_diff_pixels}px diff over {aa.component_count} cluster(s) (largest "
        f"{aa.largest_cluster_area}px) with 0 erosion survivors — over the isolated-AA floor "
        f"but no solid block; likely cross-run render nondeterminism or a stale baseline. "
        f"Recapture via --update-snapshots; VERIFY the cluster metrics first (a large thin "
        f"cluster could be a genuine thin-border regression).",
        aa, cs,
    )


def measure(                                        # pragma: no cover - straight-line delegation with no branch of its own: it reads bytes, hands them to the two comparators, and returns classify_visual_flake's answer unchanged
    actual_png           : bytes,
    golden_png           : bytes,
    *,
    threshold            : float = 0.1,
    max_shift            : int   = 1,
    max_height_delta     : int   = 1,
    max_isolated_cluster : int   = 2,
    erode_iterations     : int   = 1,
    max_total_scatter    : "int | None" = None,
) -> FlakeVerdict:
    """
    Run both tolerant comparators on the PNG byte pair and classify the result.

    The comparator import is LAZY (function-local) so importing this module stays
    free of the PIL/numpy/scipy image stack — keeping classify_visual_flake unit-
    testable in a lightweight environment.

    Requires:
        - actual_png and golden_png are valid PNG byte strings
    Ensures:
        - returns the FlakeVerdict from classify_visual_flake over both results
    """
    from tests.e2e_ui.visual_height_tolerance import (
        compare_pngs_aa_scatter_tolerant,
        compare_pngs_content_shift_tolerant,
    )

    cs = compare_pngs_content_shift_tolerant(
        actual_png, golden_png,
        threshold=threshold, max_shift=max_shift, max_height_delta=max_height_delta,
    )
    aa = compare_pngs_aa_scatter_tolerant(
        actual_png, golden_png,
        threshold=threshold, max_height_delta=max_height_delta,
        max_isolated_cluster=max_isolated_cluster, erode_iterations=erode_iterations,
        max_total_scatter=max_total_scatter,
    )
    return classify_visual_flake( aa, cs )


def format_report( verdict: FlakeVerdict, actual_path: str, golden_path: str ) -> str:  # pragma: no cover - pure string formatting for the CLI; carries no decision logic (the verdict + all metrics are already computed).
    """Render a human-readable triage report for the CLI."""
    aa = verdict.aa
    cs = verdict.content_shift
    lines = [
        f"visual-flake triage",
        f"  actual : {actual_path}",
        f"  golden : {golden_path}",
        f"",
        f"  content-shift : matched={cs.matched}  best_dx={cs.best_dx}  best_dy={cs.best_dy}  best_mismatch={cs.best_mismatch}",
        f"  aa-scatter    : matched={aa.matched}  total_diff={aa.total_diff_pixels}  components={aa.component_count}  "
        f"largest_cluster={aa.largest_cluster_area}  erosion_survivors={aa.erosion_survivors}",
        f"",
        f"  VERDICT: {verdict.verdict}  (exit {verdict.exit_code})",
        f"  {verdict.rationale}",
    ]
    return "\n".join( lines )


def main( argv=None ) -> int:                       # pragma: no cover - CLI/IO shell (argparse + file read + print + exit-code map); no decision logic. Pragma pre-approved (Tiberius, 2026-07-07).
    """CLI entry point. Returns the verdict's exit code."""
    parser = argparse.ArgumentParser(
        prog="measure_visual_flake",
        description="Triage a failing visual snapshot: SWAP / RECAPTURE / ESCALATE.",
    )
    parser.add_argument( "--actual", required=True, help="path to the ACTUAL (freshly-captured) PNG" )
    parser.add_argument( "--golden", required=True, help="path to the GOLDEN (committed baseline) PNG" )
    parser.add_argument( "--threshold",            type=float, default=0.1 )
    parser.add_argument( "--max-shift",            type=int,   default=1 )
    parser.add_argument( "--max-height-delta",     type=int,   default=1 )
    parser.add_argument( "--max-isolated-cluster", type=int,   default=2 )
    parser.add_argument( "--erode-iterations",     type=int,   default=1 )
    parser.add_argument( "--max-total-scatter",    type=int,   default=None )
    args = parser.parse_args( argv )

    with open( args.actual, "rb" ) as fh:
        actual_png = fh.read()
    with open( args.golden, "rb" ) as fh:
        golden_png = fh.read()

    verdict = measure(
        actual_png, golden_png,
        threshold=args.threshold, max_shift=args.max_shift,
        max_height_delta=args.max_height_delta, max_isolated_cluster=args.max_isolated_cluster,
        erode_iterations=args.erode_iterations, max_total_scatter=args.max_total_scatter,
    )
    print( format_report( verdict, args.actual, args.golden ) )
    return verdict.exit_code


if __name__ == "__main__":                          # pragma: no cover - process entrypoint
    sys.exit( main() )
