#!/usr/bin/env python3
"""
Regression tests for ask_yes_no()'s unattended paths, and for the attribution
its deep_research callers write to the log.

Row 84933a05. Third manufacture shape in the same module, and the one both
earlier sweeps were blind to: `return default == "yes"`. A predicate built
from labels[0] missed it, and so did one built from list(range(len(...))).

WHY IT IS NOT THE SAME DEFECT AS 741011ba, and why the fix differs:
the answer here is chosen by a CALLER-DECLARED parameter, not by list
position, so reordering nothing changes the verdict. What is wrong is that
`default: str = "no"` is IMPLICIT — a caller who never thought about
unattended operation still gets an answer manufactured for them, silently —
and that the return is a bare bool, so a forged yes is byte-identical to a
real one.

The fix keeps `default` meaning what it has always meant (the value offered
at an interactive [Y/n] prompt) and adds a SEPARATE `unattended_default` for
"what does it mean when there is no human at all". Overloading one parameter
for both questions is what let a prompt default silently become consent.

SEPARATELY: a notification must not say "User approved" when no user acted.
That half is worth doing regardless of the signature, and is pinned here.
"""

import ast
import sys
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import cosa.utils.util as cu


@pytest.fixture
def vio():
    """Yield the module with its globals restored afterwards."""
    from cosa.agents.utils import voice_io as mod

    saved = ( mod._cosa_interface, mod._voice_available, mod._force_cli_mode )
    try:
        yield mod
    finally:
        mod._cosa_interface, mod._voice_available, mod._force_cli_mode = saved


def _cli_no_human( mod ):
    mod._cosa_interface  = None
    mod._voice_available = False
    mod._force_cli_mode  = True


def _voice_that_raises( mod ):
    iface = type( "I", (), {} )()
    iface.ask_confirmation = AsyncMock( side_effect=RuntimeError( "503 User is offline" ) )
    iface.present_choices  = AsyncMock()
    mod._cosa_interface  = iface
    mod._voice_available = True
    mod._force_cli_mode  = False
    return iface


def _no_tty():
    return patch.object( sys, "stdin", **{ "isatty.return_value": False } )


def _tty():
    return patch.object( sys, "stdin", **{ "isatty.return_value": True } )


class TestUnattendedAnswerMustBeDeclared:

    @pytest.mark.asyncio
    async def test_non_interactive_without_an_unattended_default_refuses( self, vio ):
        """
        The queue/Docker shape. `default="yes"` describes what an interactive
        prompt should offer — it is not a statement that an ABSENT human meant
        yes, and it must not be read as one.
        """
        _cli_no_human( vio )
        with _no_tty():
            with pytest.raises( vio.VoiceGateNoDefaultError ):
                await vio.ask_yes_no( "Continue with partial audio?", default="yes" )

    @pytest.mark.asyncio
    async def test_dispatch_failure_without_an_unattended_default_refuses( self, vio ):
        """The 503-offline shape that started this whole chain."""
        _voice_that_raises( vio )
        with _no_tty():
            with pytest.raises( vio.VoiceGateNoDefaultError ):
                await vio.ask_yes_no( "Proceed with this research plan?", default="yes" )

    @pytest.mark.asyncio
    async def test_declared_unattended_default_is_honoured_and_logged( self, vio, caplog ):
        _cli_no_human( vio )
        with _no_tty():
            with caplog.at_level( logging.WARNING, logger="cosa.agents.utils.voice_io" ):
                result = await vio.ask_yes_no( "Proceed?", default="yes", unattended_default=True )
        assert result is True
        assert "DECLARED DEFAULT" in " ".join( r.getMessage() for r in caplog.records ), (
            "an unattended yes left no trace; it is indistinguishable from a human yes"
        )

    @pytest.mark.asyncio
    async def test_an_unattended_false_is_a_declaration_not_an_absence( self, vio ):
        """
        False is falsy but explicitly declared. It must be honoured, not
        treated as "nothing was said" — the check has to be `is None`.
        """
        _cli_no_human( vio )
        with _no_tty():
            assert await vio.ask_yes_no( "Proceed?", unattended_default=False ) is False


