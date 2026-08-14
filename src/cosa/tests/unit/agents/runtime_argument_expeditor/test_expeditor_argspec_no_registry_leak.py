#!/usr/bin/env python3
"""
Regression tests for bug 8aa89f42 — ArgSpec.from_entry must COPY fallback_defaults.

Before the fix, ArgSpec.from_entry handed out the registry entry's own
fallback_defaults dict, and extract() seeded a missing required arg's default into
it in place. The write is guarded by "arg not in fallback_defaults", so it fires
ONCE and then sticks: the first user's question text became every later user's
default for the life of the process. The fix copies the dict once at the from_entry
seam, so each call gets its own.

Guards:
  1. Two extract() calls for the same command with DIFFERENT questions → the
     second's default is the SECOND question, not the first (María's leak-catcher;
     a same-question or single-call check passes while the leak still works).
     PROVEN to go red against the pre-fix code (red receipt in the crew report).
  2. The registry entry is byte-for-byte unchanged after a full expedite().
  3. from_entry copies fallback_defaults for EVERY registry command (scope is the
     whole table, not just DR).
  4. ArgSpec declares no mutable-literal constructor default (the anti-pattern
     that would reintroduce a shared-state leak).

DR ("deep research") is the primary fixture: required ["query"], and its
fallback_defaults has no "query" key, so extract() always tries to seed it — the
exact write site.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure src/cosa/.venv/bin/python \
     -m pytest src/cosa/tests/unit/agents/runtime_argument_expeditor/test_expeditor_argspec_no_registry_leak.py -v
"""

import copy
import unittest
from dataclasses import fields, MISSING
from unittest.mock import patch

from cosa.agents.runtime_argument_expeditor.expeditor import ArgSpec
from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

from cosa.tests.unit.agents.runtime_argument_expeditor.test_expeditor_flow import (
    _mk_expeditor,
    _FlowFixture,
    _expeditor_resp,
    DR,
)


class TestArgSpecNoRegistryLeak( unittest.TestCase ):

    def setUp( self ):
        # Snapshot the registry entry and restore it after each test, so a
        # regressed (leaking) run cannot poison sibling tests.
        self._snapshot = copy.deepcopy( AGENTIC_AGENTS[ DR ] )

    def tearDown( self ):
        AGENTIC_AGENTS[ DR ] = self._snapshot

    def _extract_with_question( self, o, question ):
        spec = ArgSpec.from_entry( AGENTIC_AGENTS[ DR ] )
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp() ):
            return o.extract( DR, "", question, spec )

    def test_second_user_default_is_not_first_users_question( self ):
        before = copy.deepcopy( AGENTIC_AGENTS[ DR ][ "fallback_defaults" ] )
        o  = _mk_expeditor()
        r1 = self._extract_with_question( o, "FIRST user question" )
        r2 = self._extract_with_question( o, "SECOND user question" )
        # The leak-catcher: with the shared dict + once-and-sticks guard, r2 would
        # still read "FIRST user question". With the copy, each call stands alone.
        self.assertEqual( r1.fallback_defaults[ "query" ], "FIRST user question" )
        self.assertEqual( r2.fallback_defaults[ "query" ], "SECOND user question" )
        # And the registry entry never grew a "query" key at all.
        self.assertEqual( AGENTIC_AGENTS[ DR ][ "fallback_defaults" ], before )
        self.assertNotIn( "query", AGENTIC_AGENTS[ DR ][ "fallback_defaults" ] )

    def test_registry_entry_unchanged_after_full_expedite( self ):
        before = copy.deepcopy( AGENTIC_AGENTS[ DR ] )
        o = _mk_expeditor()
        with _FlowFixture( o, user_visible=[ "query" ], parsed=_expeditor_resp() ), \
             patch.object( o, "_build_request_context", return_value="ctx" ), \
             patch.object( o, "_resolve_default",       return_value="please research topic X" ), \
             patch.object( o, "_ask_for_arg",           return_value="quantum computing" ), \
             patch.object( o, "_confirm_and_iterate",   return_value={ "query": "quantum computing" } ):
            out = o.expedite( DR, "", "u@x", "s", "uid", "please research topic X" )
        self.assertIsNotNone( out )
        self.assertEqual( AGENTIC_AGENTS[ DR ], before )

    def test_from_entry_copies_fallback_defaults_for_every_command( self ):
        # Whole-table scope (9 of 10 agents carry a fallback_defaults dict): the
        # spec's dict must never BE the registry entry's own object.
        checked = 0
        for command, entry in AGENTIC_AGENTS.items():
            if "fallback_defaults" not in entry:
                continue
            spec = ArgSpec.from_entry( entry )
            self.assertIsNot( spec.fallback_defaults, entry[ "fallback_defaults" ],
                              f"{command}: fallback_defaults handed out by reference" )
            self.assertEqual( spec.fallback_defaults, entry[ "fallback_defaults" ] )
            checked += 1
        self.assertGreaterEqual( checked, 9, "expected the whole registry, not one agent" )

    def test_argspec_has_no_mutable_literal_constructor_default( self ):
        for f in fields( ArgSpec ):
            if f.default is not MISSING:
                self.assertNotIsInstance( f.default, ( list, dict, set ),
                                          f"{f.name} has a mutable default literal" )
            # ArgSpec declares every field required — no default, no factory.
            self.assertIs( f.default,         MISSING, f"{f.name} should have no default" )
            self.assertIs( f.default_factory, MISSING, f"{f.name} should have no default_factory" )


if __name__ == "__main__":
    unittest.main()
