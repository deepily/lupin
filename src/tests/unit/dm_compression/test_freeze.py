"""
Tests for the freeze protocol.

The organising idea: a literal-preservation suite that has never failed is not
evidence, it is an untested assertion. So the centre of gravity here is not the
happy path — it is the mutation classes, where every validator check is shown to
FIRE against a deliberately broken rewrite. A check nobody has watched fail is
not known to work.

That is also why the negative control sits after the mutation tests rather than
standing in for them. Turning freezing off does not reliably turn a suite red: a
model that preserves a literal by luck looks exactly like a literal that was
protected. Each check needs its own mutation aimed squarely at it.

Zero API spend. Everything here runs offline against handwritten cases and the
pinned corpus snapshot.
"""

import dataclasses
import json
import os
import random
import string

import pytest

from cosa.agents.dm_compression.freeze import (
    freeze,
    validate,
    restore,
    compress_or_original,
    extract_spans,
    resolve_spans,
    segment_clauses,
    count_verify_literals,
    OPEN_DELIM,
    CLOSE_DELIM,
    HARD_KINDS,
    SOFT_KINDS,
    VERIFY_KINDS,
    REMOVABLE_KINDS,
)

import cosa.utils.util as cu


SNAPSHOT = cu.get_project_root() + "/src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl"

# Deliberately a REALISTIC message rather than a minimal one.
#
# The first version of this fixture was the plan's one-line worked example, and
# it was so dense with literals that the bypass gate skipped it — which made two
# delivery tests fail against a system that was behaving correctly. A fixture
# that cannot survive its own pipeline tests nothing about that pipeline.
SAMPLE = (
    "I spent the morning tracing the leak and I am fairly confident it sits at "
    "judge.py:572, which is the line that shipped in d256e25a last Tuesday. The "
    "consumer thread returns before the pool callback has run, so the job stays "
    "in the running queue even though the work behind it finished perfectly "
    "cleanly. Have a look at src/cosa/rest/queue.py when you get a moment and "
    "tell me whether you read it the same way that I do."
)


@pytest.fixture( scope="module" )
def corpus():
    """Real DM bodies from the pinned snapshot."""
    if not os.path.exists( SNAPSHOT ):
        pytest.skip( f"corpus snapshot not present: {SNAPSHOT}" )

    bodies = []
    with open( SNAPSHOT ) as handle:
        for line in handle:
            line = line.strip()
            if not line: continue
            try: record = json.loads( line )
            except json.JSONDecodeError: continue
            if record.get( "body" ): bodies.append( record[ "body" ] )

    return bodies


@pytest.fixture
def frozen():
    return freeze( SAMPLE )


def _violations_of( result, check ):
    return [ detail for name, detail in result.violations if name == check ]


def _plausible_rewrite( frozen_message ):
    """
    Stand in for the model: shorten the prose, leave every token untouched.

    This is what a well-behaved rewriter produces, and several tests need it.
    Written as one helper so that a change to SAMPLE cannot silently turn the
    "rewrite" into a no-op — which is exactly what happened when these tests
    each carried their own hardcoded substring.
    """
    rewritten = frozen_message.frozen_text
    for verbose, terse in [
        ( "I spent the morning tracing the leak and I am fairly confident it sits at", "The leak is at" ),
        ( "which is the line that shipped in",                                        "shipped in" ),
        ( "when you get a moment and tell me whether you read it the same way that I do", "and tell me if you agree" ),
    ]:
        rewritten = rewritten.replace( verbose, terse )

    assert rewritten != frozen_message.frozen_text, "the simulated rewrite changed nothing"
    return rewritten


# ──────────────────────────────────────────────────────────────────────────────
# The identity property
#
# Split from the rewriter-path property on purpose. A rewritten message CANNOT
# be byte-equal to the original — that is the point of rewriting it — so byte
# equality belongs to the extractor/restorer pair alone, and the rewriter path
# gets the weaker, correct claim: every mapped literal survives.
# ──────────────────────────────────────────────────────────────────────────────

