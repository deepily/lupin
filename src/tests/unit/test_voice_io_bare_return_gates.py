#!/usr/bin/env python3
"""
Regression tests for the BARE-RETURN voice gates in
cosa.agents.utils.voice_io — choose(), select_themes(), select_topics().

Row 741011ba. Sibling of test_voice_io_gate_failure_fallback.py, which covers
present_choices(). The split is not cosmetic: present_choices returns a dict,
so the fix could carry provenance in new keys. These three return a bare
string or a bare list, with nowhere to put a `default_used` flag, so the
contract is the other half of the same rule — an explicitly declared default
is honoured and logged, and the absence of one raises instead of guessing.

WHAT EACH FUNCTION USED TO DO WHEN NO HUMAN ANSWERED:
    choose          -> labels[0]                 (the answer tracked option ORDER)
    select_themes   -> list(range(len(themes)))  ("nobody answered" => "wants all")
    select_topics   -> list(range(len(topics)))  (same, incl. on a CLI typo)

The select_* pair is the worse shape: it does not merely pick something, it
maximises scope, on a path that spends real per-token search budget.

Genuine input is NOT forgery and is pinned here too — typing "all", typing
"none", and picking a valid number must still work exactly as before.
"""

import sys
import logging
from unittest.mock import AsyncMock, patch

import pytest


OPTIONS = [
    { "label": "Approve", "description": "ship it" },
    { "label": "Revise",  "description": "another pass" },
    { "label": "Cancel",  "description": "stop" },
]

THEMES = [
    { "name": "Alpha", "description": "a", "subquery_indices": [ 0 ] },
    { "name": "Beta",  "description": "b", "subquery_indices": [ 1 ] },
]

TOPICS = [ { "topic": "t1", "objective": "o1" }, { "topic": "t2", "objective": "o2" } ]


@pytest.fixture
def vio():
    """
    Yield the module with its globals restored afterwards, plus helpers that
    put it into each of the three reachable states.
    """
    from cosa.agents.utils import voice_io as mod

    saved = ( mod._cosa_interface, mod._voice_available, mod._force_cli_mode )

    class _H:
        @staticmethod
        def cli_no_human():
            """CLI fallback, no tty — the queue/Docker shape."""
            mod._cosa_interface  = None
            mod._voice_available = False
            mod._force_cli_mode  = True

        @staticmethod
        def cli_with_human():
            """CLI fallback with a tty, so input() is reached."""
            mod._cosa_interface  = None
            mod._voice_available = False
            mod._force_cli_mode  = True

        @staticmethod
        def voice( **kw ):
            """Voice mode with a stub interface."""
            iface = type( "I", (), {} )()
            iface.present_choices = AsyncMock( **kw )
            mod._cosa_interface  = iface
            mod._voice_available = True
            mod._force_cli_mode  = False
            return iface

    try:
        yield mod, _H
    finally:
        mod._cosa_interface, mod._voice_available, mod._force_cli_mode = saved


def _no_tty():
    return patch.object( sys, "stdin", **{ "isatty.return_value": False } )


def _tty():
    return patch.object( sys, "stdin", **{ "isatty.return_value": True } )


# =============================================================================
# choose()
# =============================================================================

