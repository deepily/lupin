"""
THE PROMOTION ASK MUST NAME THE ROW, NOT JUST THE ASKER — row 218f139c.

Rick raised this to P0 himself. Until 2026-09-09 the spoken question read:

    "{actor} wants to promote a row out of the holding area. Allow it?"

WHO, and nothing about WHAT. Every promotion he approved before that date told him a
persona name only — so the single thing he could weigh was the identity of the asker,
which is the one thing this module's own gate says proves nothing. A gate that cannot
say what it is gating is asking for a rubber stamp.

⚠️ THE ABSTRACT WAS NEVER THE DEFECT. It has always carried the id, the title and the
requester. The bug was ONLY in the SPOKEN line — precisely the half Rick gets when he
answers from across the room. Sibling file `test_the_promotion_ask_says_who_it_is.py`
guards the sender; this one guards the subject.

🔴 THE ASSERTIONS RUN THROUGH `promotion_ask_kwargs`, NOT ONLY THE FORMATTER. The row's
acceptance says so in as many words: a test that the formatter CAN produce the title is
a different claim from the ask ACTUALLY carrying it. A perfect builder whose output is
never placed in the fired kwargs reaches nobody.
"""
import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.rest import task_promotion_gate as gate


# The store's own title cap — a title AT this length is the case the row's acceptance
# names, and it is the one a short-title test would never exercise.
STORE_TITLE_CAP = 120

# The server rejects a spoken payload over this and the ENTIRE ask fails: perceived
# silence plus a burned retry. Asserted as a hard ceiling, never as a target.
SPOKEN_PAYLOAD_CAP = 500

ACTOR = "mr radio 81381447"
TASK  = "218f139c-e3bb-47d0-b94a-f9b25f8684f6"


# ---------------------------------------------------------------------------
# The control FIRST — a green file must not also be consistent with the builder
# ignoring its title argument entirely.
# ---------------------------------------------------------------------------

def test_the_question_actually_varies_with_the_title():
    """
    🔴 THE DISCRIMINATOR, AND WITHOUT IT EVERY ARM BELOW IS SATISFIABLE BY A CONSTANT.

    A builder that ignored `title` and returned fixed prose would pass "the question
    mentions the holding area" and "the question is under the cap" and every other
    shape assertion here. Two titles, two questions, and they must differ.
    """
    q_one, _ = gate.promotion_ask_kwargs( ACTOR, TASK, "the first row" )[ "question" ], None
    q_two    = gate.promotion_ask_kwargs( ACTOR, TASK, "a completely different row" )[ "question" ]

    assert q_one != q_two, (
        "the spoken question did not change when the title did — it is not reading the "
        "title at all, and every other assertion in this file would still pass"
    )


# ---------------------------------------------------------------------------
# The claim itself, through the ASSEMBLED kwargs.
# ---------------------------------------------------------------------------

def test_the_fired_ask_names_the_row_in_the_SPOKEN_question():
    """The defect, stated positively and driven through the kwargs the ask fires with."""
    title  = "The promotion ask names WHO wants it and never WHAT"
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, title )

    assert title in kwargs[ "question" ], (
        f"the spoken question does not name the row. Rick hears only this line when he "
        f"answers from a distance, so a question without the title asks him to approve "
        f"something he cannot identify. Got: {kwargs[ 'question' ]!r}"
    )


def test_the_fired_ask_still_names_the_asker():
    """
    The old question's ONE virtue must survive the fix. A repair that swapped who for
    what would trade one half-blind question for another.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "some row" )
    assert ACTOR in kwargs[ "question" ]


def test_the_abstract_is_unchanged_and_still_carries_the_id():
    """
    🔴 THE REGRESSION GUARD ON THE HALF THAT WAS ALREADY RIGHT. The abstract carried the
    id, title and requester before this change and must carry them after — a fix aimed
    at the question must not quietly rewrite the card.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "some row" )
    abstract = kwargs[ "abstract" ]

    assert TASK in abstract
    assert "some row" in abstract
    assert ACTOR in abstract


def test_the_id_stays_OUT_of_the_spoken_question():
    """
    🔴 A DELIBERATE DEPARTURE FROM THE ROW'S OWN ACCEPTANCE, WHICH ASKED FOR "title and
    the short id, at minimum".

    A hash verbalizes as character-by-character gibberish, and *"I have no idea what
    that hash means"* is Rick's own complaint — the very thing this row exists to fix.
    Speaking an id would reproduce the defect one layer over while appearing to satisfy
    the acceptance. The id belongs in the abstract, where it can be read and clicked.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "some row" )
    assert TASK not in kwargs[ "question" ]


# ---------------------------------------------------------------------------
# The cap — measured at the length the row's acceptance names, not a short one.
# ---------------------------------------------------------------------------

def test_a_title_at_the_STORE_CAP_still_fits_the_spoken_payload():
    """
    The row's acceptance is explicit: assert this "with a title AT the cap, not a short
    one". A short title proves nothing about the case that would actually break.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "T" * STORE_TITLE_CAP )

    assert len( kwargs[ "question" ] ) < SPOKEN_PAYLOAD_CAP, (
        f"the spoken question is {len( kwargs[ 'question' ] )} chars against a "
        f"~{SPOKEN_PAYLOAD_CAP} cap — over it the WHOLE ask is rejected and Rick hears "
        f"nothing at all, which is worse than the vague question this row replaced"
    )


