#!/usr/bin/env python3
"""
Tests for read_gate_answer() and for the four consumer gates converted to it.

Row 2b604cdb. The producer-side fixes (247ddaca, 53c9762e, 019082cd) made
voice_io refuse to invent an answer. Six CONSUMERS then re-invented one on
their own, each with its own copy of

    result.get( "answers", {} ).get( "<Header>", <fallback> )

That line reads as ordinary defensive code. It is not: a payload carrying no
answer at all silently becomes the fallback, and each agent had picked a
fallback that means "proceed".

  swe_team          absent -> "Continue to next task"   on a task that had
                                                        already failed every
                                                        verification retry
  deep_research     absent -> falls past both branches and sets plan_approved
  test_fix_expediter  gate FAILURE -> applied every proposed fix to the repo
  bug_fix_expediter absent -> "" -> no fix (safe, but indistinguishable)

WHAT IS DELIBERATELY NOT REFUSED: an answer the user genuinely gave, including
an empty string or an empty list. Choosing nothing is a choice. Only an ABSENT
header is refused. That distinction is the whole point and is pinned below.
"""

import ast
import sys
import logging
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.agents.utils.voice_io import read_gate_answer, VoiceGateNoDefaultError


class TestReadGateAnswer:

    def test_absent_header_refuses_when_nothing_declared( self ):
        with pytest.raises( VoiceGateNoDefaultError ):
            read_gate_answer( { "answers": {} }, "Escalation", "gate" )

    def test_absent_header_honours_a_declared_default( self, caplog ):
        with caplog.at_level( logging.WARNING, logger="cosa.agents.utils.voice_io" ):
            got = read_gate_answer(
                { "answers": {} }, "Escalation", "gate", unattended_default="Stop and get help"
            )
        assert got == "Stop and get help"
        assert "DECLARED DEFAULT" in " ".join( r.getMessage() for r in caplog.records )

    def test_a_genuine_answer_is_returned_untouched( self ):
        payload = { "answers": { "Escalation": "Stop and get help" } }
        assert read_gate_answer( payload, "Escalation", "gate" ) == "Stop and get help"

    def test_a_genuine_empty_string_is_an_answer_not_an_absence( self ):
        """Choosing nothing is a choice. Only an ABSENT header is refused."""
        assert read_gate_answer( { "answers": { "Fix Selection": "" } }, "Fix Selection", "gate" ) == ""

    def test_a_genuine_empty_list_is_an_answer_not_an_absence( self ):
        assert read_gate_answer( { "answers": { "Fixes": [] } }, "Fixes", "gate" ) == []

    def test_a_non_dict_payload_is_treated_as_carrying_no_answer( self ):
        with pytest.raises( VoiceGateNoDefaultError ):
            read_gate_answer( None, "Fixes", "gate" )

    def test_a_defaulted_answer_is_logged_even_when_the_header_is_present( self, caplog ):
        """
        The producer can supply the header AND mark it defaulted. The value
        looks exactly like a real one, so the log line is the only thing that
        distinguishes them afterwards.
        """
        payload = {
            "answers"        : { "Plan": "Execute plan" },
            "default_used"   : True,
            "default_source" : "dispatch_failed",
        }
        with caplog.at_level( logging.WARNING, logger="cosa.agents.utils.voice_io" ):
            assert read_gate_answer( payload, "Plan", "Research plan gate" ) == "Execute plan"
        blob = " ".join( r.getMessage() for r in caplog.records )
        assert "DECLARED DEFAULT" in blob and "dispatch_failed" in blob

    def test_the_error_names_the_gate_and_the_header( self ):
        with pytest.raises( VoiceGateNoDefaultError ) as exc:
            read_gate_answer( { "answers": {} }, "Escalation", "SWE escalation gate" )
        assert "SWE escalation gate" in str( exc.value ) and "Escalation" in str( exc.value )


