#!/usr/bin/env python3
"""
The two `display_name` gates, and the must-fail controls that make them mean
something (Clayton 😎, reviewed with Mr Radio, 2026-08-22).

`display_name` is the string the dropdown SHOWS, deliberately separate from
`label`, the string a user HEARS ("new math job..."). Without the split, moving the
dropdown onto the registry would have regressed visible option text from
"Date & Time" to "date and time".

TWO GATES, AND THE SECOND IS NOT REDUNDANT
------------------------------------------
GATE A — every agentic spec's `display_name` equals its JOB_ARG_CONTRACTS entry's.

  🔴 Its control is a HAND-DECLARED spec with a DIFFERING value, NOT a mutation of
  the contract. This is the trap Clayton caught: `_agentic_spec` builds the spec
  FROM the entry (`display_name = entry.get("display_name")`, registry.py:215), so
  mutating the contract propagates to BOTH sides of the equality and the control
  can never go red. Anyone who then "fixed" the control until it did red would have
  un-derived the field — breaking the very property the gate exists to protect.

GATE B — every agentic spec has a NON-EMPTY `display_name`.

  Independent of A, and A is structurally blind to what B catches: when a contract
  entry omits the key, `entry.get("display_name")` is None and the spec's value is
  None, so A compares None == None and PASSES. All 11 agentic commands carry one
  today, so B is green now; it goes red the day a 12th contract entry omits the key
  and the dropdown would render a blank option.

Both gates run through ONE shared predicate, `display_name_drift`, which the live
guards and the controls both call — never a parallel re-implementation. That is the
same discipline `_card_drift` uses in test_v2_registry_drift_guard.py.

Venue: :7999. Pure table reads, no server, no persistent state.
"""

import unittest

from cosa.rest.v2.registry import REGISTRY, AgentSpec, CommandClass
from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS


def display_name_drift( specs, contracts ):
    """
    Problems with the display_name of a set of AGENTIC specs. Empty list ⇒ clean.

    Requires:
        - specs is an iterable of AgentSpec whose cls is AGENTIC
        - contracts maps command -> the raw JOB_ARG_CONTRACTS entry

    Ensures:
        - ABSENT for a spec whose display_name is missing or blank (GATE B) — checked
          FIRST and independently, because the equality arm below cannot see it: an
          omitted contract key makes both sides None and None == None passes
        - MISMATCH for a spec whose display_name differs from its contract entry's
          (GATE A)
        - NO CONTRACT for an agentic spec with no entry at all, so a missing contract
          reads as itself rather than as a mismatch against None
    """
    problems = []
    for spec in specs:
        entry = contracts.get( spec.command )

        if spec.display_name is None or not str( spec.display_name ).strip():
            problems.append(
                f"ABSENT: {spec.command!r} has no display_name "
                f"({spec.display_name!r}) — the dropdown would render a blank option"
            )

        if entry is None:
            problems.append( f"NO CONTRACT: {spec.command!r} is agentic but has no JOB_ARG_CONTRACTS entry" )
            continue

        expected = entry.get( "display_name" )
        if spec.display_name != expected:
            problems.append(
                f"MISMATCH: {spec.command!r} carries {spec.display_name!r} "
                f"but its contract says {expected!r}"
            )
    return problems


def _agentic_specs():
    return [ s for s in REGISTRY.values() if s.cls is CommandClass.AGENTIC ]


# -- The live guards, on real data ---------------------------------------------
class TestDisplayNameGates( unittest.TestCase ):

    def test_gate_a_every_agentic_display_name_matches_its_contract( self ):
        problems = [ p for p in display_name_drift( _agentic_specs(), JOB_ARG_CONTRACTS )
                     if p.startswith( "MISMATCH" ) or p.startswith( "NO CONTRACT" ) ]
        self.assertEqual( problems, [], "display_name drift (gate A):\n  " + "\n  ".join( problems ) )

    def test_gate_b_every_agentic_spec_has_a_non_empty_display_name( self ):
        problems = [ p for p in display_name_drift( _agentic_specs(), JOB_ARG_CONTRACTS )
                     if p.startswith( "ABSENT" ) ]
        self.assertEqual( problems, [], "blank display_name (gate B):\n  " + "\n  ".join( problems ) )

    def test_the_agentic_set_is_not_empty( self ):
        # Guards both gates above against passing vacuously. An empty spec list makes
        # display_name_drift return [] and BOTH gates green while proving nothing —
        # the same empty-oracle trap as the select contract. Asserted, not assumed.
        self.assertGreater( len( _agentic_specs() ), 0 )