class TestIdentityRoundTrip:

    def test_placehold_then_restore_is_byte_identical( self ):
        fm = freeze( SAMPLE )
        assert restore( fm.frozen_text, fm ) == SAMPLE

    @pytest.mark.parametrize( "text", [
        "",
        "no literals here at all just plain words",
        "judge.py:572",
        "⟦already carries the plan's original delimiters⟧",
        "[[L00]] looks exactly like one of ours",
        "(L207) is an ordinary line reference in this fleet",
        "a" * 5000,
        "🦉🌸 glyphs and 🫡 acknowledgements",
        "日本語のテキストと judge.py:572",
        "trailing whitespace   ",
        "\n\n\n",
    ] )
    def test_identity_holds_on_edge_cases( self, text ):
        fm = freeze( text )
        assert restore( fm.frozen_text, fm ) == text

    def test_identity_holds_across_the_whole_corpus( self, corpus ):
        failures = []
        for body in corpus:
            fm = freeze( body )
            if restore( fm.frozen_text, fm ) != body: failures.append( body[ :100 ] )

        assert not failures, f"{len( failures )} of {len( corpus )} bodies failed: {failures[ :3 ]}"

    def test_placeholders_never_appear_in_the_source( self, corpus ):
        """A token already present in the text would be restored twice."""
        for body in corpus[ :500 ]:
            fm = freeze( body )
            for placeholder in fm.placeholders:
                assert placeholder.token not in body


class TestRewriterPathProperty:

    def test_every_mapped_literal_survives_a_real_rewrite( self, frozen ):
        restored = restore( _plausible_rewrite( frozen ), frozen )

        for placeholder in frozen.placeholders:
            assert placeholder.literal in restored

    def test_rewrite_is_shorter_but_literals_are_intact( self, frozen ):
        restored = restore( _plausible_rewrite( frozen ), frozen )

        assert len( restored ) < len( SAMPLE )
        assert "judge.py:572" in restored
        assert "d256e25a"     in restored


# ──────────────────────────────────────────────────────────────────────────────
# Mutation — the heart of the suite
# ──────────────────────────────────────────────────────────────────────────────

class TestMutationOmission:

    def test_dropping_a_placeholder_fails_set_equality( self, frozen ):
        mutated = frozen.frozen_text.replace( frozen.placeholders[ 0 ].token, "" )
        result  = validate( mutated, frozen )

        assert not result.ok
        assert _violations_of( result, "set_equality" )

    def test_every_single_placeholder_is_individually_load_bearing( self, frozen ):
        """Drop each in turn — none may pass unnoticed."""
        for placeholder in frozen.placeholders:
            mutated = frozen.frozen_text.replace( placeholder.token, "" )
            assert not validate( mutated, frozen ).ok, f"omitting {placeholder.token} went undetected"


class TestMutationDuplication:

    def test_duplicating_a_placeholder_fails_multiplicity( self, frozen ):
        token   = frozen.placeholders[ 0 ].token
        mutated = frozen.frozen_text.replace( token, token + " and " + token )
        result  = validate( mutated, frozen )

        assert not result.ok
        assert _violations_of( result, "multiplicity" )


class TestMutationBoundary:

    @pytest.mark.parametrize( "label,corrupt", [
        ( "dropped closing bracket", lambda t: t[ :-2 ] + "]" ),
        ( "dropped opening bracket", lambda t: "[" + t[ 2: ] ),
        ( "substituted delimiters",  lambda t: t.replace( "[[", "(" ).replace( "]]", ")" ) ),
        ( "unicode lookalikes",      lambda t: t.replace( "[[", "〚" ).replace( "]]", "〛" ) ),
        ( "delimiters stripped",     lambda t: t[ 2:-2 ] ),
        ( "split by a space",        lambda t: t.replace( "L", "L " ) ),
    ] )
    def test_mangling_a_delimiter_is_caught( self, frozen, label, corrupt ):
        token   = frozen.placeholders[ 0 ].token
        mutated = frozen.frozen_text.replace( token, corrupt( token ) )

        assert not validate( mutated, frozen ).ok, f"{label} passed validation"

    def test_gluing_text_onto_a_token_fails_boundary_integrity( self, frozen ):
        token   = frozen.placeholders[ 0 ].token
        mutated = frozen.frozen_text.replace( token, token + "s" )
        result  = validate( mutated, frozen )

        assert not result.ok
        assert _violations_of( result, "boundary_integrity" )

    def test_truncating_the_output_at_a_boundary_is_caught( self, frozen ):
        cut     = frozen.frozen_text.index( frozen.placeholders[ -1 ].token )
        mutated = frozen.frozen_text[ :cut + 3 ]

        assert not validate( mutated, frozen ).ok

    def test_legitimate_adjacency_in_the_source_is_not_a_violation( self ):
        """
        A literal butted against a word character is ordinary, not a defect.

        This is the case that made the first version of the boundary check
        reject real corpus text: it judged adjacency absolutely instead of
        against how the token was actually sent.
        """
        text = "the v1.2.3rc build"
        fm   = freeze( text )

        assert validate( fm.frozen_text, fm ).ok
        assert restore( fm.frozen_text, fm ) == text


