"""
Unit tests for the pixel-stage strictness of the three PNG comparators (row 4f5301ad).

pixelmatch scores a pixel pair in YIQ, so at the old per-pixel threshold of 0.1 a flat
blue shift of +78/255 across EVERY pixel counted as zero difference, and its default
includeAA=False dropped isolated renderer-blended edge pixels from the count. These
tests pin the repaired behaviour at each call site:

    :129  compare_pngs_height_tolerant         must differ on a flat +78 tint and on one AA-edge pixel
    :646  compare_pngs_content_shift_tolerant  must differ on the same two
    :407  compare_pngs_aa_scatter_tolerant     must differ on the tint, and still FORGIVE a lone pixel
                                               (isolated scatter is what it exists to absorb)

The AA-edge pixel comes from a supersampled circle, so its edge is really blended (a
hard-edged PIL line is not anti-aliased and proves nothing). The fixture is also checked
against pixelmatch's own default, so a fixture that stops being AA fails loudly here
instead of quietly turning the test into a flat-pixel test.

Pure in-memory images, no Playwright and no server: :7999-discretionary.
"""

from __future__ import annotations

import ast
import inspect
import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pixelmatch.contrib.PIL import pixelmatch

_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

import visual_height_tolerance as vht  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — mid-tone content so a +78 blue shift never clips at 255
# ---------------------------------------------------------------------------

_BG   = ( 100, 120, 90 )
_DISC = ( 10, 20, 15 )

def _png( arr: np.ndarray ) -> bytes:
    buf = BytesIO()
    Image.fromarray( arr ).save( buf, "PNG" )
    return buf.getvalue()

def _base() -> np.ndarray:
    """A 96x96 disc with a genuinely anti-aliased edge (drawn at 4x, BOX-reduced: no ringing, so pixelmatch sees a clean blended edge)."""
    big = Image.new( "RGB", ( 384, 384 ), _BG )
    from PIL import ImageDraw
    ImageDraw.Draw( big ).ellipse( ( 60, 60, 324, 324 ), fill=_DISC )
    return np.array( big.resize( ( 96, 96 ), Image.BOX ) )

def _pm( a: np.ndarray, b: np.ndarray, **kw ) -> int:
    ia, ib = Image.fromarray( a ), Image.fromarray( b )
    return pixelmatch( ia, ib, Image.new( "RGBA", ia.size ), threshold=0, **kw )

def _perturbed( arr: np.ndarray, y: int, x: int ) -> np.ndarray:
    out = arr.copy()
    out[ y, x ] = ( 255, 0, 255 )
    return out

def _find_pixel( arr: np.ndarray, *, edge: bool ):
    """
    A pixel to perturb, chosen by asking pixelmatch itself: an edge pixel is one its default
    (includeAA=False) DROPS but includeAA=True counts; a flat pixel is one it counts either way.
    Guessing from luma spread picked pixels the classifier did not treat as anti-aliasing.
    """
    h, w = arr.shape[ :2 ]
    g    = arr.astype( int ).sum( axis=2 ) / 3
    for y in range( 5, h - 5 ):
        for x in range( 5, w - 5 ):
            n = g[ y - 1:y + 2, x - 1:x + 2 ]
            if edge and n.max() - n.min() <= 30: continue      # cheap prefilter; pixelmatch decides below
            # judge on a small crop: the classifier only reads a pixel's neighbourhood
            base = arr[ y - 4:y + 5, x - 4:x + 5 ]
            pert = _perturbed( base, 4, 4 )
            dropped, counted = _pm( pert, base, includeAA=False ), _pm( pert, base, includeAA=True )
            if ( dropped, counted ) == ( ( 0, 1 ) if edge else ( 1, 1 ) ):
                return y, x
    raise AssertionError( f"fixture has no {'edge' if edge else 'flat'} pixel" )   # pragma: no cover - the fixture always has both

def _with_pixel( arr: np.ndarray, at ) -> np.ndarray:
    out = arr.copy()
    out[ at ] = ( 255, 0, 255 )
    return out

def _tinted( arr: np.ndarray, d: int, channel: int = 2 ) -> np.ndarray:
    out = arr.astype( int )
    out[ :, :, channel ] = np.clip( out[ :, :, channel ] + d, 0, 255 )
    return out.astype( np.uint8 )

def _all_three( actual: np.ndarray, baseline: np.ndarray, **kw ):
    a, b = _png( actual ), _png( baseline )
    return (
        vht.compare_pngs_height_tolerant( a, b, **kw ).matched,
        vht.compare_pngs_aa_scatter_tolerant( a, b, **kw ).matched,
        vht.compare_pngs_content_shift_tolerant( a, b, **kw ).matched,
    )


BASE = _base()


