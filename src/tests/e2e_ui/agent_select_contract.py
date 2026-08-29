"""
The `#agent-mode` select contract — ONE predicate, shared by the live E2E guards
and their committed must-fail control.

WHY THIS EXISTS (Tiberius, 2026-08-22, Mr Radio's word). Five tests touched that
select and three of them could not fail:

    test_qa_submission.py:54        assert options.count() >= 2
    test_qa_submission.py:176-180   if mode_select.is_visible():
                                        if options.count() >= 2:
                                            ...
    test_notifications_sections.py  assert ...count() > 0

A count over a list is not a gate — the retirement plan's own §6 disqualifies that
shape in as many words, and the two `if` wrappers are worse than the count: they
turn "the select did not render" into a SKIP that reports green. That matters right
now because phase 3 of the Q&A-card work makes this select JS-populated from
`GET /api/v2/agents`. If that endpoint 500s or the render throws, the select comes
back EMPTY — and all three assertions above pass. The safety net had a hole shaped
exactly like the change it was meant to catch.

THE ORACLE MOVES, AND THE PREDICATE MAKES IT MOVE. Before phase 3 the checked-in
`<option>` values in notifications.html ARE the source of truth, so the live guard
compares the rendered DOM against the file on disk — a real boundary (browser vs
tree), not a count derived from the thing it checks. Phase 3 empties that file, and
`ORACLE EMPTY` below fires the moment it does: the guard goes RED until whoever
lands phase 3 repoints `expected` at the registry's `USER_INITIABLE_COMMANDS`. The
sequencing enforces itself instead of relying on somebody remembering.

NOTE THE EMPTY-vs-EMPTY TRAP, which is the whole reason `ORACLE EMPTY` is an arm
and not an assumption: an emptied HTML file yields `expected == set()`, an errored
endpoint yields `rendered == set()`, and set-equality between them PASSES. A
set-equality gate with a silently-empty oracle is a green suite bought by weakening
an assertion — the exact failure mode this work was warned about. So the predicate
refuses an empty oracle before it ever compares.

Falsifiability: `src/tests/unit/test_agent_select_contract_control.py` drives THIS
function — never a parallel re-implementation — and each arm is seen RED on a
synthetic input.
"""

import re

import cosa.utils.util as cu

NOTIFICATIONS_HTML = "/src/lupin_app/static/html/notifications.html"

# Auto-Route is a rendered option with a sentinel value, NOT a registry command and
# NOT an exemption (Clayton, 2026-08-22): a waiver that can never go stale, sitting
# in a table whose credibility rests on waivers expiring, is the widening vector
# rather than the control. A sentinel leaves nothing to exempt.
AUTO_ROUTE_SENTINEL = "__auto_route__"


def checked_in_option_values():
    """
    The `<option value=...>` strings inside `#agent-mode` AS CHECKED IN.

    Read from SOURCE rather than from a live page, so this is an oracle the browser
    cannot influence — the same reason the registry drift guard reads the tree
    instead of importing a live object.

    Ensures:
        - returns a set of the option values found between `id="agent-mode"` and the
          closing `</select>`
        - returns an EMPTY set once phase 3 removes the hardcoded options, which is
          what makes `option_value_drift` fire ORACLE EMPTY and force the repoint
    """
    text  = cu.get_file_as_string( cu.get_project_root() + NOTIFICATIONS_HTML )
    start = text.find( 'id="agent-mode"' )
    if start == -1: return set()
    end   = text.find( "</select>", start )
    if end == -1: return set()
    return set( re.findall( r'<option\s+value="([^"]*)"', text[ start:end ] ) )


def expected_option_values():
    """
    THE ORACLE, AFTER PHASE 3: the registry's user-initiable set plus the Auto-Route
    sentinel — exactly what `#agent-mode` must render.

    This replaced `checked_in_option_values()` on 2026-08-22, and the handover was
    FORCED rather than remembered: phase 3 emptied the hardcoded options out of
    notifications.html, `checked_in_option_values()` started returning an empty set,
    and `option_value_drift`'s ORACLE EMPTY arm refused to compare. The guards went
    red until this function existed. That was the design.

    Auto-Route is included as a SENTINEL rather than exempted (Clayton, 2026-08-22):
    a waiver that can never go stale, sitting in a table whose credibility rests on
    waivers expiring, is a widening vector. A sentinel leaves nothing to exempt.

    Ensures:
        - returns USER_INITIABLE_COMMANDS | { AUTO_ROUTE_VALUE }
        - reads the registry, so it crosses a real boundary against a rendered DOM
    """
    from cosa.rest.v2.registry import AUTO_ROUTE_VALUE, USER_INITIABLE_COMMANDS
    return set( USER_INITIABLE_COMMANDS ) | { AUTO_ROUTE_VALUE }


def option_value_drift( rendered, expected ):
    """
    Problems with the option values a page actually rendered. Empty list ⇒ clean.

    Requires:
        - rendered is an iterable of the `value` attributes read off the live select
        - expected is the set the select is supposed to show (checked-in options
          today; `USER_INITIABLE_COMMANDS` once phase 3 lands)

    Ensures:
        - ORACLE EMPTY when expected is empty — refuses to compare rather than pass
          an empty-vs-empty equality
        - NO OPTIONS when the select rendered nothing, stated separately so the
          phase-3 failure mode reads as itself in the failure text
        - BLANK VALUE for any option carrying an empty/whitespace value, which a
          set-equality alone would silently absorb
        - MISSING / PHANTOM for each side of the set difference
    """
    problems = []
    rendered_list = [ v for v in rendered ]
    expected_set  = set( expected )

    if not expected_set:
        problems.append(
            "ORACLE EMPTY: the expected set is empty, so this comparison cannot fail. "
            "If phase 3 has removed the hardcoded options from notifications.html, "
            "repoint `expected` at the registry's USER_INITIABLE_COMMANDS."
        )

    if not rendered_list:
        problems.append(
            "NO OPTIONS: the select rendered nothing. This is the phase-3 failure "
            "mode (endpoint error or a throwing render), never a pass."
        )

    for value in rendered_list:
        if value is None or not str( value ).strip():
            problems.append( f"BLANK VALUE: an option carries an empty value ({value!r})" )

    # Only compare once the oracle is real — an empty oracle has already been
    # reported above, and set differences against it would be noise on top of it.
    if expected_set:
        rendered_set = { v for v in rendered_list if v is not None }
        for value in sorted( expected_set - rendered_set ):
            problems.append( f"MISSING: {value!r} is expected but was not rendered" )
        for value in sorted( rendered_set - expected_set ):
            problems.append( f"PHANTOM: {value!r} was rendered but is not in the expected set" )

    return problems