class TestMutationInvention:

    def test_an_in_namespace_placeholder_we_never_sent_is_caught( self, frozen ):
        mutated = frozen.frozen_text + f" {OPEN_DELIM}{frozen.namespace}L99{CLOSE_DELIM}"
        assert not validate( mutated, frozen ).ok

    def test_an_out_of_namespace_placeholder_is_caught( self, frozen ):
        mutated = frozen.frozen_text + " [[L77]]"
        assert not validate( mutated, frozen ).ok

    @pytest.mark.parametrize( "prose", [
        "status is [done] and the other one is [dropped] for now",
        "see (L207) and (L345) for the line references in that file",
        "the array [0] and the dict [key] both need a second look here",
    ] )
    def test_ordinary_bracketed_prose_is_not_an_invented_placeholder( self, prose ):
        """
        The check must not be so broad that real traffic trips it.

        `[done]`, `[dropped]` and `(L207)` are all live in the corpus. An
        earlier version flagged every one and would have bypassed compression
        on a large slice of ordinary messages.
        """
        fm = freeze( prose )
        assert validate( fm.frozen_text, fm ).ok
        assert restore( fm.frozen_text, fm ) == prose


class TestMutationVerifyTier:
    """
    The second tier: literals too cheap to afford a placeholder, checked where
    they stand. No substitution, so the only available assertion is that the
    multiset is unchanged.
    """

    def test_dropping_a_bare_integer_is_caught( self ):
        text = "the run shows 2710 passed and 1 skipped across 199 statements"
        fm   = freeze( text )

        result = validate( fm.frozen_text.replace( "2710", "" ), fm )

        assert not result.ok
        assert _violations_of( result, "verify_literals" )

    def test_altering_a_bare_integer_is_caught( self ):
        text = "census 31 of 31 rows accounted for in the sweep"
        fm   = freeze( text )

        assert not validate( fm.frozen_text.replace( "31 of 31", "30 of 31" ), fm ).ok

    def test_inventing_an_integer_is_caught( self ):
        text = "the suite reports 2710 passed with nothing outstanding"
        fm   = freeze( text )

        assert not validate( fm.frozen_text + " and 45 failures", fm ).ok

    @pytest.mark.parametrize( "text,literal,replacement", [
        ( "bounce :7999 when you get a chance later on today",  ":7999", ":8000" ),
        ( "we are at 90% coverage on that module right now",    "90%",   "80%" ),
        ( "see §6.4 for the ratified wording of that rule",     "§6.4",  "§6.5" ),
        ( "throughput moved 0.043→0.628 over the whole window", "0.628", "0.728" ),
    ] )
    def test_every_verify_class_is_actually_checked( self, text, literal, replacement ):
        """
        These are NOT frozen — they cost less than a placeholder — which makes
        it easy to assume they are unprotected. They are not: each is counted in
        place, and changing one is caught.
        """
        fm = freeze( text )

        assert literal not in [ p.literal for p in fm.placeholders ], \
            f"{literal!r} should be verify-tier, not frozen"
        assert not validate( fm.frozen_text.replace( literal, replacement ), fm ).ok

    def test_swapping_two_integers_is_NOT_caught_and_that_is_deliberate( self ):
        """
        The honest limit of the verify tier, pinned in place.

        A multiset check cannot see relocation: "3 failed / 21669 passed" with
        the numbers exchanged has an identical multiset. This test exists so
        nobody later reads a green verify-tier result as meaning the numbers are
        attached to the right claims.
        """
        text = "3 failed / 21669 passed"
        fm   = freeze( text )

        swapped = fm.frozen_text.replace( "3 failed / 21669 passed", "21669 failed / 3 passed" )

        assert validate( swapped, fm ).ok, \
            "if this ever fails the verify tier got stronger — update the docs, do not delete this test"


