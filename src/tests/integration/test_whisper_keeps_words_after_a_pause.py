"""Integration test — Whisper must not end a transcript at the first pause on noisy audio.

Row 05ddc8f0 (filed by Tiffany 💍 from mobile bug 4be8fe63). Without
`return_timestamps=True`, distil-large-v3 transcribed Rick's old-mic recording as
"Testing, testing." and silently dropped "One, two, three." — the words are in the
audio, because the 1.9-4.4 s slice alone transcribes them. The fix is commit 6e75695e:
the model server's /transcribe and the provider's local path both decode with
timestamps on.

THE FIXTURE IS A REAL RECORDING OF RICK'S VOICE, committed with his permission
(ask_yes_no, clean "yes", 2026-09-16 ~14:55 EDT). It is the only clip known to
reproduce the bug: 5.56 s, 44.1 kHz mono, noise floor about -34 dB, high-passed at
80 Hz. A synthetic clip was the declined alternative because it may not reproduce the
defect, and a guard that cannot see its bug is worse than none.

WHAT IT ASSERTS. The words AFTER the pause survive. It does not assert punctuation or
case, which vary run to run, and it does not assert the words before the pause alone,
because the broken decode returned those too — an assertion the bug satisfies would
pass against the bug.

Venue: :8000 only. It spends real transcription on the server's stack and writes an
InputAndOutputTable row, so it is not :7999-eligible under CLAUDE.md § Testing venues.
Submit via POST /api/test-suite/submit on a verified-idle server. ⚠️ The model server
must be RESTARTED after 6e75695e for this to go green; a red here on a server that
predates the commit is the stale process, not the fix.
"""

import os

import pytest
import requests

import cosa.utils.util as cu

from tests.helpers.opus_accuracy import words


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_TRANSCRIBE = f"{BASE_URL}/api/upload-and-transcribe-wav"

_FIXTURE = "/src/tests/fixtures/audio/noisy-pause-testing-one-two-three.wav"

# The words after the pause, as words() tokenizes them. Whisper may write them as
# digits ("1, 2, 3") on another run, so both spellings are accepted per position.
_AFTER_THE_PAUSE = [ { "one", "1" }, { "two", "2" }, { "three", "3" } ]

_UPLOAD_TIMEOUT_S = 300


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once → {"Authorization": "Bearer ..."}."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": _EMAIL, "password": _PASSWORD },
        timeout = 10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    body   = resp.json()
    tokens = body.get( "tokens", body )
    token  = tokens.get( "access_token" ) or tokens.get( "accessToken" )
    assert token, f"No access token in login response: {body}"
    return { "Authorization": f"Bearer {token}" }


def _contains_in_order( tokens, wanted ):
    """
    Whether `wanted` (a list of accepted-spelling sets) appears as a contiguous run in `tokens`.

    Requires:
        - tokens is a list of str, wanted is a non-empty list of sets of str

    Ensures:
        - True iff some i has tokens[ i + k ] in wanted[ k ] for every k
    """
    n = len( wanted )
    return any(
        all( tokens[ i + k ] in wanted[ k ] for k in range( n ) )
        for i in range( len( tokens ) - n + 1 )
    )


def test_contains_in_order_finds_the_run_and_rejects_its_absence():
    """The matcher itself, so a green below cannot come from a matcher that says yes to everything."""
    assert _contains_in_order( [ "testing", "testing", "one", "two", "three" ], _AFTER_THE_PAUSE )
    assert _contains_in_order( [ "testing", "1", "2", "3" ], _AFTER_THE_PAUSE )
    assert not _contains_in_order( [ "testing", "testing" ], _AFTER_THE_PAUSE )
    assert not _contains_in_order( [ "one", "three", "two" ], _AFTER_THE_PAUSE )


def test_words_after_the_pause_survive( auth_headers ):
    path = cu.get_project_root() + _FIXTURE
    assert os.path.isfile( path ), f"fixture missing: {path}"

    with open( path, "rb" ) as handle:
        payload = handle.read()

    resp = requests.post(
        _TRANSCRIBE,
        files   = { "file": ( os.path.basename( path ), payload, "audio/wav" ) },
        headers = auth_headers,
        timeout = _UPLOAD_TIMEOUT_S,
    )
    assert resp.status_code == 200, f"transcription door answered {resp.status_code} — {resp.text[ :300 ]}"

    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    transcript = ( body if isinstance( body, str ) else str( body ) ).strip()

    tokens = words( transcript )
    assert _contains_in_order( tokens, _AFTER_THE_PAUSE ), (
        f"the words after the pause were dropped — got {transcript!r}. "
        f"If the model server predates 6e75695e, restart it before reading this as a regression."
    )