class TestInteractivePathsAreUnchanged:
    """A human at a terminal still answers exactly as before."""

    @pytest.mark.asyncio
    async def test_typed_yes_is_yes( self, vio ):
        _cli_no_human( vio )
        with _tty(), patch( "builtins.input", return_value="y" ):
            assert await vio.ask_yes_no( "Proceed?" ) is True

    @pytest.mark.asyncio
    async def test_typed_no_is_no( self, vio ):
        _cli_no_human( vio )
        with _tty(), patch( "builtins.input", return_value="n" ):
            assert await vio.ask_yes_no( "Proceed?" ) is False

    @pytest.mark.asyncio
    async def test_enter_at_the_prompt_still_takes_the_shown_default( self, vio ):
        """
        Pressing Enter at a prompt DISPLAYING [Y/n] is consent — the human
        acted. This path is deliberately untouched, and pinned so the fix
        cannot creep into it.
        """
        _cli_no_human( vio )
        with _tty(), patch( "builtins.input", return_value="" ):
            assert await vio.ask_yes_no( "Proceed?", default="yes" ) is True
            assert await vio.ask_yes_no( "Proceed?", default="no" ) is False


class TestCallersDoNotClaimAUserActed:
    """
    Source-level gate. deep_research announced the outcome of these gates as
    "User approved..." / "User rejected...". On an unattended path no user did
    either, and that line outlives the run as evidence — someone auditing "did
    a human approve this?" reads a log that says yes.

    Structural on purpose: the string is the defect, and asserting on the
    string is what a future edit would have to notice.
    """

    def _cli_source( self ):
        return ( Path( cu.get_project_root() ) / "src/cosa/agents/deep_research/cli.py" ).read_text()

    def test_no_notification_claims_a_user_acted( self ):
        src = self._cli_source()
        offenders = [
            ( n, line.strip() )
            for n, line in enumerate( src.splitlines(), 1 )
            if "User " in line and ( "approved" in line or "rejected" in line or "declined" in line )
        ]
        assert offenders == [], (
            "these lines assert that a user acted, on paths that can run with no "
            f"user present: {offenders}"
        )

    def test_the_gate_can_see_the_announcements_at_all( self ):
        """
        Control. If the notify calls move or are reworded past recognition,
        the test above would pass by finding nothing. Pin that the outcome
        announcements still exist to be checked.
        """
        src = self._cli_source()
        assert "research plan" in src and "partial report" in src, (
            "the two announcements this gate watches are no longer findable in "
            "cli.py — the gate is green because it is blind, not because it is clean"
        )


class TestEveryAskYesNoCallerDeclaresItsUnattendedAnswer:
    """
    The companion to 53c9762e's caller gate. ask_yes_no now raises when the
    human is unreachable and nothing was declared — so a caller that loses its
    declaration starts failing in the queue, not at the desk.
    """

    CALLERS = [
        "src/cosa/agents/deep_research/cli.py",
        "src/cosa/agents/podcast_generator/orchestrator.py",
    ]

    def _calls( self ):
        found = []
        for rel in self.CALLERS:
            path = Path( cu.get_project_root() ) / rel
            tree = ast.parse( path.read_text() )
            for node in ast.walk( tree ):
                if not isinstance( node, ast.Call ):
                    continue
                f = node.func
                if isinstance( f, ast.Attribute ) and f.attr == "ask_yes_no":
                    declared = any( kw.arg == "unattended_default" for kw in node.keywords )
                    found.append( ( rel, node.lineno, declared ) )
        return found

    def test_the_gate_sees_the_call_sites( self ):
        calls = self._calls()
        assert len( calls ) >= 4, (
            f"expected at least 4 ask_yes_no call sites, found {len( calls )} — "
            f"either they moved or this gate has gone blind"
        )

    def test_each_caller_declares_it( self ):
        undeclared = [ ( rel, ln ) for rel, ln, declared in self._calls() if not declared ]
        assert undeclared == [], (
            f"these ask_yes_no calls do not say what an absent human means, so "
            f"they will raise unattended: {undeclared}"
        )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
