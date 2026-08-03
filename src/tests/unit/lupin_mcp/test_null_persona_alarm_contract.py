"""
Regression guard for the null-persona ALARM contract in the cosa-voice MCP
`instructions` payload (bug 975b24ac, candidate D of the 468ea39f composed trap).

THE DEFECT THIS GUARDS AGAINST
------------------------------
The boot self-announcement is the only zero-interrupt broadcast in startup.
It used to be gated OFF exactly when `voice_persona` was None ("skip the
greeting — there's no name to use"), which optimised the greeting's CONTENT
and silenced the ALARM: the system was quietest precisely when something was
wrong. D inverts that.

WHY THIS TEST READS SOURCE TEXT RATHER THAN IMPORTING
-----------------------------------------------------
Importing `lupin_mcp.cosa_voice_mcp` builds the FastMCP server at module
scope and starts a background session-watcher thread — side effects a unit
test has no business triggering. The `instructions` payload is a static
concatenation of string literals, so asserting on the source is sufficient
to catch a regression AND keeps the test hermetic.

Because the payload is built from adjacent f-string literals, a phrase may be
split across a concatenation boundary in SOURCE while being contiguous in the
RENDERED string. Assertions here therefore match SOURCE-LITERAL forms. (This
bit the author once: grepping the source for a rendered-only phrase reported
a false "already removed".)
"""

import re
from pathlib import Path

import pytest

import cosa.utils.util as cu


MCP_SOURCE = Path( cu.get_project_root() ) / "src" / "lupin_mcp" / "cosa_voice_mcp.py"


@pytest.fixture( scope="module" )
def source() -> str:
    """Raw source text of the cosa-voice MCP module."""
    assert MCP_SOURCE.exists(), f"MCP source not found at {MCP_SOURCE}"
    return MCP_SOURCE.read_text( encoding="utf-8" )


# ═════════════════════════════════════════════════════════════════════════════
# The inversion itself — a null session must ANNOUNCE, never skip
# ═════════════════════════════════════════════════════════════════════════════

class TestNullAnnouncementInversion:
    """The `:707` greeting-skip must stay inverted."""

    def test_skip_the_greeting_instruction_is_gone( self, source ):
        """
        The original defect, in its source-literal form (the phrase spans an
        f-string concatenation boundary). Its return is the regression.
        """
        defect = 'skip the "\n        f"greeting — there\'s no name to use.'
        assert defect not in source, (
            "The null-persona greeting-skip has returned. A session that boots "
            "broken must ANNOUNCE, not go quiet — see bug 975b24ac."
        )

    def test_null_case_is_told_to_announce( self, source ):
        """Null must be an explicit ANNOUNCE instruction, not a silent path."""
        assert "ANNOUNCE THE NULL" in source

    def test_startup_step_announces_in_both_cases( self, source ):
        """
        Phase A step 3 must fire `notify()` for BOTH the named and null cases.
        Re-gating it on a non-null name would silently restore the defect one
        layer up from `:707`.
        """
        assert "ALWAYS, in BOTH cases" in source


# ═════════════════════════════════════════════════════════════════════════════
# The binding constraint — the alarm must carry its own identity
# ═════════════════════════════════════════════════════════════════════════════

class TestAlarmCarriesSessionId:
    """
    The UI badge is gated on `sender_id && voice_persona`, so a null session's
    card renders WITHOUT its badge — the one channel that normally carries
    identity is exactly the channel that disappears. The id must therefore be
    in the alarm TEXT, in the spoken message as well as the abstract.
    """

    def test_session_id_is_mandatory( self, source ):
        assert "The session id is MANDATORY in both" in source

    def test_spoken_message_carries_short_id( self, source ):
        assert "FIRST 8 " in source and "CHARACTERS of `claude_code.session_id`" in source

    def test_badge_gate_rationale_is_documented( self, source ):
        """
        The REASON must survive alongside the rule. A bare 'include the id'
        reads as ceremony and gets optimised away by the next editor.
        """
        assert "sender_id && voice_persona" in source

    def test_tts_id_exception_is_explicit( self, source ):
        """
        Empirically load-bearing: without an explicit carve-out, the standing
        'ids belong in abstract, never in speech' TTS rule wins and the spoken
        alarm goes out unattributed. Observed live on probe arm B (session
        a0d674a8): id in abstract, absent from speech. Adding this clause
        flipped arm B2 (65294de1) to id-in-both.
        """
        assert "EXCEPTION to the standing TTS rule" in source

    def test_abstract_only_shortcut_is_closed( self, source ):
        """The specific non-compliance observed on arm B must stay named."""
        assert "silently relocate the id to" in source


# ═════════════════════════════════════════════════════════════════════════════
# Failure Mode 2 — the free remedies must precede the blocking one
# ═════════════════════════════════════════════════════════════════════════════

class TestFailureModeTwoRemedyOrdering:
    """
    A standing drive-to-completion order correctly prices out INTERRUPTS. It
    does NOT price out NON-BLOCKING SIGNALS. When `converse()` is presented as
    the only remedy, a worker correctly declines it and stays unnamed forever.
    """

    def test_remedies_are_cost_ordered( self, source ):
        assert "ORDERED BY COST" in source

    def test_notify_and_dm_precede_converse( self, source ):
        """
        Ordering is the whole point — assert position, not mere presence.
        """
        fm2 = source[ source.index( "**2. `voice_persona: None`" ) : ]
        fm2 = fm2[ : fm2.index( "**3. (retired)" ) ]

        notify_at   = fm2.index( "`notify()` the null alarm" )
        dm_at       = fm2.index( "`dm_send()` your manager" )
        converse_at = fm2.index( "converse(message='Which persona am I?'" )

        assert notify_at < converse_at, "notify() must be offered before the blocking converse()"
        assert dm_at     < converse_at, "manager DM must be offered before the blocking converse()"

    def test_zero_cost_remedies_are_marked_free( self, source ):
        """
        The cost column is what defeats the drive-to-completion objection. If
        the free remedies stop being marked free, the trap reopens.
        """
        # `[^|]*` spans the optional in-cell gloss (e.g. "— fire-and-forget")
        # between the cost cell and the permission cell.
        assert re.search( r"\*\*none\*\*[^|]*\|\s*none; self-disclosure tier", source )
        assert re.search( r"\*\*none\*\*[^|]*\|\s*none; DM tier", source )

    def test_self_heal_prohibition_survives( self, source ):
        """
        D deliberately does NOT adopt candidate B. Rule 2 (request_persona is
        user-initiated only) must remain intact — D adds an alarm, it does not
        license self-allocation.
        """
        assert "do not self-heal" in source.lower()
