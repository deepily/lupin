"""Integration test — the spoken-ask door, POST /api/v2/ask-audio, against the running server.

Plan: lupin-mobile `src/rnd/2026.09.11-spoken-ask-streamed-door-implementation-plan.md` §2.4,
the Integration row. The unit tier (`src/tests/unit/test_v2_ask_audio.py`) drives the handler
with a fake flow and a fake transcriber, so it cannot see three things this file exists for:

  · the REAL transcriber turning speech into text on the server's own stack;
  · a format other than WAV surviving the upload — the door promises to accept any audio, and
    only a real decoder can prove that about an Ogg/Opus body;
  · the two NDJSON lines arriving over a real HTTP connection, in order, and line 2's `job_id`
    being a job the queue will actually let you cancel.

WHAT "LINE 1 BEFORE THE BODY CLOSES" MEANS AT THIS ALTITUDE, stated so nobody reads more into a
green than it holds. The response is read as a stream and each line is taken as it arrives; the
test asserts the transcript line is a complete line of its own and comes first. It does NOT prove
the timing — that the ask was already started when line 1 left the server. That is D4, and it is
proven a tier down by the unit file's five arms, where the ordering can be controlled. The
elapsed time to each line is printed so a run's log carries the measurement anyway.

WHY THE CLIP ASKS THE TIME — a harmless question with a measured route. The first version of
this file used a real-speech sentence about launching "an automated software engineering job",
and the router's command list includes `claude code` and `automatic`, so a live run could have
started real work with real spend (John's review, Mr. Radio's ruling, 2026-09-14). Both clips now
say "What time is it?", and every link from the audio to a cancellable job was measured on
2026-09-14 in the `lupin-rest-dev` container, which shares `lupin-model-server` and the router
LoRA with the test server:

  · transcription: both clips → " What time is it?", two runs each, through the container's
    SpeechToTextProvider — the server's own transcriber;
  · routing: "What time is it?" → `agent router go to datetime`, three of three, through
    `RouterClient.route` — the router v2 uses; the old sentence routed to `none`;
  · the flow: that spec declares no required args, so `ask` goes straight to the executor
    (`args_none`), and `[Lupin: Testing]` inherits `v2 executor = queued`, so line 2 is
    `status="waiting"` with a `job_id`;
  · the cancel: `POST /api/jobs/{id}/cancel` accepts a todo or running job and answers 404 for
    one that has already finished.

⚠️ Measured on the DEV container, not on :8000 itself, which only takes suite submissions.
If the test server's router or transcriber differs, case 1 fails on the named command and prints
the whole result — a different clip is the fix, never a looser assertion.

Under monopolize the suite holds the queue's consumer, so the handed-off job waits in `todo`
and the cancel removes it outright ("cancelled"). On a box with a free consumer a date-and-time
job can finish before the cancel lands, and the cancel would then answer 404 — this file assumes
the monopolize hold it is submitted under. Either way the teardown drops anything left in `todo`,
so this file leaves no queued work behind (row ff4166d9).

Venue: :8000 only — it spends real transcription, writes io rows and enqueues a job. Submit via
POST /api/test-suite/submit on a verified-idle server (`cosa.rest.venue_idle --port 8000` exit 0),
after §A's merge and refresh. Never run by hand against :7999.
"""

import json
import os
import time
import uuid

import pytest
import requests

import cosa.utils.util as cu

from tests.integration.v2_queued import drop_from_todo


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_ASK_AUDIO = f"{BASE_URL}/api/v2/ask-audio"

# Both clips say "What time is it?": synthesized with gTTS 2.5.4 (the lupin-mobile precedent,
# test/fixtures/asr/canned-focus-mode-test.provenance.json), then /usr/bin/ffmpeg 4.4.2, bitexact.
#   WAV: -ar 44100 -ac 1 -sample_fmt s16      1.248 s  sha256 fd3489e96c50633e2c18499f9abaae5072f7d96c20867bb56af9e0d2e672786d
#   Ogg: -ac 1 -c:a libopus -b:a 24k          1.2545 s sha256 059a856c1b64228e7816b4b57dabaea522ad6e4793b327b1db3d4f291395d2fe
_WAV = "/src/tests/fixtures/audio/what-time-is-it.wav"
_OGG = "/src/tests/fixtures/audio/what-time-is-it.ogg"

