#!/usr/bin/env python3
"""
THE UI'S VERB VOCABULARY AND THE STORE'S STATUS VOCABULARY, BOUND BY CONSTRUCTION.

Row 8af64f5a (P0). The row control offers five verbs; each one posts a STATUS the
store has to accept. Those two vocabularies live in two languages and two files —
`shared/task-verbs.js` and `cosa/rest/task_store_rules.py` — and until this guard
existed nothing checked that they agreed.

⇒ THEY DID AGREE. They agreed by COINCIDENCE, not by construction, which is the
shape this crew has been bitten by repeatedly: `manager_refusal`'s own comment names
it, and `authenticated_user_id` and `_resolve_project_from_bridge_cwd` are the same
disease. Two derivations of one fact that happen to land on the same value are not
agreeing — they are coinciding, and the day the inputs diverge is the day you find
out.

WHAT THIS FILE IS *NOT*. It is not the pane walk. That guard
(`every_pane_offers_and_routes_every_verb.test.ts`) asks whether each PANE offers and
routes each verb, and takes its oracle from the same JS module this file reads. This
one asks a different question — whether the verbs the UI speaks are words the STORE
knows — and the two must not be folded together: a UI that offers every verb
correctly can still post a status the store rejects, and a UI missing a verb entirely
can still have a perfectly consistent status map.

🔴 WHY THE VERB LIST IS NOT IN `task_store_rules.py`. It was proposed there as the
single source of truth. It cannot live there and satisfy the condition that made the
proposal worth making: NOTHING IN PYTHON CONSUMES A VERB LIST. Measured 2026-09-04 —
the store knows STATUSES (`VALID_STATUSES`, 10) and TRANSITIONS
(`LEGAL_TRANSITIONS`); the verbs are a UI concept, and every consumer of them is
JavaScript. A constant added to the Python module would have had zero Python readers
and would have been exactly the parallel copy the proposal was trying to prevent, one
file to the left. So the list lives where it is CONSUMED, and this file is the seam
that binds it to the store's authority.

Requires:
    - `src/lupin_app/static/js/shared/task-verbs.js` is present and parseable
    - `cosa.rest.task_store_rules` is importable

Ensures:
    - every verb's target status is a status the store accepts
    - the two-click arming policy is pinned against the store's TERMINAL_STATUSES
    - park's offered-from set is EXACTLY the store's PARK_LEGAL_FROM_STATUSES
    - every status named in any `legalFrom` / `illegalFrom` is a real store status
    - the corpus is EXACTLY the expected membership, so neither an empty parse nor a
      renamed verb can pass as agreement
"""

import json
import re

import pytest

import cosa.utils.util as cu
from cosa.rest.task_store_rules import (
    PARK_LEGAL_FROM_STATUSES,
    TERMINAL_STATUSES,
    VALID_STATUSES,
)

VERBS_JS = cu.get_project_root() + "/src/lupin_app/static/js/shared/task-verbs.js"

# 🔴 HAND-WRITTEN MEMBERSHIP, NOT A COUNT — and the difference is MEASURED, not argued.
# A floor catches a corpus that SHRINKS. It does not catch one that changes IDENTITY.
# Measured 2026-09-04, renaming `demote` to `sendback` in the module AND in the cell so
# the two stayed consistent: the 15-cell pane walk reported 31/31 GREEN and this file
# reported 5/5 GREEN. A verb had vanished from the operator's reach and every derived
# guard agreed with the change — because every one of them takes its corpus from the
# file that changed.
#
# ⇒ ONE SIDE OF ONE COMPARISON MUST BE SOMETHING THE CLIENT CANNOT EDIT. This is it.
# Adding a verb SHOULD redden this line: that is the review step, not a nuisance.
# 🔴 DO NOT "DE-DUPLICATE" THIS LIST — the duplication IS the control. See the block
# above: an imported or parsed corpus moves with the module and cannot see a rename.
EXPECTED_VERBS   = ( "park", "drop", "demote", "wont_fix", "approve" )
KNOWN_VERB_FLOOR = len( EXPECTED_VERBS )


def _parse_verb_specs():
    """
    Read the shipped verb vocabulary out of the JS module.

    🔴 IT PARSES THE SHIPPED FILE RATHER THAN RESTATING IT. A hand-copied table here
    would be a THIRD derivation of the same list, which is the defect this guard
    exists to catch, committed by the guard itself.

    The module is plain data with JS-flavoured syntax (unquoted keys, trailing
    commentary), so it is normalised into JSON rather than executed — running a JS
    file from a Python test would need a node subprocess and would fail for reasons
    that have nothing to do with the vocabulary.

    Ensures:
        - returns { verb: spec-dict } for every entry in TASK_VERB_SPECS
        - raises AssertionError naming the file when the block cannot be located,
          so a rename fails LOUDLY instead of yielding an empty dict
    """
    source = open( VERBS_JS, encoding="utf-8" ).read()

    start = source.find( "export const TASK_VERB_SPECS = {" )
    assert start >= 0, (
        f"TASK_VERB_SPECS was not found in {VERBS_JS}. The module was renamed, moved "
        f"or restructured — this guard cannot speak to a file it cannot find, and is "
        f"failing rather than reporting an empty vocabulary as agreement."
    )
    brace = source.index( "{", start )

    depth, end = 0, None
    for i in range( brace, len( source ) ):
        if   source[ i ] == "{": depth += 1
        elif source[ i ] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    assert end is not None, f"unbalanced braces in TASK_VERB_SPECS in {VERBS_JS}"

    block = source[ brace:end ]
    block = re.sub( r"//[^\n]*", "", block )                       # line comments
    block = re.sub( r"(\w+)\s*:", r'"\1":', block )                # unquoted keys
    block = re.sub( r",(\s*[}\]])", r"\1", block )                 # trailing commas
    return json.loads( block )