class TestChooseRefusesToAnswerForAnAbsentHuman:

    @pytest.mark.asyncio
    async def test_non_interactive_without_a_default_raises( self, vio ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.choose( "Ship it?", OPTIONS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_NON_INTERACTIVE

    @pytest.mark.asyncio
    async def test_declared_default_is_honoured_and_logged( self, vio, caplog ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            with caplog.at_level( logging.WARNING, logger="cosa.agents.utils.voice_io" ):
                result = await mod.choose( "Ship it?", OPTIONS, response_default="Cancel" )
        assert result == "Cancel"
        blob = " ".join( r.getMessage() for r in caplog.records )
        assert "DECLARED DEFAULT" in blob, "a defaulted answer left no trace in the log"

    @pytest.mark.asyncio
    async def test_the_verdict_no_longer_tracks_option_order( self, vio ):
        """
        The load-bearing one. The old code answered labels[0], so reordering
        the SAME gate silently changed what an absent user was deemed to have
        chosen. Both orderings must now behave identically — and neither may
        return an answer.
        """
        mod, h = vio
        h.cli_no_human()
        reordered = list( reversed( OPTIONS ) )

        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ):
                await mod.choose( "Ship it?", OPTIONS )
            with pytest.raises( mod.VoiceGateNoDefaultError ):
                await mod.choose( "Ship it?", reordered )

    @pytest.mark.asyncio
    async def test_dispatch_failure_without_a_default_raises( self, vio ):
        mod, h = vio
        h.voice( side_effect=RuntimeError( "503 User is offline" ) )
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.choose( "Ship it?", OPTIONS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_DISPATCH_FAILED

    @pytest.mark.asyncio
    async def test_dispatch_returning_no_choice_is_not_a_selection( self, vio ):
        """
        Distinct from a failure: the call succeeded and simply carried no
        recognisable choice. That is still not consent.
        """
        mod, h = vio
        h.voice( return_value={ "answers": {} } )
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.choose( "Ship it?", OPTIONS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_NO_SELECTION

    @pytest.mark.asyncio
    async def test_refusal_is_not_swallowed_by_the_functions_own_except( self, vio ):
        """
        choose() wraps its voice path in `except Exception`. The no-selection
        refusal is raised INSIDE that block, so without an explicit re-raise
        it would be caught and answered as though the dispatch had failed —
        the fix defeating itself one line later. Pins the guard.
        """
        mod, h = vio
        h.voice( return_value={ "answers": {} } )
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.choose( "Ship it?", OPTIONS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_NO_SELECTION, (
            "the no-selection refusal was recaught and relabelled as a dispatch "
            "failure — the except block swallowed its own guard"
        )

    @pytest.mark.asyncio
    async def test_a_genuine_voice_selection_is_returned_unchanged( self, vio ):
        mod, h = vio
        h.voice( return_value={ "answers": { "Choice": "Revise" } } )
        with _no_tty():
            assert await mod.choose( "Ship it?", OPTIONS ) == "Revise"

    @pytest.mark.asyncio
    async def test_a_genuine_cli_number_is_returned_unchanged( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="2" ):
            assert await mod.choose( "Ship it?", OPTIONS ) == "Revise"

    @pytest.mark.asyncio
    async def test_an_unusable_cli_entry_raises_rather_than_picking_first( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="not a number" ):
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.choose( "Ship it?", OPTIONS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_CLI_BAD_INDEX


# =============================================================================
# select_themes() / select_topics() — "nobody answered" must not mean "all"
# =============================================================================

class TestSelectGatesDoNotMaximiseScopeOnSilence:

    @pytest.mark.asyncio
    async def test_themes_non_interactive_raises_instead_of_selecting_all( self, vio ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.select_themes( THEMES )
        assert exc.value.reason == mod._DEFAULT_SOURCE_NON_INTERACTIVE

    @pytest.mark.asyncio
    async def test_topics_non_interactive_raises_instead_of_selecting_all( self, vio ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ):
                await mod.select_topics( TOPICS )

    @pytest.mark.asyncio
    async def test_themes_declared_default_is_honoured( self, vio ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            assert await mod.select_themes( THEMES, response_default=[ 0, 1 ] ) == [ 0, 1 ]

    @pytest.mark.asyncio
    async def test_topics_declared_default_is_honoured( self, vio ):
        mod, h = vio
        h.cli_no_human()
        with _no_tty():
            assert await mod.select_topics( TOPICS, response_default=[ 1 ] ) == [ 1 ]

    @pytest.mark.asyncio
    async def test_a_typo_does_not_expand_the_topic_run( self, vio ):
        """
        The worst single site in the row: select_topics' unparseable-entry
        branch returned every index under a comment reading "Default to all on
        error", so a mistyped entry silently expanded a run that spends real
        per-token budget.
        """
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="1, oops" ):
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.select_topics( TOPICS )
        assert exc.value.reason == mod._DEFAULT_SOURCE_CLI_UNPARSEABLE

    @pytest.mark.asyncio
    async def test_a_typo_does_not_silently_select_nothing_either( self, vio ):
        """
        select_themes had the mirror-image bug: an unparseable entry became an
        EMPTY selection. Wrong in the opposite direction, equally invented.
        """
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="oops" ):
            with pytest.raises( mod.VoiceGateNoDefaultError ) as exc:
                await mod.select_themes( THEMES )
        assert exc.value.reason == mod._DEFAULT_SOURCE_CLI_UNPARSEABLE


class TestGenuineSelectionsAreUntouched:
    """Typing 'all' or 'none' is a human act. None of it may start raising."""

    @pytest.mark.asyncio
    async def test_typing_all_still_selects_all_themes( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="all" ):
            assert await mod.select_themes( THEMES ) == [ 0, 1 ]

    @pytest.mark.asyncio
    async def test_typing_all_still_selects_all_topics( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="all" ):
            assert await mod.select_topics( TOPICS ) == [ 0, 1 ]

    @pytest.mark.asyncio
    async def test_typing_none_still_selects_nothing( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="none" ):
            assert await mod.select_topics( TOPICS ) == []

    @pytest.mark.asyncio
    async def test_a_valid_number_list_still_parses( self, vio ):
        mod, h = vio
        h.cli_with_human()
        with _tty(), patch( "builtins.input", return_value="2" ):
            assert await mod.select_themes( THEMES ) == [ 1 ]


class TestVoiceModeAbsentHeaderIsNotAnEmptySelection:
    """
    The manufacture that an AST-over-returns pass cannot see.

    Both select gates read their answer as
        result.get( "answers", {} ).get( "<Header>", [] )
    and then map names to indices. The returns themselves are honest list
    comprehensions — the invented value lives one line up, in the DEFAULT on
    the lookup. A payload carrying no answer for the header becomes an empty
    list, and the caller is told the user deselected everything.

    Same shape as the presentation orchestrator's
    `.get( "answers", {} ).get( header, "Approve" )`, fixed in 770ec03a. That
    fix was applied to the consumer without checking whether the library it
    was protecting had the same line in it.

    The distinction that matters: an EMPTY selection the user genuinely made
    is legal and must keep working. What must be refused is an ABSENT header.
    """

    @pytest.mark.asyncio
    async def test_themes_absent_header_refuses( self, vio ):
        mod, h = vio
        h.voice( return_value={ "answers": {} } )       # dispatch fine, no answer
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ):
                await mod.select_themes( THEMES )

    @pytest.mark.asyncio
    async def test_topics_absent_header_refuses( self, vio ):
        mod, h = vio
        h.voice( return_value={ "answers": {} } )
        with _no_tty():
            with pytest.raises( mod.VoiceGateNoDefaultError ):
                await mod.select_topics( TOPICS )

    @pytest.mark.asyncio
    async def test_a_genuine_empty_selection_still_returns_empty( self, vio ):
        """
        The user opened the picker and deselected everything. The header IS
        present and its value is an empty list. That is an answer, and the
        refusal must not swallow it.
        """
        mod, h = vio
        h.voice( return_value={ "answers": { "Themes": [] } } )
        with _no_tty():
            assert await mod.select_themes( THEMES ) == []

    @pytest.mark.asyncio
    async def test_a_genuine_selection_still_maps_to_indices( self, vio ):
        mod, h = vio
        h.voice( return_value={ "answers": { "Themes": [ "Beta" ] } } )
        with _no_tty():
            assert await mod.select_themes( THEMES ) == [ 1 ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
