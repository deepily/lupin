#!/usr/bin/env python3
"""
ONE BOOLEAN PARSER IN `task_approval_settings`, ENFORCED BY PREDICATE.

🔨 MR. RADIO 🦉, 2026-09-08: "One reader. Every surface on it. `_as_bool_or_none`, no
exceptions. Write the PREDICATE, not the enumeration. The guard must catch a FIFTH
surface appearing next month, not the four you found."

WHY THIS IS A GUARD AND NOT A PARAGRAPH. The module has been bitten three times by the
same defect and each time the remedy was a sentence naming the current offenders:

    e98659d2  fixed `get_enforcement_active`, and its own docstring then said the
              defect was "live TODAY in get_enforcement_active" — a sentence that
              became false the moment it shipped and was never re-aimed
    2026-09-08 the REAL live instance turned out to be `default_mint_status`, 140 lines
              away, which no note mentioned at all

⇒ A prose pointer at a defect goes stale the moment somebody fixes it, and NOTHING
REDDENS WHEN IT DOES. A predicate over the module's own syntax cannot go stale that
way: it does not know which functions exist today, so a function written next month is
inside its population automatically.

WHAT IT FORBIDS: any function in the module — except the one parser — coercing with
`bool( ... )`, or testing membership against boolean words. Both are how the three live
instances were written.

⚠️ WHAT IT CANNOT SEE, said rather than left for somebody to discover. It reads SYNTAX,
so a fifth surface that parses booleans some other way — `str( raw )[ 0 ] == "t"`, a
regex, a dict lookup — passes it. It is a guard against the shape this module keeps
producing, not a proof that no coercion exists. The denominator is stated in
`test_the_denominator_is_stated_out_loud` so a reader knows what was swept.
"""
import ast
import os
import pathlib
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.rest.task_approval_settings as approval


# The one function permitted to parse a boolean. Everything else must delegate to it.
THE_ONE_PARSER = "_as_bool_or_none"

# Words that only ever appear in a boolean parse. Kept here rather than imported from
# the module so that widening the module's own TRUE_WORDS cannot silently widen what
# this guard tolerates.
BOOLEAN_WORDS = { "true", "false", "yes", "no", "on", "off", "1", "0" }

# 🔴 AND THE NAMED CONSTANTS, WHICH IS THE HOLE THE FIRST VERSION OF THIS GUARD HAD.
# It keyed on LITERAL tuples only, so a fifth surface written `raw in TRUE_WORDS` — the
# most likely way somebody writes it, because the constants are sitting right there —
# evaded it completely. Caught with a planted probe before this file shipped; the probe
# survives as `test_the_predicate_catches_a_planted_fifth_surface`.
BOOLEAN_WORD_CONSTANTS = { "TRUE_WORDS", "FALSE_WORDS" }


def _boolean_parses_in( fn ):
    """
    Every boolean parse-or-coerce a function performs ITSELF.

    Requires:
        - fn is an ast.FunctionDef / ast.AsyncFunctionDef

    Ensures:
        - returns a list of ( lineno, description ) for each offence found
        - returns [ ] for a function that delegates its parsing
        - counts a `bool( ... )` call, a membership test against a literal collection
          containing a boolean word, and a membership test against TRUE_WORDS /
          FALSE_WORDS by name
    """
    hits = [ ]
    for node in ast.walk( fn ):
        if isinstance( node, ast.Call ) and isinstance( node.func, ast.Name ) \
           and node.func.id == "bool":
            hits.append( ( node.lineno, "bool() coercion" ) )

        if isinstance( node, ast.Compare ) and any( isinstance( op, ast.In ) for op in node.ops ):
            for comparator in node.comparators:
                if isinstance( comparator, ast.Name ) and comparator.id in BOOLEAN_WORD_CONSTANTS:
                    hits.append( ( node.lineno, f"membership test against {comparator.id}" ) )
                if isinstance( comparator, ( ast.Tuple, ast.List, ast.Set ) ):
                    literals = { element.value.lower() for element in comparator.elts
                                 if isinstance( element, ast.Constant )
                                 and isinstance( element.value, str ) }
                    if literals & BOOLEAN_WORDS:
                        hits.append( ( node.lineno,
                                       f"membership test against {sorted( literals )}" ) )
    return hits


