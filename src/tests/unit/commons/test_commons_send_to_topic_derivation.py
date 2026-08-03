"""
Unit tests for `_derive_dm_topic` — wrapper-side DM topic derivation (used by
the cascade heartbeat scheduler + dm-topic migration tooling for `dm-<persona>`
topic-file routing).

⚠️ CONTRACT CHANGE — Phase 3 persona-name normalization (2026-06-19).
`_derive_dm_topic` now routes through the shared `persona_slug` root
(`src/lupin_mcp/persona_normalization.py`) so a DM topic ALWAYS equals the
recipient's canonical persona key with spaces → `_`. This REVERSES the
2026-05-17 Q8 "unicode all the way down" directive these tests previously
asserted. Under the canonical root:
  - accents strip:           "María" → "dm-maria"   (was "dm-maría")
  - non-Latin scripts drop:  "中文"  → "dm-"         (was "dm-中文")   ← degenerate
  - internal separators → _: "jean-luc" → "dm-jean_luc"  (bug 951a22be: a
                             separator run maps to ONE underscore boundary,
                             NOT dropped — was "dm-jeanluc" under drop-separators)
  - emoji/punct strip:       "maria🌸" → "dm-maria" (was "dm-maria_")
This is correct for REAL personas (every voice-pool name is ASCII/accented-Latin
and is keyed canonically in the store), but it is a genuine contract change on
arbitrary input — see the Phase 3 handoff flag. The "dm-" degenerate output for
non-Latin input is documented in `test_non_latin_script_collapses_degenerate`.

These assertions double as the FLIP guard for the seam: revert `_derive_dm_topic`
to the old accent-/unicode-preserving `re.sub` and the accent/hyphen/CJK cases
fail immediately.

Per `src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md` §Phase 3.

**Venue: :7999** (AI-discretionary — pure unit tests, no state mutation,
no MCP subprocess involvement). Run via `pytest src/tests/unit/commons/
test_commons_send_to_topic_derivation.py -v`.
"""

import re

import pytest

from lupin_mcp.cosa_voice_mcp import _derive_dm_topic


# ═════════════════════════════════════════════════════════════════════════════
# TestDeriveDmTopic — canonical persona-slug derivation (Phase 3)
# ═════════════════════════════════════════════════════════════════════════════