class TestRemovableBoilerplate:
    """
    The one thing the rewriter is allowed to delete.

    Without this split the system fights itself: stripping ceremony is Rick's
    second goal, the ceremony in this fleet is largely glyphs, and 58% of
    messages carry one. Verifying them all would fire fail-closed across most of
    the corpus because the rewriter did exactly what it was told.
    """

    def test_a_leading_persona_glyph_may_be_removed( self ):
        text = "🦉 Bounced the dev server myself — it came back healthy in eleven seconds."
        fm   = freeze( text )

        assert validate( fm.frozen_text.replace( "🦉 ", "" ), fm ).ok

    @pytest.mark.parametrize( "glyph", [ "🦉", "🫡", "🕊️", "🌸" ] )
    def test_the_common_leading_glyphs_are_all_removable( self, glyph ):
        text = f"{glyph} the queue drained cleanly overnight and nothing is outstanding"
        fm   = freeze( text )

        assert validate( fm.frozen_text.replace( glyph + " ", "" ), fm ).ok

    def test_an_inline_glyph_is_content_and_may_not_be_removed( self ):
        """
        Mid-sentence ✅ ⚠️ ✓ are content markers, not decoration. The sender's
        identity is in the envelope; a status marker is not.
        """
        text = "the first gate is ✅ and the second one is still open for review"
        fm   = freeze( text )

        assert not validate( fm.frozen_text.replace( "✅", "" ), fm ).ok

    def test_a_glyph_opening_a_LATER_line_is_CLAIMED_by_the_removable_rule( self ):
        """
        The gap between the two tiers — and note what this asserts.

        The inline rule excluded a line-leading glyph as not-inline; the
        removable rule anchored only at the start of the message and never saw
        it. 68 occurrences across 59 messages sat in NEITHER tier and could be
        deleted with no check at all.

        ⚠️ Asserting that deleting it validates cleanly does NOT test this. An
        unguarded glyph also validates cleanly — that is the bug. The assertion
        has to be that the removable rule positively CLAIMS the glyph, which is
        the only thing that distinguishes "allowed" from "unwatched".
        """
        import sys
        module = sys.modules[ "cosa.agents.dm_compression.freeze" ]

        text     = "First line about the queue.\n🦉 Second line with more detail here."
        claimed  = [ kind for kind, pattern in module._REMOVABLE_BOILERPLATE if pattern.search( text ) ]

        assert "LEADING_GLYPH" in claimed, "a line-leading glyph is in no tier — it can be deleted unchecked"

        fm = freeze( text )
        assert validate( fm.frozen_text.replace( "🦉 ", "" ), fm ).ok

    def test_removable_kinds_are_declared_not_implicit( self ):
        assert REMOVABLE_KINDS, "the removable set must be explicit — silence here means anything goes"


class TestMutationRelocation:
    """
    🔴 This class does NOT establish that relocation is detected. It establishes
    the opposite, on purpose.

    A rewrite can swap which claim each placeholder belongs to while leaving the
    tokens in ascending order inside one clause, and nothing here fires. Nothing
    in this suite covers relocation. Do not read a green run as meaning
    placeholders are attached to the right claims.
    """

    def test_a_realistic_in_clause_swap_is_NOT_detected( self ):
        """
        The case that matters, and it delivers clean.

        Both signals miss it: order does not fire because the tokens are still
        ascending, and confinement does not fire because nothing left its
        clause. Only the claims moved, and claims are not structure.
        """
        text = "The bug is in judge.py:572 and the fix is in src/cosa/rest/queue.py today"
        fm   = freeze( text )

        tokens  = [ p.token for p in fm.placeholders ]
        swapped = f"Fix in {tokens[ 0 ]} and bug in {tokens[ 1 ]} today"
        result  = validate( swapped, fm )

        assert result.ok, "structural validation cannot see this — that is the documented limit"
        assert not result.warnings, \
            "if a warning now fires here, the proxy got stronger — update the docs, do not delete this test"

    def test_a_reshaped_rewrite_reports_that_confinement_could_not_be_checked( self ):
        """
        Silence and 'not checkable' are different answers.

        Real compression reshapes clauses, so the confinement check is
        unavailable precisely when compression worked. It used to skip silently,
        which meant it only ever spoke up about rewrites that had barely changed
        anything.
        """
        text = "The bug is in judge.py:572. The fix is in src/cosa/rest/queue.py."
        fm   = freeze( text )

        tokens   = [ p.token for p in fm.placeholders ]
        reshaped = f"Bug {tokens[ 0 ]}, fix {tokens[ 1 ]}"
        result   = validate( reshaped, fm )

        assert result.ok
        assert any( name == "clause_confinement_unavailable" for name, _ in result.warnings )

    def test_moving_a_placeholder_across_clauses_warns_but_does_not_fail( self ):
        text = "The bug is at judge.py:572. The fix is in src/cosa/rest/queue.py."
        fm   = freeze( text )

        tokens  = [ p.token for p in fm.placeholders ]
        swapped = ( fm.frozen_text
                    .replace( tokens[ 0 ], "@@" )
                    .replace( tokens[ 1 ], tokens[ 0 ] )
                    .replace( "@@", tokens[ 1 ] ) )
        result  = validate( swapped, fm )

        assert result.ok,       "relocation is structurally invisible — it must not gate delivery"
        assert result.warnings, "relocation must at least raise telemetry"


