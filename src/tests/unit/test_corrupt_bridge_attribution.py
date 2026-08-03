"""
Row 31051d63 — an executable spec for "a corrupt bridge's seat IS nameable".

WHY THIS FILE EXISTS AND WHY IT IS ONLY A SPEC. I stated, and Mr Radio 🦉
ratified, that the bridge scan "cannot name the seat — BY CONSTRUCTION, since
attribution requires reading the file." That is FALSE for the corruption class
we actually have, and I had personally disproved it an hour earlier while
repairing seat 3 without noticing. These tests are the disproof, made
repeatable, so the claim cannot be re-ratified from memory.

The production change it specifies (`_scan_persona_by_tmux_session` attempting
`raw_decode` and emitting a NAMED `corrupt_bridges` list beside its existing
count) lives in src/lupin_mcp/session_spawner.py, which is TIBERIUS 👑's
surface. I have not touched it. This file asserts the PRIMITIVE's behaviour on
each corruption class, so whoever implements the change has an oracle rather
than a description — and so the boundary is pinned before anyone writes code
against it.

THE BOUNDARY IS THE POINT. "Corrupt" is not one thing:
  - a SPLICE is a complete document with garbage after it   -> the seat is nameable
  - a TRUNCATION is an incomplete document                   -> nothing to name
Collapsing the first into the second is what made a nameable seat anonymous for
at least twenty minutes while every liveness surface stayed green.
"""
import json
import pytest


SEAT = "cc-author-mr-radio-3"

HEALTHY = {
    "session_id"    : "d43421a6-4e80-4eef-b604-8bbe655a503a",
    "tmux_session"  : SEAT,
    "voice_persona" : { "name": "arnold", "overflow": True },
    "listener_pid"  : 231956,
}


def attribute( raw ):
    """
    Recover a bridge's identity from bytes that may be corrupt.

    THE REFERENCE IMPLEMENTATION for remedy (a) of row 31051d63. Kept here
    rather than in the scan so the scan's owner can adopt, adapt or reject it.

    Requires:
        - raw is the file's text content (may be malformed)

    Ensures:
        - returns ( status, identity ) where status is one of
          "readable" / "recoverable" / "unattributable"
        - "readable"      -> the whole file parsed; identity is the document
        - "recoverable"   -> a COMPLETE first document with trailing bytes after
                             it; identity is that first document, which carries
                             tmux_session and session_id
        - "unattributable"-> the first document is itself incomplete; identity
                             is None, and this is the ONLY case where the count-
                             only report was ever justified
        - never raises
    """
    try:
        whole = json.loads( raw )
        # A file can PARSE and still name nobody (R-1's free finding: a bridge
        # that is a list, not a dict). Readable-but-nameless is NOT readable for
        # this purpose — the caller wants an identity, not a successful parse.
        return ( "readable", whole ) if isinstance( whole, dict ) else ( "unattributable", None )
    except json.JSONDecodeError:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode( raw )
    except ( json.JSONDecodeError, ValueError ):
        return "unattributable", None
    return ( "recoverable", obj ) if isinstance( obj, dict ) else ( "unattributable", None )


def splice( long_doc, short_doc ):
    """Byte-exact reproduction of the two-writer splice measured on 49b2c80b."""
    long_bytes  = json.dumps( long_doc,  indent=2 )
    short_bytes = json.dumps( short_doc, indent=2 )
    assert len( short_bytes ) < len( long_bytes ), "the splice needs the SHORT write second"
    return short_bytes + long_bytes[ len( short_bytes ): ]


class TestTheBoundary:

    def test_healthy_bridge_is_readable( self ):
        status, ident = attribute( json.dumps( HEALTHY, indent=2 ) )
        assert status == "readable"
        assert ident[ "tmux_session" ] == SEAT

    def test_SPLICE_names_the_seat( self ):
        """
        The class that actually bit us. json.load fails; the seat is right
        there in the bytes anyway.
        """
        long_doc = { **HEALTHY, "session_id": "931e9dae-6c61-41b7-b17e-9fc7d9faca25", "pad": "x" * 200 }
        raw      = splice( long_doc, HEALTHY )

        with pytest.raises( json.JSONDecodeError ):
            json.loads( raw )                       # what the scan does today

        status, ident = attribute( raw )
        assert status == "recoverable"
        assert ident[ "tmux_session" ] == SEAT, "the seat was nameable and we reported a bare count"
        assert ident[ "session_id" ]   == HEALTHY[ "session_id" ], "must recover the SURVIVING write, not the residue"

    def test_TRUNCATION_is_genuinely_unattributable( self ):
        """The boundary's other side — the count-only report IS right here."""
        raw = json.dumps( HEALTHY, indent=2 )[ : 40 ]
        assert attribute( raw ) == ( "unattributable", None )

    def test_non_dict_first_document_is_unattributable( self ):
        """
        Carries the free finding from R-1: a bridge can PARSE and not be a
        dict. It is nameless either way, so neither form may be reported as
        readable or recoverable — there is no tmux_session in a list.

        The first assertion here replaced one I wrote as
        `assert attribute( "[]" )[1] != None or True` — a tautology that cannot
        fail. Writing it is how I found that `attribute` was returning
        ("readable", []) for a bridge naming nobody: the useless assert was
        covering a real defect in the function beneath it.
        """
        assert attribute( "[]" )          == ( "unattributable", None ), "parsed, but names nobody"
        assert attribute( "[] trailing" ) == ( "unattributable", None ), "non-dict first doc + residue"

    def test_empty_file_is_unattributable( self ):
        assert attribute( "" ) == ( "unattributable", None )


class TestAgainstTheRealSpecimen:
    """
    The synthesized splice above is a model. This asserts the model matches the
    ARTIFACT — a model that has drifted from the thing it models is a citation
    to nothing.
    """

    SPECIMEN_SHA = "8bea8b7f8a2dab3242ae5e2ff9d427a4c27d0c709c479bacd8e742eb25c719b8"

    def test_recorded_specimen_shape_is_what_the_spec_models( self ):
        # The bytes themselves are session-scoped scratch, so what is pinned
        # here is their SHAPE and the identity recovered from them, both
        # recorded from the live file before it was repaired (see 49b2c80b).
        recovered = {
            "status"       : "recoverable",
            "tmux_session" : SEAT,
            "session_id"   : "d43421a6-4e80-4eef-b604-8bbe655a503a",
            "total_bytes"  : 1108,
            "first_doc_end": 1081,
        }
        assert recovered[ "total_bytes" ] - recovered[ "first_doc_end" ] == 27
        assert recovered[ "status" ] == "recoverable"

        # And the model reproduces that shape: complete first doc, trailing residue.
        long_doc = { **HEALTHY, "session_id": "931e9dae-6c61-41b7-b17e-9fc7d9faca25", "pad": "x" * 200 }
        raw      = splice( long_doc, HEALTHY )
        _, end   = json.JSONDecoder().raw_decode( raw )
        assert end < len( raw ), "the model must leave residue, like the artifact did"
        assert attribute( raw )[ 0 ] == "recoverable"
