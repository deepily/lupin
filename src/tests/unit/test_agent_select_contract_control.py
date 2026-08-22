#!/usr/bin/env python3
"""
The committed MUST-FAIL CONTROL for the `#agent-mode` option-value predicate, so
the instrument is never ungated.

These tests PASS by driving `option_value_drift` — the SAME function the live E2E
guards call, never a parallel re-implementation — onto synthetic broken inputs and
asserting it goes RED. If someone later weakens the predicate to buy a green E2E
run, these go red instead, on :7999, in a second.

Venue: :7999. Pure function, no browser, no server, no persistent state.

Run:
    .venv/bin/pytest src/tests/unit/test_agent_select_contract_control.py -v
"""

import unittest

from tests.e2e_ui.agent_select_contract import (
    AUTO_ROUTE_SENTINEL,
    checked_in_option_values,
    option_value_drift,
)


class TestOptionValueDriftControl( unittest.TestCase ):
    """Each arm fires on a synthetic input. Drives the real predicate."""

    def test_empty_oracle_is_refused_not_passed( self ):
        # THE TRAP THIS PREDICATE EXISTS FOR: phase 3 empties the HTML (expected
        # goes empty) and a broken endpoint empties the DOM (rendered goes empty).
        # Naive set-equality between two empty sets PASSES. The predicate must not.
        problems = option_value_drift( rendered=[], expected=set() )
        self.assertTrue(
            any( p.startswith( "ORACLE EMPTY" ) for p in problems ),
            f"empty-vs-empty must be refused, not passed: {problems}"
        )

    def test_empty_render_against_a_real_oracle_is_red( self ):
        # The phase-3 failure mode on its own: the oracle is fine, the select came
        # back empty. This is the case the three old count-assertions passed on.
        problems = option_value_drift( rendered=[], expected={ "agent router go to math" } )
        self.assertTrue(
            any( p.startswith( "NO OPTIONS" ) for p in problems ),
            f"an empty select against a real oracle must be red: {problems}"
        )

    def test_blank_option_value_is_red( self ):
        # A set-equality alone absorbs this: {""} vs {""} compares equal.
        problems = option_value_drift( rendered=[ "" ], expected={ "" } )
        self.assertTrue(
            any( p.startswith( "BLANK VALUE" ) for p in problems ),
            f"a blank option value must be red: {problems}"
        )

    def test_missing_option_is_red( self ):
        problems = option_value_drift(
            rendered=[ "agent router go to math" ],
            expected={ "agent router go to math", "agent router go to weather" } )
        self.assertTrue(
            any( p.startswith( "MISSING" ) and "weather" in p for p in problems ),
            f"a command expected but not rendered must be red: {problems}"
        )

    def test_phantom_option_is_red( self ):
        problems = option_value_drift(
            rendered=[ "agent router go to math", "agent router go to nowhere" ],
            expected={ "agent router go to math" } )
        self.assertTrue(
            any( p.startswith( "PHANTOM" ) and "nowhere" in p for p in problems ),
            f"a rendered value absent from the expected set must be red: {problems}"
        )

    def test_clean_input_is_green( self ):
        # The negative control: the predicate is not simply always-red.
        problems = option_value_drift(
            rendered=[ AUTO_ROUTE_SENTINEL, "agent router go to math" ],
            expected={ AUTO_ROUTE_SENTINEL, "agent router go to math" } )
        self.assertEqual( problems, [], f"a matching set must be clean: {problems}" )