# ──────────────────────────────────────────────────────────────────────────────
# The negative control — required, and insufficient on its own
# ──────────────────────────────────────────────────────────────────────────────

class TestNegativeControl:

    def test_a_rewrite_that_retypes_literals_badly_is_rejected( self ):
        """The world without freezing: the model handles the literal and fumbles it."""
        text = "The leak is at judge.py:572, shipped in d256e25a."
        fm   = freeze( text )

        unfrozen = "The leak is at judge.py:527, shipped in d265e25a."

        assert not validate( unfrozen, fm ).ok, \
            "a rewrite that abandons its placeholders must never validate"

    def test_the_guard_is_what_is_doing_the_work( self ):
        """
        Delete the protection and watch it break.

        If this passes, the checks above are not testing what their names claim.
        """
        text = "See judge.py:572 and src/cosa/rest/queue.py."
        fm   = freeze( text )

        assert fm.placeholders, "extraction found nothing — the rest of this suite proves nothing"

        stripped = fm.frozen_text
        for placeholder in fm.placeholders:
            stripped = stripped.replace( placeholder.token, "REDACTED" )

        assert not validate( stripped, fm ).ok


# ──────────────────────────────────────────────────────────────────────────────
# Type independence
#
# The port pattern fires on line numbers, so a placeholder's KIND is not
# trustworthy. This makes that a permanent property rather than a fact that
# merely holds today.
# ──────────────────────────────────────────────────────────────────────────────

class TestValidatorIgnoresPlaceholderKind:

    def test_relabelling_every_kind_does_not_change_the_verdict( self, corpus ):
        for body in corpus[ :300 ]:
            fm = freeze( body )
            if not fm.placeholders: continue

            scrambled = dataclasses.replace(
                fm,
                placeholders=tuple(
                    dataclasses.replace( p, kind="WRONG", tier="WRONG" ) for p in fm.placeholders
                ),
            )

            assert validate( fm.frozen_text, fm ).ok == validate( fm.frozen_text, scrambled ).ok

    def test_no_kind_belongs_to_two_tiers_at_once( self ):
        assert not ( set( VERIFY_KINDS ) & set( HARD_KINDS + SOFT_KINDS ) )


# ──────────────────────────────────────────────────────────────────────────────
# Span resolution
# ──────────────────────────────────────────────────────────────────────────────

