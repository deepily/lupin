"""
Height-tolerant PNG comparison for visual-regression snapshots.

Straggler bug 660d02b4 — `test_task_editing_controls_visual` exhibits a
persistent ±1px HEIGHT non-determinism between capture and compare renders in
the SAME container: `--update-snapshots` writes the baseline at 960x169, but a
plain COMPARE run renders 960x170. The stock comparator
(`pytest_playwright_visual_snapshot`) is ZERO-tolerance on both dimensions AND
pixel count: it raises `ValueError` the instant the two images differ in size,
so a benign 1px sub-pixel row-height rounding fails the merge gate with no
rebaseline able to reconcile it (the direction flips run-to-run).

This module provides a PURE comparison core (no Playwright / no pytest / no
filesystem) that tolerates a bounded HEIGHT delta while staying strict on:
    - WIDTH (any width delta → fail; width is load-bearing per bug 99326963)
    - PIXELS (zero mismatched pixels required on the compared region, same
      `threshold` semantics as the stock comparator)
    - the size of the tolerated delta (delta > `max_height_delta` → fail)

Tolerance mechanism: when the two images share a width and their heights differ
by <= `max_height_delta`, BOTH are cropped (top-anchored) to the shorter height
and the overlapping region is compared with the ordinary zero-mismatch
pixelmatch. This forgives ONLY a benign bottom-edge ±1px growth — if a real
change SHIFTS content (so the overlapping region diverges), the pixel compare
still fails. It can never green a genuine regression; worst case it leaves a
non-bottom-anchored flap RED (which then escalates), it never hides one.

The design deliberately keeps this core free of I/O so it is unit-testable with
synthetic in-memory images (see src/tests/unit/test_visual_height_tolerance.py)
on the :7999-discretionary (no-server) venue — no :8000, no browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch


@dataclass( frozen=True )
class HeightTolerantResult:
    """
    Outcome of a height-tolerant comparison.

    Attributes:
        matched:         True iff the images are considered equivalent.
        reason:          Human-readable explanation (always populated).
        mismatch_pixels: Count of mismatched pixels on the compared region
                         (0 when sizes were incompatible and no compare ran).
        tolerated_delta: The height delta that was tolerated (0 when the images
                         were already the same size or the compare was refused).
    """
    matched         : bool
    reason          : str
    mismatch_pixels : int
    tolerated_delta : int


def compare_pngs_height_tolerant(
    actual_png       : bytes,
    baseline_png     : bytes,
    *,
    threshold        : float = 0.1,
    max_height_delta : int   = 1,
) -> HeightTolerantResult:
    """
    Compare two PNG byte strings, tolerating a small HEIGHT-only difference.

    Requires:
        - actual_png and baseline_png are valid PNG byte strings
        - threshold is the per-pixel color-distance threshold (0.0–1.0), same
          meaning as pixelmatch / the stock visual comparator
        - max_height_delta is a non-negative pixel budget for the height-only
          tolerance

    Ensures:
        - returns matched=True iff EITHER:
            (a) the images are byte-dimension-identical AND pixelmatch reports
                zero mismatched pixels at `threshold`, OR
            (b) the images share a WIDTH, their heights differ by
                <= max_height_delta, AND after top-anchored cropping BOTH to the
                shorter height the overlapping region has zero mismatched pixels
        - returns matched=False (never raises on a size mismatch) when the width
          differs, the height delta exceeds max_height_delta, or any compared
          pixel exceeds `threshold`
        - tolerated_delta reflects the height delta forgiven under branch (b),
          else 0

    Raises:
        - PIL.UnidentifiedImageError if either byte string is not a valid image
    """
    img_a = Image.open( BytesIO( actual_png ) ).convert( "RGBA" )
    img_b = Image.open( BytesIO( baseline_png ) ).convert( "RGBA" )

    w_a, h_a = img_a.size
    w_b, h_b = img_b.size

    # Width is never negotiable — a width flip is the real-regression signal that
    # bug 99326963's viewport pin exists to surface; do not mask it.
    if w_a != w_b:
        return HeightTolerantResult(
            matched         = False,
            reason          = f"width mismatch: actual {w_a}px vs baseline {w_b}px (not tolerated)",
            mismatch_pixels = 0,
            tolerated_delta = 0,
        )

    height_delta = abs( h_a - h_b )

    if height_delta > max_height_delta:
        return HeightTolerantResult(
            matched         = False,
            reason          = f"height delta {height_delta}px exceeds tolerance {max_height_delta}px "
                              f"(actual {h_a}px vs baseline {h_b}px)",
            mismatch_pixels = 0,
            tolerated_delta = 0,
        )

    # Same width; height delta within budget. Top-anchor crop BOTH to the shorter
    # height so the compared region is the pixel-identical overlap. When
    # height_delta == 0 this is a no-op and reduces to the ordinary strict compare.
    common_h = min( h_a, h_b )
    crop_a   = img_a.crop( ( 0, 0, w_a, common_h ) )
    crop_b   = img_b.crop( ( 0, 0, w_b, common_h ) )

    diff     = Image.new( "RGBA", ( w_a, common_h ) )
    mismatch = pixelmatch( crop_a, crop_b, diff, threshold=threshold )

    if mismatch == 0:
        if height_delta == 0:
            reason = "exact size; zero mismatched pixels"
        else:
            reason = ( f"tolerated {height_delta}px bottom-edge height delta "
                       f"(actual {h_a}px vs baseline {h_b}px); overlapping region identical" )
        return HeightTolerantResult(
            matched         = True,
            reason          = reason,
            mismatch_pixels = 0,
            tolerated_delta = height_delta,
        )

    return HeightTolerantResult(
        matched         = False,
        reason          = f"{mismatch} mismatched pixel(s) in the compared {w_a}x{common_h} region "
                          f"(threshold {threshold})",
        mismatch_pixels = mismatch,
        tolerated_delta = 0,
    )


def compare_pngs_structure_only(
    actual_png       : bytes,
    baseline_png     : bytes,
    *,
    max_height_delta : int = 1,
) -> HeightTolerantResult:
    """
    Structural-only snapshot comparison: verify WIDTH (exact) + HEIGHT (within
    max_height_delta) WITHOUT any per-pixel comparison — PIXEL-BLIND BY DESIGN.

    LOUD NOTE FOR FUTURE MAINTAINERS: the pixel-blindness is INTENTIONAL, not a
    defect. A future run of two SAME-SIZE images with TOTALLY DIFFERENT pixel
    content returns matched=True HERE ON PURPOSE. Do NOT "fix" this back into a
    per-pixel compare — that reintroduces the bug 660d02b4 flake. If you want
    pixel coverage on this card back, do it via the P3 (C) deterministic-font /
    sub-pixel-positioning harness, NOT by re-arming a pixel assertion here.

    Rationale (bug 660d02b4, resolution D — ratified by Tiberius 2026-07-01):
    `test_task_editing_controls_visual` is the single most glyph-dense of the 37
    mux visual snapshots (a full task-list data table of 11-13px text). Even with
    the suite-wide deterministic-font launch args ALREADY in place
    (`--font-render-hinting=none` / `--disable-lcd-text` / `--force-color-profile=srgb`
    / `--force-device-scale-factor=1`, see conftest `browser_type_launch_args`) its
    per-pixel glyph anti-aliasing is non-deterministic run-to-run — HIGH-VARIANCE,
    up to ~3800 scattered mismatched px. That magnitude is beyond any pixel/count
    budget that could stay safe: a budget large enough to forgive ~3800 benign px
    would also mask a genuine <2000px regression (a recolored pill / wrong
    heat-tint), which crosses the never-false-green line. The exact-pixel
    assertion is therefore DROPPED for this one card; its FUNCTIONAL behaviour is
    covered by the sibling E2E tests in the same file
    (`test_actions_column_and_controls_render`, the priority/owner PATCH-body
    tests, the drop-reason/blank-reason tests). This structural gate is retained
    because it is DETERMINISTIC (the control-height pin + the settle-fix stabilise
    the card size) and still catches a genuine STRUCTURAL regression — a card that
    renders at the wrong WIDTH or a HEIGHT outside ±max_height_delta
    (broken / missing / resized). Restoring pixel coverage under a stronger
    deterministic-font / sub-pixel-positioning harness is deferred to the P3
    follow-on (the existing font flags are already present and insufficient here).

    Requires:
        - actual_png and baseline_png are valid PNG byte strings
        - max_height_delta is a non-negative pixel budget for the height tolerance

    Ensures:
        - returns matched=True iff the widths are EQUAL and the height delta is
          <= max_height_delta — REGARDLESS of pixel content (pixel-blind by
          design; that is the entire point of resolution D)
        - returns matched=False (never raises on a size mismatch) when the width
          differs OR the height delta exceeds max_height_delta
        - mismatch_pixels is always 0 (no pixel comparison is performed)
        - tolerated_delta reflects the height delta accepted, else 0

    Raises:
        - PIL.UnidentifiedImageError if either byte string is not a valid image
    """
    w_a, h_a = Image.open( BytesIO( actual_png ) ).size
    w_b, h_b = Image.open( BytesIO( baseline_png ) ).size

    # Width stays load-bearing (bug 99326963): a width flip is a real structural
    # regression, never forgiven.
    if w_a != w_b:
        return HeightTolerantResult(
            matched         = False,
            reason          = f"width mismatch: actual {w_a}px vs baseline {w_b}px "
                              f"(structural gate; not tolerated)",
            mismatch_pixels = 0,
            tolerated_delta = 0,
        )

    height_delta = abs( h_a - h_b )
    if height_delta > max_height_delta:
        return HeightTolerantResult(
            matched         = False,
            reason          = f"height delta {height_delta}px exceeds tolerance {max_height_delta}px "
                              f"(actual {h_a}px vs baseline {h_b}px); structural gate",
            mismatch_pixels = 0,
            tolerated_delta = 0,
        )

    return HeightTolerantResult(
        matched         = True,
        reason          = f"structural match: width {w_a}px, height delta {height_delta}px "
                          f"within {max_height_delta}px (pixel comparison intentionally "
                          f"skipped — bug 660d02b4 resolution D)",
        mismatch_pixels = 0,
        tolerated_delta = height_delta,
    )


# ---------------------------------------------------------------------------
# Spatially-aware anti-aliasing-scatter-tolerant comparator (bug 660d02b4, P3
# follow-on to resolution D — task d90dcfc2).
#
# GOAL: RESTORE per-pixel coverage on `test_task_editing_controls_visual`
# WITHOUT touching the 37 shared baselines and WITHOUT any browser-flag change.
# Resolution D dropped the exact-pixel assertion because a blunt maxDiffPixels
# COUNT budget cannot separate the card's benign glyph-AA scatter (up to ~3800
# SCATTERED single-px glyph-edge diffs) from a genuine contiguous regression of
# similar px count (e.g. a recolored ~20x20=400px pill). The insight this
# comparator exploits: those two failure modes differ in SHAPE, not just count.
#   - Benign font-AA rasterization jitter  -> spatially ISOLATED single pixels
#     (each connected diff cluster is 1-2px; NOTHING survives a 3x3 erosion).
#   - A real regression (recolored pill, wrong heat-tint, a content/width shift)
#     -> a CONTIGUOUS block or a glyph-height run: a connected diff cluster with
#     real 2D/1D extent that erosion cannot dissolve.
# So we forgive ONLY diff clusters whose connected-component AREA is <= a small
# tunable floor AND that leave NO survivor under morphological erosion, and we
# FAIL the instant either signal shows contiguity. numpy + scipy are imported
# LAZILY inside the function so this module stays dependency-light — the other
# 36 visual tests import it through conftest and must not gain a hard scipy dep.
#
# EMPIRICAL VERDICT for THIS card (task d90dcfc2, measured 2026-07-01 — see
# src/rnd/v0.1.9/2026.07.01-spatial-aa-comparator-feasibility-verdict-sam.md):
# this comparator is PROVEN (28 tests, 100% line+branch, RED-first: it fails a
# 400px block a count-budget would false-green) BUT it CANNOT safely restore
# pixel coverage on `test_task_editing_controls_visual`. The card's real
# matched-code cross-process AA jitter is NOT isolated single-px scatter — it
# forms 2px-tall solid bars up to 145px (98 clusters ≥10px; 41 erosion
# survivors), geometrically indistinguishable from a plausible small regression
# (a 12x12=144px pill sits at area ≤145; a thin recolored 73x2 row-border is the
# same shape as the benign bars). No floor holds never-false-green there, so
# resolution D stands for that card. This function is retained as a proven,
# reusable primitive for a less-glyph-dense card or a future stronger-
# determinism harness — it is NOT wired into the task_editing gate.
# ---------------------------------------------------------------------------


@dataclass( frozen=True )
class AaScatterResult:
    """
    Outcome of a spatially-aware anti-aliasing-scatter-tolerant comparison.

    Attributes:
        matched:            True iff the only diffs are spatially-isolated
                            sub-floor AA scatter (never True when any cluster
                            shows contiguity).
        reason:             Human-readable explanation (always populated).
        total_diff_pixels:  Total counted mismatched px on the compared region
                            (pre-spatial-filter; the count a blunt budget sees).
        component_count:    Number of connected diff clusters (8-connectivity).
        largest_cluster_area: Area (px) of the LARGEST connected diff cluster —
                            the primary contiguity discriminator. This is the
                            key measurement for tuning the isolated-AA floor.
        erosion_survivors:  Px surviving morphological erosion — the independent
                            solid-block tripwire (>0 ⇒ a thick contiguous blob).
        tolerated_delta:    Height delta forgiven (0 when same size / refused).
    """
    matched              : bool
    reason               : str
    total_diff_pixels    : int
    component_count      : int
    largest_cluster_area : int
    erosion_survivors    : int
    tolerated_delta      : int


def compare_pngs_aa_scatter_tolerant(
    actual_png          : bytes,
    baseline_png        : bytes,
    *,
    threshold           : float = 0.1,
    max_height_delta    : int   = 1,
    max_isolated_cluster: int   = 2,
    erode_iterations    : int   = 1,
    max_total_scatter   : int | None = None,
) -> AaScatterResult:
    """
    Compare two PNG byte strings, forgiving ONLY spatially-isolated single-pixel
    glyph anti-aliasing scatter and FAILING the instant diffs form a contiguous
    block. Restores per-pixel coverage lost to resolution D without a baseline or
    browser-flag change.

    Requires:
        - actual_png and baseline_png are valid PNG byte strings
        - threshold is the per-pixel color-distance threshold (0.0–1.0), same
          meaning as pixelmatch / the stock visual comparator
        - max_height_delta is a non-negative pixel budget for the height-only
          tolerance (identical mechanism to compare_pngs_height_tolerant)
        - max_isolated_cluster is a non-negative area (px): a connected diff
          cluster of area <= this is treated as forgivable AA scatter. Tune it
          JUST above the empirically-observed benign AA cluster max, and only if
          that stays well below the smallest meaningful regression cluster.
        - erode_iterations is a positive count of 3x3 morphological erosion
          passes (higher ⇒ a block must be thicker to trip the solid-block guard)
        - max_total_scatter, if not None, is a generous sanity ceiling on the
          TOTAL forgiven scatter (defense-in-depth; the spatial filter is the
          primary guard — this only ever makes the comparator STRICTER)

    Ensures:
        - width is never negotiable: a width delta ⇒ matched=False (bug 99326963)
        - a height delta > max_height_delta ⇒ matched=False; otherwise BOTH images
          are top-anchored-cropped to the shorter height and the overlap compared
        - matched=True iff, on the overlap, EITHER there are zero diff pixels, OR
          every connected diff cluster has area <= max_isolated_cluster AND no
          pixel survives erosion AND (when set) total diff <= max_total_scatter
        - matched=False the instant ANY connected diff cluster exceeds the floor,
          OR any pixel survives erosion (a contiguous ≥erode-thick blob), OR the
          total scatter exceeds max_total_scatter — this is the never-false-green
          line: a 20x20 recolored block, a width/size change, and a content shift
          all fail even when their px count is below the benign AA scatter count
        - largest_cluster_area / erosion_survivors / component_count / total_diff
          are always populated for measurement (0 when no compare ran)
        - never raises on a size mismatch (returns matched=False instead)

    Raises:
        - PIL.UnidentifiedImageError if either byte string is not a valid image
    """
    # Lazy, function-local imports — keep the module import dependency-light so
    # the other 36 visual tests (which import this module via conftest) never
    # gain a hard numpy/scipy dependency at collection time.
    import numpy as np
    from scipy import ndimage

    img_a = Image.open( BytesIO( actual_png ) ).convert( "RGBA" )
    img_b = Image.open( BytesIO( baseline_png ) ).convert( "RGBA" )

    w_a, h_a = img_a.size
    w_b, h_b = img_b.size

    # Width is never negotiable (bug 99326963) — a width flip is a real regression.
    if w_a != w_b:
        return AaScatterResult(
            matched              = False,
            reason               = f"width mismatch: actual {w_a}px vs baseline {w_b}px (not tolerated)",
            total_diff_pixels    = 0,
            component_count      = 0,
            largest_cluster_area = 0,
            erosion_survivors    = 0,
            tolerated_delta      = 0,
        )

    height_delta = abs( h_a - h_b )
    if height_delta > max_height_delta:
        return AaScatterResult(
            matched              = False,
            reason               = f"height delta {height_delta}px exceeds tolerance {max_height_delta}px "
                                   f"(actual {h_a}px vs baseline {h_b}px)",
            total_diff_pixels    = 0,
            component_count      = 0,
            largest_cluster_area = 0,
            erosion_survivors    = 0,
            tolerated_delta      = 0,
        )

    # Same width; height delta within budget. Top-anchor crop BOTH to the shorter
    # height so the compared region is the pixel-identical overlap (identical
    # mechanism to compare_pngs_height_tolerant).
    common_h = min( h_a, h_b )
    crop_a   = img_a.crop( ( 0, 0, w_a, common_h ) )
    crop_b   = img_b.crop( ( 0, 0, w_b, common_h ) )

    # diff_mask=True paints ONLY the counted-diff pixels (rest transparent), so a
    # content-independent boolean mask is just "alpha > 0" — no color-guessing.
    diff_img = Image.new( "RGBA", ( w_a, common_h ) )
    pixelmatch( crop_a, crop_b, diff_img, threshold=threshold, diff_mask=True )
    mask     = ( np.array( diff_img )[ :, :, 3 ] > 0 )

    total_diff = int( mask.sum() )

    if total_diff == 0:
        reason = ( "exact size; zero mismatched pixels" if height_delta == 0
                   else f"tolerated {height_delta}px bottom-edge height delta; overlapping region identical" )
        return AaScatterResult(
            matched              = True,
            reason               = reason,
            total_diff_pixels    = 0,
            component_count      = 0,
            largest_cluster_area = 0,
            erosion_survivors    = 0,
            tolerated_delta      = height_delta,
        )

    # Spatial analysis on the diff mask.
    #  - 8-connectivity labeling (full 3x3 structure) MERGES diagonally-touching
    #    specks into one cluster — deliberately conservative (bigger clusters ⇒
    #    more likely to trip the floor ⇒ safer / stricter).
    #  - 3x3 binary erosion: a pixel survives only if fully surrounded, so ONLY a
    #    solid contiguous blob (≥ erode-thick in both dims) leaves a survivor;
    #    isolated specks and 1px-thin lines dissolve to nothing.
    structure       = np.ones( ( 3, 3 ), dtype=bool )
    labels, n_comp  = ndimage.label( mask, structure=structure )
    if n_comp > 0:
        comp_sizes    = ndimage.sum( mask, labels, index=np.arange( 1, n_comp + 1 ) )
        largest       = int( comp_sizes.max() )
    else:                                                # pragma: no cover - total_diff>0 guarantees ≥1 component
        largest       = 0
    eroded          = ndimage.binary_erosion( mask, structure=structure, iterations=erode_iterations )
    survivors       = int( eroded.sum() )

    # Never-false-green decision — each condition is computed explicitly (not a
    # short-circuit that hides a branch) so every contiguity signal is testable.
    area_fail    = largest > max_isolated_cluster
    block_fail   = survivors > 0
    scatter_fail = ( max_total_scatter is not None ) and ( total_diff > max_total_scatter )

    if area_fail or block_fail or scatter_fail:
        causes = []
        if area_fail:    causes.append( f"largest cluster {largest}px > isolated-AA floor {max_isolated_cluster}px" )
        if block_fail:   causes.append( f"{survivors}px survived {erode_iterations}x erosion (contiguous block)" )
        if scatter_fail: causes.append( f"total scatter {total_diff}px > ceiling {max_total_scatter}px" )
        return AaScatterResult(
            matched              = False,
            reason               = "contiguous-regression signal: " + "; ".join( causes ),
            total_diff_pixels    = total_diff,
            component_count      = n_comp,
            largest_cluster_area = largest,
            erosion_survivors    = survivors,
            tolerated_delta      = 0,
        )

    return AaScatterResult(
        matched              = True,
        reason               = f"forgave {total_diff}px of isolated AA scatter across {n_comp} cluster(s) "
                               f"(largest {largest}px ≤ floor {max_isolated_cluster}px; 0 erosion survivors)",
        total_diff_pixels    = total_diff,
        component_count      = n_comp,
        largest_cluster_area = largest,
        erosion_survivors    = survivors,
        tolerated_delta      = height_delta,
    )


# ---------------------------------------------------------------------------
# Content-shift-tolerant comparator (bug c0bbd2af — the INTERNAL-position sibling
# of compare_pngs_height_tolerant).
#
# Straggler class surfaced by re-proof ts-5012699a: `multiplexer_phase6b_tts_chrome`
# renders a ~64px green section-header band that rounds to a DIFFERENT y-origin
# run-to-run in the SAME container — committed baseline band = rows y12-76, a fresh
# COMPARE render = rows y11-75: a benign UNIFORM 1px VERTICAL content-shift of the
# whole band. The image DIMENSIONS are identical (960x130 both), so
# compare_pngs_height_tolerant (which forgives a ±1px TOTAL-HEIGHT delta) does NOT
# cover it — nothing shrank, the content SLID inside a same-size frame. And the
# aa-scatter comparator correctly REFUSES it: a 1px-tall, ~920px-wide band edge is
# one ~920px connected cluster, far above any isolated-AA floor. The shift needs its
# own mechanism.
#
# INSIGHT (three-analyst convergence, thread 5365d6b3): a benign ≤1px content-shift
# is EXACTLY reconciled by sliding one image back by that offset — at the true
# offset the overlap becomes PIXEL-PERFECT (measured: dy=1 → 0 mismatch). A genuine
# regression cannot be so reconciled: a ≥2px shift never re-aligns within a ±1px
# search, and ANY hue/color change leaves a nonzero pixel delta at EVERY offset
# (sliding cannot repaint). So we forgive ONLY when some offset within ±max_shift
# drives the overlap to ZERO mismatch, and FAIL otherwise. The anti-masking line
# (Clayton's spec: ≥2px OR any hue delta hard-fails) is STRUCTURAL here, not a
# tunable threshold — it falls out of "must fully zero at ≤1px" for free.
#
# EDGE-STRIP BOUND (documented, intentional — mirrors the height-tolerant crop): at
# a forgiven offset only the (w-|dx|) x (h-|dy|) OVERLAP is pixel-verified; the
# ≤max_shift-px border that slid out of frame is unverified. A regression large
# enough to matter perturbs the INTERIOR overlap (→ fail); a change confined
# entirely to a ≤1px border is below the perceptibility floor, the same tradeoff
# compare_pngs_height_tolerant already accepts for its bottom edge. `max_shift` MUST
# stay tiny (default 1) so the overlap is ~full and this bound cannot be abused.
#
# Pure comparison core (no Playwright / pytest / filesystem), unit-testable with
# synthetic in-memory images on the :7999-discretionary venue — no :8000, no
# browser. RED-first: the FAIL fixtures (≥2px shift, hue delta, contiguous block)
# are the load-bearing proof, exactly as 660d02b4's shifted-content test was.
# ---------------------------------------------------------------------------


@dataclass( frozen=True )
class ContentShiftResult:
    """
    Outcome of a content-shift-tolerant comparison.

    Attributes:
        matched:          True iff some offset within +/-max_shift drove the
                          overlapping region to ZERO mismatched pixels (a benign
                          <=max_shift uniform content shift). Never True when no
                          offset reconciles (a >=2px shift, a hue change, or a
                          structural regression).
        reason:           Human-readable explanation (always populated).
        best_dx:          The x offset (px) that minimised the overlap mismatch.
        best_dy:          The y offset (px) that minimised the overlap mismatch.
        best_mismatch:    Mismatched-pixel count of the BEST offset's overlap
                          (0 exactly when matched=True).
        tolerated_delta:  The height delta forgiven under the same-width crop
                          (0 when the images were already the same height).
    """
    matched         : bool
    reason          : str
    best_dx         : int
    best_dy         : int
    best_mismatch   : int
    tolerated_delta : int


def compare_pngs_content_shift_tolerant(
    actual_png       : bytes,
    baseline_png     : bytes,
    *,
    threshold        : float = 0.1,
    max_shift        : int   = 1,
    max_height_delta : int   = 1,
) -> ContentShiftResult:
    """
    Compare two PNG byte strings, forgiving ONLY a benign uniform content shift of
    at most `max_shift` px in x and/or y, and FAILING the instant no such shift
    reconciles the images to a pixel-perfect overlap.

    Requires:
        - actual_png and baseline_png are valid PNG byte strings
        - threshold is the per-pixel color-distance threshold (0.0-1.0), same
          meaning as pixelmatch / the stock visual comparator
        - max_shift is a non-negative px budget for the uniform-shift search in
          BOTH axes (keep it tiny — default 1 — so the verified overlap stays
          ~full and the edge-strip bound below cannot be abused)
        - max_height_delta is a non-negative px budget for a same-width height
          delta (identical top-anchored-crop mechanism to
          compare_pngs_height_tolerant)

    Ensures:
        - width is never negotiable: a width delta => matched=False (bug 99326963)
        - a height delta > max_height_delta => matched=False; otherwise BOTH images
          are top-anchored-cropped to the shorter height and the search runs on the
          overlap
        - matched=True iff SOME integer offset (dx, dy) with |dx| <= max_shift and
          |dy| <= max_shift makes the shift-aligned overlap have ZERO mismatched
          pixels at `threshold` (a benign <=max_shift uniform content shift; dx=dy=0
          reduces to the ordinary strict exact compare)
        - matched=False when the best offset still leaves >0 mismatched pixels —
          this is the never-false-green line: a >=2px shift cannot re-align within a
          +/-1px search, and any hue/color change leaves a nonzero delta at EVERY
          offset (sliding cannot repaint), so both hard-fail exactly as Clayton's
          >=2px-or-hue spec requires
        - only the (w-|best_dx|) x (h-|best_dy|) overlap is pixel-verified on a
          forgiven match; the <=max_shift-px border that slid out of frame is
          unverified BY DESIGN (documented edge-strip bound above)
        - best_dx / best_dy / best_mismatch / tolerated_delta are always populated
        - never raises on a size mismatch (returns matched=False instead)

    Raises:
        - PIL.UnidentifiedImageError if either byte string is not a valid image
    """
    img_a = Image.open( BytesIO( actual_png ) ).convert( "RGBA" )
    img_b = Image.open( BytesIO( baseline_png ) ).convert( "RGBA" )

    w_a, h_a = img_a.size
    w_b, h_b = img_b.size

    # Width is never negotiable (bug 99326963) — a width flip is a real regression.
    if w_a != w_b:
        return ContentShiftResult(
            matched         = False,
            reason          = f"width mismatch: actual {w_a}px vs baseline {w_b}px (not tolerated)",
            best_dx         = 0,
            best_dy         = 0,
            best_mismatch   = 0,
            tolerated_delta = 0,
        )

    height_delta = abs( h_a - h_b )
    if height_delta > max_height_delta:
        return ContentShiftResult(
            matched         = False,
            reason          = f"height delta {height_delta}px exceeds tolerance {max_height_delta}px "
                              f"(actual {h_a}px vs baseline {h_b}px)",
            best_dx         = 0,
            best_dy         = 0,
            best_mismatch   = 0,
            tolerated_delta = 0,
        )

    # Same width; height delta within budget. Top-anchor crop BOTH to the shorter
    # height so the compared region is the pixel-identical overlap (identical
    # mechanism to compare_pngs_height_tolerant). When height_delta == 0 this is a
    # no-op and the search reduces to a plain strict compare at offset (0, 0).
    w        = w_a
    common_h = min( h_a, h_b )
    crop_a   = img_a.crop( ( 0, 0, w, common_h ) )
    crop_b   = img_b.crop( ( 0, 0, w, common_h ) )

    best_mismatch = None
    best_dx       = 0
    best_dy       = 0

    for dy in range( -max_shift, max_shift + 1 ):
        for dx in range( -max_shift, max_shift + 1 ):
            # Overlap in crop_a coordinates: a-pixel (x, y) pairs with b-pixel
            # (x - dx, y - dy); keep only pairs where BOTH indices are in-bounds.
            ax0 = max( 0, dx )
            ay0 = max( 0, dy )
            ax1 = min( w, w + dx )
            ay1 = min( common_h, common_h + dy )
            if ax1 <= ax0 or ay1 <= ay0:
                continue                                   # degenerate overlap (shift wider than the image)

            region_a = crop_a.crop( ( ax0, ay0, ax1, ay1 ) )
            region_b = crop_b.crop( ( ax0 - dx, ay0 - dy, ax1 - dx, ay1 - dy ) )

            diff     = Image.new( "RGBA", ( ax1 - ax0, ay1 - ay0 ) )
            mismatch = pixelmatch( region_a, region_b, diff, threshold=threshold )

            if best_mismatch is None or mismatch < best_mismatch:
                best_mismatch = mismatch
                best_dx       = dx
                best_dy       = dy
                if mismatch == 0:
                    break                                  # cannot beat a perfect overlap
        if best_mismatch == 0:
            break

    if best_mismatch == 0:
        if best_dx == 0 and best_dy == 0:
            reason = "exact overlap at zero shift; zero mismatched pixels"
        else:
            reason = ( f"forgave a uniform ({best_dx},{best_dy})px content shift "
                       f"(<= {max_shift}px); shift-aligned overlap identical" )
        return ContentShiftResult(
            matched         = True,
            reason          = reason,
            best_dx         = best_dx,
            best_dy         = best_dy,
            best_mismatch   = 0,
            tolerated_delta = height_delta,
        )

    return ContentShiftResult(
        matched         = False,
        reason          = f"no <= {max_shift}px shift reconciles the images: best offset "
                          f"({best_dx},{best_dy})px still leaves {best_mismatch} mismatched pixel(s) "
                          f"(threshold {threshold}) — a >= {max_shift + 1}px shift, a hue change, or a "
                          f"structural regression",
        best_dx         = best_dx,
        best_dy         = best_dy,
        best_mismatch   = best_mismatch,
        tolerated_delta = 0,
    )
