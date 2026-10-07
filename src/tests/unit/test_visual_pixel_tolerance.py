"""
Unit tests for the one pixel tolerance of the visual comparators.

The e2e_a gate went red on pictures that differed by 1 shade on a third of their pixels.
The largest difference was 7 of 255, nothing a person could see. PIXEL_THRESHOLD now forgives that
and nothing bigger. These tests drive the real comparators with the real constant on synthetic
pictures, so they need no browser and no server.

    - shade noise up to 7 grey on 36% of the pixels passes all three comparators
    - a block moved 12 shades or more, or a recoloured block, fails all three
    - a lone dot moved 60 shades fails the height and shift comparators
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

import visual_height_tolerance as vht  # noqa: E402


def _png( arr: np.ndarray ) -> bytes:
    buf = BytesIO()
    Image.fromarray( arr ).save( buf, "PNG" )
    return buf.getvalue()


def _card() -> np.ndarray:
    """A 160x100 mid-tone card with a header band and a lighter body; no shift clips."""
    arr = np.full( ( 100, 160, 3 ), 120, dtype=np.uint8 )
    arr[ :30 ] = ( 90, 100, 130 )
    arr[ 60:90, 20:140 ] = ( 150, 150, 150 )
    return arr


def _noisy( arr: np.ndarray, *, top: int, share: float ) -> np.ndarray:
    """Move `share` of the pixels by up to `top` grey shades; seeded, so a run repeats."""
    rng  = np.random.default_rng( 7 )
    out  = arr.astype( int )
    hit  = rng.random( arr.shape[ :2 ] ) < share
    step = rng.integers( 1, top + 1, size=arr.shape[ :2 ] ) * rng.choice( [ -1, 1 ], size=arr.shape[ :2 ] )
    out[ hit ] += step[ hit ][ :, None ]
    out[ 5, 5 ] = arr[ 5, 5 ].astype( int ) + top
    return np.clip( out, 0, 255 ).astype( np.uint8 )


def _moved( arr: np.ndarray, box: tuple, delta: tuple ) -> np.ndarray:
    top, left, bottom, right = box
    out = arr.astype( int )
    out[ top:bottom, left:right ] += np.array( delta )
    return np.clip( out, 0, 255 ).astype( np.uint8 )


def _all_three( actual: np.ndarray, baseline: np.ndarray ) -> dict:
    a, b = _png( actual ), _png( baseline )
    return {
        "height"       : vht.compare_pngs_height_tolerant( a, b ).matched,
        "aa_scatter"   : vht.compare_pngs_aa_scatter_tolerant( a, b ).matched,
        "content_shift": vht.compare_pngs_content_shift_tolerant( a, b ).matched,
    }


CARD = _card()


def test_the_noise_fixture_really_is_wide_and_shallow():
    noisy = _noisy( CARD, top=7, share=0.36 )
    gap   = np.abs( noisy.astype( int ) - CARD.astype( int ) ).max( axis=2 )
    assert int( gap.max() ) == 7
    assert 0.30 < ( gap > 0 ).mean() < 0.42


def test_the_noise_fixture_fails_at_the_old_strict_threshold():
    # Without this the pass below could be a picture that never differed.
    noisy = _noisy( CARD, top=7, share=0.36 )
    assert vht.compare_pngs_height_tolerant( _png( noisy ), _png( CARD ), threshold=0.0 ).matched is False
    assert vht.compare_pngs_content_shift_tolerant( _png( noisy ), _png( CARD ), threshold=0.0 ).matched is False


def test_shade_noise_of_seven_on_a_third_of_the_pixels_passes_all_three():
    assert _all_three( _noisy( CARD, top=7, share=0.36 ), CARD ) == { "height": True, "aa_scatter": True, "content_shift": True }


@pytest.mark.parametrize( "delta", [ ( 12, 12, 12 ), ( 20, 20, 20 ), ( 40, 0, 0 ) ], ids=[ "grey-12", "grey-20", "red-40" ] )
def test_a_block_moved_past_the_tolerance_fails_all_three( delta ):
    changed = _moved( CARD, ( 40, 50, 60, 70 ), delta )
    assert _all_three( changed, CARD ) == { "height": False, "aa_scatter": False, "content_shift": False }


@pytest.mark.parametrize( "box", [ ( 40, 50, 42, 52 ), ( 40, 50, 41, 51 ) ], ids=[ "2x2-dot", "1-pixel" ] )
def test_a_dot_moved_sixty_shades_fails_height_and_shift( box ):
    # aa_scatter exists to forgive an isolated dot, so it is not asked here (see the strictness tests).
    result = _all_three( _moved( CARD, box, ( 60, 60, 60 ) ), CARD )
    assert result[ "height" ] is False and result[ "content_shift" ] is False


def test_the_tolerance_does_not_hide_a_size_change():
    taller = np.vstack( [ CARD, CARD[ -3: ] ] )
    assert vht.compare_pngs_height_tolerant( _png( taller ), _png( CARD ) ).matched is False
