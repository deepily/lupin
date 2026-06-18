"""
Unit tests for `_derive_dm_topic` — wrapper-side DM topic derivation (used by
the cascade heartbeat scheduler + dm-topic migration tooling for `dm-<persona>`
topic-file routing).

Per `src/rnd/v0.1.7/2026.05.17-commons-dm-topic-case-and-truncation/01-design.md`
§2.1 (Sub-bug A topic-case + Sub-bug C persona-space-in-topic, unified fix
ratified Q8 with unicode broadening 2026-05-17).

Note: the server-side `RegisterQuestionRequest`-pattern regression class was
removed in the cosa-voice token-reduction full-removal pass (2026-06-17) — the
register-question endpoint + its topic pattern are gone. The wrapper/server
charset contract is still locked by
`TestDeriveDmTopic.test_output_always_matches_server_topic_pattern` (inline
`[\\w-]+` assertion).

**Venue: :7999** (AI-discretionary — pure unit tests, no state mutation,
no MCP subprocess involvement). Run via `pytest src/tests/unit/commons/
test_commons_send_to_topic_derivation.py -v`.
"""

import re

import pytest

from lupin_mcp.cosa_voice_mcp import _derive_dm_topic


# ═════════════════════════════════════════════════════════════════════════════
# TestDeriveDmTopic — Sub-bug A (case) + Sub-bug C (whitespace/punct)
# ═════════════════════════════════════════════════════════════════════════════


class TestDeriveDmTopic:
    """Behavior matrix for `_derive_dm_topic` per design §2.1 v3."""

    def test_lowercase_persona_preserved( self ):
        """Sub-bug A: already-lowercase persona round-trips unchanged."""
        assert _derive_dm_topic( "tiberius" ) == "dm-tiberius"

    def test_capitalized_persona_lowercased( self ):
        """Sub-bug A: capitalized persona normalizes to lowercase canonical."""
        assert _derive_dm_topic( "Tiberius" ) == "dm-tiberius"

    def test_all_caps_persona_lowercased( self ):
        """Sub-bug A: ALL CAPS persona also normalizes."""
        assert _derive_dm_topic( "RIO" ) == "dm-rio"

    def test_space_in_persona_becomes_underscore( self ):
        """Sub-bug C: space collapses to underscore."""
        assert _derive_dm_topic( "Mr Radio" ) == "dm-mr_radio"

    def test_lowercase_space_in_persona_becomes_underscore( self ):
        """Sub-bug C: already-lowercase with space still collapses correctly."""
        assert _derive_dm_topic( "mr radio" ) == "dm-mr_radio"

    def test_multiple_spaces_collapse_to_single_underscore( self ):
        """Sub-bug C: consecutive whitespace becomes ONE underscore (regex +)."""
        assert _derive_dm_topic( "Dr   X" ) == "dm-dr_x"

    def test_punctuation_becomes_underscore( self ):
        """
        Sub-bug C: punctuation in name (e.g., periods) collapses.

        Note 1: the regex `[^\\w-]+` uses `+` (one-or-more), so consecutive
        invalid chars collapse to ONE underscore — `". "` (period+space, two
        invalid chars adjacent) becomes a single `_`, not two.

        Note 2: literal `-` IS allowed in topic charset, so "Strange-Love"
        keeps its internal hyphen.
        """
        assert _derive_dm_topic( "Dr. Strange-Love" ) == "dm-dr_strange-love"

    def test_hyphen_preserved_in_persona( self ):
        """`-` is allowed by the server pattern; persona-internal hyphens survive."""
        assert _derive_dm_topic( "jean-luc" ) == "dm-jean-luc"

    # ── Unicode (Q8 broadening ratified 2026-05-17) ──

    def test_unicode_persona_preserved_maria( self ):
        """Q8 unicode: María's accented 'í' survives the regex pass."""
        assert _derive_dm_topic( "María" ) == "dm-maría"

    def test_unicode_persona_lowercased_with_diacritic( self ):
        """Q8 unicode: capitalization preserves the diacritic (lowercase still has í)."""
        assert _derive_dm_topic( "MARÍA" ) == "dm-maría"

    def test_unicode_persona_with_space( self ):
        """Q8 unicode + Sub-bug C: unicode persona name with space gets unicode + underscore."""
        assert _derive_dm_topic( "José Ruiz" ) == "dm-josé_ruiz"

    def test_unicode_persona_cjk( self ):
        """Q8 unicode: CJK characters survive the regex (`\\w` re.UNICODE matches them)."""
        assert _derive_dm_topic( "中文" ) == "dm-中文"

    def test_unicode_persona_emoji_in_name( self ):
        """Emoji are NOT word characters in re.UNICODE — they collapse to underscore."""
        # 🌸 is not in \w category, so it collapses
        assert _derive_dm_topic( "maria🌸" ) == "dm-maria_"

    # ── Path-safety ──

    def test_path_separator_collapses_to_underscore( self ):
        """Defense-in-depth: forward slash never reaches the topic name."""
        assert _derive_dm_topic( "evil/path" ) == "dm-evil_path"

    def test_backslash_collapses_to_underscore( self ):
        """Defense-in-depth: backslash never reaches the topic name."""
        assert _derive_dm_topic( "evil\\path" ) == "dm-evil_path"

    def test_control_char_collapses_to_underscore( self ):
        """Defense-in-depth: control chars (newlines, tabs) collapse."""
        assert _derive_dm_topic( "name\nwith\tcontrol" ) == "dm-name_with_control"

    def test_all_invalid_input_yields_single_underscore( self ):
        """Edge case: input made entirely of invalid chars yields `dm-_`."""
        assert _derive_dm_topic( "   " ) == "dm-_"

    # ── Output-shape invariants (every output matches the server pattern) ──

    @pytest.mark.parametrize(
        "persona_input",
        [
            "tiberius",
            "Mr Radio",
            "María",
            "José Ruiz",
            "中文",
            "Dr. Strange-Love",
            "evil/path",
            "MARÍA",
        ],
    )
    def test_output_always_matches_server_topic_pattern( self, persona_input ):
        """
        Every output of `_derive_dm_topic` MUST be accepted by the server-side
        `_TOPIC_OR_QID_PATTERN` (the post-Q8-broadening unicode pattern).
        This locks the wrapper/server contract — broadening one without the
        other (the silent-failure footgun) regresses the contract instantly.
        """
        result = _derive_dm_topic( persona_input )
        # Match the same pattern the server uses
        assert re.match( r"^[\w-]+$", result, flags=re.UNICODE ), (
            f"Derived topic {result!r} from input {persona_input!r} does NOT "
            f"match server-side pattern; wrapper/server contract broken."
        )