_DATETIME  = "agent router go to datetime"
_CANCELLED = { "cancelled", "cancel_requested" }


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once → {"Authorization": "Bearer ..."}. /api/v2/ask-audio is JWT-guarded."""
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


def _ask_audio( path, filename, content_type, headers ):
    """
    POST one clip to the door and read the NDJSON reply line by line as it arrives.

    Requires:
        - path is a project-relative audio path starting with /src/
        - headers carries a valid bearer token

    Ensures:
        - returns ( response, lines, elapsed ) where lines is every decoded JSON line in arrival
          order and elapsed is the seconds from send to each line
        - speak and interactive are off, and websocket_id is a fresh id nobody listens on, so the
          ask speaks nothing and asks nothing back
    """
    params = { "websocket_id": f"itest-ask-audio-{uuid.uuid4().hex[ :8 ]}", "speak": "false", "interactive": "false" }
    with open( cu.get_project_root() + path, "rb" ) as f:
        audio = f.read()
    started = time.monotonic()
    resp    = requests.post(
        _ASK_AUDIO,
        params  = params,
        files   = { "file": ( filename, audio, content_type ) },
        headers = headers,
        stream  = True,
        timeout = 240,
    )
    lines, elapsed = [ ], [ ]
    if resp.status_code == 200:
        for raw in resp.iter_lines():
            if not raw: continue
            lines.append( json.loads( raw ) )
            elapsed.append( round( time.monotonic() - started, 3 ) )
    resp.close()
    print( f"[ask-audio] {filename}: status={resp.status_code} lines={len( lines )} elapsed_s={elapsed}" )
    return resp, lines, elapsed


def test_a_spoken_wav_streams_its_transcript_first_and_hands_a_cancellable_job_to_the_queue( auth_headers ):
    """
    Case 1: the WAV gives a transcript line, then an `ask` line that names the date-and-time agent
    and carries a `job_id` the cancel endpoint accepts.

    RED WHEN: the door stops streaming NDJSON (media type), line 2 comes first or not at all, the
    transcriber mishears the question, the ask is not serialised through AskResponse, the router
    sends the question anywhere but date-and-time, or the job_id is not one the queue knows.
    """
    job_id = None
    try:
        resp, lines, _elapsed = _ask_audio( _WAV, "what-time-is-it.wav", "audio/wav", auth_headers )
        assert resp.status_code == 200, f"ask-audio: {resp.status_code} {resp.text}"
        assert resp.headers[ "content-type" ].startswith( "application/x-ndjson" ), resp.headers

        assert len( lines ) == 2, f"expected exactly two NDJSON lines, got {len( lines )}: {lines}"
        first, second = lines
        assert first[ "type" ] == "transcript", f"line 1 must be the transcript: {first}"
        assert "time" in first[ "transcription" ].lower(), f"the clip says 'What time is it?': {first}"
        assert second[ "type" ] == "ask", f"line 2 must be the ask result, not an error: {second}"

        result = second[ "result" ]
        job_id = result.get( "job_id" )
        assert result[ "command" ] == _DATETIME and result[ "path" ] in ( "agent", "replay" ), (
            f"the question must route to the date-and-time agent, as measured in the dev container "
            f"(module docstring). Anything else is a different clip's problem, never a looser "
            f"assertion. Whole result: {result}"
        )
        assert result[ "status" ] == "waiting" and job_id, (
            f"a queued executor hands the ask off with a job_id; got none to cancel: {result}"
        )

        cancel = requests.post( f"{BASE_URL}/api/jobs/{job_id}/cancel", headers=auth_headers, timeout=30 )
        assert cancel.status_code == 200, f"cancel {job_id}: {cancel.status_code} {cancel.text}"
        assert cancel.json()[ "status" ] in _CANCELLED, f"cancel did not take: {cancel.json()}"
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )


def test_an_ogg_opus_clip_is_transcribed_by_the_real_transcriber( auth_headers ):
    """
    Case 2: the same question as Ogg/Opus gives a transcript line that heard it. This is the
    format-agnostic claim, proven with a real decoder rather than a fake.

    Its ask still runs and queues a date-and-time job; that job is cancelled and dropped here too,
    because this case is about the transcript and must not leave work behind.

    RED WHEN: the upload suffix is lost (the transcriber is handed Opus bytes under a `.wav`
    name), the server cannot decode Ogg/Opus, or the door answers non-200 for a non-WAV body.
    """
    job_id = None
    try:
        resp, lines, _elapsed = _ask_audio( _OGG, "what-time-is-it.ogg", "audio/ogg", auth_headers )
        assert resp.status_code == 200, f"ask-audio (ogg): {resp.status_code} {resp.text}"
        assert lines, "the door answered 200 with no lines at all"
        assert lines[ 0 ][ "type" ] == "transcript", f"line 1 must be the transcript: {lines[ 0 ]}"
        assert "time" in lines[ 0 ][ "transcription" ].lower(), f"the Ogg clip says 'What time is it?': {lines[ 0 ]}"

        if len( lines ) > 1 and lines[ 1 ][ "type" ] == "ask":
            job_id = lines[ 1 ][ "result" ].get( "job_id" )
            if job_id:
                requests.post( f"{BASE_URL}/api/jobs/{job_id}/cancel", headers=auth_headers, timeout=30 )
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )
