"""
Control-proof for the synthetic DM corpus.

THE FAILURE THIS FILE EXISTS TO PREVENT. A generator written by the same person who wrote
the checks is an instrument certifying itself. The corpus's whole claim is "these bodies
strain the span extractor", and nothing about a hand-written literal table makes that true
— it is true only while the table keeps up with `freeze._PATTERNS`, which nobody is
obliged to remember.

So the central test does not read this file's own list. It derives the kind names from
`freeze._PATTERNS` AT RUNTIME and demands every one of them actually produce a span when
the corpus is run through the real extractor. Add a pattern to freeze.py and forget the
corpus, and that test reddens naming the kind. That is the second reading from outside the
thing under test.

Venue :7999/unit — pure in-process generation and extraction. No corpus file, no network,
no state.
"""

import pytest

from cosa.agents.dm_compression.corpus_synth import (
    synth_corpus,
    _LITERALS,
    _ADVERSARIAL,
)
from cosa.agents.dm_compression.freeze import (
    _PATTERNS,
    freeze,
    restore,
    validate,
    extract_spans,
    resolve_spans,
    compress_or_original,
    OPEN_DELIM,
)


def _live_kind_names():
    """The kind names the REAL extractor knows about, read from freeze at runtime."""
    return { kind for kind, _tier, _rx in _PATTERNS }


# ── the guard that stops this corpus certifying itself ────────────────────────────

def test_the_literal_table_covers_every_kind_the_extractor_knows():
    """
    Derived from freeze._PATTERNS, never from a list in the corpus module. A pattern added
    to freeze.py and forgotten here fails HERE, naming the kind — rather than silently
    going unexercised while the suite still reports a full green.
    """
    missing = _live_kind_names() - set( _LITERALS )

    assert not missing, (
        f"freeze._PATTERNS gained {sorted( missing )} and corpus_synth._LITERALS was not "
        "updated — those kinds are now unexercised by every corpus test, and nothing else "
        "would have told you" )


def test_the_literal_table_has_no_kind_the_extractor_dropped():
    """The mirror direction: a kind removed from freeze leaves a literal nobody needs."""
    stale = set( _LITERALS ) - _live_kind_names()

    assert not stale, (
        f"corpus_synth._LITERALS still carries {sorted( stale )}, which freeze._PATTERNS no "
        "longer defines — the table is describing an extractor that does not exist" )


def test_every_hard_and_soft_kind_actually_produces_a_span():
    """
    THE ONE THAT MATTERS. The two tests above compare NAMES; this runs the REAL extractor
    over the REAL generated bodies. A literal that looks right but does not match its own
    pattern passes both name checks and contributes nothing.

    It earned its keep on its first run: it caught NUMWORD carrying "3 retries" when the
    pattern wants a SPELLED-OUT number. Both name tests were green at the time.

    Scoped to HARD and SOFT because `extract_spans` accepts only those two tiers
    (freeze.py:482 @ 8bf71a64, `tier="HARD+SOFT"`, ValueError on anything else).
    VERIFY kinds are
    excluded there BY DESIGN and are covered by the next test instead — asserting them
    here would be measuring the wrong function, which is what the first draft of this
    file did.
    """
    hard_soft = { kind for kind, tier, _rx in _PATTERNS if tier in ( "HARD", "SOFT" ) }
    corpus    = synth_corpus()
    seen      = { span.kind for body in corpus for span in extract_spans( body ) }

    missing = hard_soft - seen

    assert not missing, (
        f"{sorted( missing )} never produced a span across {len( corpus )} generated bodies "
        "— each literal is in the table but does not match its own pattern" )


def test_every_verify_kind_matches_its_own_pattern_in_the_corpus():
    """
    VERIFY spans never come back from `extract_spans`, so the check for them is against
    the patterns directly: each VERIFY literal must actually be found by its own regex
    somewhere in the generated bodies.
    """
    corpus = synth_corpus()
    joined = "\n".join( corpus )

    unmatched = [ kind for kind, tier, rx in _PATTERNS
                  if tier == "VERIFY" and not rx.search( joined ) ]

    assert not unmatched, (
        f"{sorted( unmatched )} have literals in the table that their own pattern does not "
        "match anywhere in the generated corpus" )


