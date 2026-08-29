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


def _write_pptx( path, n_slides, decoys=(), compression=zipfile.ZIP_STORED, text_runs_per_slide=1 ):
    """
    Write a minimal OPC-shaped zip: a content-types part, n_slides real slide
    parts (ppt/slides/slideN.xml), plus any decoy member names verbatim.
    ZIP_STORED so a data byte can be corrupted at a known location later.

    Each slide carries `text_runs_per_slide` DrawingML text runs (<a:t>…</a:t>)
    so a real deck also clears the text-layer gate. Set it to 0 to model the
    all-image deck from row f507034e (slides present, zero selectable text).
    """
    with zipfile.ZipFile( str( path ), "w", compression=compression ) as zf:
        zf.writestr( "[Content_Types].xml", "<Types/>" )
        for i in range( 1, n_slides + 1 ):
            runs = "".join( f"<a:t>Run {i}.{j}</a:t>" for j in range( text_runs_per_slide ) )
            zf.writestr( f"ppt/slides/slide{i}.xml", f"<p:sld>SLIDE-CONTENT-MARKER-{i}{runs}</p:sld>" )
        for name in decoys:
            zf.writestr( name, "<decoy/>" )
    return str( path )


def _write_pptx_raw( path, slide_xmls, notes_xmls=() ):
    """
    Write a deck with caller-supplied raw slide XML bodies — for exercising the
    text-run counter's tag matching directly. `notes_xmls` land under
    ppt/notesSlides/ to prove notes text is NEVER counted as slide text.
    """
    with zipfile.ZipFile( str( path ), "w" ) as zf:
        zf.writestr( "[Content_Types].xml", "<Types/>" )
        for i, body in enumerate( slide_xmls, start=1 ):
            zf.writestr( f"ppt/slides/slide{i}.xml", body )
        for i, body in enumerate( notes_xmls, start=1 ):
            zf.writestr( f"ppt/notesSlides/notesSlide{i}.xml", body )
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


# ---- the text-layer gate: row f507034e ------------------------------------

def test_image_only_deck_fails_text_gate( tmp_path ):
    # Slides present, but zero <a:t> runs — the all-image deck the row measured.
    p = _write_pptx( tmp_path / "image-only.pptx", n_slides=20, text_runs_per_slide=0 )
    v = verify_presentation_deck( p )
    assert not v
    assert v.slide_count == 20
    assert v.text_run_count == 0
    assert "no selectable text" in v.reason


def test_text_bearing_deck_passes_text_gate( tmp_path ):
    p = _write_pptx( tmp_path / "with-text.pptx", n_slides=4, text_runs_per_slide=3 )
    v = verify_presentation_deck( p )
    assert v
    assert v.slide_count == 4
    assert v.text_run_count == 12                 # 4 slides * 3 runs
    assert "text runs" in v.reason


def test_min_text_runs_threshold_fails( tmp_path ):
    p = _write_pptx( tmp_path / "thin-text.pptx", n_slides=2, text_runs_per_slide=1 )
    v = verify_presentation_deck( p, min_text_runs=5 )
    assert not v
    assert v.text_run_count == 2
    assert "need >= 5" in v.reason


def test_min_text_runs_zero_skips_gate( tmp_path ):
    # Opt out of the text gate: an image-only deck passes when the floor is 0.
    p = _write_pptx( tmp_path / "opt-out.pptx", n_slides=3, text_runs_per_slide=0 )
    v = verify_presentation_deck( p, min_text_runs=0 )
    assert v
    assert v.text_run_count == 0


def test_empty_self_closing_run_not_counted( tmp_path ):
    # <a:t/> is an empty run — not selectable text, so it must not count.
    p = _write_pptx_raw( tmp_path / "empty-run.pptx", slide_xmls=[ "<p:sld><a:t/></p:sld>" ] )
    v = verify_presentation_deck( p )
    assert not v
    assert v.text_run_count == 0


def test_text_run_with_attributes_is_counted( tmp_path ):
    # <a:t xml:space="preserve"> is a real run — the space after `t` must match.
    p = _write_pptx_raw(
        tmp_path / "attr-run.pptx",
        slide_xmls=[ '<p:sld><a:t xml:space="preserve">Hi</a:t></p:sld>' ],
    )
    v = verify_presentation_deck( p )
    assert v
    assert v.text_run_count == 1


def test_notes_text_never_counts_as_slide_text( tmp_path ):
    # Notes are real text but live under notesSlides/ — the exact shape of the
    # deck the row separated out. Slides have zero runs; the deck must FAIL.
    p = _write_pptx_raw(
        tmp_path / "notes-only.pptx",
        slide_xmls=[ "<p:sld></p:sld>", "<p:sld></p:sld>" ],
        notes_xmls=[ "<p:notes><a:t>lots of talking points</a:t></p:notes>" ],
    )
    v = verify_presentation_deck( p )
    assert not v
    assert v.text_run_count == 0                  # notes text excluded


# ---- the verdict object is the single source of truth ----------------------

def test_verdict_truthiness_and_repr():
    ok  = DeckVerdict( True,  "valid deck: 15 slides", "/x.pptx", 100, 15, 42 )
    bad = DeckVerdict( False, "no pptx_path recorded", None )
    assert bool( ok ) is True and bool( bad ) is False
    assert "PASS" in repr( ok ) and "FAIL" in repr( bad )
    assert "text_runs=42" in repr( ok )
