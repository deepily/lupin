#!/usr/bin/env python3
"""
THE SPLAINER'S "in-code fallback X" IS A PROSE COPY OF A CODE CONSTANT — this watches it.

Row `3493ae9b`. Raised by Mr. Radio 🦉 on 2026-09-06: he asked whether
`lupin-app-splainer.ini` DESCRIBES the default or RESTATES it as a second source of truth.

🔴 THE ANSWER WAS "NEITHER, QUITE", AND THAT IS WHY THIS FILE EXISTS. The splainer does
not restate `lupin-app.ini`'s value — "in-code fallback False" names what the CODE does
when the KEY IS ABSENT, which is a genuinely different fact from what an operator set. So
it is not two derivations of one value.

⚠️ BUT IT IS A PROSE COPY OF A CODE CONSTANT, AND NOTHING WATCHED IT. Flip
`FALLBACK_ASYNCHRONOUS` to True and the splainer goes silently wrong, in the direction
that matters most: an operator reading it would believe an absent config fails CLOSED
while the code had started failing open. That is the UNGUARDED third state — correct
today, untestable-if-wrong — not a defect, and it wants a test rather than a fix.

⚠️ THE PARITY CHECK THAT ALREADY EXISTED IS A DIFFERENT CLAIM. Loading the splainer file
cleanly proves the key has an ENTRY. It says nothing about whether the entry is TRUE.
Presence is not agreement.

VENUE: `:7999`. Pure file reads, milliseconds, no monopoly.
"""
import os
import re
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu
from cosa.rest import task_promotion_gate as gate

SPLAINER = os.path.join( cu.get_project_root(), "src", "conf", "lupin-app-splainer.ini" )

# 🔴 THE CLAIM IS A PREDICATE, NOT A LIST OF KEYS, AND THE DISTINCTION IS THE POINT.
# What this file asserts is "wherever the splainer names an in-code fallback for a key
# this row owns, the prose and the constant agree" — the pairs below are the population
# it is checked over, not the rule itself. A key that grows the phrase later is caught by
# adding one line here; a key that never had it is not silently blessed, because
# `test_every_pair_below_was_actually_FOUND` refuses a pair the extractor could not read.
FALLBACK_PAIRS = [
    ( gate.INI_KEY_ASYNCHRONOUS, gate.FALLBACK_ASYNCHRONOUS ),
    ( gate.INI_KEY_ASK_TIMEOUT,  gate.FALLBACK_ASK_TIMEOUT_SECONDS ),
]

# 🔴 THE FIRST CUT OF THIS WAS `[A-Za-z0-9_.]+` AND IT ATE THE SENTENCE'S FULL STOP,
# capturing "False." and "120." — so the guard went red against constants it agreed with
# perfectly, and the red READ AS "the prose disagrees with the code" when it meant "my
# regex is wrong". Two failures wanting opposite fixes, printing the same colour.
#
# ⚠️ A HAND-WRITTEN CHARACTER CLASS IS A HAND-MAINTAINED ENUMERATION OF CHARACTERS, and
# nothing about the smaller scale makes it safer. The predicate it approximates is "the
# token naming a fallback VALUE" — an identifier, or a number that may carry a decimal
# point. Written that way a trailing period cannot be absorbed, because a sentence's full
# stop is not followed by digits.
_PHRASE = re.compile( r"in-code fallback\s+([A-Za-z0-9_]+(?:\.[0-9]+)?)" )


def _stated_fallback( key ):
    """
    The fallback value the splainer's entry for `key` CLAIMS, as a string, or None.

    Ensures:
        - returns None when the key has no entry, or its entry names no fallback —
          the two are deliberately NOT distinguished here, because
          `test_every_pair_below_was_actually_FOUND` is what refuses a None
    """
    with open( SPLAINER, encoding="utf-8" ) as handle:
        for line in handle:
            if not line.startswith( key ): continue
            found = _PHRASE.search( line )
            return found.group( 1 ) if found else None
    return None


@pytest.mark.parametrize( "key,constant", FALLBACK_PAIRS, ids=lambda v: str( v )[ :40 ] )
def test_the_splainer_states_the_value_the_code_actually_falls_back_to( key, constant ):
    """
    🔴 THE KILL. The splainer is what an OPERATOR reads to decide whether a missing key
    is safe. For the asynchronous flag, "in-code fallback False" is the sentence that
    tells them an absent config stays synchronous — and if the constant were flipped, the
    prose would keep saying so while the code handed out 202s to callers that read any
    2xx as success.
    """
    stated = _stated_fallback( key )
    assert stated == str( constant ), (
        f"the splainer entry for {key!r} says the in-code fallback is {stated!r}, and the "
        f"code's constant is {str( constant )!r}. An operator reading the splainer would "
        f"be wrong about what a missing key does."
    )


def test_every_pair_below_was_actually_FOUND():
    """
    🔴 THE POSITIVE CONTROL, AND WITHOUT IT THIS FILE IS WORTHLESS. A regex that matched
    NOTHING would make `_stated_fallback` return None for every key, and the arm above
    would then be comparing None against a string and failing — which is safe. But a
    regex that matched nothing while the constants were ALSO None-ish would pass
    vacuously, and more importantly: an empty search and a search that ran are
    indistinguishable in a result. This asserts the instrument reaches the corpus.
    """
    found = { key: _stated_fallback( key ) for key, _ in FALLBACK_PAIRS }
    missing = [ key for key, value in found.items() if value is None ]
    assert not missing, (
        f"the splainer names no in-code fallback for {missing} — this guard did not fail, "
        f"it was unable to look. Either the entry lost its sentence or the phrase changed."
    )


def test_the_extractor_returns_None_for_a_key_that_has_no_such_sentence():
    """
    THE DISCRIMINATING HALF. Without it, `_stated_fallback` could be returning the same
    value for everything and the arms above would still be green.
    """
    assert _stated_fallback( "a key no splainer entry will ever begin with" ) is None


def test_the_asynchronous_flag_falls_back_CLOSED_which_is_what_the_prose_promises():
    """
    ⚠️ A SEPARATE CLAIM FROM AGREEMENT, deliberately. The arms above prove the prose and
    the constant say the same thing; they would both be green if both said True. This
    pins the VALUE, because fail-closed here is a ruling and not an implementation
    detail: an absent config must not start handing out a status code existing callers
    misread as success.
    """
    assert gate.FALLBACK_ASYNCHRONOUS is False