@pytest.fixture( scope="module" )
def specs():
    return _parse_verb_specs()


def test_the_parse_finds_exactly_the_expected_vocabulary( specs ):
    """
    POSITIVE CONTROL AND MEMBERSHIP CHECK, and it earns its place twice over.

    Every other test in this file loops over `specs`. An empty parse would make all of
    them pass without asserting anything, and this file would report a confident green
    while measuring nothing — the empty-loop defect.

    🔴 AND MEMBERSHIP, NOT MERELY SIZE. A count is satisfied by a RENAME, and a rename is
    a verb disappearing from the operator's reach with the arithmetic undisturbed. The
    measurement is beside EXPECTED_VERBS: one renamed verb left both derived guards fully
    green.
    """
    assert len( specs ) >= KNOWN_VERB_FLOOR, (
        f"parsed {len( specs )} verbs from {VERBS_JS}, expected at least "
        f"{KNOWN_VERB_FLOOR}. Either the module shrank — in which case a verb was "
        f"removed and that is the finding — or the parse broke. Both are red."
    )
    assert set( specs ) == set( EXPECTED_VERBS ), (
        f"the shipped vocabulary is {sorted( specs )} and this test expects "
        f"{sorted( EXPECTED_VERBS )}.\n"
        f"  · a verb ADDED is the intended workflow — extend EXPECTED_VERBS and every "
        f"per-verb check below starts covering it\n"
        f"  · a verb RENAMED or REMOVED is what this assertion exists for: no guard that "
        f"derives its corpus from this module can see it"
    )
    for verb, spec in specs.items():
        assert spec.get( "status" ), f"verb {verb!r} carries no target status"


def test_every_verb_posts_a_status_the_store_accepts( specs ):
    """
    The seam itself. A verb posting a status outside VALID_STATUSES is a 422 the
    operator meets at the moment they click, with a correct-looking control.
    """
    for verb, spec in specs.items():
        assert spec[ "status" ] in VALID_STATUSES, (
            f"the UI verb {verb!r} posts status {spec['status']!r}, which the store "
            f"does not accept. Store statuses: {sorted( VALID_STATUSES )}"
        )


def test_the_two_click_arming_policy_is_pinned_against_the_store( specs ):
    """
    🔴 THIS TEST FIRST ASSERTED AN EQUIVALENCE THAT IS FALSE, AND THE RED WAS THE
    GUARD'S FAULT RATHER THAN THE PRODUCT'S. The JS field was called `terminal`, so the
    obvious assertion was `spec.terminal == (status in TERMINAL_STATUSES)`. It fails on
    `drop`: `dropped` IS terminal in the store, and Drop commits on ONE click. The field
    never meant "the target status is terminal" — it means "Submit arms first" — and a
    name that asserts a store fact it does not carry is how a correct control gets
    reported as broken. The field is now `armsTwice`; this test asserts what is true.

    ⚠️ AND IT PINS A POLICY RATHER THAN JUDGING IT. Two verbs post terminal statuses and
    only one of them asks twice. Whether Drop should also arm is Rick's call, not this
    file's — it is irreversible in the store exactly as won't-fix is. Pinned so that
    changing the policy is a deliberate edit here, and so that an accidental change
    reddens.
    """
    arming   = { v for v, spec in specs.items() if spec.get( "armsTwice" ) }
    terminal = { v for v, spec in specs.items() if spec[ "status" ] in TERMINAL_STATUSES }

    assert arming <= terminal, (
        f"verbs {sorted( arming - terminal )} ask for a second click but do not close the "
        f"row. Confirmation is for irreversibility; asking twice for a reversible move "
        f"teaches the operator to click through it."
    )
    assert arming == { "wont_fix" }, (
        f"the arming set is {sorted( arming )}, and the policy pinned here is "
        f"{{'wont_fix'}}. If this is a deliberate change, edit this assertion and say so "
        f"— it is a product decision about which irreversible moves ask twice."
    )
    assert terminal == { "drop", "wont_fix" }, (
        f"the verbs posting terminal statuses are now {sorted( terminal )}. The arming "
        f"policy above was ruled against {{'drop', 'wont_fix'}}; a new terminal verb "
        f"needs that ruling extended rather than inherited silently."
    )


def test_park_is_offered_from_exactly_the_statuses_the_store_allows( specs ):
    """
    🔴 THE ONE VERB WHERE THE STORE PUBLISHES ITS OWN LEGALITY, so it is the one place
    the two sides can be compared directly rather than inferred. Offering park from a
    status the store refuses produces a 422 the operator cannot act on — which is the
    exact failure the spec's Amendment 6 asked to prevent by greying the control.
    """
    offered = tuple( specs[ "park" ].get( "legalFrom" ) or () )
    assert offered == tuple( PARK_LEGAL_FROM_STATUSES ), (
        f"the UI offers park from {offered} and the store allows it from "
        f"{tuple( PARK_LEGAL_FROM_STATUSES )}. These agreed by coincidence until this "
        f"guard existed; they must agree by construction."
    )


def test_every_status_named_in_a_legality_list_is_a_real_store_status( specs ):
    """
    A typo in `legalFrom` does not fail anywhere — it silently makes a verb unreachable
    (whitelist) or always-offered (blacklist), which reads as a design decision.
    """
    for verb, spec in specs.items():
        for field in ( "legalFrom", "illegalFrom" ):
            for status in ( spec.get( field ) or () ):
                assert status in VALID_STATUSES, (
                    f"verb {verb!r} names status {status!r} in {field}, which is not a "
                    f"store status. A misspelling here changes what the control offers "
                    f"and fails nowhere else."
                )