def test_an_absurdly_long_title_is_TRUNCATED_rather_than_overflowing():
    """
    The store's cap is not a guarantee about every caller. A title far past it must be
    cut by this module rather than trusted, or the ask fails silently.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "T" * 5000 )

    assert len( kwargs[ "question" ] ) < SPOKEN_PAYLOAD_CAP
    assert gate.TRUNCATION_SPOKEN_AS in kwargs[ "question" ], (
        "a truncated title must SAY it was truncated IN WORDS — a silent cut tells the "
        "listener they heard the whole title when they heard a fragment"
    )
    # 🔴 THE ELLIPSIS IS BANNED, AND THIS ARM IS WHY THE FIRST CUT WAS WRONG. U+2026 may
    # verbalize as NOTHING, so asserting it present asserts a character the listener may
    # never hear: the test passes and the human is still misled. (María 🌸 caught it.)
    assert "…" not in kwargs[ "question" ]


# ---------------------------------------------------------------------------
# Degenerate titles — a question must still be a sentence.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "title", [ None, "", "   " ] )
def test_a_missing_title_still_yields_a_speakable_question( title ):
    """
    A blank title must not leave a gap the listener cannot place. "wants to promote
    this row out of the holding area: . Allow it?" is worse than the old wording.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, title )
    question = kwargs[ "question" ]

    assert "a row with no title" in question
    assert ": ." not in question, "the question has an empty slot where the title should be"


def test_a_multiline_title_is_flattened_before_it_is_spoken():
    """
    A newline is spoken as NOTHING, which silently joins two clauses into one false
    phrase. Flattening is the only way the listener hears what the row says.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "first clause\nsecond clause" )
    question = kwargs[ "question" ]

    assert "\n" not in question
    assert "first clause second clause" in question


def test_internal_whitespace_runs_are_collapsed():
    """Tabs and runs of spaces are audible as nothing; they only pad the payload."""
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "spaced\t\t   out" )
    assert "spaced out" in kwargs[ "question" ]


# ---------------------------------------------------------------------------
# The budget constant is a budget, not a fit.
# ---------------------------------------------------------------------------

def test_the_spoken_title_budget_leaves_room_for_the_rest_of_the_question():
    """
    Pins the RELATIONSHIP rather than the number, so raising the budget without
    re-checking the payload reddens here instead of in production.
    """
    longest = gate.promotion_ask_kwargs( ACTOR, TASK, "T" * gate.SPOKEN_TITLE_BUDGET )
    assert len( longest[ "question" ] ) < SPOKEN_PAYLOAD_CAP

# ---------------------------------------------------------------------------
# Hex identifiers in the TITLE — the same defect one layer over.
# ---------------------------------------------------------------------------

def test_a_sha_inside_the_TITLE_is_not_spoken_as_gibberish():
    """
    🔴 THE FIX'S OWN BLIND SPOT, FOUND BY MARÍA 🌸 IN REVIEW. I kept the row ID out of
    the spoken line and then read a title containing somebody else's sha out loud —
    the identical defect, one layer over.

    MEASURED, not assumed: ~16 of a 120-row sample carry a hex identifier in the
    title. Roughly one in eight, counted independently by both of us.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "shipped at a0f04df1" )
    question = kwargs[ "question" ]

    assert "a0f04df1" not in question, (
        f"a commit sha is being read aloud character by character. Got: {question!r}"
    )
    assert gate.HEX_SPOKEN_AS in question, (
        "the identifier was dropped without a word in its place, which leaves broken "
        "prose — the sentence must still stand up"
    )


def test_EVERY_sha_in_a_multi_hash_title_is_redacted_not_just_the_first():
    """
    Real titles carry more than one. "Review c00b4b0e for bcf15f08" is a live example,
    and a `sub` that stopped at the first match would pass the arm above and still
    speak gibberish here.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "Review c00b4b0e for bcf15f08 — two guards" )
    question = kwargs[ "question" ]

    assert "c00b4b0e" not in question
    assert "bcf15f08" not in question
    assert question.count( gate.HEX_SPOKEN_AS ) == 2


def test_the_ABSTRACT_keeps_the_real_sha():
    """
    🔴 THE REDACTION IS FOR SPEECH ONLY. The card is READ, so it must carry the actual
    identifier — redacting there would destroy the one place Rick can copy it from.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "shipped at a0f04df1" )
    assert "a0f04df1" in kwargs[ "abstract" ]


def test_ordinary_words_are_NOT_mistaken_for_hashes():
    """
    THE FALSE-POSITIVE CONTROL. A redactor that ate real words would quietly mangle
    every title, and the arms above cannot see that — they only check hashes go away.
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "the coverage gate discards its own breakdown" )

    assert "coverage" in kwargs[ "question" ]
    assert "breakdown" in kwargs[ "question" ]
    assert gate.HEX_SPOKEN_AS not in kwargs[ "question" ], (
        "a title with no identifier in it came back with a redaction marker — the "
        "pattern is matching ordinary prose"
    )


def test_a_short_hex_word_is_left_alone():
    """
    The floor is 7 because `git log --oneline` abbreviates to 7. Shorter hex-ish words
    are ordinary English and must survive — "added", "faced", "beef".
    """
    kwargs = gate.promotion_ask_kwargs( ACTOR, TASK, "beef added to the cafe menu" )
    assert "beef" in kwargs[ "question" ]
    assert gate.HEX_SPOKEN_AS not in kwargs[ "question" ]
