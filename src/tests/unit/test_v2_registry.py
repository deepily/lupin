#!/usr/bin/env python3
"""
CJ Flow v2 — registry guard (plan §9; revised by cascade handoff R-A2 / R-D4 /
R-A5 / R-D10). Unit A deliverable.

EXECUTOR: AI — every assertion is machine-run; no human step, no live server,
no inference. Runs on :7999-class unit venue (pure import + file read).

Coverage: this file exercises all of `src/cosa/rest/v2/registry.py` — resolve()'s
hit / alias / miss arms, AgentSpec.required_args' three arms (declared_args →
AGENTIC_AGENTS → literal), and the four-bucket partition. Asserts 100% lines +
branches of registry.py when run with
  --cov=cosa.rest.v2.registry --cov-branch --cov-report=term-missing

The drift guard (test_every_template_command_is_bucketed) is the plan's named
defence against the three-mechanism routing drift reappearing: every command the
router can emit must sit in exactly ONE of four buckets — a v2 agent, the deferred
set, a mode-control command, or the receptionist. R-A2 added the fourth bucket
(CONTROL_COMMANDS) after the router template's `agent router go to automatic` broke
a three-bucket set-equality on its first run.

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/tests/unit/test_v2_registry.py -v
"""

import re
import types
import unittest
from itertools import combinations

import cosa.utils.util as cu
from cosa.rest.v2.registry import (
    AgentSpec,
    V2_AGENTS,
    AGENTIC_COMMANDS,
    DEFERRED_COMMANDS,
    CONTROL_COMMANDS,
    RECEPTIONIST_OR_NONE,
    resolve,
    resolve_agentic,
)
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

ROUTER_TEMPLATE = "/src/conf/prompts/agent-router-template-completion.txt"


def _template_commands():
    """The set of routing commands the router template can emit.

    The template's <command> tags are the enumerated commands PLUS one empty
    `<command></command>` — the response-format answer slot the model fills in,
    not a command — which is excluded. `none` IS an emittable command (the router's
    no-command outcome) and is kept.
    """
    text = cu.get_file_as_string( cu.get_project_root() + ROUTER_TEMPLATE )
    return { c for c in re.findall( r"<command>(.*?)</command>", text ) if c }


class TestRegistryDriftGuard( unittest.TestCase ):
    """The §9 set-equality — the defence against the three-mechanism drift."""

    def test_every_template_command_is_bucketed_exactly_once( self ):
        template = _template_commands()
        buckets = [ set( V2_AGENTS ), set( DEFERRED_COMMANDS ),
                    set( CONTROL_COMMANDS ), set( RECEPTIONIST_OR_NONE ) ]
        covered = set().union( *buckets )

        # Both directions: no template command uncovered, and no bucket carries a
        # command the template cannot emit (R-A2 / R-D4).
        self.assertEqual( template, covered )

        # Partition: no command lands in two buckets at once.
        for a, b in combinations( buckets, 2 ):
            self.assertEqual( a & b, set(), f"command in two buckets: {a & b}" )

    # test_bucket_counts REMOVED (phase 1, Rachel's ruling 2026-08-15): a count
    # derived from the registry and asserted against the registry is a tautology
    # that can never go red, and the set-equality above proves strictly more — a
    # count cannot fail unless a set-equality would have failed first.


class TestAgenticSetOwnership( unittest.TestCase ):
    """The registry now OWNS the agentic set (§5.1); these guard the two seams
    that ownership opens — cls vs the source table, and the interim DEFERRED name."""

    # test_cls_agentic_matches_agentic_agents REMOVED (Rachel 2026-08-15): the
    # AGENTIC specs are built by iterating AGENTIC_AGENTS, so set(AGENTIC_COMMANDS)
    # == set(AGENTIC_AGENTS) is true BY CONSTRUCTION — a tautology like the count.
    # The invariant is enforced instead by the construction warning at registry.py's
    # _AGENTIC comprehension.

    def test_deferred_is_template_emittable_agentic_subset( self ):
        # DEFERRED_COMMANDS is a bounded interim (retired phase 2). Pin it to the
        # template-emittable agentic subset so it cannot silently drift from the
        # owned set: the 3 AGENTIC commands absent from the template (bug fix
        # expediter, test fix expediter resume, test suite) are excluded here.
        template          = _template_commands()
        emittable_agentic = { c for c in AGENTIC_COMMANDS if c in template }
        self.assertEqual( DEFERRED_COMMANDS, emittable_agentic )


