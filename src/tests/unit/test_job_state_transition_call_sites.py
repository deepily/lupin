#!/usr/bin/env python3
"""
Guards every emit_job_state_transition() call site against UI-container vocabulary.

The defect found 2026-08-02: podcast_generator.py passed 'todo' and 'dead' —
which are frontend CONTAINER names from STATE_TO_UI_CONTAINER, not JobState
members. assert_valid_transition() does JobState('todo') and raises ValueError,
so /api/podcast-generator/submit returned a 500 the moment the speculative card
was emitted. Six call sites in that one file had never been migrated to the
enum, and the canonical smoke-test example in queue_util.py taught the same
wrong vocabulary.

Rather than assert on the six sites we happened to find, this scans the real
source for every literal argument handed to emit_job_state_transition and
checks it against the enum. A new call site written with container names fails
here, in any file.
"""

import ast
from pathlib import Path

import pytest

import cosa.rest.queue_util as queue_util
from cosa.rest.job_state import JobState, VALID_TRANSITIONS, STATE_TO_UI_CONTAINER


# Derive the scan root from the module that defines the function, so the guard
# follows the code rather than depending on cwd or an env var.
COSA_ROOT = Path( queue_util.__file__ ).parent

VALID_STATE_VALUES = { s.value for s in JobState }


def _iter_emit_calls():
    """Yield (path, lineno, [literal str args]) for each emit_job_state_transition call."""
    for py_file in COSA_ROOT.rglob( "*.py" ):
        try:
            # Read bytes so ast.parse honors each file's own PEP 263 encoding
            # declaration rather than assuming utf-8.
            tree = ast.parse( py_file.read_bytes() )
        except ( SyntaxError, ValueError, OSError ):
            continue

        for node in ast.walk( tree ):
            if not isinstance( node, ast.Call ):
                continue

            func = node.func
            name = func.attr if isinstance( func, ast.Attribute ) else getattr( func, "id", None )
            if name != "emit_job_state_transition":
                continue

            # positional args 3 and 4 are from_state / to_state
            literals = [
                a.value for a in node.args[ 2:4 ]
                if isinstance( a, ast.Constant ) and isinstance( a.value, str )
            ]
            if literals:
                yield py_file, node.lineno, literals


class TestEmitCallSitesUseJobStates:
    """No call site may pass a UI container name where a state belongs."""

    def test_scan_finds_call_sites_at_all( self ):
        """
        Control. If the scanner silently matches nothing, every assertion below
        passes vacuously and this file proves exactly nothing.
        """
        all_calls = list( _iter_emit_calls() )
        assert all_calls, "scanner found no emit_job_state_transition string literals — the guard is not looking at anything"

    def test_no_call_site_passes_a_container_name( self ):
        """The specific confusion: 'todo', 'run', 'done', 'dead' are containers."""
        container_names = set( STATE_TO_UI_CONTAINER.values() )
        offenders = []

        for path, lineno, literals in _iter_emit_calls():
            for literal in literals:
                if literal in container_names and literal not in VALID_STATE_VALUES:
                    offenders.append( f"{path.name}:{lineno} passed container name '{literal}'" )

        assert not offenders, "UI container names used as job states:\n  " + "\n  ".join( offenders )

    def test_every_literal_is_a_real_job_state( self ):
        """Broader net — catches typos, not just container names."""
        offenders = []

        for path, lineno, literals in _iter_emit_calls():
            for literal in literals:
                if literal not in VALID_STATE_VALUES:
                    offenders.append( f"{path.name}:{lineno} passed '{literal}'" )

        assert not offenders, "arguments that are not JobState values:\n  " + "\n  ".join( offenders )


class TestPodcastRouterTransitionsAreLegal:
    """The transitions the podcast submit path now uses must be in the matrix."""

    @pytest.mark.parametrize( "from_state,to_state", [
        ( JobState.PENDING, JobState.QUEUED ),      # speculative card emitted
        ( JobState.QUEUED,  JobState.FAILED ),      # no matches / bad path / missing file / build failed
        ( JobState.QUEUED,  JobState.CANCELLED ),   # user declined the document choice
    ] )
    def test_transition_is_permitted( self, from_state, to_state ):
        assert to_state in VALID_TRANSITIONS[ from_state ]

    def test_the_original_broken_value_is_not_a_state( self ):
        """
        Control for the fix. 'todo' must remain an invalid JobState — if it ever
        becomes valid, the guard above stops meaning anything.
        """
        with pytest.raises( ValueError ):
            JobState( "todo" )
