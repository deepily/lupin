"""
Presentation deck verdict — the SINGLE authority on whether a presentation run
produced a real PowerPoint deck.

Row 63f4d4a6. A prior scratchpad harness reported PASS off the intermediate
Phase-5 ``.yaml`` and then tried to locate the finished ``.pptx`` by basename.
The deck's filename timestamp is recomputed at export time (Phase 8.5), minutes
after the yaml (Phase 5), so the stems differ and the basename match silently
found nothing while the banner still said PASS. Worse, the affirmative banner
was printed by a code path separate from the wait loop that knew no deck had
been found — so a negative finding never reached the verdict.

This module removes both failure modes:

  1. It never reconstructs a path by basename. The caller passes the
     AUTHORITATIVE path the job recorded (``job.pptx_path`` /
     ``job.artifacts["pptx_path"]`` / the done-queue metadata ``pptx_path``).
  2. There is exactly ONE verdict: the return value of
     ``verify_presentation_deck()``. Its truth value derives entirely from the
     real deck on disk, and a missing / null / unreadable / slideless deck is a
     hard False with a specific reason — never a silent skip. A caller cannot
     obtain a truthy verdict without every check having passed.

A ``.pptx`` is an OPC (Open Packaging Conventions) zip; slide parts live at
``ppt/slides/slideN.xml``. Verification is pure ``zipfile`` (stdlib) — the same
shape as the manual disk check the tester fell back on ("valid zip, N slide
XMLs") — so it adds no dependency and inspects the real artifact, not a proxy.
"""

import os
import re
import zipfile

# A .pptx slide part is ppt/slides/slideN.xml where N is a decimal integer.
_SLIDE_ENTRY_PREFIX = "ppt/slides/slide"
_SLIDE_ENTRY_SUFFIX = ".xml"

# A DrawingML text run is <a:t>…</a:t>. The opening tag is `<a:t>` (no attrs) or
# `<a:t xml:space="preserve">` (with attrs) — the char after `t` is `>` or a
# space. `<a:t/>` (self-closing, empty) has `/` after `t`, so this pattern
# deliberately excludes it: an empty run is not text on the slide.
_TEXT_RUN_OPEN = re.compile( rb"<a:t[ >]" )


class DeckVerdict:
    """
    The verdict on one presentation deck. Its truth value IS the verdict, so a
    caller that writes ``if verify_presentation_deck( path ):`` cannot render a
    PASS without the underlying checks having passed.
    """

    def __init__( self, passed, reason, pptx_path=None, size_bytes=None, slide_count=None, text_run_count=None ):
        self.passed         = passed
        self.reason         = reason
        self.pptx_path      = pptx_path
        self.size_bytes     = size_bytes
        self.slide_count    = slide_count
        self.text_run_count = text_run_count

    def __bool__( self ):
        return self.passed

    def __repr__( self ):
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"DeckVerdict({verdict}: {self.reason} | "
            f"path={self.pptx_path} size={self.size_bytes} slides={self.slide_count} "
            f"text_runs={self.text_run_count})"
        )


def _count_slide_xmls( zf ):
    """
    Count ppt/slides/slideN.xml members (N a decimal integer). Excludes
    non-slide neighbours such as ppt/slides/slideLayoutX.xml-shaped decoys.
    """
    count = 0
    for name in zf.namelist():
        if name.startswith( _SLIDE_ENTRY_PREFIX ) and name.endswith( _SLIDE_ENTRY_SUFFIX ):
            middle = name[ len( _SLIDE_ENTRY_PREFIX ) : -len( _SLIDE_ENTRY_SUFFIX ) ]
            if middle.isdigit():
                count += 1
    return count


def _count_slide_text_runs( zf ):
    """
    Count DrawingML text runs (<a:t> …) across ppt/slides/slideN.xml parts ONLY.

    Notes live in ppt/notesSlides/*, NOT ppt/slides/* — they are deliberately
    excluded. A deck of pure rendered images has notes text but zero slide text
    runs, and it is exactly that deck this counter exists to catch. Empty runs
    (<a:t/>) do not count (see _TEXT_RUN_OPEN).

    Requires:
        - zf is an open zipfile.ZipFile

    Ensures:
        - returns the total number of non-empty <a:t> opening tags found across
          all slide parts (never notes parts)
    """
    count = 0
    for name in zf.namelist():
        if name.startswith( _SLIDE_ENTRY_PREFIX ) and name.endswith( _SLIDE_ENTRY_SUFFIX ):
            middle = name[ len( _SLIDE_ENTRY_PREFIX ) : -len( _SLIDE_ENTRY_SUFFIX ) ]
            if middle.isdigit():
                count += len( _TEXT_RUN_OPEN.findall( zf.read( name ) ) )
    return count


def verify_presentation_deck( pptx_path, min_slides=1, min_text_runs=1 ):
    """
    Verify a finished presentation ``.pptx`` on disk.

    Requires:
        - pptx_path is the AUTHORITATIVE absolute path the job recorded for the
          finished deck (never a basename reconstructed from the .yaml stem);
          None / "" means the job produced no deck
        - min_slides is a positive int
        - min_text_runs is a non-negative int; the minimum number of DrawingML
          text runs (<a:t>) that must exist across the slide parts. The default
          of 1 makes a deck of pure rendered images a hard failure — that is the
          check that catches row f507034e. Pass 0 to skip the text-layer gate.

    Ensures:
        - returns a DeckVerdict whose truth value is the verdict
        - passed is True ONLY when: pptx_path is non-empty, the file exists, is
          a non-empty valid zip whose members all pass their CRC, contains
          >= min_slides slide XMLs, AND carries >= min_text_runs text runs on
          the slides (notes text does not count)
        - every failure mode yields passed=False with a specific reason; a
          missing, slideless, or text-free deck is a hard failure, never a
          silent skip
    """
    if not pptx_path:
        return DeckVerdict( False, "no pptx_path recorded (job produced no deck)", pptx_path )

    if not os.path.isfile( pptx_path ):
        return DeckVerdict( False, "pptx_path recorded but no file on disk", pptx_path )

    size_bytes = os.path.getsize( pptx_path )
    if size_bytes == 0:
        return DeckVerdict( False, "deck file is empty (0 bytes)", pptx_path, size_bytes )

    if not zipfile.is_zipfile( pptx_path ):
        return DeckVerdict( False, "deck is not a valid zip/OPC container", pptx_path, size_bytes )

    with zipfile.ZipFile( pptx_path ) as zf:
        bad = zf.testzip()
        if bad is not None:
            return DeckVerdict( False, f"deck zip is corrupt at member {bad}", pptx_path, size_bytes )
        slide_count    = _count_slide_xmls( zf )
        text_run_count = _count_slide_text_runs( zf )

    if slide_count < min_slides:
        return DeckVerdict(
            False, f"deck has {slide_count} slide(s), need >= {min_slides}",
            pptx_path, size_bytes, slide_count, text_run_count
        )

    if text_run_count < min_text_runs:
        return DeckVerdict(
            False,
            f"deck has {text_run_count} slide text run(s), need >= {min_text_runs} "
            f"(slides carry no selectable text — likely rendered images)",
            pptx_path, size_bytes, slide_count, text_run_count
        )

    return DeckVerdict(
        True, f"valid deck: {slide_count} slides, {text_run_count} text runs, {size_bytes} bytes",
        pptx_path, size_bytes, slide_count, text_run_count
    )