class TestSpanResolution:

    def test_resolved_spans_never_overlap( self, corpus ):
        for body in corpus[ :500 ]:
            spans = resolve_spans( extract_spans( body ) )
            for earlier, later in zip( spans, spans[ 1: ] ):
                assert earlier.end <= later.start

    def test_nested_literals_resolve_to_one_span( self ):
        """A sha inside backticks inside a quote is ONE span, not three."""
        text  = 'he said "the fix is `d256e25a` exactly" yesterday'
        spans = resolve_spans( extract_spans( text ) )

        assert len( [ s for s in spans if "d256e25a" in s.text ] ) == 1

    @pytest.mark.parametrize( "text,expected", [
        ( "job.py:58,106,249",              "job.py:58,106,249" ),
        ( "agent_registry.py:134-148,157",  "agent_registry.py:134-148,157" ),
        ( "orchestrator.py:1441,1456-1459", "orchestrator.py:1441,1456-1459" ),
        ( "job.py:249-256",                 "job.py:249-256" ),
        ( "file.py:12:34",                  "file.py:12:34" ),
        ( "config.py:297,298",              "config.py:297,298" ),
        # Citations that END A SENTENCE. The closing guard used to be
        # `(?![\w.])`, which refused to match `judge.py:572.` at all and matched
        # `judge.py:249-256.` as `judge.py:249` — reintroducing the truncation
        # bug whenever a citation landed at the end of a sentence. 21 of 647
        # corpus citations do exactly that.
        ( "the leak is at judge.py:572.",        "judge.py:572" ),
        ( "the leak spans job.py:249-256.",      "job.py:249-256" ),
        ( "see config.py:297,298. Then bounce.", "config.py:297,298" ),
    ] )
    def test_file_line_citations_are_frozen_whole( self, text, expected ):
        """
        The truncation bug, pinned.

        Freezing only the head of `job.py:58,106,249` leaves `,106,249` as
        compressible prose. A rewriter that drops it produces a citation that
        looks entirely valid and names fewer sites than the author did — and it
        passes every structural check, because structurally nothing went wrong.
        """
        fm = freeze( text )
        assert expected in [ p.literal for p in fm.placeholders ]

    def test_dropping_a_trailing_element_from_a_comma_list_is_caught( self ):
        """The shape that reads as a valid citation while naming fewer sites."""
        text = "the leak spans job.py:58,106,249 in that order across the run"
        fm   = freeze( text )

        token   = [ p.token for p in fm.placeholders if "job.py" in p.literal ][ 0 ]
        mutated = fm.frozen_text.replace( token, "job.py:58,106" )

        assert not validate( mutated, fm ).ok

    @pytest.mark.parametrize( "text", [
        "gate the queue and gate by hand",
        "we should gate that behind a flag",
        "gate before you bounce it",
    ] )
    def test_gate_pointer_does_not_swallow_the_next_word( self, text ):
        """
        The greedy pattern that produced 1,307 junk spans.

        `gate the` matched as `gate t` — it took the first letter of the
        following word. It never showed up as a high frozen ratio because it
        spread thinly across the corpus instead of dominating any one message,
        which is exactly why it survived the first round of measurement.
        """
        counts = count_verify_literals( text, "" )
        junk   = [ k for k in counts if k.lower().startswith( "gate " ) and len( k ) == 6 ]

        assert not junk, f"gate pointer swallowed a word: {junk}"

    def test_verify_patterns_track_edits_to_the_taxonomy( self ):
        """
        The verify view must be DERIVED, never snapshotted.

        A module-level snapshot is built once at import, so changing a pattern
        afterwards leaves the freeze path and the verify path disagreeing. That
        divergence fooled a falsification pass: reverting the section-pointer
        fix left the verify path holding the fixed pattern, the guard test kept
        passing, and a real guard was reported as absent.

        This asserts the two views cannot drift apart again.
        """
        import sys
        module = sys.modules[ "cosa.agents.dm_compression.freeze" ]

        derived  = { kind for kind, _ in module._verify_patterns() }
        declared = { kind for kind, tier, _ in module._PATTERNS if tier == "VERIFY" }

        assert declared <= derived
        assert not hasattr( module, "_VERIFY_PATTERNS" ), \
            "a snapshot reappeared — it will drift from _PATTERNS and hide a broken guard"

    def test_gate_pointer_still_matches_real_references( self ):
        counts = count_verify_literals( "see gate (a) and gate 2 for the wording", "" )

        assert "gate (a)" in counts
        assert "gate 2"   in counts


# ──────────────────────────────────────────────────────────────────────────────
# Property-based fuzzing
#
# Handwritten adversarial cases only cover what someone thought of.
# ──────────────────────────────────────────────────────────────────────────────

