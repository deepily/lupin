"""
Unit tests — spatially-aware anti-aliasing-scatter-tolerant comparator
(bug 660d02b4, P3 follow-on to resolution D; task d90dcfc2).

Pure, synthetic in-memory PNGs; NO Playwright, NO server, NO :8000. Venue :7999
(AI-discretionary). Proves the NEVER-FALSE-GREEN contract of
`src/tests/e2e_ui/visual_height_tolerance.compare_pngs_aa_scatter_tolerant`
and drives it to 100% line + branch coverage.

THE CENTRAL PROOF (test_scatter_passes_while_smaller_block_fails): a 500px field
of spatially-ISOLATED single-pixel scatter PASSES, while a 400px CONTIGUOUS
recolored block FAILS — even though the block has FEWER mismatched pixels. This
is exactly the discrimination a blunt maxDiffPixels COUNT budget cannot make
(the reason resolution D dropped the pixel assertion), and the reason a spatial
connected-component + erosion filter can: benign font-AA jitter is isolated
specks; a real regression is a contiguous cluster.

The mandatory proof matrix (per task d90dcfc2):
    (a) ~20x20=400px CONTIGUOUS recolored block  -> FAIL (even though 400 < scatter count)
    (b) width change / size (height) change       -> FAIL
    (c) real content shift                        -> FAIL
    (d) pure scattered isolated AA                -> PASS
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

from visual_height_tolerance import compare_pngs_aa_scatter_tolerant  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic-image helpers
# ---------------------------------------------------------------------------

WHITE = ( 255, 255, 255, 255 )
BLACK = ( 0, 0, 0, 255 )
PILL  = ( 80, 120, 200, 255 )     # a "recolored pill / heat-tint" regression color
RED   = ( 255, 0, 0, 255 )


def _png( width: int, height: int, color=WHITE ) -> bytes:
    img = Image.new( "RGBA", ( width, height ), color )
    buf = BytesIO()
    img.save( buf, format="PNG" )
    return buf.getvalue()


def _to_bytes( img: Image.Image ) -> bytes:
    buf = BytesIO()
    img.save( buf, format="PNG" )
    return buf.getvalue()


def _white( width: int, height: int ) -> Image.Image:
    return Image.new( "RGBA", ( width, height ), WHITE )


def _png_with_specks( width: int, height: int, points ) -> bytes:
    """A white field with isolated single-pixel BLACK specks at `points`."""
    img = _white( width, height )
    px  = img.load()
    for ( x, y ) in points:
        px[ x, y ] = BLACK
    return _to_bytes( img )


def _grid_specks( width: int, height: int, count: int, stride: int = 3 ):
    """`count` points on a stride-spaced grid so NONE are 8-connected (each stays
    an isolated cluster of area 1). stride>=2 guarantees a ≥1px gap on every
    side including diagonals."""
    pts = []
    for y in range( 1, height, stride ):
        for x in range( 1, width, stride ):
            pts.append( ( x, y ) )
            if len( pts ) == count:
                return pts
    return pts


def _png_with_block( width: int, height: int, box, color=PILL ) -> bytes:
    """A white field with one solid contiguous recolored rectangle `box`=(x,y,w,h)."""
    img          = _white( width, height )
    x, y, bw, bh = box
    img.paste( Image.new( "RGBA", ( bw, bh ), color ), ( x, y ) )
    return _to_bytes( img )


def _png_vbars( width: int, height: int, x_positions, bar_w=2, bar_h=12, y=4 ) -> bytes:
    """White field with vertical BLACK bars (glyph-stroke stand-ins) at the given
    x positions. Shifting these models a real content shift."""
    img = _white( width, height )
    for x in x_positions:
        img.paste( Image.new( "RGBA", ( bar_w, bar_h ), BLACK ), ( x, y ) )
    return _to_bytes( img )


# ---------------------------------------------------------------------------
# THE CENTRAL never-false-green proof
# ---------------------------------------------------------------------------

def test_scatter_passes_while_smaller_block_fails():
    """
    500px of ISOLATED scatter PASSES; a 400px CONTIGUOUS block FAILS — despite
    the block having FEWER mismatched pixels. This is the exact discrimination a
    maxDiffPixels COUNT budget cannot make and this comparator can.
    """
    W, H = 200, 120

    baseline = _png( W, H, WHITE )

    # 500 isolated single-px specks (more px than the block below).
    scatter  = _png_with_specks( W, H, _grid_specks( W, H, count=500 ) )
    scat_res = compare_pngs_aa_scatter_tolerant( scatter, baseline )

    # 20x20 = 400px contiguous recolored pill (fewer px than the scatter).
    block    = _png_with_block( W, H, box=( 40, 40, 20, 20 ) )
    blk_res  = compare_pngs_aa_scatter_tolerant( block, baseline )

    # The count budget's blind spot, made explicit:
    assert scat_res.total_diff_pixels > blk_res.total_diff_pixels   # 500 > 400
    # ...yet the spatial verdicts are opposite and correct:
    assert scat_res.matched is True                                  # (d) isolated scatter forgiven
    assert scat_res.largest_cluster_area == 1                        # every cluster is a lone pixel
    assert scat_res.erosion_survivors == 0
    assert blk_res.matched is False                                  # (a) contiguous block caught
    assert blk_res.largest_cluster_area == 400
    assert "contiguous-regression signal" in blk_res.reason


# ---------------------------------------------------------------------------
# (a) contiguous block FAILS
# ---------------------------------------------------------------------------

def test_contiguous_20x20_block_fails():
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_block( 200, 120, box=( 50, 50, 20, 20 ) )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is False
    assert res.total_diff_pixels == 400
    assert res.largest_cluster_area == 400
    assert res.erosion_survivors > 0                # solid blob survives erosion
    assert "largest cluster" in res.reason


# ---------------------------------------------------------------------------
# (b) width / size change FAILS
# ---------------------------------------------------------------------------

def test_width_change_fails():
    baseline = _png( 200, 120, WHITE )
    actual   = _png( 201, 120, WHITE )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is False
    assert res.largest_cluster_area == 0
    assert "width mismatch" in res.reason


def test_height_change_beyond_budget_fails():
    baseline = _png( 200, 120, WHITE )
    actual   = _png( 200, 123, WHITE )              # +3px, default budget 1

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is False
    assert res.erosion_survivors == 0
    assert "exceeds tolerance" in res.reason


# ---------------------------------------------------------------------------
# (c) real content shift FAILS
# ---------------------------------------------------------------------------

def test_content_shift_fails():
    """Vertical glyph-stroke bars shifted right by 3px → connected glyph-height
    runs whose area exceeds the isolated-AA floor → FAIL (no false green)."""
    W, H     = 200, 40
    xs       = [ 20, 40, 60, 80, 100 ]
    baseline = _png_vbars( W, H, xs )
    actual   = _png_vbars( W, H, [ x + 3 for x in xs ] )     # shifted content

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is False
    assert res.largest_cluster_area > 2             # a glyph-height run, not a speck
    assert "contiguous-regression signal" in res.reason


# ---------------------------------------------------------------------------
# (d) pure scattered isolated AA PASSES
# ---------------------------------------------------------------------------

def test_pure_isolated_scatter_passes():
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_specks( 200, 120, _grid_specks( 200, 120, count=300 ) )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is True
    assert res.total_diff_pixels == 300
    assert res.component_count == 300               # each speck its own cluster
    assert res.largest_cluster_area == 1
    assert res.erosion_survivors == 0
    assert "isolated AA scatter" in res.reason


# ---------------------------------------------------------------------------
# Branch coverage — the total_diff==0 (identical overlap) paths
# ---------------------------------------------------------------------------

def test_identical_same_size_matches_exactly():
    baseline = _png( 200, 120, WHITE )
    actual   = _png( 200, 120, WHITE )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is True
    assert res.total_diff_pixels == 0
    assert res.tolerated_delta == 0
    assert "exact size" in res.reason


def test_benign_height_delta_identical_overlap_matches():
    # Baseline 200x120 white; actual 200x121 = same 120 white rows + 1 extra
    # white bottom row. Overlap identical (0 diff) → matched with tolerated_delta.
    baseline = _png( 200, 120, WHITE )
    actual   = _png( 200, 121, WHITE )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline )

    assert res.matched is True
    assert res.total_diff_pixels == 0
    assert res.tolerated_delta == 1
    assert "bottom-edge height delta" in res.reason


# ---------------------------------------------------------------------------
# Branch coverage — each contiguity signal, isolated
# ---------------------------------------------------------------------------

def test_block_fail_via_erosion_when_area_floor_is_lifted():
    """Independently exercise the erosion (solid-block) branch: lift the area
    floor above the block so area_fail is False, leaving erosion as the tripwire."""
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_block( 200, 120, box=( 40, 40, 20, 20 ) )   # area 400

    res = compare_pngs_aa_scatter_tolerant( actual, baseline, max_isolated_cluster=1000 )

    assert res.matched is False
    assert res.largest_cluster_area == 400          # 400 ≤ 1000 → area_fail False
    assert res.erosion_survivors > 0                # ...but erosion catches the blob
    assert "survived" in res.reason
    assert "largest cluster" not in res.reason      # area branch did NOT fire


def test_scatter_fail_via_total_ceiling_when_clusters_are_isolated():
    """Independently exercise the total-scatter ceiling branch: all clusters are
    isolated (area 1, no erosion survivor) but the total exceeds the ceiling."""
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_specks( 200, 120, _grid_specks( 200, 120, count=5 ) )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline, max_total_scatter=3 )

    assert res.matched is False
    assert res.largest_cluster_area == 1            # area_fail False
    assert res.erosion_survivors == 0               # block_fail False
    assert res.total_diff_pixels == 5               # 5 > ceiling 3 → scatter_fail True
    assert "total scatter" in res.reason


def test_total_ceiling_not_exceeded_still_passes():
    """max_total_scatter set but NOT exceeded → the scatter_fail-False branch."""
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_specks( 200, 120, _grid_specks( 200, 120, count=5 ) )

    res = compare_pngs_aa_scatter_tolerant( actual, baseline, max_total_scatter=100 )

    assert res.matched is True
    assert res.total_diff_pixels == 5
    assert "isolated AA scatter" in res.reason


def test_all_three_signals_report_together():
    """A large, thick, high-count block trips area AND erosion AND ceiling — the
    reason enumerates every fired cause."""
    baseline = _png( 200, 120, WHITE )
    actual   = _png_with_block( 200, 120, box=( 20, 20, 40, 40 ), color=BLACK )  # 1600px

    res = compare_pngs_aa_scatter_tolerant( actual, baseline, max_total_scatter=100 )

    assert res.matched is False
    assert "largest cluster" in res.reason
    assert "survived" in res.reason
    assert "total scatter" in res.reason


def test_cluster_just_above_floor_fails_but_at_floor_passes():
    """Boundary: a 2-px connected cluster is at the default floor (PASS on the
    area signal); a 3-px connected L keeps erosion at 0 but trips area (FAIL).
    Pins the > (not >=) semantics of the floor."""
    baseline = _png( 60, 60, WHITE )

    # Two horizontally-adjacent px = one cluster of area 2 (== floor 2). A 1px-thin
    # 2-long line has no erosion survivor → PASS.
    at_floor = _png_with_specks( 60, 60, [ ( 10, 10 ), ( 11, 10 ) ] )
    res_ok   = compare_pngs_aa_scatter_tolerant( at_floor, baseline )
    assert res_ok.matched is True
    assert res_ok.largest_cluster_area == 2
    assert res_ok.erosion_survivors == 0

    # Three px in an L (area 3 > floor 2), still 1px-thin so erosion stays 0 →
    # FAIL purely on the area signal (isolates area_fail from block_fail).
    above    = _png_with_specks( 60, 60, [ ( 20, 20 ), ( 21, 20 ), ( 20, 21 ) ] )
    res_bad  = compare_pngs_aa_scatter_tolerant( above, baseline )
    assert res_bad.matched is False
    assert res_bad.largest_cluster_area == 3
    assert res_bad.erosion_survivors == 0           # area branch alone fired
    assert "largest cluster" in res_bad.reason
    assert "survived" not in res_bad.reason


if __name__ == "__main__":
    import pytest
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