class TestResolve( unittest.TestCase ):

    def test_full_command_resolves_to_spec( self ):
        spec = resolve( "agent router go to weather" )
        self.assertIsInstance( spec, AgentSpec )
        self.assertEqual( spec.command, "agent router go to weather" )

    def test_short_form_alias_resolves_to_spec( self ):
        self.assertEqual( resolve( "weather" ).command, "agent router go to weather" )
        self.assertEqual( resolve( "todo list" ).command, "agent router go to todo" )

    def test_deferred_command_resolves_to_none( self ):
        self.assertIsNone( resolve( "agent router go to deep research" ) )

    def test_control_command_resolves_to_none( self ):
        self.assertIsNone( resolve( "agent router go to automatic" ) )

    def test_receptionist_resolves_to_none( self ):
        self.assertIsNone( resolve( "agent router go to receptionist" ) )

    def test_unknown_command_resolves_to_none( self ):
        self.assertIsNone( resolve( "agent router go to nowhere" ) )

    def test_agentic_command_resolves_to_none_in_resolve( self ):
        # §5.1.3: resolve() stays scoped to CONVERSATIONAL — an owned agentic
        # command must still return None here, unchanged from before phase 1.
        self.assertIsNone( resolve( "agent router go to deep research" ) )

    def test_resolve_agentic_returns_spec( self ):
        spec = resolve_agentic( "agent router go to deep research" )
        self.assertIsInstance( spec, AgentSpec )
        self.assertEqual( spec.command, "agent router go to deep research" )

    def test_resolve_agentic_returns_none_for_conversational( self ):
        self.assertIsNone( resolve_agentic( "agent router go to weather" ) )

    def test_resolve_agentic_returns_none_for_unknown( self ):
        self.assertIsNone( resolve_agentic( "agent router go to nowhere" ) )


class TestRequiredArgsResolutionOrder( unittest.TestCase ):
    """The §3a migration path — declared_args → AGENTIC_AGENTS → literal tuple."""

    def test_literal_tuple_arm( self ):
        # weather has no declared_args and is not in AGENTIC_AGENTS → literal tuple.
        self.assertEqual( resolve( "agent router go to weather" ).required_args, ( "location", ) )

    def test_empty_when_no_source( self ):
        # math: no declared_args, not in AGENTIC_AGENTS, no literal → ().
        self.assertEqual( resolve( "agent router go to math" ).required_args, () )

    def test_agentic_agents_table_arm( self ):
        # A spec whose command IS in AGENTIC_AGENTS reads its required_user_args.
        command = "agent router go to deep research"
        expected = tuple( AGENTIC_AGENTS[ command ][ "required_user_args" ] )
        spec = AgentSpec( command, factory=object )   # object has no declared_args
        self.assertEqual( spec.required_args, expected )

    def test_agent_declared_args_arm_wins( self ):
        # A factory that declares its own args short-circuits the tables (phase-2
        # destination). Uses a command that IS in AGENTIC_AGENTS to prove the
        # declaration wins over the table.
        class _Declaring:
            @classmethod
            def declared_args( cls ):
                return types.SimpleNamespace( required=( "foo", ), optional=() )

        spec = AgentSpec( "agent router go to deep research", factory=_Declaring )
        self.assertEqual( spec.required_args, ( "foo", ) )


if __name__ == "__main__":
    unittest.main()
