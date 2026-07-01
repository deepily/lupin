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