def _module_functions():
    """
    Every function defined in `task_approval_settings`, read from its source.

    Ensures:
        - returns a list of ast function nodes
        - reads the file the imported module was loaded from, so this cannot drift onto
          a different checkout's copy the way a hardcoded path would
    """
    source = pathlib.Path( approval.__file__ ).read_text()
    return [ node for node in ast.walk( ast.parse( source ) )
             if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) ]


def test_no_function_parses_a_boolean_except_the_one_that_is_allowed_to():
    """
    THE GUARD. A fifth surface written next month reddens this by name.
    """
    offenders = { }
    for fn in _module_functions():
        if fn.name == THE_ONE_PARSER: continue
        hits = _boolean_parses_in( fn )
        if hits: offenders[ fn.name ] = hits

    assert offenders == { }, (
        f"these functions parse a boolean themselves instead of calling "
        f"{THE_ONE_PARSER}: {offenders}. Three separate hand-rolled parses in this "
        f"module drifted apart and produced the `bool( \"false\" )` defect twice — "
        f"`bool( \"false\" )` is True, so a falsy STRING switches a gate ON. Delegate "
        f"to {THE_ONE_PARSER}, which returns None for a value it cannot parse so the "
        f"caller's own fallback decides rather than a coercion."
    )


def test_the_one_parser_actually_exists_and_is_what_the_module_uses():
    """
    THE POSITIVE CONTROL FOR THE GUARD ABOVE, and it is not ceremony.

    A guard that asserts an empty set passes vacuously if the parser were renamed or
    deleted — every function would then be "not the one parser", find nothing, and the
    suite would stay green over a module with no parser at all.
    """
    assert callable( getattr( approval, THE_ONE_PARSER, None ) ), (
        f"{THE_ONE_PARSER} is gone. The guard above would still pass, having checked "
        f"every function against a rule with no subject."
    )

    callers = [ fn.name for fn in _module_functions()
                if fn.name != THE_ONE_PARSER
                and any( isinstance( n, ast.Call ) and isinstance( n.func, ast.Name )
                         and n.func.id == THE_ONE_PARSER for n in ast.walk( fn ) ) ]
    assert len( callers ) >= 3, (
        f"only {callers} delegate to {THE_ONE_PARSER}. Three boolean settings exist "
        f"(enforcement_active, default_to_holding, manager_pull_disabled); if fewer "
        f"than three readers call the parser, one of them is parsing its own."
    )


@pytest.mark.parametrize( "planted, why", [
    ( "def a_fifth_surface():\n    return bool( raw )",
      "the bare coercion — how default_mint_status was written" ),
    ( 'def a_fifth_surface():\n    return raw in ( "true", "1", "yes", "on" )',
      "the literal membership test — how get_enforcement_active was written" ),
    ( "def a_fifth_surface():\n    return raw in TRUE_WORDS",
      "the NAMED constant — the hole the first version of this guard had" ),
] )
def test_the_predicate_catches_a_planted_fifth_surface( planted, why ):
    """
    PROVE THE INSTRUMENT. A guard reporting an empty set is worth nothing until it has
    been watched returning a non-empty one.

    🔴 THE THIRD ARM IS THE ONE THAT MATTERS AND IT IS WHY THIS TEST EXISTS. The first
    version of `_boolean_parses_in` keyed on literal collections only, so `raw in
    TRUE_WORDS` — using the constants already in the module, which is the most natural
    way to write it — sailed straight through. The guard looked correct, passed its own
    review, and had a hole exactly where a future author would step.
    """
    fn = ast.parse( planted ).body[ 0 ]
    assert _boolean_parses_in( fn ), (
        f"the predicate did not catch {why}. A guard that cannot see the shape it was "
        f"written for is a green test over an open hole."
    )


def test_a_delegating_reader_is_NOT_flagged():
    """
    THE NEGATIVE CONTROL. A guard that fires on everything discriminates nothing — it
    would redden the correct fix as loudly as the defect and teach the next author to
    delete it.
    """
    fn = ast.parse(
        'def a_correct_reader():\n'
        '    return _as_bool_or_none( raw, "override file" )'
    ).body[ 0 ]
    assert _boolean_parses_in( fn ) == [ ], (
        "the predicate flagged a reader that correctly delegates. It must accept the "
        "fix, or it is not a guard, it is noise."
    )


