"""
Cross-language contract: the browser's FALLBACK session-ID generator must emit a
form the server's WebSocket validator accepts.

WHY THIS TEST EXISTS. On 2026-08-31 the GCP VM reconnect-looped on every socket:

    [WS-AUDIO] Rejected connection with invalid session ID: clever_owl
    INFO: "WebSocket /ws/audio/clever_owl" 403

`generateFallbackSessionId()` in notifications.js joined its two words with an
UNDERSCORE, while `is_valid_session_id()` accepts only a single SPACE (browser
format) or a HYPHEN (programmatic format). Both sides were internally consistent
and self-evidently correct when read alone. Nothing in either language's tests
compared them, so the disagreement was invisible until a browser met a server.

⚠️ A PYTHON-ONLY TEST OF THE VALIDATOR CANNOT CATCH THIS, and that is the whole
point of reading the JS file rather than restating its format here. Asserting
`is_valid_session_id( "clever owl" )` is True passes happily while the browser
emits `clever_owl` — the test would be measuring a string this file wrote, not
the string the browser actually produces. The separator has to come OFF DISK,
from the shipped asset, or the test re-encodes the assumption instead of
checking it.
"""
import re
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.rest.routers.websocket import is_valid_session_id


NOTIFICATIONS_JS = "/src/lupin_app/static/js/notifications.js"

# The `return` line of generateFallbackSessionId, whatever separator it uses.
# Captures the separator so a change to it is visible rather than silently absorbed.
_RETURN_RE = re.compile( r"return\s+`\$\{\s*adj\s*\}(?P<sep>.*?)\$\{\s*animal\s*\}`" )


def _fallback_separator():
    """
    Extract the separator the shipped JS uses to join its two words.

    Requires:
        - notifications.js exists under the project root
        - it defines generateFallbackSessionId() returning a two-word template

    Ensures:
        - returns the literal separator string between the two interpolations
        - fails loudly if the anchor matches zero times or more than once

    Raises:
        - pytest.fail if the anchor does not match exactly once
    """
    source  = Path( cu.get_project_root() + NOTIFICATIONS_JS ).read_text()
    matches = _RETURN_RE.findall( source )

    # A pointer that cannot fail is a pointer that silently lands in the wrong
    # place: say what to do at zero and at two, rather than guessing.
    if len( matches ) != 1:
        pytest.fail(
            f"expected exactly ONE fallback-return anchor in {NOTIFICATIONS_JS}, "
            f"found {len( matches )}. The generator moved or was duplicated — "
            f"re-point this test at it rather than relaxing the pattern."
        )

    return matches[ 0 ]


def test_the_shipped_fallback_separator_is_a_single_space():
    """The regression itself: an underscore here 403s every WebSocket handshake."""
    separator = _fallback_separator()

    assert separator == " ", (
        f"generateFallbackSessionId joins its words with {separator!r}. "
        f"is_valid_session_id accepts a single space (browser format) or a hyphen "
        f"(programmatic format) — anything else 403s and the client reconnect-loops."
    )


def test_every_word_pair_the_browser_can_emit_passes_the_server_validator():
    """
    Drive the REAL validator with the REAL separator over the REAL word lists.

    This is the assertion the 403 needed and nobody had: it fails if either side
    moves, because neither side is restated here.
    """
    separator  = _fallback_separator()
    adjectives = [ "wise", "clever", "swift", "bright", "keen", "bold", "calm", "cool", "fair", "fine" ]
    animals    = [ "penguin", "dolphin", "eagle", "tiger", "wolf", "bear", "lion", "hawk", "fox", "owl" ]

    rejected = [
        f"{adj}{separator}{animal}"
        for adj in adjectives
        for animal in animals
        if not is_valid_session_id( f"{adj}{separator}{animal}" )
    ]

    assert rejected == [], (
        f"{len( rejected )} of {len( adjectives ) * len( animals )} fallback ids are "
        f"rejected by is_valid_session_id, e.g. {rejected[ :3 ]}"
    )


def test_the_underscore_form_is_genuinely_rejected():
    """
    Negative control. Without it, the test above passes for the wrong reason if
    is_valid_session_id ever degrades into accepting everything — a green that
    means the validator stopped discriminating, not that the ids are correct.
    """
    assert not is_valid_session_id( "clever_owl" ), (
        "is_valid_session_id accepts the underscore form, so the positive test "
        "above no longer proves anything about the separator."
    )
