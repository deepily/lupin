#!/usr/bin/env python3
"""
CJ Flow v2 — resolve() scope guard (design §5.1.3).

Cascade R2 deliverable (Tiffany 💍). Proves the invariant the design names as
"the sharpest hazard": once the agentic set is owned by the unified registry,
resolve() must STAY scoped to CONVERSATIONAL commands, and agentic commands must
be served only by a separate resolve_agentic(). A naive REGISTRY.get() inside
resolve() would silently start returning specs for agentic commands — changing
v2's live routing as a side effect of a bookkeeping change.

EXECUTOR: AI — pure import, no server, no human step. :7999-class unit venue.

Run: PYTHONPATH=src src/cosa/.venv/bin/python -m pytest \
     src/tests/unit/test_v2_registry_resolve_scope_guard.py -v

FORWARD-COMPAT NOTE for the builder: the agentic bucket is SPEAKABLE_JOBS
today and becomes JOB_COMMANDS after design §5.1.2 renames it. This file
imports whichever exists, so it guards the invariant across the phase-1 rename
WITHOUT edit. The resolve_agentic() half skips until §5.1.3 lands the split
reader, then becomes a live guard automatically.
"""

import unittest

from cosa.rest.v2.registry import resolve

# The agentic bucket: SPEAKABLE_JOBS pre-move, JOB_COMMANDS post-move
# (§5.1.2). Import whichever the tree currently exposes so this guard survives
# the rename untouched.
try:
    from cosa.rest.v2.registry import JOB_COMMANDS as _AGENTIC_BUCKET
except ImportError:
    from cosa.rest.v2.registry import SPEAKABLE_JOBS as _AGENTIC_BUCKET

# The split reader the design mandates (§5.1.3). Absent until phase 1 builds it.
try:
    from cosa.rest.v2.registry import resolve_agentic
    _HAS_RESOLVE_AGENTIC = True
except ImportError:
    _HAS_RESOLVE_AGENTIC = False


class TestResolveStaysScopedToConversational( unittest.TestCase ):
    """resolve() must never hand back a spec for an agentic command (§5.1.3)."""

    def test_resolve_never_returns_a_spec_for_any_agentic_command( self ):
        # Whole-set guard, not a single example. Fails loudly the moment any
        # agentic command becomes resolvable through resolve() — the exact
        # regression §5.1.3 warns a naive REGISTRY.get() would introduce.
        leaks = sorted( c for c in _AGENTIC_BUCKET if resolve( c ) is not None )
        self.assertEqual(
            leaks, [],
            f"resolve() leaked specs for agentic commands (must return None): {leaks}"
        )

    @unittest.skipUnless( _HAS_RESOLVE_AGENTIC,
                          "resolve_agentic() not built yet — design §5.1.3 (phase 1)" )
    def test_resolve_agentic_is_the_reader_that_serves_agentic_commands( self ):
        # Once the split reader exists, prove the two readers stay separated:
        # every agentic command is invisible to resolve() and served by
        # resolve_agentic(). This is what makes "same table, two readers, no
        # behaviour change" (§5.1.3) verifiable rather than asserted.
        for command in sorted( _AGENTIC_BUCKET ):
            self.assertIsNone(
                resolve( command ),
                f"resolve() must not serve agentic command {command!r}"
            )
            self.assertIsNotNone(
                resolve_agentic( command ),
                f"resolve_agentic() must serve agentic command {command!r}"
            )


class TestFalsifiability( unittest.TestCase ):
    """The guard above must be demonstrably able to go red (design §6)."""

    def test_guard_would_fire_if_resolve_leaked_an_agentic_spec( self ):
        # Synthetic proof the assertion is not a no-op: a stand-in resolver that
        # DOES return a spec for an agentic command makes the same predicate
        # non-empty. If this ever passes with an empty list, the real guard is
        # asleep.
        fake_resolve = lambda c: object()   # leaks a "spec" for everything
        leaks = sorted( c for c in _AGENTIC_BUCKET if fake_resolve( c ) is not None )
        self.assertEqual( leaks, sorted( _AGENTIC_BUCKET ) )
        self.assertNotEqual( leaks, [] )   # the red the real guard is written to catch


if __name__ == "__main__":
    unittest.main()
