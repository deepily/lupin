"""
Gated unit tests for the presentation deck verdict (row 63f4d4a6).

These tests ARE the gate the prior scratchpad harness never had: they assert
that the one verdict authority goes RED for every way a deck can be absent or
malformed, and GREEN only for a real multi-slide OPC zip. Because the verdict's
truth value is the return value, a caller cannot render PASS without these
checks passing — which is the structural fix for "an affirmative banner beats
its own wait loop."

Venue: :7999 (pure, read-only against tmp fixtures, sub-second, no server, no
generation) — meets all three §TESTING VENUES criteria.

Decks are built in tmp_path with stdlib zipfile (a .pptx is an OPC zip); no
committed binary and no python-pptx dependency.
"""

import zipfile

import pytest

from cosa.agents.presentation_generator.deck_verdict import (
    verify_presentation_deck,
    DeckVerdict,
)

_SLIDE_MARKER = b"SLIDE-CONTENT-MARKER-1"


def _write_pptx( path, n_slides, decoys=(), compression=zipfile.ZIP_STORED ):
    """
    Write a minimal OPC-shaped zip: a content-types part, n_slides real slide
    parts (ppt/slides/slideN.xml), plus any decoy member names verbatim.
    ZIP_STORED so a data byte can be corrupted at a known location later.
    """
    with zipfile.ZipFile( str( path ), "w", compression=compression ) as zf:
        zf.writestr( "[Content_Types].xml", "<Types/>" )
        for i in range( 1, n_slides + 1 ):
            zf.writestr( f"ppt/slides/slide{i}.xml", f"<p:sld>SLIDE-CONTENT-MARKER-{i}</p:sld>" )
        for name in decoys:
            zf.writestr( name, "<decoy/>" )
    return str( path )


def _corrupt_member_data( path ):
    """Flip one byte inside slide1's stored data so its CRC no longer matches,
    while leaving the End-Of-Central-Directory intact (is_zipfile stays True)."""
    with open( path, "rb" ) as fh:
        raw = bytearray( fh.read() )
    idx = raw.find( _SLIDE_MARKER )
    assert idx != -1, "marker must be present verbatim under ZIP_STORED"
    target = idx + len( _SLIDE_MARKER )          # a data byte after the marker
    raw[ target ] = raw[ target ] ^ 0xFF
    with open( path, "wb" ) as fh:
        fh.write( raw )


# ---- failure modes: each must be a hard FAIL, never a silent skip ----------

@pytest.mark.parametrize( "empty_path", [ None, "" ] )
def test_null_or_empty_path_fails( empty_path ):
    v = verify_presentation_deck( empty_path )
    assert not v
    assert "no pptx_path" in v.reason


def test_recorded_path_but_no_file_fails( tmp_path ):
    v = verify_presentation_deck( str( tmp_path / "never-exported.pptx" ) )
    assert not v
    assert "no file on disk" in v.reason


def test_empty_file_fails( tmp_path ):
    p = tmp_path / "empty.pptx"
    p.write_bytes( b"" )
    v = verify_presentation_deck( str( p ) )
    assert not v
    assert "0 bytes" in v.reason


def test_non_zip_file_fails( tmp_path ):
    p = tmp_path / "not-a-zip.pptx"
    p.write_bytes( b"this is plainly not a zip archive at all" )
    v = verify_presentation_deck( str( p ) )
    assert not v
    assert "not a valid zip" in v.reason


def test_corrupt_zip_member_fails( tmp_path ):
    p = _write_pptx( tmp_path / "corrupt.pptx", n_slides=3 )
    _corrupt_member_data( p )
    assert zipfile.is_zipfile( p )               # still a zip by signature...
    v = verify_presentation_deck( p )
    assert not v                                  # ...but a member fails CRC
    assert "corrupt" in v.reason


def test_valid_zip_with_zero_slides_fails( tmp_path ):
    p = _write_pptx( tmp_path / "no-slides.pptx", n_slides=0 )
    v = verify_presentation_deck( p )
    assert not v
    assert "0 slide" in v.reason


def test_too_few_slides_fails( tmp_path ):
    p = _write_pptx( tmp_path / "three.pptx", n_slides=3 )
    v = verify_presentation_deck( p, min_slides=15 )
    assert not v
    assert "need >= 15" in v.reason


# ---- the pass case, and that decoys are not miscounted ---------------------

def test_valid_multi_slide_deck_passes( tmp_path ):
    p = _write_pptx( tmp_path / "real.pptx", n_slides=15 )
    v = verify_presentation_deck( p )
    assert v
    assert v.slide_count == 15
    assert v.size_bytes > 0


def test_decoy_slide_parts_are_not_counted( tmp_path ):
    # slideLayout / slideMaster-shaped neighbours share the prefix but are not slides.
    p = _write_pptx(
        tmp_path / "with-decoys.pptx", n_slides=2,
        decoys=[ "ppt/slides/slideLayout.xml", "docProps/core.xml" ],
    )
    v = verify_presentation_deck( p )
    assert v
    assert v.slide_count == 2                     # decoys excluded


# ---- the verdict object is the single source of truth ----------------------

def test_verdict_truthiness_and_repr():
    ok  = DeckVerdict( True,  "valid deck: 15 slides", "/x.pptx", 100, 15 )
    bad = DeckVerdict( False, "no pptx_path recorded", None )
    assert bool( ok ) is True and bool( bad ) is False
    assert "PASS" in repr( ok ) and "FAIL" in repr( bad )
