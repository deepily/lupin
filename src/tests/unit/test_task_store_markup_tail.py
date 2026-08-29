"""
Unit tests for the tool-call markup-tail DETECTOR (row 91ccbc26).

WHAT THIS FILE PINS, and why it is a detector rather than a guard
-----------------------------------------------------------------
Row 91ccbc26 records two writes — sam's and Rio's, on different rows, at
different fragment sizes — where a free-text field silently ended up holding the
tail of the writer's own tool-call envelope. Neither write failed. Neither
warned. Both were caught only when a human re-read his own prose later.

A differential probe (2026-08-29) sent ONE 242-byte canary through two entry
paths — raw HTTP, and an MCP tool call — and got an identical sha256 both ways.
That exonerates the transport and the store: the corruption enters ABOVE the
JSON boundary, in the caller's composition. It also proves something sharper,
which is what these tests exist to protect:

    A CORRUPTED WRITE AND AN HONEST QUOTE ARE BYTE-IDENTICAL AT THIS BOUNDARY.

So a stripper cannot tell them apart and would eat real content, and a rejecter
would refuse honest reasons — including any reason documenting this very defect,
which necessarily quotes the tail. The detector reports and changes nothing.

BOTH DIRECTIONS MATTER, and the negative one is load-bearing. A detector that
flagged every angle bracket would be worse than none: the reasons this fleet
writes quote code and XML constantly. The `TestSilentOnLegitimateQuoting` class
is not padding — it is the control the row's brief demanded, "proving a reason
that legitimately quotes code, angle brackets and all, still survives."
"""

import os
import sys

import pytest

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )

from cosa.rest.task_store_rules import (
    MARKUP_PRONE_FIELDS,
    markup_tail_advisory,
    trailing_markup_run,
)

# Assembled from two pieces on purpose. A literal close-tag written into this
# file would terminate the tool call of any session that quotes the file back —
# which is the very defect under test, and it bit this author once already.
LT = "<" + "/"

# The verbatim tail of Rio's specimen, preserved in row 91ccbc26's second
# amendment BEFORE the field holding it was cleared by an un-park. The field
# itself is gone; this literal is the surviving copy — which is precisely why
# that row's third amendment says park_reason is not an evidence store.
RIO_SPECIMEN      = "thing to run the checklist against.</park_reason>\n</invoke>\n"
RIO_EXPECTED_TAIL = "</park_reason>\n</invoke>\n"

# sam's, reported one fragment smaller: a single stray close-tag.
SAM_SPECIMEN      = "Third park attempt — the two before it captured a stray close-tag.</park_reason>"


class TestFiresOnTheRecordedSpecimenShapes:
    """The positive direction — both recorded fragment sizes are caught."""

    def test_catches_rios_two_tag_tail_exactly( self ):
        assert trailing_markup_run( RIO_SPECIMEN ) == RIO_EXPECTED_TAIL
        assert len( trailing_markup_run( RIO_SPECIMEN ) ) == 25

    def test_catches_sams_single_stray_close_tag( self ):
        assert trailing_markup_run( SAM_SPECIMEN ) == "</park_reason>"

    def test_catches_a_value_that_is_nothing_but_markup( self ):
        assert trailing_markup_run( "</invoke>\n" ) == "</invoke>\n"

    def test_catches_tag_names_carrying_dots_colons_and_hyphens( self ):
        # The envelope this fleet actually emits uses namespaced tag names, so a
        # detector that only understood bare identifiers would miss the real one.
        assert trailing_markup_run( "text</a.b:c-d>" ) == "</a.b:c-d>"

    def test_reports_without_ever_mutating_the_value( self ):
        # The whole design rests on this: the caller still holds every byte it
        # sent. A detector that quietly trimmed would be the stripper the
        # measurement ruled out.
        original = RIO_SPECIMEN
        trailing_markup_run( original )
        assert original == "thing to run the checklist against.</park_reason>\n</invoke>\n"


class TestSilentOnLegitimateQuoting:
    """
    The CONTROL the brief demanded. Markup that appears mid-sentence, with the
    author still speaking afterwards, is ordinary writing and must pass clean.
    """

    def test_code_with_a_less_than_operator_passes_clean( self ):
        reason = 'A reason may quote code: if ( a < b ) { return "<x>"; } and read fine.'
        assert trailing_markup_run( reason ) == ""

    def test_a_quoted_xml_element_mid_sentence_passes_clean( self ):
        reason = 'The tag <parameter name="p">v' + LT + 'parameter> is how the envelope looks.'
        assert trailing_markup_run( reason ) == ""

    def test_prose_that_NAMES_the_offending_tag_passes_clean( self ):
        # This row's own writeups do exactly this. A detector that flagged them
        # would fire on every honest description of the defect.
        reason = "Never emit </invoke> by hand inside a value — that is the defect."
        assert trailing_markup_run( reason ) == ""

    def test_empty_string_passes_clean( self ):
        assert trailing_markup_run( "" ) == ""

    def test_whitespace_only_passes_clean( self ):
        assert trailing_markup_run( "   \n\n  " ) == ""

    def test_an_opening_tag_at_the_end_is_not_a_close_run( self ):
        assert trailing_markup_run( "trailing open tag <invoke>" ) == ""

    @pytest.mark.parametrize( "value", [ None, 42, [ "</park_reason>" ], { }, object() ] )
    def test_non_string_values_pass_clean_rather_than_raising( self, value ):
        assert trailing_markup_run( value ) == ""


class TestAdvisoryOverAFieldSet:
    """
    `markup_tail_advisory` is the multi-field face. The probe measured that
    `reason` and `note` carry markup exactly as `park_reason` does, so guarding
    one field alone would guard only the field we happened to notice.
    """

    def test_names_every_dirty_field_and_omits_every_clean_one( self ):
        advisory = markup_tail_advisory( {
            "park_reason" : RIO_SPECIMEN,
            "reason"      : "an ordinary reason with no markup at all",
            "note"        : SAM_SPECIMEN,
        } )
        assert advisory == {
            "park_reason" : RIO_EXPECTED_TAIL,
            "note"        : "</park_reason>",
        }

    def test_an_all_clean_field_set_yields_an_empty_advisory( self ):
        assert markup_tail_advisory( { "reason": "clean", "note": "also clean" } ) == { }

    def test_an_empty_field_set_yields_an_empty_advisory( self ):
        assert markup_tail_advisory( { } ) == { }

    def test_non_string_values_are_skipped_rather_than_reported( self ):
        assert markup_tail_advisory( { "body": None, "title": 7 } ) == { }

    def test_the_input_dict_is_not_modified( self ):
        fields = { "park_reason": RIO_SPECIMEN }
        markup_tail_advisory( fields )
        assert fields == { "park_reason": RIO_SPECIMEN }

    def test_the_prone_field_list_covers_the_three_measured_carriers( self ):
        # park_reason was reported; reason and note were MEASURED to carry a
        # canary verbatim in the same probe. All three must be listed.
        for field in ( "park_reason", "reason", "note" ):
            assert field in MARKUP_PRONE_FIELDS
