#!/usr/bin/env python3
"""
`get_approver_accounts` PARSES THE INI FORM, AND ITS SKIP CONTRACT WAS UNGUARDED.

🔴 HOW THIS WAS FOUND — a coverage reading, not a hunch. After the settings stamp landed
(`e121b4c6`) the module measured 270 statements with **0 missed lines** and 132 branches
with **3 partial**, all three inside this one function:

    442->441   the `continue` on an INI entry with no `=`
    448->447   the `continue` on a non-string email or persona
    450->447   the `continue` on a blank email or persona

⇒ Every line ran; not one of the three SKIPS ever did. That is the third state — the code
is right and no test could see it break. The function's own docstring promises exactly
this behaviour:

    "INI form is comma-separated `email = persona` pairs; an entry missing its `=`, or
     blank on either side, is SKIPPED rather than raising — a typo in one pair must not
     take the whole map, and with it the browser's door, down"

⇒ A documented contract with no guard. Delete any of the three `continue`s and the map
either raises or silently gains a junk entry, and the whole suite stays green.

⚠️ WHY THAT MATTERS MORE THAN IT LOOKS. This map is the BROWSER'S door: it is what turns a
validated login account into an approver persona. A `ValueError` here does not degrade the
feature, it takes the approval gate down for everybody — from one typo in one INI pair.

⚠️ THE THREE PARTIALS ARE NOT MINE. They pre-date my work, from the commit that added the
account door. Named rather than absorbed, and closed here because the 100% mandate is
Lupin-wide and the debt is real whoever booked it.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval


@pytest.fixture
def ini( monkeypatch ):
    """
    Drive the INI layer with no override file in play.

    🔴 THE OVERRIDE MUST BE STOOD DOWN OR THESE ARMS MEASURE NOTHING. `approver_accounts`
    from the override file WINS, and when it is a dict the INI branch never executes — so
    an arm that forgot this would exercise `list( raw.items() )` while its name claimed to
    be testing the comma-split parser.
    """
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "approver_accounts": None } )

    def _set( text ):
        monkeypatch.setattr( approval, "_ini_value", lambda key, rt, fb: text )
    return _set


def test_the_INI_PARSER_IS_REACHED_AT_ALL( ini ):
    """
    🔴 THE POSITIVE CONTROL, FIRST. Every arm below asserts something is ABSENT from the
    map, and absence is exactly what a parser that never ran also produces. This one
    proves a well-formed pair DOES land, so the omissions below mean something.
    """
    ini( "rick@example.com = Rick" )
    assert approval.get_approver_accounts() == { "rick@example.com": "rick" }


def test_an_entry_with_NO_EQUALS_is_skipped_and_the_others_survive( ini ):
    """
    Closes branch `442->441`.

    ⚠️ THE GOOD PAIR IS THE POINT, not decoration. Asserting only that the junk is absent
    would pass against a parser that returned `{}` for the whole string — which is the
    failure this contract exists to prevent. The map must lose the typo and keep the rest.
    """
    ini( "rick@example.com = Rick, this-entry-has-no-equals-sign, maya@example.com = Maya" )

    accounts = approval.get_approver_accounts()
    assert accounts == { "rick@example.com": "rick", "maya@example.com": "maya" }, (
        "one malformed pair changed the rest of the map — a typo took the browser's "
        "approver door down with it"
    )


@pytest.mark.parametrize( "text,why", [
    ( "= Rick",                        "an empty email is not an address"        ),
    ( "rick@example.com =",            "an empty persona names nobody"           ),
    ( "   =   ",                       "whitespace on both sides is still blank" ),
    ( "rick@example.com =    ",        "a whitespace-only persona is blank"      ),
] )
def test_a_BLANK_side_is_skipped_rather_than_stored( ini, text, why ):
    """
    Closes branch `450->447`.

    A blank key or value satisfies a presence check while naming nobody — and an entry
    mapping `""` to a persona is worse than absent, because a caller with no account
    email would match it.
    """
    ini( f"maya@example.com = Maya, {text}" )

    accounts = approval.get_approver_accounts()
    assert accounts == { "maya@example.com": "maya" }, why
    assert "" not in accounts, "a blank email became a key — an empty account now matches"


def test_a_NON_STRING_pair_from_the_OVERRIDE_FILE_is_skipped( monkeypatch ):
    """
    Closes branch `448->447`, and it is reachable only from the OVERRIDE path — the INI
    branch splits a string, so both halves are strings by construction there.

    ⚠️ SO THIS ARM DELIBERATELY DOES NOT USE THE `ini` FIXTURE. A JSON object can hold any
    value at all, which is precisely why the guard exists: `{"a@b.c": 7}` is valid JSON and
    `7.strip()` is an AttributeError that would take the map, and the approval gate, down.
    """
    monkeypatch.setattr( approval, "_read_overrides", lambda: { "approver_accounts": {
        "rick@example.com": "Rick",     # the control — a good pair must survive
        "maya@example.com": 7,          # non-string persona
        99                : "Maya",     # non-string email
    } } )

    accounts = approval.get_approver_accounts()
    assert accounts == { "rick@example.com": "rick" }, (
        "a non-string pair either raised or was stored — the override file can hold any "
        "JSON value, so neither is acceptable"
    )


def test_an_ENTIRELY_MALFORMED_ini_yields_an_EMPTY_MAP_and_never_raises( ini ):
    """
    The edge where every pair is junk. It must return `{}` — the documented unconfigured
    answer — rather than raising, because a settings typo must never be able to take the
    browser's approver door down.
    """
    ini( "nonsense, more nonsense, = , " )
    assert approval.get_approver_accounts() == { }