# ── determinism, which is what makes a failure reproducible ───────────────────────

def test_the_same_seed_gives_the_same_corpus():
    assert synth_corpus( seed=7 ) == synth_corpus( seed=7 )


def test_a_different_seed_gives_a_different_corpus():
    """Otherwise the seed parameter is decoration and the generator is a constant."""
    assert synth_corpus( seed=7 ) != synth_corpus( seed=8 )


def test_the_adversarial_cases_come_first_so_a_slice_keeps_them():
    """
    Four of the six corpus tests take `corpus[ :300 ]`. Hard cases sorted to the end of a
    600-body list would be exercised by exactly two of them.
    """
    corpus = synth_corpus()

    assert corpus[ :len( _ADVERSARIAL ) ] == _ADVERSARIAL
    for case in _ADVERSARIAL:
        assert case in corpus[ :300 ]


def test_the_corpus_never_shrinks_below_its_own_floor():
    """A caller asking for 5 must still get every adversarial case and every kind."""
    corpus = synth_corpus( count=5 )

    assert len( corpus ) >= len( _ADVERSARIAL ) + len( _LITERALS )


# ── the invariants the real corpus was there to exercise ──────────────────────────
#
# These mirror the six tests in test_freeze.py. They are here as well as there because
# these run against the corpus THIS module generates — if the generator ever produces
# something that breaks freeze, this file names the generator as the suspect.

def test_freeze_restore_is_identity_across_the_generated_corpus():
    failures = [ body for body in synth_corpus()
                 if restore( freeze( body ).frozen_text, freeze( body ) ) != body ]

    assert not failures, f"{len( failures )} generated bodies failed to round-trip"


def test_placeholders_never_collide_with_the_generated_source():
    for body in synth_corpus():
        frozen = freeze( body )
        for placeholder in frozen.placeholders:
            assert placeholder.token not in body


def test_resolved_spans_never_overlap_on_the_generated_corpus():
    for body in synth_corpus():
        spans = resolve_spans( extract_spans( body ) )
        for earlier, later in zip( spans, spans[ 1: ] ):
            assert earlier.end <= later.start, f"overlapping spans in: {body[ :80 ]!r}"


def test_the_verdict_does_not_depend_on_a_spans_label():
    import dataclasses

    for body in synth_corpus( count=200 ):
        frozen = freeze( body )
        if not frozen.placeholders: continue

        scrambled = dataclasses.replace(
            frozen,
            placeholders=tuple( dataclasses.replace( p, kind="WRONG", tier="WRONG" )
                                for p in frozen.placeholders ) )

        assert validate( frozen.frozen_text, frozen ).ok == validate( frozen.frozen_text,
                                                                      scrambled ).ok


def test_no_unrestored_placeholder_reaches_delivery():
    for body in synth_corpus( count=200 ):
        frozen       = freeze( body )
        delivered, _ = compress_or_original( frozen.frozen_text, frozen )

        assert OPEN_DELIM not in delivered or OPEN_DELIM in body


def test_compress_or_original_never_raises_on_the_generated_corpus():
    for body in synth_corpus( count=200 ):
        frozen = freeze( body )
        compress_or_original( "garbage " + frozen.frozen_text[ :20 ], frozen )


# ── the honesty clause ────────────────────────────────────────────────────────────

def test_the_module_says_what_it_does_not_cover():
    """
    A synthetic corpus that quietly misses a case is the same false green in new clothes.
    The docstring must keep saying so — this holds the disclosure in place against a
    future tidy-up that trims it as boilerplate.
    """
    import cosa.agents.dm_compression.corpus_synth as module

    doc = module.__doc__

    assert "WHAT THIS DOES NOT COVER" in doc
    assert "combinations nobody designed" in doc, (
        "the disclosure must name the thing real traffic gave us and this cannot" )
    assert "never as" in doc, "it must say how NOT to read a green from this corpus"
