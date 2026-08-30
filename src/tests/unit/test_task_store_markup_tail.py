"""
Unit tests for the tool-call ENVELOPE-TAIL REFUSAL (row 91ccbc26).

WHAT THIS FILE PINS
-------------------
Row 91ccbc26 records two writes — sam's and Rio's, on different rows, at
different fragment sizes — where a free-text field silently ended up holding the
tail of the writer's own tool-call envelope. Neither write failed. Neither
warned. Both were caught only when a human re-read his own prose later.

A differential probe (2026-08-29) sent ONE 242-byte canary through two entry
paths — raw HTTP, and an MCP tool call — and read back an identical sha256 both
ways; Krishna corroborated with an md5 read straight out of postgres. The
transport and the store are faithful, so the corruption is composed by the
CALLER and cannot be prevented here. What CAN be fixed is the property both
incidents shared: SILENCE. Mr. Radio ruled a hard refusal (2026-08-29) — it is
recoverable, and known to work, since sam's third attempt landed clean.

🔴 WHY THE NEGATIVE TESTS ARE THE LOAD-BEARING HALF
A corrupted write and an HONEST quote are BYTE-IDENTICAL at this boundary —
proven by deliberately sending the exact corruption bytes as legitimate content.
Nothing here can read intent. Under a REFUSAL policy a false positive BLOCKS
REAL WORK, so the signature is deliberately as tight as the evidence allows: a
CLOSED list of known envelope tags, matched only at the very END of the value.
`TestLegitimateQuotingIsNotRefused` is therefore not padding — it is the control
the row's brief demanded, "proving a reason that legitimately quotes code, angle
brackets and all, still survives." If that class ever goes red, the guard has
started eating honest writes and is worse than the defect it stops.

COVERAGE IS THREE FIELDS, MEASURED (Mr. Radio's ruling): park_reason on a park,
`reason` on every transition, `note` on every amendment. The probe stored a
canary verbatim in all three.
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
    envelope_tail_tag,
    validate_no_envelope_tail,
    validate_transition,
)

# Assembled from two pieces on purpose. A literal close-tag written into this
# file TERMINATES the tool call of any session that writes or quotes it — the
# second failure mode of this same defect, which bit two authors while building
# the fix. The module under test assembles its tag list the same way.
LT = "<" + "/"

PARK_CLOSE   = LT + "park_reason>"
INVOKE_CLOSE = LT + "invoke>"

# The verbatim tail of Rio's specimen, preserved in row 91ccbc26's second
# amendment BEFORE the field holding it was cleared by an un-park. The field is
# gone; this literal is the surviving copy — which is exactly why that row's
# third amendment says park_reason is not an evidence store.
RIO_SPECIMEN = "thing to run the checklist against." + PARK_CLOSE + "\n" + INVOKE_CLOSE + "\n"

# sam's, reported one fragment smaller: a single stray close-tag.
SAM_SPECIMEN = "Third park attempt — the two before it captured a stray close-tag." + PARK_CLOSE


class TestTheRecordedSpecimensAreCaught:
    """The positive direction — both recorded fragment sizes are refused."""

    def test_rios_stacked_tail_names_the_nearest_tag( self ):
        # The corruption stacks, so the tag NEAREST the end is the one named.
        assert envelope_tail_tag( RIO_SPECIMEN ) == INVOKE_CLOSE

    def test_sams_single_stray_close_tag_is_caught( self ):
        assert envelope_tail_tag( SAM_SPECIMEN ) == PARK_CLOSE

    def test_trailing_whitespace_does_not_hide_the_tag( self ):
        assert envelope_tail_tag( "a reason" + INVOKE_CLOSE + "  \n\n" ) == INVOKE_CLOSE

    def test_every_tag_in_the_closed_list_is_caught( self ):
        from cosa.rest.task_store_rules import _ENVELOPE_TAGS
        for tag in _ENVELOPE_TAGS:
            assert envelope_tail_tag( "some authored prose" + tag ) == tag

    def test_the_namespaced_variants_are_distinct_entries( self ):
        # A terminal strips the namespace prefix on display, so these LOOK like
        # duplicates and are not. Measured by length, which rendering cannot lie
        # about — reading the repr is what nearly got them "cleaned up".
        from cosa.rest.task_store_rules import _ENVELOPE_TAGS
        assert len( _ENVELOPE_TAGS ) == len( set( _ENVELOPE_TAGS ) ) == 6

    def test_the_value_is_never_mutated_or_truncated( self ):
        original = RIO_SPECIMEN
        envelope_tail_tag( original )
        validate_no_envelope_tail( { "park_reason": original } )
        assert original == RIO_SPECIMEN


class TestLegitimateQuotingIsNotRefused:
    """
    🔴 THE CONTROL. Under a refusal policy a false positive blocks real work.
    Markup quoted mid-sentence, with the author still speaking afterwards, is
    ordinary writing and MUST pass.
    """

    def test_code_carrying_a_less_than_operator_passes( self ):
        assert envelope_tail_tag( 'quote code: if ( a < b ) { return "<x>"; } and read on.' ) is None

    def test_an_xml_element_quoted_mid_sentence_passes( self ):
        assert envelope_tail_tag( 'the tag <parameter name="p">v' + LT + 'parameter> is how it looks.' ) is None

    def test_prose_that_NAMES_the_offending_tag_passes( self ):
        # This row's own writeups do exactly this. A guard that refused them
        # would refuse every honest description of the defect.
        assert envelope_tail_tag( "Never emit " + INVOKE_CLOSE + " by hand inside a value." ) is None

    def test_rios_specimen_QUOTED_mid_sentence_passes( self ):
        # The strongest form of the control: the exact corrupted bytes, used as
        # honest content, with the author continuing afterwards.
        assert envelope_tail_tag( RIO_SPECIMEN + " — that is the fragment we recorded." ) is None

    def test_a_close_tag_outside_the_closed_list_passes( self ):
        # Breadth is a LIABILITY under refusal: an author quoting HTML that ends
        # on a div close-tag must not be blocked.
        assert envelope_tail_tag( "see the layout " + LT + "div>" ) is None

    def test_an_opening_tag_at_the_end_is_not_a_tail( self ):
        assert envelope_tail_tag( "trailing open tag <invoke>" ) is None

    @pytest.mark.parametrize( "value", [ None, 42, [ PARK_CLOSE ], { }, "", "   \n " ] )
    def test_blank_and_non_string_values_are_not_this_rule_s_business( self, value ):
        # validate_park and the amend handler own the "missing / blank" message;
        # this guard must never compete for it.
        assert envelope_tail_tag( value ) is None


class TestValidateNoEnvelopeTail:
    """The multi-field face, and the error text the author has to act on."""

    def test_reports_one_error_per_offending_field( self ):
        errors = validate_no_envelope_tail( {
            "park_reason" : RIO_SPECIMEN,
            "reason"      : "an ordinary reason with no markup",
            "note"        : SAM_SPECIMEN,
        } )
        assert len( errors ) == 2
        assert any( e.startswith( "park_reason ends with" ) for e in errors )
        assert any( e.startswith( "note ends with" ) for e in errors )

    def test_the_error_names_the_tag_and_says_what_to_do( self ):
        error = validate_no_envelope_tail( { "reason": SAM_SPECIMEN } )[ 0 ]
        assert PARK_CLOSE in error
        assert "Re-send it without the trailing tag" in error

    def test_a_clean_field_set_yields_no_errors( self ):
        assert validate_no_envelope_tail( { "reason": "clean", "note": "also clean" } ) == [ ]

    def test_an_empty_field_set_yields_no_errors( self ):
        assert validate_no_envelope_tail( { } ) == [ ]

    def test_the_input_dict_is_not_modified( self ):
        fields = { "park_reason": RIO_SPECIMEN }
        validate_no_envelope_tail( fields )
        assert fields == { "park_reason": RIO_SPECIMEN }

    def test_the_prone_field_list_is_exactly_the_three_ruled_fields( self ):
        assert MARKUP_PRONE_FIELDS == ( "park_reason", "reason", "note" )


class TestWiredIntoEveryTransition:
    """
    The sibling coverage Mr. Radio ruled: `reason` rides EVERY transition, not
    just ->parked. A guard that only fired on a park would be the half-fix.
    """

    def test_a_captured_tag_in_reason_refuses_an_ordinary_transition( self ):
        errors = validate_transition( "queued", "in_progress", "standing",
                                      reason="picking this up" + INVOKE_CLOSE )
        assert any( "reason ends with" in e for e in errors )

    def test_a_captured_tag_in_park_reason_refuses_a_park( self ):
        errors = validate_transition( "queued", "parked", "standing",
                                      park_reason="held for now" + PARK_CLOSE,
                                      next_chase_ts="2026-09-04T09:00:00-04:00" )
        assert any( "park_reason ends with" in e for e in errors )

    def test_a_clean_transition_is_untouched_by_the_guard( self ):
        errors = validate_transition( "queued", "in_progress", "standing",
                                      reason="picking this up" )
        assert errors == [ ]

    def test_a_reason_quoting_markup_mid_sentence_still_transitions( self ):
        # The control, at the call site rather than the predicate.
        errors = validate_transition( "queued", "in_progress", "standing",
                                      reason="the tail was " + INVOKE_CLOSE + " and I removed it" )
        assert errors == [ ]

    def test_the_transition_error_is_reported_before_the_markup_error( self ):
        # A caller who is both mis-transitioning AND carrying a tag hears about
        # the transition first — that is the error they can act on.
        errors = validate_transition( "done", "queued", "standing",
                                      reason="reopening" + INVOKE_CLOSE )
        assert len( errors ) >= 2
        assert "reason ends with" not in errors[ 0 ]
        assert any( "reason ends with" in e for e in errors )