# ---------------------------------------------------------------------------
# Fixture self-checks — the perturbations are what the docstring says they are
# ---------------------------------------------------------------------------

def test_fixture_edge_pixel_really_is_antialiasing_to_pixelmatch():
    edge = _with_pixel( BASE, _find_pixel( BASE, edge=True ) )
    a, b = Image.fromarray( edge ), Image.fromarray( BASE )
    dropped = pixelmatch( a, b, Image.new( "RGBA", a.size ), threshold=0, includeAA=False )
    counted = pixelmatch( a, b, Image.new( "RGBA", a.size ), threshold=0, includeAA=True )
    assert ( dropped, counted ) == ( 0, 1 )   # default drops it; includeAA=True counts it


def test_fixture_flat_pixel_is_not_dropped_as_antialiasing():
    flat = _with_pixel( BASE, _find_pixel( BASE, edge=False ) )
    a, b = Image.fromarray( flat ), Image.fromarray( BASE )
    assert pixelmatch( a, b, Image.new( "RGBA", a.size ), threshold=0, includeAA=False ) == 1


def test_fixture_tint_actually_changes_pixels_and_does_not_clip():
    tint = _tinted( BASE, 78 )
    assert ( tint[ :, :, 2 ].astype( int ) - BASE[ :, :, 2 ].astype( int ) == 78 ).all()


# ---------------------------------------------------------------------------
# The repaired behaviour, one assertion per call site
# ---------------------------------------------------------------------------

def test_identical_images_match_at_all_three_sites():
    assert _all_three( BASE, BASE ) == ( True, True, True )


def test_flat_blue_78_shift_differs_at_all_three_sites():
    # Old settings judged this MATCH at every site (measured 12/12 on real baselines).
    height_tol, aa_scatter, content_shift = _all_three( _tinted( BASE, 78 ), BASE )
    assert height_tol    is False   # :129
    assert content_shift is False   # :646
    assert aa_scatter    is False   # :407 — a tint is not isolated scatter


def test_single_antialiased_edge_pixel_differs_at_129_and_646():
    height_tol, _aa_scatter, content_shift = _all_three( _with_pixel( BASE, _find_pixel( BASE, edge=True ) ), BASE )
    assert height_tol    is False   # :129 — includeAA=True counts the edge pixel
    assert content_shift is False   # :646


@pytest.mark.parametrize( "edge", [ True, False ], ids=[ "aa-edge-pixel", "flat-pixel" ] )
def test_lone_pixel_is_forgiven_at_407(edge):
    # :407 exists to absorb isolated scatter; tightening the pixel stage must not take that away.
    lone = _with_pixel( BASE, _find_pixel( BASE, edge=edge ) )
    assert vht.compare_pngs_aa_scatter_tolerant( _png( lone ), _png( BASE ) ).matched is True


# ---------------------------------------------------------------------------
# Threshold handling: the default is the one tolerance, and an explicit value is honoured
# ---------------------------------------------------------------------------

def test_explicit_threshold_is_honoured_at_every_site():
    # +78 is inside pixelmatch's 0.1 budget, so asking for 0.1 must reproduce the old leniency.
    # This is what fails if a site hardcodes its own threshold and ignores the argument.
    assert _all_three( _tinted( BASE, 78 ), BASE, threshold=0.1 ) == ( True, True, True )


def test_pixel_threshold_is_the_one_tolerance_and_every_signature_uses_it():
    assert vht.PIXEL_THRESHOLD == 0.03
    for fn in (
        vht.compare_pngs_height_tolerant,
        vht.compare_pngs_aa_scatter_tolerant,
        vht.compare_pngs_content_shift_tolerant,
    ):
        assert inspect.signature( fn ).parameters[ "threshold" ].default == vht.PIXEL_THRESHOLD, fn.__name__


def test_gate_callers_do_not_reintroduce_the_ini_threshold():
    """
    The fixtures in e2e_ui/conftest.py used to pass the ini key's 0.1 into every comparator,
    which would have made the new default unreachable from the merge gate. Walk the calls
    instead of grepping the text, so a rename or a reflow cannot hide one.
    """
    tree  = ast.parse( ( _E2E_UI_DIR / "conftest.py" ).read_text() )
    names = { "compare_pngs_height_tolerant", "compare_pngs_aa_scatter_tolerant", "compare_pngs_content_shift_tolerant" }
    calls = [
        n for n in ast.walk( tree )
        if isinstance( n, ast.Call ) and isinstance( n.func, ast.Name ) and n.func.id in names
    ]
    assert { c.func.id for c in calls } == names            # found all three, so the loop below is not vacuous
    for c in calls:
        assert "threshold" not in { k.arg for k in c.keywords }, c.func.id
