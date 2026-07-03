"""
Unit tests for the content-shift-tolerant PNG comparator (bug c0bbd2af).

Covers `compare_pngs_content_shift_tolerant` — the INTERNAL-position sibling of
`compare_pngs_height_tolerant`. The comparator forgives ONLY a benign uniform
content shift of <= max_shift px (in x and/or y) that reconciles the overlap to
ZERO mismatched pixels, and hard-fails everything else.

RED-FIRST DISCIPLINE (Clayton's gate): the FAIL suite is the load-bearing proof
and leads this file — a >=2px shift, a hue change, a 1px-shift-that-masks-a-recolor,
and a contiguous block must ALL hard-fail. The never-false-green line is what the
comparator exists to hold; the PASS cases (the actual 1px band-shift flake class)
are the easy half.

Pure in-memory synthetic images (no Playwright / pytest-playwright / :8000 / browser)
— :7999-discretionary venue. 100% line + branch coverage target.
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

# Make the e2e_ui pure helper importable without pulling in the Playwright-heavy
# conftest (the comparator core has no Playwright dependency). Matches the sibling
# suites' convention (test_visual_height_tolerance / test_visual_aa_scatter_tolerant)
# so all three share ONE module object — coverage measures the bare name cleanly.
_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

from visual_height_tolerance import (  # noqa: E402
    ContentShiftResult,
    compare_pngs_content_shift_tolerant,
)


# ---------------------------------------------------------------------------
# Synthetic-image helpers — an ASYMMETRIC mark (a solid square at a known
# position) so a shift is both detectable AND uniquely reconcilable: unlike a
# full-width band, a square breaks x- AND y-translation symmetry, so an identical
# pair zeroes ONLY at offset (0, 0).
# ---------------------------------------------------------------------------

_BG    = ( 250, 250, 250 )
_GREEN = ( 25, 135, 84 )      # #198754 — the legacy header green
_RED   = ( 200, 60, 60 )      # a hue-swap that pixelmatch must never forgive
_BLUE  = ( 10, 10, 200 )      # a contiguous foreign block

def _png( img: Image.Image ) -> bytes:
    buf = BytesIO()
    img.save( buf, "PNG" )
    return buf.getvalue()

def _mark( *, dx=0, dy=0, hue=False, block=False, size=( 60, 60 ), extra_height=0 ) -> bytes:
    """
    A `size` white canvas (optionally `extra_height` px taller) with a 12x12 solid
    square at (18+dx, 18+dy). `hue` recolors the square red; `block` adds a foreign
    blue rectangle in a corner (a contiguous regression no shift can remove).
    """
    w, h = size
    img  = Image.new( "RGB", ( w, h + extra_height ), _BG )
    px   = img.load()
    color = _RED if hue else _GREEN
    for y in range( 18 + dy, 30 + dy ):
        for x in range( 18 + dx, 30 + dx ):
            px[ x, y ] = color
    if block:
        for y in range( 2, 10 ):
            for x in range( 2, 24 ):
                px[ x, y ] = _BLUE
    return _png( img )


# ===========================================================================
# FAIL SUITE  (leads the file — the never-false-green proof)
# ===========================================================================

def test_fail_two_px_shift_not_reconciled():
    """A >=2px uniform shift cannot re-align within a +/-1px search -> hard-fail."""
    result = compare_pngs_content_shift_tolerant( _mark( dx=2 ), _mark() )
    assert result.matched is False
    assert result.best_mismatch > 0
    assert "no <= 1px shift reconciles" in result.reason

def test_fail_hue_delta_at_zero_shift():
    """A pure recolor (no shift) leaves a nonzero delta at every offset -> hard-fail."""
    result = compare_pngs_content_shift_tolerant( _mark( hue=True ), _mark() )
    assert result.matched is False
    assert result.best_mismatch > 0

def test_fail_one_px_shift_plus_hue_recolor():
    """
    Clayton's key case: a 1px shift that ALSO recolors. The geometric offset aligns
    position, but pixelmatch still sees the hue at the aligned pixels -> no offset
    fully zeroes -> hard-fail. A shift can never launder a recolor.
    """
    result = compare_pngs_content_shift_tolerant( _mark( dx=1, dy=1, hue=True ), _mark() )
    assert result.matched is False
    assert result.best_mismatch > 0

def test_fail_contiguous_block_regression():
    """A new contiguous block present in only one image -> no shift removes it -> fail."""
    result = compare_pngs_content_shift_tolerant( _mark( block=True ), _mark() )
    assert result.matched is False
    assert result.best_mismatch > 0

def test_fail_width_mismatch_never_tolerated():
    """Width is load-bearing (bug 99326963) — any width delta hard-fails, no search."""
    result = compare_pngs_content_shift_tolerant( _mark( size=( 61, 60 ) ), _mark( size=( 60, 60 ) ) )
    assert result.matched is False
    assert "width mismatch" in result.reason
    assert result.best_dx == 0 and result.best_dy == 0

def test_fail_height_delta_exceeds_tolerance():
    """A height delta beyond max_height_delta hard-fails before any pixel search."""
    result = compare_pngs_content_shift_tolerant(
        _mark( extra_height=3 ), _mark(), max_height_delta=1
    )
    assert result.matched is False
    assert "height delta" in result.reason


# ===========================================================================
# PASS SUITE  (the benign 1px content-shift flake class)
# ===========================================================================

def test_pass_one_px_vertical_shift():
    """The real flake class: a uniform 1px vertical content shift is forgiven."""
    result = compare_pngs_content_shift_tolerant( _mark( dy=1 ), _mark() )
    assert result.matched is True
    assert result.best_mismatch == 0
    assert ( result.best_dx, result.best_dy ) == ( 0, 1 )
    assert "forgave a uniform" in result.reason

def test_pass_one_px_horizontal_shift():
    """A uniform 1px horizontal content shift is forgiven too (x within budget)."""
    result = compare_pngs_content_shift_tolerant( _mark( dx=1 ), _mark() )
    assert result.matched is True
    assert ( result.best_dx, result.best_dy ) == ( 1, 0 )

def test_pass_exact_identical_reports_zero_offset():
    """
    Byte-identical asymmetric images zero UNIQUELY at (0,0) — exercises the
    exact-overlap reason branch (distinct from the shifted-forgive branch).
    """
    result = compare_pngs_content_shift_tolerant( _mark(), _mark() )
    assert result.matched is True
    assert ( result.best_dx, result.best_dy ) == ( 0, 0 )
    assert "exact overlap at zero shift" in result.reason

def test_pass_shift_with_tolerated_height_delta():
    """A 1px shift AND a <=max_height_delta height growth are BOTH forgiven; the
    tolerated_delta reflects the height forgiven under the same-width crop."""
    result = compare_pngs_content_shift_tolerant( _mark( dy=1, extra_height=1 ), _mark() )
    assert result.matched is True
    assert result.tolerated_delta == 1


# ===========================================================================
# BRANCH-COVERAGE EDGES
# ===========================================================================

def test_degenerate_overlap_offsets_are_skipped():
    """
    A 1x1 image with max_shift=1: the +/-1 offsets have an EMPTY overlap (skipped
    via `continue`), and only (0,0) is a valid compare. Identical -> matched at (0,0).
    Exercises the degenerate-overlap guard.
    """
    one = _png( Image.new( "RGB", ( 1, 1 ), _GREEN ) )
    result = compare_pngs_content_shift_tolerant( one, one, max_shift=1 )
    assert result.matched is True
    assert ( result.best_dx, result.best_dy ) == ( 0, 0 )

def test_threshold_is_honored():
    """A sub-threshold color jitter is absorbed by pixelmatch's own threshold, so
    even at zero shift the images read as matching (threshold semantics preserved)."""
    base = _mark()
    # a 1-level per-channel jitter on the whole canvas, no shift
    img  = Image.open( BytesIO( base ) ).convert( "RGB" )
    px   = img.load()
    w, h = img.size
    for y in range( h ):
        for x in range( w ):
            r, g, b = px[ x, y ]
            px[ x, y ] = ( min( 255, r + 1 ), g, b )
    result = compare_pngs_content_shift_tolerant( _png( img ), base, threshold=0.2 )
    assert result.matched is True

def test_result_is_frozen_dataclass():
    """ContentShiftResult is an immutable receipt (no post-hoc mutation of a verdict)."""
    result = compare_pngs_content_shift_tolerant( _mark(), _mark() )
    assert isinstance( result, ContentShiftResult )
    with pytest.raises( Exception ):
        result.matched = False        # frozen -> FrozenInstanceError


if __name__ == "__main__":            # pragma: no cover - manual entrypoint
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
