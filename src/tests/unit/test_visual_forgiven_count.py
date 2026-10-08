"""
A pass inside the tolerance says how many pixels the tolerance forgave.

A pass at the 0.03 threshold means zero mismatched pixels at that threshold, so the comparator's own count
is always 0 on a pass. The number worth knowing is how many pixels differ at threshold 0.0 on the same
region. A clean pass prints nothing, a failure fails as before, and the extra count can never fail a pass.

Pure in-memory images, no Playwright and no server: :7999-discretionary.
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

_E2E_UI_DIR = Path( __file__ ).resolve().parents[ 1 ] / "e2e_ui"
if str( _E2E_UI_DIR ) not in sys.path:
    sys.path.insert( 0, str( _E2E_UI_DIR ) )

import numpy as np
import visual_height_tolerance as vht  # noqa: E402
from tests.unit import test_visual_pixel_comparator_strictness as strict  # noqa: E402

GREY = ( 120, 120, 120, 255 )
NAME = "card.png"


def _png( width, height, dots=0, shade=2 ):
    """A flat grey picture; `dots` pixels on the top row are `shade` grey levels lighter."""
    img = Image.new( "RGBA", ( width, height ), GREY )
    for x in range( dots ): img.putpixel( ( x, 0 ), ( GREY[ 0 ] + shade, GREY[ 1 ] + shade, GREY[ 2 ] + shade, 255 ) )
    buf = BytesIO()
    img.save( buf, "PNG" )
    return buf.getvalue()


def test_a_pass_inside_the_tolerance_counts_the_forgiven_pixels_and_prints_one_line():
    result = vht.compare_pngs_height_tolerant( _png( 40, 30, dots=12 ), _png( 40, 30 ) )
    assert result.matched is True, "the 2-shade dither must pass at the 0.03 threshold"
    assert result.mismatch_pixels == 0, "a pass has no mismatch at the threshold in force"
    assert result.forgiven_pixels == 12, f"expected the 12 dithered pixels, got {result.forgiven_pixels}"
    assert ( result.compared_width, result.compared_height ) == ( 40, 30 )
    line = vht.forgiven_line( NAME, result, vht.PIXEL_THRESHOLD )
    for part in ( NAME, "12 pixel(s) differ at threshold 0.0", "40x30", "threshold in force 0.03" ):
        assert part in line, f"{part!r} is missing from the printed line: {line!r}"
    assert "\n" not in line


def test_an_exact_match_prints_nothing():
    result = vht.compare_pngs_height_tolerant( _png( 40, 30 ), _png( 40, 30 ) )
    assert result.matched is True
    assert result.forgiven_pixels == 0, "no pixel differs, so none was forgiven"
    assert vht.forgiven_line( NAME, result, vht.PIXEL_THRESHOLD ) is None, "an exact match must print nothing"


def test_a_mismatch_over_the_tolerance_still_fails_and_forgives_nothing():
    result = vht.compare_pngs_height_tolerant( _png( 40, 30, dots=5, shade=60 ), _png( 40, 30 ) )
    assert result.matched is False, "a 60-shade change is over the tolerance and must fail"
    assert result.mismatch_pixels == 5
    assert result.forgiven_pixels == 0, "a failure forgives nothing"
    assert vht.forgiven_line( NAME, result, vht.PIXEL_THRESHOLD ) is None


def test_the_count_is_taken_over_the_overlap_when_the_heights_differ():
    result = vht.compare_pngs_height_tolerant( _png( 40, 31, dots=7 ), _png( 40, 30 ) )
    assert result.matched is True and result.tolerated_delta == 1
    assert result.forgiven_pixels == 7
    assert ( result.compared_width, result.compared_height ) == ( 40, 30 ), "the region is the shorter height, top-anchored"


def test_a_failing_second_count_cannot_turn_a_pass_into_a_failure( monkeypatch ):
    real  = vht.pixelmatch
    calls = [ ]
    def second_call_breaks( a, b, out, **kwargs ):
        calls.append( kwargs[ "threshold" ] )
        if kwargs[ "threshold" ] == 0.0: raise MemoryError( "the extra count failed" )
        return real( a, b, out, **kwargs )
    monkeypatch.setattr( vht, "pixelmatch", second_call_breaks )
    result = vht.compare_pngs_height_tolerant( _png( 40, 30, dots=12 ), _png( 40, 30 ) )
    assert calls == [ vht.PIXEL_THRESHOLD, 0.0 ], f"expected the gate call then the extra count, got {calls}"
    assert result.matched is True, "the extra count raised, and the pass must stand"
    assert result.forgiven_pixels == -1
    assert "could not be counted" in vht.forgiven_line( NAME, result, vht.PIXEL_THRESHOLD )


def _png_uncompressed( width, height ):
    buf = BytesIO()
    Image.new( "RGBA", ( width, height ), GREY ).save( buf, "PNG", compress_level=0 )
    return buf.getvalue()


def test_a_threshold_of_zero_takes_no_second_count( monkeypatch ):
    real  = vht.pixelmatch
    calls = [ ]
    monkeypatch.setattr( vht, "pixelmatch", lambda a, b, out, **kwargs: calls.append( kwargs[ "threshold" ] ) or real( a, b, out, **kwargs ) )
    assert _png( 40, 30 ) != _png_uncompressed( 40, 30 ), "the two files must differ in bytes, or the identical-bytes skip hides the check"
    result = vht.compare_pngs_height_tolerant( _png( 40, 30 ), _png_uncompressed( 40, 30 ), threshold=0.0 )
    assert result.matched is True and result.forgiven_pixels == 0
    assert calls == [ 0.0 ], f"nothing was forgiven at threshold 0.0, so one call only, got {calls}"


def test_the_line_for_an_uncounted_pass_is_not_silent():
    result = vht.HeightTolerantResult( matched=True, reason="r", mismatch_pixels=0, tolerated_delta=0, forgiven_pixels=-1, compared_width=4, compared_height=3 )
    line = vht.forgiven_line( NAME, result, 0.03 )
    assert line is not None and NAME in line and "4x3" in line


def test_a_result_built_without_the_new_fields_reads_as_nothing_forgiven():
    result = vht.HeightTolerantResult( matched=True, reason="r", mismatch_pixels=0, tolerated_delta=0 )
    assert (result.forgiven_pixels, result.compared_width, result.compared_height) == (0, 0, 0)
    assert vht.forgiven_line( NAME, result, 0.03 ) is None


def test_byte_identical_pictures_skip_the_second_count( monkeypatch ):
    real  = vht.pixelmatch
    calls = [ ]
    monkeypatch.setattr( vht, "pixelmatch", lambda a, b, out, **kwargs: calls.append( kwargs[ "threshold" ] ) or real( a, b, out, **kwargs ) )
    same = _png( 40, 30 )
    result = vht.compare_pngs_height_tolerant( same, bytes( same ) )
    assert result.matched is True and result.forgiven_pixels == 0
    assert calls == [ vht.PIXEL_THRESHOLD ], f"identical bytes need no second count, got {calls}"
    again = vht.compare_pngs_height_tolerant( _png( 40, 30, dots=1 ), _png( 40, 30 ) )
    assert again.forgiven_pixels == 1, "different bytes must still take the second count"


def test_an_anti_aliased_edge_pixel_is_counted_too():
    nudged = strict.BASE.copy()
    nudged[ 15, 40 ] = np.clip( nudged[ 15, 40 ].astype( int ) + 2, 0, 255 ).astype( np.uint8 )
    a, b = Image.fromarray( nudged ).convert( "RGBA" ), Image.fromarray( strict.BASE ).convert( "RGBA" )
    blank = lambda: Image.new( "RGBA", a.size )
    assert vht.pixelmatch( a, b, blank(), threshold=0.0, includeAA=False ) == 0, "the fixture pixel must be one the default count drops"
    result = vht.compare_pngs_height_tolerant( strict._png( nudged ), strict._png( strict.BASE ) )
    assert result.matched is True, "a 2-shade nudge of one edge pixel is inside the tolerance"
    assert result.forgiven_pixels == 1, f"the edge pixel was dropped from the count: {result.forgiven_pixels}"