# -- The committed must-fail controls ------------------------------------------
class TestDisplayNameGateControls( unittest.TestCase ):
    """Drives the SAME predicate the live guards use, onto synthetic broken input."""

    def test_gate_a_control_uses_a_HAND_DECLARED_spec_not_a_contract_mutation( self ):
        # 🔴 THE POINT (Clayton): a hand-declared spec is the ONLY way to get the two
        # sides to disagree. Going through _agentic_spec would copy the contract's
        # value onto the spec and the arm could never fire.
        command  = "agent router go to deep research"
        contract = JOB_ARG_CONTRACTS[ command ]
        hand     = AgentSpec( command, cls=CommandClass.AGENTIC, display_name="Something Else Entirely" )

        self.assertNotEqual( hand.display_name, contract.get( "display_name" ) )   # the precondition, asserted
        problems = display_name_drift( [ hand ], JOB_ARG_CONTRACTS )
        self.assertTrue(
            any( p.startswith( "MISMATCH" ) and command in p for p in problems ),
            f"gate A must red on a spec disagreeing with its contract: {problems}"
        )

    def test_mutating_the_CONTRACT_can_never_red_gate_a___the_trap_named( self ):
        # The proof that the control above had to be shaped that way. Build the spec
        # THROUGH the derivation, from a mutated contract: both sides move together
        # and the equality holds. A control written this way would be permanently
        # green and would look like a passing gate.
        command  = "agent router go to deep research"
        mutated  = { **JOB_ARG_CONTRACTS[ command ], "display_name": "Mutated In The Contract" }
        derived  = AgentSpec( command, cls=CommandClass.AGENTIC,
                              display_name=mutated.get( "display_name" ) )   # what _agentic_spec does
        problems = display_name_drift( [ derived ], { command: mutated } )
        self.assertEqual(
            problems, [],
            "a contract mutation propagated to the spec must stay GREEN — if this ever "
            "reds, display_name has been un-derived and gate A's control is no longer "
            "guarding what it claims to."
        )

    def test_gate_b_control_reds_on_an_absent_display_name( self ):
        command = "agent router go to deep research"
        blank   = AgentSpec( command, cls=CommandClass.AGENTIC, display_name=None )
        problems = display_name_drift( [ blank ], JOB_ARG_CONTRACTS )
        self.assertTrue(
            any( p.startswith( "ABSENT" ) and command in p for p in problems ),
            f"gate B must red on a missing display_name: {problems}"
        )

    def test_gate_b_control_reds_on_a_whitespace_only_display_name( self ):
        # A blank-looking string is not None and would slip past a bare `is None`
        # check while still rendering an empty-looking option.
        blank    = AgentSpec( "agent router go to deep research", cls=CommandClass.AGENTIC, display_name="   " )
        problems = display_name_drift( [ blank ], JOB_ARG_CONTRACTS )
        self.assertTrue( any( p.startswith( "ABSENT" ) for p in problems ), problems )

    def test_gate_a_is_BLIND_to_the_omitted_key___which_is_why_gate_b_exists( self ):
        # 🔴 The independence proof. A contract with the key OMITTED yields None on
        # both sides, so gate A's equality PASSES — and only gate B catches it.
        command    = "agent router go to synthetic"
        no_key     = { command: { "required_user_args": [] } }
        spec       = AgentSpec( command, cls=CommandClass.AGENTIC, display_name=None )
        problems   = display_name_drift( [ spec ], no_key )

        self.assertFalse(
            any( p.startswith( "MISMATCH" ) for p in problems ),
            f"gate A should be blind here (None == None): {problems}"
        )
        self.assertTrue(
            any( p.startswith( "ABSENT" ) for p in problems ),
            f"gate B must catch what gate A cannot: {problems}"
        )

    def test_no_contract_reads_as_itself_not_as_a_mismatch( self ):
        spec     = AgentSpec( "agent router go to orphan", cls=CommandClass.AGENTIC, display_name="Orphan" )
        problems = display_name_drift( [ spec ], {} )
        self.assertTrue( any( p.startswith( "NO CONTRACT" ) for p in problems ), problems )
        self.assertFalse( any( p.startswith( "MISMATCH" ) for p in problems ), problems )

    def test_a_clean_spec_is_green( self ):
        # The negative control: the predicate is not simply always-red.
        command = "agent router go to deep research"
        clean   = AgentSpec( command, cls=CommandClass.AGENTIC,
                             display_name=JOB_ARG_CONTRACTS[ command ].get( "display_name" ) )
        self.assertEqual( display_name_drift( [ clean ], JOB_ARG_CONTRACTS ), [] )


if __name__ == "__main__":
    unittest.main()