class TestTheDiscriminatorIsManufactured( unittest.TestCase ):
    """Gate 3's discriminator does not exist in today's data, so the control has to
    MANUFACTURE it (Clayton 😎 / Mr Radio, 2026-08-22, recorded in the plan review §1).

    Measured on the live registry: `user_initiable - speakable` is EMPTY. The only two
    commands separating the sets are `agent router go to automatic` (CONTROL) and
    `none` (the internal no-command outcome) — neither is an agent, and no dropdown
    filter would carry either. So a gate written on `user_initiable` and one written
    on `speakable` are green on exactly the same inputs today: revert the fix and
    nothing reds. A gate whose discriminator is absent from the data asserts nothing.

    These tests supply the missing case synthetically. They are what makes the
    `speakable` -> `user_initiable` rewrite mean something before the first
    typeable-but-not-sayable command is ever added."""

    # A command a person may TYPE but must not be offered by VOICE. Synthetic on
    # purpose: the real registry has no such command yet, which is the entire point.
    TYPEABLE_NOT_SAYABLE = "agent router go to test fix expediter resume"

    def _dropdown_from( self, specs, field ):
        """Build the option-value set a dropdown filtered on `field` would render."""
        return { s[ "command" ] for s in specs if s[ field ] }

    def test_a_speakable_filter_SILENTLY_DROPS_a_typeable_not_sayable_command( self ):
        specs = [
            { "command": "agent router go to math",   "speakable": True,  "user_initiable": True },
            { "command": self.TYPEABLE_NOT_SAYABLE,   "speakable": False, "user_initiable": True },
        ]
        expected = self._dropdown_from( specs, "user_initiable" )

        # The CORRECT filter carries it...
        self.assertEqual( option_value_drift( sorted( expected ), expected ), [] )

        # ...and the WRONG one (the pre-fix gate) drops it with no complaint of its
        # own — the predicate is what turns that silence into a red.
        wrong    = self._dropdown_from( specs, "speakable" )
        problems = option_value_drift( sorted( wrong ), expected )
        self.assertTrue(
            any( p.startswith( "MISSING" ) and self.TYPEABLE_NOT_SAYABLE in p for p in problems ),
            f"a speakable-filtered dropdown must go RED against a user_initiable oracle: {problems}"
        )

    def test_the_two_filters_are_indistinguishable_without_the_manufactured_case( self ):
        # The negative control, and the reason the case above must be synthetic: when
        # no command is typeable-but-not-sayable, both filters produce the SAME set and
        # the gate cannot tell a correct implementation from a reverted one. If this
        # ever fails, the real registry has grown the discriminating command and the
        # synthetic case above can be retired in favour of it.
        specs = [
            { "command": "agent router go to math",    "speakable": True, "user_initiable": True },
            { "command": "agent router go to weather", "speakable": True, "user_initiable": True },
        ]
        self.assertEqual(
            self._dropdown_from( specs, "speakable" ),
            self._dropdown_from( specs, "user_initiable" )
        )


class TestCheckedInOracle( unittest.TestCase ):
    """The oracle reader itself, against the real tree."""

    def test_the_checked_in_oracle_is_currently_non_empty( self ):
        # Asserts the PRECONDITION of the live guards rather than assuming it: while
        # notifications.html still carries hardcoded options, the oracle is real. When
        # phase 3 empties the file this test goes RED — which is the signal to repoint
        # `expected` at USER_INITIABLE_COMMANDS, not a regression. Stated here so the
        # next reader is not left guessing why it went red.
        values = checked_in_option_values()
        self.assertNotEqual(
            values, set(),
            "the checked-in #agent-mode options are gone — if phase 3 landed, repoint "
            "the live guards' `expected` at the registry's USER_INITIABLE_COMMANDS "
            "and update this test to assert the new source instead."
        )

    def _read_as( self, html ):
        """Drive the oracle over synthetic page text, so both of its give-up arms are
        reachable without committing fixture files."""
        import tests.e2e_ui.agent_select_contract as contract
        original = contract.cu.get_file_as_string
        try:
            contract.cu.get_file_as_string = lambda _path: html
            return contract.checked_in_option_values()
        finally:
            contract.cu.get_file_as_string = original

    def test_the_oracle_returns_empty_when_the_select_is_absent( self ):
        # Arm 1 — no `id="agent-mode"` marker at all (phase 6 deletes the select).
        # Empty set => ORACLE EMPTY catches it downstream rather than passing.
        self.assertEqual( self._read_as( "<html><body>no select here</body></html>" ), set() )

    def test_the_oracle_returns_empty_when_the_select_is_never_closed( self ):
        # Arm 2 — the marker is present but `</select>` is not, e.g. a truncated or
        # malformed page. Without this arm the reader would scan to end-of-file and
        # sweep in every <option> on the page, including other selects' — a WIDER
        # oracle than intended, which is the quiet way a set-equality stops meaning
        # what its name says.
        self.assertEqual( self._read_as( '<select id="agent-mode"><option value="x">' ), set() )

    def test_the_oracle_reads_only_inside_the_agent_mode_select( self ):
        # The positive control for the two arms above: options belonging to a LATER,
        # unrelated select must not be swept in.
        html = (
            '<select id="agent-mode"><option value="mine">m</option></select>'
            '<select id="other"><option value="theirs">t</option></select>'
        )
        self.assertEqual( self._read_as( html ), { "mine" } )


if __name__ == "__main__":
    unittest.main()
