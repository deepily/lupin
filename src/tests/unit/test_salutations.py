#!/usr/bin/env python3
"""
Ensures-contract tests for cosa.rest.salutations.parse_salutations (brain
integration step 4 — the shared salutation list + parser that the v1 queue and
the v2 flow both call, so they never disagree about what a greeting is).

Each test pins ONE clause of the docstring's Ensures block and carries the
falsifier it was proven against (red on that mutation, green on c02f9a8b):

  1. trailing punctuation is ignored when MATCHING
       falsifier: `if word.lower() in known:`
  2. only a LEADING run is taken — the first non-salutation ends it
       falsifier: `else: break` → `else: continue`
  3. the ORIGINAL words (case + punctuation) come back in the salutation half
       falsifier: append the normalised word instead of `word`

Pure function, no I/O. :7999-eligible.
"""

import pytest

from cosa.rest.salutations import SALUTATIONS, parse_salutations


# ── 1. trailing punctuation ignored when matching ──────────────────────────────

def test_trailing_punctuation_is_ignored_when_matching():
    # "hey," and "buddy." only match because the comparison strips ',.:;!?'.
    # Falsifier `if word.lower() in known:` returns ( "", <whole sentence> ).
    assert parse_salutations( "hey, buddy. what time is it" ) == ( "hey, buddy.", "what time is it" )


@pytest.mark.parametrize( "punct", [ ",", ".", ":", ";", "!", "?", "!?", "..." ] )
def test_every_listed_trailing_punctuation_mark_is_ignored( punct ):
    sal, rest = parse_salutations( f"hello{punct} what is the weather" )
    assert sal  == f"hello{punct}"
    assert rest == "what is the weather"


# ── 2. only a LEADING run is taken ─────────────────────────────────────────────

def test_only_the_leading_run_is_taken():
    # "is" ends the run; "my" later in the sentence is a salutation word but
    # must stay in the remainder. Falsifier `else: continue` yields
    # ( "hey there my", "my package here" ).
    assert parse_salutations( "hey there is my package here" ) == ( "hey there", "is my package here" )


def test_salutation_words_after_the_first_non_salutation_are_not_consumed():
    # Every word after "how" is ALSO a salutation word — none of them may move.
    assert parse_salutations( "hi how good morning friend" ) == ( "hi", "how good morning friend" )


def test_no_leading_salutation_returns_empty_prefix_and_text_intact():
    assert parse_salutations( "what time is it, buddy" ) == ( "", "what time is it, buddy" )


def test_all_salutations_returns_empty_remainder():
    assert parse_salutations( "hey there buddy" ) == ( "hey there buddy", "" )


def test_empty_and_whitespace_only_return_two_empty_strings():
    assert parse_salutations( "" )      == ( "", "" )
    assert parse_salutations( "   " )   == ( "", "" )


# ── 3. original words come back — case + punctuation preserved ────────────────

def test_returned_salutation_preserves_case_and_punctuation_exactly_as_typed():
    # Matching is case-insensitive and punctuation-blind, but what comes BACK
    # is the text as typed. Falsifier: appending the normalised word gives
    # "hey buddy".
    assert parse_salutations( "Hey, Buddy! what's up" ) == ( "Hey, Buddy!", "what's up" )


def test_mixed_case_and_accented_entries_match_and_are_returned_verbatim():
    # "día" is in the list as typed (accent kept); "Buenas"/"Noches" exercise mixed case.
    assert parse_salutations( "Buenas Noches, Jarvis: how are you" ) == ( "Buenas Noches, Jarvis:", "how are you" )
    assert parse_salutations( "Buen Día! qué hora es" ) == ( "Buen Día!", "qué hora es" )


def test_remainder_is_also_verbatim_words_rejoined_with_single_spaces():
    # split()/join normalises internal whitespace but never the words themselves.
    assert parse_salutations( "hey   Computer,   What's   UP?" ) == ( "hey Computer,", "What's UP?" )


# ── list + injection seam ──────────────────────────────────────────────────────

def test_custom_salutation_list_is_honoured_and_default_is_untouched():
    assert parse_salutations( "howdy partner, what time is it", salutations=[ "howdy", "partner" ] ) \
        == ( "howdy partner,", "what time is it" )
    # The default list does not know "howdy" — nothing stripped.
    assert parse_salutations( "howdy partner, what time is it" ) == ( "", "howdy partner, what time is it" )
    # An EMPTY custom list (not None) means strip nothing — `salutations=None` is the only default trigger.
    assert parse_salutations( "hey buddy what", salutations=[] ) == ( "", "hey buddy what" )


def test_shared_list_carries_the_queue_era_entries_verbatim():
    # Moved from TodoFifoQueue.__init__ "verbatim" — spot-check the ones users
    # actually open with, across English + Spanish, lowercase as stored.
    for word in [ "hey", "hello", "hi", "buddy", "computer", "jarvis", "buenos", "dias", "día", "good", "morning", "my", "friend" ]:
        assert word in SALUTATIONS
    assert all( w == w.lower() for w in SALUTATIONS ), "list is stored lowercase; matching lowercases the input"
