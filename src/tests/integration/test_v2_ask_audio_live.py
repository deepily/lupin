"""Integration test — the spoken-ask door, POST /api/v2/ask-audio, against the running server.

Plan: lupin-mobile `src/rnd/2026.09.11-spoken-ask-streamed-door-implementation-plan.md` §2.4,
the Integration row. The unit tier (`src/tests/unit/test_v2_ask_audio.py`) drives the handler
with a fake flow and a fake transcriber, so it cannot see three things this file exists for:

  · the REAL transcriber turning real speech into text on the server's own stack;
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

⚠️ ROUTING IS NOT MEASURED. Case 1 needs line 2 to carry a `job_id`, which means the router must
route the clip's sentence ("Imagine you launch an automated software engineering job at 8 p.m.
before going to bed.") to an agent and hand it to the queue. That was not measured before this
file was written: the router's model path is only set inside the server container. If it routes
somewhere that makes no job, the assertion fails and prints the whole result rather than
skipping — a measured answer to pick a different clip from, not a flake.

Under monopolize the suite holds the queue's consumer, so the handed-off job waits in `todo`
and the cancel removes it outright ("cancelled"). On a box with a free consumer it may have
started, and a graceful stop ("cancel_requested") is the same claim. Either way the teardown
drops anything left in `todo`, so this file leaves no queued work behind (row ff4166d9).

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

# The 5 s clip is the committed real-speech recording from the 2026-09-10 transcription
# measurement; the 3 s Ogg/Opus clip was cut from it with /usr/bin/ffmpeg
# (-t 3 -ac 1 -c:a libopus -b:a 24k, bitexact), sha256 f50f8f1f…ebfe8.
_WAV_5S  = "/src/rnd/assets/2026.09.10-voice-real-speech-measurement/speech-5s.wav"
_OGG_3S  = "/src/tests/fixtures/audio/speech-3s.ogg"

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
    Case 1: the 5 s WAV gives a transcript line, then an `ask` line whose `job_id` the cancel
    endpoint accepts.

    RED WHEN: the door stops streaming NDJSON (media type), line 2 comes first or not at all, the
    transcriber returns nothing for real speech, the ask is not serialised through AskResponse,
    or the job_id is not one the queue knows.
    """
    job_id = None
    try:
        resp, lines, _elapsed = _ask_audio( _WAV_5S, "speech-5s.wav", "audio/wav", auth_headers )
        assert resp.status_code == 200, f"ask-audio: {resp.status_code} {resp.text}"
        assert resp.headers[ "content-type" ].startswith( "application/x-ndjson" ), resp.headers

        assert len( lines ) == 2, f"expected exactly two NDJSON lines, got {len( lines )}: {lines}"
        first, second = lines
        assert first[ "type" ] == "transcript", f"line 1 must be the transcript: {first}"
        assert first[ "transcription" ].strip(), f"real speech transcribed to nothing: {first}"
        assert second[ "type" ] == "ask", f"line 2 must be the ask result, not an error: {second}"

        result = second[ "result" ]
        job_id = result.get( "job_id" )
        assert job_id, (
            f"line 2 carried no job_id, so there is nothing to cancel. The router did not hand "
            f"{first[ 'transcription' ]!r} to the queue — routing for this clip was never measured "
            f"(see the module docstring). Whole result: {result}"
        )

        cancel = requests.post( f"{BASE_URL}/api/jobs/{job_id}/cancel", headers=auth_headers, timeout=30 )
        assert cancel.status_code == 200, f"cancel {job_id}: {cancel.status_code} {cancel.text}"
        assert cancel.json()[ "status" ] in _CANCELLED, f"cancel did not take: {cancel.json()}"
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )


def test_an_ogg_opus_clip_is_transcribed_by_the_real_transcriber( auth_headers ):
    """
    Case 2: a 3 s Ogg/Opus clip, cut from the same recording, gives a non-empty transcript line.
    This is the format-agnostic claim, proven with a real decoder rather than a fake.

    Its ask still runs and may queue a job; that job is cancelled and dropped here too, because
    this case is about the transcript and must not leave work behind.

    RED WHEN: the upload suffix is lost (the transcriber is handed Opus bytes under a `.wav`
    name), the server cannot decode Ogg/Opus, or the door answers non-200 for a non-WAV body.
    """
    job_id = None
    try:
        resp, lines, _elapsed = _ask_audio( _OGG_3S, "speech-3s.ogg", "audio/ogg", auth_headers )
        assert resp.status_code == 200, f"ask-audio (ogg): {resp.status_code} {resp.text}"
        assert lines, "the door answered 200 with no lines at all"
        assert lines[ 0 ][ "type" ] == "transcript", f"line 1 must be the transcript: {lines[ 0 ]}"
        assert lines[ 0 ][ "transcription" ].strip(), f"Ogg/Opus speech transcribed to nothing: {lines[ 0 ]}"

        if len( lines ) > 1 and lines[ 1 ][ "type" ] == "ask":
            job_id = lines[ 1 ][ "result" ].get( "job_id" )
            if job_id:
                requests.post( f"{BASE_URL}/api/jobs/{job_id}/cancel", headers=auth_headers, timeout=30 )
    finally:
        drop_from_todo( BASE_URL, job_id, auth_headers )