class TestDeriveDmTopic:
    """Behavior matrix for `_derive_dm_topic` = `dm-{persona_slug(name, '_')}`."""

    def test_lowercase_persona_preserved( self ):
        """Already-lowercase ASCII persona round-trips unchanged."""
        assert _derive_dm_topic( "tiberius" ) == "dm-tiberius"

    def test_capitalized_persona_lowercased( self ):
        assert _derive_dm_topic( "Tiberius" ) == "dm-tiberius"

    def test_all_caps_persona_lowercased( self ):
        assert _derive_dm_topic( "RIO" ) == "dm-rio"

    def test_space_in_persona_becomes_underscore( self ):
        assert _derive_dm_topic( "Mr Radio" ) == "dm-mr_radio"

    def test_lowercase_space_in_persona_becomes_underscore( self ):
        assert _derive_dm_topic( "mr radio" ) == "dm-mr_radio"

    def test_multiple_spaces_collapse_to_single_underscore( self ):
        """Consecutive whitespace collapses to ONE underscore (canonical key
        collapses runs of whitespace before the space→`_` substitution)."""
        assert _derive_dm_topic( "Dr   X" ) == "dm-dr_x"

    def test_punctuation_and_hyphen_become_underscore( self ):
        """CONTRACT CHANGE (bug 951a22be): every run of non-alphanumerics —
        period, space, AND internal hyphen — now maps to a SINGLE underscore
        boundary via the shared canonical root, rather than being dropped.
        "Dr. Strange-Love" → "dr strange love" → "dm-dr_strange_love"
        (was "dm-dr_strangelove" under the drop-separators contract)."""
        assert _derive_dm_topic( "Dr. Strange-Love" ) == "dm-dr_strange_love"

    def test_internal_hyphen_becomes_underscore( self ):
        """CONTRACT CHANGE (bug 951a22be): an internal hyphen is a separator run
        → mapped to a SINGLE underscore (a preserved word boundary), NOT dropped.
        "jean-luc" → "jean luc" → "dm-jean_luc" (was "dm-jeanluc")."""
        assert _derive_dm_topic( "jean-luc" ) == "dm-jean_luc"

    # ── Accents now strip (FIXES the prior accent-blind contract) ──

    def test_accent_stripped_maria( self ):
        """CONTRACT CHANGE (the core Phase 3 fix): "María" → "dm-maria"
        (was "dm-maría"). FLIP: revert to the old re.sub and this fails."""
        assert _derive_dm_topic( "María" ) == "dm-maria"

    def test_accent_stripped_all_caps( self ):
        assert _derive_dm_topic( "MARÍA" ) == "dm-maria"

    def test_accent_stripped_with_space( self ):
        """CONTRACT CHANGE: "José Ruiz" → "dm-jose_ruiz" (was "dm-josé_ruiz")."""
        assert _derive_dm_topic( "José Ruiz" ) == "dm-jose_ruiz"

    def test_non_latin_script_collapses_degenerate( self ):
        """CONTRACT CHANGE + documented degenerate case: the canonical root
        reduces to [a-z0-9 ], so a purely non-Latin name collapses to nothing →
        "中文" → "dm-" (was "dm-中文"). No CJK persona exists in the pool, so this
        is acceptable; flagged in the Phase 3 handoff as the one real regression
        if a non-Latin persona were ever introduced."""
        assert _derive_dm_topic( "中文" ) == "dm-"

    def test_emoji_stripped( self ):
        """CONTRACT CHANGE: emoji strip cleanly now. "maria🌸" → "dm-maria"
        (was "dm-maria_" — the trailing underscore is gone)."""
        assert _derive_dm_topic( "maria🌸" ) == "dm-maria"

    # ── Path-safety (still holds — the raw separator char NEVER survives; under
    #    bug 951a22be it maps to an underscore boundary instead of being dropped) ──

    def test_path_separator_never_survives( self ):
        """Defense-in-depth (bug 951a22be): a forward slash is a separator run →
        mapped to an underscore boundary, so the raw "/" NEVER survives into the
        output. "evil/path" → "dm-evil_path" (was "dm-evilpath" when separators
        were dropped). The safety invariant is asserted EXPLICITLY and
        independently of the exact value — no "/" may appear regardless."""
        result = _derive_dm_topic( "evil/path" )
        assert result == "dm-evil_path"
        assert "/" not in result

    def test_backslash_never_survives( self ):
        """Defense-in-depth (bug 951a22be): a backslash is a separator run →
        underscore boundary; the raw backslash NEVER survives. "evil\\path" →
        "dm-evil_path" (was "dm-evilpath"). Safety invariant asserted explicitly."""
        result = _derive_dm_topic( "evil\\path" )
        assert result == "dm-evil_path"
        assert "\\" not in result

    def test_control_chars_become_underscore( self ):
        """CONTRACT CHANGE (bug 951a22be): control whitespace (newline, tab) is a
        non-alphanumeric run → mapped to a SINGLE underscore boundary, NOT dropped.
        "name\\nwith\\tcontrol" → "name with control" → "dm-name_with_control"
        (was "dm-namewithcontrol"). Safety invariant asserted explicitly: no raw
        control char may survive into the output regardless of the example."""
        result = _derive_dm_topic( "name\nwith\tcontrol" )
        assert result == "dm-name_with_control"
        assert "\n" not in result and "\t" not in result

    def test_all_invalid_input_yields_bare_prefix( self ):
        """CONTRACT CHANGE: whitespace/punct-only input canonicalizes to "" →
        "dm-" (was "dm-_")."""
        assert _derive_dm_topic( "   " ) == "dm-"

    # ── Output-shape invariant (every output still matches the server pattern) ──

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
        `_TOPIC_OR_QID_PATTERN` (`[\\w-]+`). The canonical slug is a STRICT
        SUBSET of the accepted charset (`[a-z0-9_-]`), so this invariant is
        preserved (and even the degenerate "dm-" matches `[\\w-]+`).
        """
        result = _derive_dm_topic( persona_input )
        assert re.match( r"^[\w-]+$", result, flags=re.UNICODE ), (
            f"Derived topic {result!r} from input {persona_input!r} does NOT "
            f"match server-side pattern; wrapper/server contract broken."
        )