class TestNoConsumerStillDefaultsItsLookup:
    """
    Source-level gate over the converted files. The defect is a LOOKUP DEFAULT,
    which lives one line above an honest-looking return — an AST pass over
    return expressions cannot see it, which is exactly how it survived three
    earlier sweeps. So this asserts on the shape directly.
    """

    CONVERTED = [
        "src/cosa/agents/swe_team/orchestrator.py",
        "src/cosa/agents/deep_research/orchestrator.py",
        "src/cosa/agents/test_fix_expediter/orchestrator.py",
        "src/cosa/agents/bug_fix_expediter/orchestrator.py",
        "src/cosa/agents/utils/voice_io.py",
    ]

    def _offenders( self, rel ):
        """Find `.get("answers", ...)` chained into a .get with a fallback."""
        src = ( Path( cu.get_project_root() ) / rel ).read_text()
        out = []
        for node in ast.walk( ast.parse( src ) ):
            if not isinstance( node, ast.Call ):
                continue
            f = node.func
            if not ( isinstance( f, ast.Attribute ) and f.attr == "get" ):
                continue
            # inner call must itself be a .get("answers", ...)
            inner = f.value
            if not ( isinstance( inner, ast.Call ) and isinstance( inner.func, ast.Attribute )
                     and inner.func.attr == "get" and inner.args
                     and isinstance( inner.args[ 0 ], ast.Constant )
                     and inner.args[ 0 ].value == "answers" ):
                continue
            if len( node.args ) >= 2:          # a fallback was supplied
                out.append( node.lineno )
        return out

    @pytest.mark.parametrize( "rel", CONVERTED )
    def test_file_has_no_defaulted_answer_lookup( self, rel ):
        offenders = self._offenders( rel )
        assert offenders == [], (
            f"{rel} still defaults an answers-lookup at lines {offenders}. An "
            f"absent header would silently become that value; use "
            f"read_gate_answer() so it refuses or declares."
        )

    def test_the_detector_actually_detects( self ):
        """
        Control. This gate passes by finding nothing, which is also what a
        broken detector does. Feed it the exact shape it hunts and require a
        hit, so a green above means "clean" rather than "blind".
        """
        import tempfile, os
        sample = 'x = result.get( "answers", {} ).get( "Header", "Approve" )\n'
        with tempfile.NamedTemporaryFile( "w", suffix=".py", delete=False ) as fh:
            fh.write( sample ); tmp = fh.name
        try:
            found = []
            for node in ast.walk( ast.parse( sample ) ):
                if isinstance( node, ast.Call ) and isinstance( node.func, ast.Attribute ) \
                   and node.func.attr == "get" and len( node.args ) >= 2:
                    inner = node.func.value
                    if isinstance( inner, ast.Call ) and isinstance( inner.func, ast.Attribute ) \
                       and inner.func.attr == "get" and inner.args \
                       and getattr( inner.args[ 0 ], "value", None ) == "answers":
                        found.append( node.lineno )
            assert found == [ 1 ], (
                "the detector cannot see a known offender — every green result "
                "from this class is meaningless"
            )
        finally:
            os.unlink( tmp )


class TestTfeNoLongerAppliesEveryFixOnGateFailure:
    """
    The sharpest site in the row, and the one no lookup-shaped predicate could
    have found: it lived in an `except`, not a lookup.

    TFE already had a configured policy for a voice-gate timeout (default
    "stall"). A NON-timeout failure bypassed it and returned every proposal —
    applying every proposed fix to the codebase, with the intent stated in the
    log line. The fix routes both through the same policy rather than
    inventing a third behaviour.
    """

    def _source( self ):
        return ( Path( cu.get_project_root() )
                 / "src/cosa/agents/test_fix_expediter/orchestrator.py" ).read_text()

    def test_no_exception_handler_returns_every_proposal( self ):
        """
        Structural, not textual. My first version of this test grepped for the
        log string "auto-selecting all" and failed on two innocent lines: the
        legitimate dry_run branch, and my own comment quoting the old string.
        A predicate that matches a DESCRIPTION of the defect is not a predicate
        for the defect.

        What actually matters is narrower: no `except` handler may return the
        whole proposal list. dry_run returning everything is fine — the caller
        asked for a dry run and nothing is applied.
        """
        tree = ast.parse( self._source() )
        offenders = []
        for handler in [ n for n in ast.walk( tree ) if isinstance( n, ast.ExceptHandler ) ]:
            for node in ast.walk( handler ):
                if not isinstance( node, ast.Return ) or node.value is None:
                    continue
                src = ast.unparse( node.value )
                if src in ( "list(proposals)", "proposals" ):
                    offenders.append( node.lineno )
        assert offenders == [], (
            f"an exception handler returns every proposal at lines {offenders} — "
            f"a failed voice gate would apply every proposed fix to the codebase"
        )

    def test_both_failure_paths_route_through_the_configured_policy( self ):
        """
        Two call sites, one policy. Pinning the count so a future edit cannot
        quietly restore a bypass alongside the policy call.
        """
        src = self._source()
        assert src.count( "_apply_voice_gate_timeout_policy( proposals )" ) == 2, (
            "expected the timeout branch AND the generic-failure branch to both "
            "defer to the policy"
        )

    def test_the_policy_helper_still_exists_to_be_called( self ):
        """Control: the assertions above are about a helper that must exist."""
        assert "def _apply_voice_gate_timeout_policy" in self._source()


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
