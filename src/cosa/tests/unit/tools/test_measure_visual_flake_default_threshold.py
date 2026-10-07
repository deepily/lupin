"""
Unit tests for the default pixel threshold of the visual flake triage tool.

The gate counts a pixel only past PIXEL_THRESHOLD, so the triage tool that classifies a failing
snapshot must count the same pixels by default. These tests run the real comparators on
synthetic pictures, one inside the tolerance and one just past it.
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image

from cosa.tests.tools.measure_visual_flake import SWAP, main, measure


def _png( arr ):
    buf = BytesIO()
    Image.fromarray( arr ).save( buf, "PNG" )
    return buf.getvalue()


def _card():
    arr = np.full( ( 100, 160, 3 ), 120, dtype=np.uint8 )
    arr[ :30 ] = ( 90, 100, 130 )
    return arr


def _with_block( arr, shades ):
    out = arr.astype( int )
    out[ 40:60, 50:70 ] += shades
    return np.clip( out, 0, 255 ).astype( np.uint8 )


GOLDEN        = _png( _card() )
INSIDE        = _png( _with_block( _card(), 7 ) )
JUST_PAST     = _png( _with_block( _card(), 8 ) )


def test_the_default_threshold_forgives_a_block_seven_shades_off():
    assert measure( INSIDE, GOLDEN ).verdict == SWAP


def test_the_default_threshold_still_counts_a_block_eight_shades_off():
    assert measure( JUST_PAST, GOLDEN ).verdict != SWAP


def test_an_explicit_zero_threshold_counts_the_block_seven_shades_off():
    assert measure( INSIDE, GOLDEN, threshold=0.0 ).verdict != SWAP


def test_the_command_line_default_matches_the_gate( tmp_path ):
    ( tmp_path / "golden.png" ).write_bytes( GOLDEN )
    ( tmp_path / "inside.png" ).write_bytes( INSIDE )
    ( tmp_path / "past.png" ).write_bytes( JUST_PAST )
    assert main( [ "--actual", str( tmp_path / "inside.png" ), "--golden", str( tmp_path / "golden.png" ) ] ) == 0
    assert main( [ "--actual", str( tmp_path / "past.png" ), "--golden", str( tmp_path / "golden.png" ) ] ) != 0
