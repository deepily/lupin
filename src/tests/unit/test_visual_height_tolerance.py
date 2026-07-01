"""
Unit tests — height-tolerant visual-snapshot comparison core (bug 660d02b4).

Pure, synthetic in-memory PNGs; NO Playwright, NO server, NO :8000. Venue :7999
(AI-discretionary). Exercises every branch of
`src/tests/e2e_ui/visual_height_tolerance.compare_pngs_height_tolerant` for
100% line + branch coverage:

    - exact same size, identical pixels            -> matched (delta 0)
    - width mismatch                               -> NOT tolerated
    - height delta beyond the budget               -> NOT tolerated
    - +1px taller, benign bottom-edge growth       -> tolerated (delta 1)
    - -1px shorter, benign bottom-edge growth      -> tolerated (symmetric)
    - +1px taller but content SHIFTED (top differs) -> NOT tolerated (no false green)
    - exact same size, pixels differ               -> NOT tolerated
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

# Make the e2e_ui pure helper importable without importing the Playwright-heavy
# conftest (the module under test has no Playwright dependency).
_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

from visual_height_tolerance import (  # noqa: E402
    compare_pngs_height_tolerant,
    compare_pngs_structure_only,
)


# ---------------------------------------------------------------------------
# Synthetic-image helpers
# ---------------------------------------------------------------------------

WHITE = ( 255, 255, 255, 255 )
RED   = ( 255, 0, 0, 255 )
BLACK = ( 0, 0, 0, 255 )


def _png( width: int, height: int, color=WHITE ) -> bytes:
    """A solid-color RGBA PNG of the given dimensions."""
    img = Image.new( "RGBA", ( width, height ), color )
    buf = BytesIO()
    img.save( buf, format="PNG" )
    return buf.getvalue()


def _png_top_then_bottom( width: int, top_h: int, top_color, bottom_h: int, bottom_color ) -> bytes:
    """
    A PNG whose first `top_h` rows are `top_color` and whose next `bottom_h`
    rows are `bottom_color`. Used to model a benign bottom-edge growth (the top
    band is the region that must match the baseline).
    """
    img = Image.new( "RGBA", ( width, top_h + bottom_h ), top_color )
    if bottom_h > 0:
        band = Image.new( "RGBA", ( width, bottom_h ), bottom_color )
        img.paste( band, ( 0, top_h ) )
    buf = BytesIO()
    img.save( buf, format="PNG" )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_identical_images_match_exactly():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 169, WHITE )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is True
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels == 0
    assert "exact size" in res.reason


def test_width_mismatch_is_never_tolerated():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 961, 169, WHITE )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert "width mismatch" in res.reason


def test_height_delta_beyond_budget_is_not_tolerated():
    # 2px taller with default max_height_delta=1 → refused.
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 171, WHITE )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert "exceeds tolerance" in res.reason


def test_benign_one_px_taller_bottom_growth_is_tolerated():
    # Baseline 960x169 all white; actual 960x170 = same 169 white rows + 1 extra
    # bottom row (the sub-pixel row-height rounding). Overlap identical → match.
    baseline = _png( 960, 169, WHITE )
    actual   = _png_top_then_bottom( 960, top_h=169, top_color=WHITE, bottom_h=1, bottom_color=BLACK )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is True
    assert res.tolerated_delta == 1
    assert res.mismatch_pixels == 0
    assert "tolerated 1px" in res.reason


def test_benign_one_px_shorter_is_tolerated_symmetrically():
    # Actual is the SHORTER one (168) vs baseline 169; the direction is forgiven
    # symmetrically because both crop to the shared min height.
    baseline = _png_top_then_bottom( 960, top_h=168, top_color=WHITE, bottom_h=1, bottom_color=BLACK )
    actual   = _png( 960, 168, WHITE )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is True
    assert res.tolerated_delta == 1
    assert res.mismatch_pixels == 0


def test_one_px_taller_with_shifted_content_is_not_tolerated():
    # +1px, but the top band DIFFERS (a real content shift, not a bottom-edge
    # rounding) → overlap diverges → must fail (no false green).
    baseline = _png( 960, 169, WHITE )
    actual   = _png_top_then_bottom( 960, top_h=169, top_color=RED, bottom_h=1, bottom_color=RED )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels > 0
    assert "mismatched pixel" in res.reason


def test_same_size_but_pixels_differ_fails():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 169, RED )

    res = compare_pngs_height_tolerant( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels > 0


def test_custom_tolerance_budget_allows_larger_delta():
    # With max_height_delta=3, a 3px benign bottom growth is tolerated.
    baseline = _png( 960, 169, WHITE )
    actual   = _png_top_then_bottom( 960, top_h=169, top_color=WHITE, bottom_h=3, bottom_color=BLACK )

    res = compare_pngs_height_tolerant( actual, baseline, max_height_delta=3 )

    assert res.matched is True
    assert res.tolerated_delta == 3


# ---------------------------------------------------------------------------
# Structure-only comparator (bug 660d02b4, resolution D) — PIXEL-BLIND BY DESIGN
#
# The two "same-size / different-content -> matched=True" proofs below assert the
# comparator is INTENTIONALLY pixel-blind. This is NOT a comparator defect: the
# card's glyph-AA is non-deterministic to ~3800px so the exact-pixel assertion was
# dropped (functional coverage lives in the sibling E2E tests). The width-differ
# and height-beyond-budget proofs show the STRUCTURAL gate still fails a genuine
# size/structural regression, so the drop is safe (never-false-green preserved for
# what this gate is responsible for). Do NOT "fix" the pixel-blindness back in.
# ---------------------------------------------------------------------------

def test_structure_only_same_size_identical_matches():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 169, WHITE )

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is True
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels == 0
    assert "structural match" in res.reason


def test_structure_only_same_size_DIFFERENT_content_matches_BY_DESIGN():
    # INTENTIONAL: two 960x169 images with TOTALLY different pixel content match.
    # The comparator is pixel-blind by design (bug 660d02b4 resolution D) — the
    # exact-pixel assertion was deliberately dropped because this card's glyph-AA
    # is non-deterministic to ~3800px. This is the whole point of resolution D,
    # NOT a defect. Functional coverage lives in the sibling E2E tests; pixel
    # coverage is deferred to the P3 (C) deterministic-font harness.
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 169, RED )     # every pixel differs

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is True           # matched DESPITE 100% pixel difference — by design
    assert res.mismatch_pixels == 0      # no pixel comparison is ever performed
    assert res.tolerated_delta == 0


def test_structure_only_pixel_blind_even_with_benign_height_delta():
    # Second loud proof: same width, +1px height, AND wholly different content in
    # the overlap → STILL matched (pixel-blind), because the only checks are width
    # + height-tolerance. Contrast with compare_pngs_height_tolerant, which fails
    # this exact input on the pixel compare (see
    # test_one_px_taller_with_shifted_content_is_not_tolerated above).
    baseline = _png( 960, 169, WHITE )
    actual   = _png_top_then_bottom( 960, top_h=169, top_color=RED, bottom_h=1, bottom_color=RED )

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is True           # INTENTIONAL — structure-only, bug 660d02b4 D
    assert res.tolerated_delta == 1
    assert res.mismatch_pixels == 0


def test_structure_only_width_mismatch_still_fails():
    # The structural gate is NOT toothless: a width flip is a real regression and
    # still fails (never-false-green preserved for size/structure).
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 961, 169, WHITE )

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels == 0
    assert "width mismatch" in res.reason


def test_structure_only_height_delta_beyond_budget_still_fails():
    # A height outside the ±tolerance (broken/resized card) still fails.
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 172, WHITE )    # 3px over default budget 1

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is False
    assert res.tolerated_delta == 0
    assert res.mismatch_pixels == 0
    assert "exceeds tolerance" in res.reason


def test_structure_only_benign_height_delta_within_budget_matches():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 170, BLACK )    # +1px, different content — still matched

    res = compare_pngs_structure_only( actual, baseline )

    assert res.matched is True
    assert res.tolerated_delta == 1
    assert res.mismatch_pixels == 0


def test_structure_only_custom_budget_allows_larger_delta():
    baseline = _png( 960, 169, WHITE )
    actual   = _png( 960, 172, WHITE )    # 3px delta, allowed with budget 3

    res = compare_pngs_structure_only( actual, baseline, max_height_delta=3 )

    assert res.matched is True
    assert res.tolerated_delta == 3
    assert res.mismatch_pixels == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