def test_the_denominator_is_stated_out_loud():
    """
    HOW MANY SURFACES EXIST, HOW MANY WERE SWEPT, AND HOW THEY WERE COUNTED.

    🔨 Mr. Radio's instruction: "say the denominator out loud — how many surfaces
    exist, how many you swept, how you counted them."

    The population is EVERY function in the module, derived from the module's own AST
    rather than from a list somebody maintains. That is the whole point: a list of four
    names cannot notice a fifth, and this cannot fail to.
    """
    functions = _module_functions()

    assert len( functions ) >= 17, (
        f"the module has {len( functions )} functions; it had 17 when this guard was "
        f"written and functions are not expected to vanish. If they did, this guard's "
        f"population shrank and it is reporting on less than it claims."
    )

    booleans_swept = [ fn.name for fn in functions
                       if any( isinstance( n, ast.Call ) and isinstance( n.func, ast.Name )
                               and n.func.id == THE_ONE_PARSER for n in ast.walk( fn ) ) ]

    # The three boolean SETTINGS this module reads. Written out because the count is the
    # claim: three settings, three delegating readers, zero hand-rolled parses.
    assert set( booleans_swept ) >= {
        "get_enforcement_active", "default_mint_status", "get_manager_pull_disabled",
    }, (
        f"expected all three boolean readers to delegate; only {booleans_swept} do."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NO REFUSAL MESSAGE PRESCRIBES THE UNSANCTIONED PATH
# ═══════════════════════════════════════════════════════════════════════════════
#
# 🔨 MR. RADIO 🦉, 2026-09-08, and his framing is sharper than mine: "the defect is that
# the refusal for the unsanctioned path PRESCRIBES the unsanctioned path."
#
# `refusal_for_pull` told a caller to "clear manager_pull_disabled in <path>" — a rule
# teaching its own bypass. THREE functions did it, not the one I was pointed at, and I
# found the other two only by asking the predicate rather than grepping the one I knew.
#
# 🔴 AND THIS GUARD EXISTS BECAUSE ITS ABSENCE WAS MEASURED, NOT SUSPECTED. Mutation arm
# M11 — put the path back into the message — SURVIVED the whole 159-test suite. Ten
# other arms died; this one walked. I had fixed three messages and guarded none of them,
# which is precisely the "green suite over a deleted guard is the finding, not the fix"
# shape. The arm now kills.


def _refusal_builders():
    """
    Every function whose job is to build a refusal message.

    By PREDICATE — any `refusal_for_*` — so a fourth refusal written next month is
    inside this guard's population without anybody adding it to a list.
    """
    return [ fn for fn in _module_functions() if fn.name.startswith( "refusal_for" ) ]


def test_there_ARE_refusal_builders_to_check():
    """
    THE POSITIVE CONTROL. A predicate that matches nothing passes every assertion in
    the loop below it — the empty-population defect, which is the one failure mode a
    guard cannot report on itself.
    """
    names = [ fn.name for fn in _refusal_builders() ]
    assert len( names ) >= 3, (
        f"only found {names}. This guard reports on the functions it can see; if the "
        f"naming convention moved, it is guarding nothing and saying so cheerfully."
    )


def test_no_refusal_message_tells_the_caller_to_EDIT_THE_FILE():
    """
    THE GUARD. A refusal must name the DOOR, never the file it is protecting.

    ⚠️ AND IT MUST NAME THE PATH AT ALL, not merely name it wrongly. `override_path()`
    is evaluated ON THE SERVER, which runs in a container with LUPIN_ROOT=/var/lupin —
    so it truthfully names a filesystem the reader cannot reach. Correct AND unreachable
    is worse than wrong: a host reader follows it, finds nothing, and concludes the file
    is missing.
    """
    offenders = { }
    for fn in _refusal_builders():
        hits = [ node.lineno for node in ast.walk( fn )
                 if isinstance( node, ast.Call ) and isinstance( node.func, ast.Name )
                 and node.func.id == "override_path" ]
        if hits: offenders[ fn.name ] = hits

    assert offenders == { }, (
        f"these refusal messages name the settings file: {offenders}. A refusal for the "
        f"unsanctioned path must not PRESCRIBE the unsanctioned path — name the "
        f"endpoint instead. The path is also evaluated on the SERVER, so it names a "
        f"container filesystem the reader cannot reach."
    )


def _refusal_from( builder, monkeypatch ):
    """
    Drive one named builder into ACTUALLY REFUSING, and return its message.

    🔴 THE WINDOW MUST BE FORCED ON FOR THE BATCH ARM, and discovering that is the whole
    reason this helper exists. `refusal_for_batch` returns None when the admission window
    is 0 — which is the default. My first version of this test called it with plausible
    arguments, got None, and would have asserted `"...json" not in None`.

    ⇒ It failed loudly with a TypeError, which is the lucky outcome. Had I written the
    assertion defensively — `if message:` — the arm would have PASSED over a builder it
    never made speak, and the file-path guard for batch would have been decorative. An
    empty result and a clean result are the same shape; this helper's job is to make the
    difference impossible to miss.
    """
    if builder == "refusal_for_pull":
        return approval.refusal_for_pull( "queued", "in_progress", "somebody" )
    if builder == "refusal_for_admission":
        return approval.refusal_for_admission( "not_approved", "queued", "somebody" )
    if builder == "refusal_for_batch":
        monkeypatch.setattr( approval, "get_admission_window_seconds", lambda: 300 )
        return approval.refusal_for_batch( "somebody", None, 99 )
    raise AssertionError( f"no driver for {builder}" )


@pytest.mark.parametrize( "builder", [
    "refusal_for_pull", "refusal_for_admission", "refusal_for_batch",
] )
def test_EACH_refusal_builder_BY_NAME_does_not_prescribe_the_file( builder, monkeypatch ):
    """
    🔨 MR. RADIO 🦉, 2026-09-08: "Assert on each of refusal_for_pull /
    refusal_for_admission / refusal_for_batch BY NAME, at the function, not through a
    router."

    🔴 AND HE IS CORRECTING A REAL WEAKNESS IN MY FIRST ATTEMPT AT THIS GUARD. My
    original refusal test read the 403 detail from the NEW endpoint — a message that was
    never the defect. It could not have failed for the right reason, which is why arm
    M11 walked through it.

    ⇒ Three builders, three named arms, called DIRECTLY. A router can be unwired, can
    stop being reached, or can wrap the message; asserting at the function removes every
    one of those from between the test and its subject. And a parametrized arm NAMES the
    offender in its own id, so a failing set says WHICH message regressed rather than
    that some message did.
    """
    message = _refusal_from( builder, monkeypatch )

    # THE POSITIVE CONTROL, and it is the one this arm already needed once: a builder
    # that returns None asserts nothing at all, and `not in None` is the only reason
    # that showed up as a failure rather than as a pass.
    assert message, (
        f"{builder} did not refuse, so this arm measured nothing. Drive it into the "
        f"refusing branch or the assertions below are vacuous."
    )

    assert "task-approval-settings.json" not in message, (
        f"{builder} names the settings file. A refusal for the unsanctioned path must "
        f"not PRESCRIBE the unsanctioned path."
    )
    assert "/var/lupin" not in message, (
        f"{builder} names a container filesystem the reader cannot reach — "
        f"`override_path()` is evaluated on the SERVER. Correct and unreachable is "
        f"worse than wrong: a host reader follows it, finds nothing, and concludes the "
        f"file is missing."
    )


def test_the_pull_refusal_names_the_DOOR( monkeypatch ):
    """
    The behavioural half. The predicate above sees SYNTAX; this reads the message a
    caller actually gets, so a path reintroduced as a literal string is caught too.
    """
    message = approval.refusal_for_pull( "queued", "in_progress", "somebody" )
    assert "task-approval-settings.json" not in message
    assert "/var/lupin"                   not in message
    assert "/api/tasks/approval-settings" in message, (
        "the refusal does not tell the caller where the sanctioned door IS. A refusal "
        "with no way forward sends people to the file by default."
    )