class TestPropertyBasedFuzz:

    ALPHABET = string.printable + "⟦⟧🦉🌸日本語–—±→§"

    @pytest.mark.parametrize( "seed", range( 200 ) )
    def test_identity_holds_for_arbitrary_text( self, seed ):
        rng  = random.Random( seed )
        text = "".join( rng.choice( self.ALPHABET ) for _ in range( rng.randint( 0, 400 ) ) )

        fm = freeze( text )
        assert restore( fm.frozen_text, fm ) == text

    @pytest.mark.parametrize( "seed", range( 100 ) )
    def test_freezing_is_deterministic( self, seed ):
        rng  = random.Random( seed )
        text = " ".join(
            rng.choice( [ "judge.py:572", "d256e25a", "word", ":7999", "§4", "42", "🦉" ] )
            for _ in range( rng.randint( 1, 40 ) )
        )

        first, second = freeze( text ), freeze( text )

        assert first.frozen_text == second.frozen_text
        assert [ p.literal for p in first.placeholders ] == [ p.literal for p in second.placeholders ]

    @pytest.mark.parametrize( "seed", range( 100 ) )
    def test_validation_never_raises_on_hostile_input( self, seed ):
        """A validator that crashes fails open. It must always return a verdict."""
        rng = random.Random( seed )
        fm  = freeze( "the fix is at judge.py:572 in src/cosa/rest/queue.py" )

        hostile = "".join( rng.choice( self.ALPHABET ) for _ in range( rng.randint( 0, 200 ) ) )

        assert validate( hostile, fm ).ok in ( True, False )


# ──────────────────────────────────────────────────────────────────────────────
# Fail-closed delivery
# ──────────────────────────────────────────────────────────────────────────────

class TestFailClosed:

    def test_a_broken_rewrite_delivers_the_original( self, frozen ):
        broken            = frozen.frozen_text.replace( frozen.placeholders[ 0 ].token, "" )
        delivered, reason = compress_or_original( broken, frozen )

        assert delivered == SAMPLE
        assert reason is not None

    def test_a_good_rewrite_delivers_the_compressed_form( self, frozen ):
        delivered, reason = compress_or_original( _plausible_rewrite( frozen ), frozen )

        assert reason is None
        assert delivered != SAMPLE
        assert "judge.py:572" in delivered

    def test_strict_restore_refuses_rather_than_returning_partial_text( self, frozen ):
        broken = frozen.frozen_text.replace( frozen.placeholders[ 0 ].token, "" )

        with pytest.raises( ValueError ):
            restore( broken, frozen, strict=True )

    def test_delivered_text_never_contains_an_unrestored_placeholder( self, corpus ):
        for body in corpus[ :300 ]:
            fm = freeze( body )
            delivered, _ = compress_or_original( fm.frozen_text, fm )

            assert OPEN_DELIM not in delivered or OPEN_DELIM in body

    def test_compress_or_original_never_raises( self, corpus ):
        """It sits in the delivery path. An exception here drops a message."""
        for body in corpus[ :300 ]:
            fm = freeze( body )
            compress_or_original( "garbage " + fm.frozen_text[ :20 ], fm )


# ──────────────────────────────────────────────────────────────────────────────
# Bypass
# ──────────────────────────────────────────────────────────────────────────────

class TestBypass:

    def test_a_message_that_is_mostly_literals_is_bypassed( self ):
        fm = freeze(
            "judge.py:572 src/cosa/rest/queue.py d256e25a src/cosa/agents/base.py "
            "test_dm_verbs.py orchestrator.py:1441 api_client.py:413-419"
        )
        assert fm.should_bypass

    def test_a_normal_message_is_not_bypassed( self ):
        assert not freeze( SAMPLE ).should_bypass

    def test_a_short_message_is_bypassed_because_there_is_nothing_to_win( self ):
        """
        Below the floor there is not enough prose for a rewrite to pay for
        itself. 5.7% of the corpus lands here, median 31 words.
        """
        fm = freeze( "I looked at the queue code this morning and it seems fine to me" )

        assert fm.should_bypass
        assert "compressible words" in fm.bypass_reason

    def test_bypass_carries_a_reason( self ):
        fm = freeze( "judge.py:572" )
        assert fm.bypass_reason

    def test_a_bypassed_message_delivers_the_original_untouched( self ):
        text = "judge.py:572"
        fm   = freeze( text )

        delivered, reason = compress_or_original( fm.frozen_text, fm )

        assert delivered == text
        assert "bypass" in reason


# ──────────────────────────────────────────────────────────────────────────────
# Clause segmentation
# ──────────────────────────────────────────────────────────────────────────────

class TestClauseSegmentation:

    @pytest.mark.parametrize( "text", [
        "",
        "one clause only",
        "First. Second. Third.",
        "line one\nline two\n\nline four",
        "Semicolons; also count: and colons too.",
    ] )
    def test_clause_spans_tile_the_text_exactly( self, text ):
        spans = segment_clauses( text )
        assert "".join( text[ s:e ] for s, e in spans ) == text


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
