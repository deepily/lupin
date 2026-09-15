"""Integration test — does ~32 kbps Ogg/Opus transcribe as well as the WAV it came from?

Row 9b1f7701. The lupin-mobile Android recorder ships WAV today, which is ~20x the bytes
of Opus at speech quality. Rick ruled the switch is allowed only if the transcripts survive
it, and ruled that this question gets answered as a PROPER TEST through the submit door on
:8000 — not as an ad hoc script somebody runs once and reports from memory.

WHAT IT MEASURES. For each real recording in LUPIN_OPUS_ACCURACY_DIR it sends the original
WAV and a mono 32 kbps Opus encode of that same WAV through the SAME door,
POST /api/upload-and-transcribe-wav, and diffs the two transcripts word by word. The WAV
transcript is the reference; the criterion is the pooled corpus word error rate.

WHY THE WAV TRANSCRIPT IS THE REFERENCE AND NOT A HUMAN ONE. The question on the table is
not "is Whisper accurate" — it is "does the codec change the answer". Referencing the WAV
transcript isolates exactly the codec's contribution and needs no hand-typed ground truth,
which is the part nobody would keep up to date.

WHAT IT CANNOT SEE. Whisper is not bit-deterministic, so a small nonzero WER is the floor
even for two runs on identical audio — the threshold below is set above that floor on
purpose. And it compares only WORDING: case and punctuation are folded away, because those
vary run to run and a criterion that counted them would be measuring the transcriber's mood.

WHY THE RECORDINGS ARE NOT IN THE REPO. They are real speech recorded on a real handset via
the app's "Keep voice recordings" switch. With the env var unset the whole file SKIPS — it
never synthesises audio and never passes vacuously, because a green that proves nothing is
worse here than a skip that says so.

Venue: :8000 only. It spends real transcription on the server's own stack and writes an
InputAndOutputTable row per request (two per recording), so it is not :7999-eligible under
the CLAUDE.md § Testing venues rubric. Submit via POST /api/test-suite/submit on a
verified-idle server (`PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000`, exit 0).

⚠️ LUPIN_OPUS_ACCURACY_DIR is read by the PYTEST PROCESS the test-suite runner spawns on the
server, so it must be exported where that runner lives, and the directory must be readable
from there. A repo-relative value starting /src/ or /io/ is joined to the project root, which
is the easy way to hand it a path both sides agree on (io/ is gitignored).
"""

import os
import subprocess

import pytest
import requests

import cosa.utils.util as cu

from tests.helpers.opus_accuracy import (
    build_opus_command,
    corpus_word_error_rate,
    ffmpeg_has_libopus,
    list_wav_files,
    resolve_recordings_dir,
    word_diff,
    word_error_rate,
    words,
)


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_TRANSCRIBE = f"{BASE_URL}/api/upload-and-transcribe-wav"

_RECORDINGS_ENV = "LUPIN_OPUS_ACCURACY_DIR"

# ── THE CRITERION ────────────────────────────────────────────────────────────────────────
# Row 9b1f7701's switch-the-recorder criterion: the Android app may move from WAV to 32 kbps
# Opus iff the pooled corpus word error rate against the WAV transcripts stays at or under
# this. 5% is one changed word in twenty. Chosen for two reasons and not as a round number:
# libopus at 32 kbps mono with the voip tuning is near-transparent for speech, so a real
# codec regression lands far above 5% rather than just over it; and Whisper's own run-to-run
# variation puts a small nonzero floor under any comparison, which a 1% bar would trip on
# noise alone. Tighten it only with measurements in hand, never to look strict.
MAX_CORPUS_WER = 0.05

_OPUS_BITRATE     = "32k"
_OPUS_APPLICATION = "voip"

_UPLOAD_TIMEOUT_S = 300


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once → {"Authorization": "Bearer ..."}, so both uploads are attributed to one user."""
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


@pytest.fixture( scope="module" )
def recordings_dir():
    """
    The directory of real WAV recordings, or a skip that says exactly what to set.

    Ensures:
        - skips when LUPIN_OPUS_ACCURACY_DIR is unset, empty or whitespace
        - fails (does NOT skip) when it is set but names nothing usable — the operator
          asked for this run, so a typo'd path is a red, not a quiet pass
    """
    resolved = resolve_recordings_dir( os.environ.get( _RECORDINGS_ENV ), cu.get_project_root() )
    if resolved is None:
        pytest.skip(
            f"{_RECORDINGS_ENV} is not set. This test needs REAL recordings — it will not "
            f"synthesise audio. Record ~10 questions on the handset with Settings → "
            f"\"Keep voice recordings\" on, pull them off the device, and point the runner at "
            f"the directory holding the .wav files, e.g. "
            f"{_RECORDINGS_ENV}=/io/opus-accuracy/recordings (a value starting /src/ or /io/ "
            f"is taken as project-relative) or an absolute host path. It must be exported "
            f"where the test-suite runner's pytest process runs, not only in your shell."
        )

    if not os.path.isdir( resolved ):
        pytest.fail( f"{_RECORDINGS_ENV} points at {resolved}, which is not a directory" )

    wavs = list_wav_files( resolved )
    if not wavs:
        pytest.fail( f"{_RECORDINGS_ENV} points at {resolved}, which holds no .wav files" )

    return resolved, wavs


@pytest.fixture( scope="module" )
def ffmpeg_with_libopus():
    """Skip cleanly when the host ffmpeg cannot encode Opus — nothing to compare without it."""
    try:
        probe = subprocess.run(
            [ "ffmpeg", "-hide_banner", "-encoders" ],
            capture_output = True, text = True, timeout = 30
        )
    except FileNotFoundError:
        pytest.skip( "ffmpeg is not on PATH — install ffmpeg built with libopus to run this test" )
    except subprocess.TimeoutExpired:
        pytest.skip( "ffmpeg -encoders did not answer within 30s" )

    if not ffmpeg_has_libopus( probe.stdout ):
        pytest.skip(
            "this ffmpeg has no libopus encoder (ffmpeg -encoders lists no 'libopus') — "
            "install an ffmpeg built with libopus to run this test"
        )
    return True


def _probe_wav( path ):
    """
    Sample rate, channel count and duration of a PCM WAV.

    Requires:
        - path names a readable RIFF/WAVE file

    Ensures:
        - returns ( rate_hz, channels, duration_seconds )

    Raises:
        - wave.Error if the file is not a readable PCM WAV
    """
    import wave
    with wave.open( path, "rb" ) as handle:
        rate     = handle.getframerate()
        channels = handle.getnchannels()
        frames   = handle.getnframes()
    return rate, channels, ( frames / rate if rate else 0.0 )


def _transcribe( path, content_type, headers ):
    """
    POST one audio file to the transcription door and return the transcript.

    Requires:
        - path is readable, headers carries a valid bearer token

    Ensures:
        - returns the transcript as a stripped str
        - the door answers a bare JSON string, so the body is decoded rather than
          pattern-matched out of the raw text

    Raises:
        - AssertionError on any non-200, naming the file and the body
    """
    with open( path, "rb" ) as handle:
        payload = handle.read()

    resp = requests.post(
        _TRANSCRIBE,
        files   = { "file": ( os.path.basename( path ), payload, content_type ) },
        headers = headers,
        timeout = _UPLOAD_TIMEOUT_S,
    )
    assert resp.status_code == 200, (
        f"{os.path.basename( path )}: transcription door answered "
        f"{resp.status_code} — {resp.text[ :300 ]}"
    )

    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    return ( body if isinstance( body, str ) else str( body ) ).strip()


def _encode_all( recordings_dir, out_dir ):
    """
    Encode every recording to mono 32 kbps Ogg/Opus and report what each one cost.

    Requires:
        - recordings_dir holds the .wav files, out_dir is writable

    Ensures:
        - returns ( rows, last_command ) with one row per recording, each carrying
          file / rate_hz / channels / seconds / wav_kb / opus_kb / shrink_x and both paths
        - exactly one ffmpeg invocation per recording

    Raises:
        - subprocess.CalledProcessError if any encode fails
    """
    directory, wavs = recordings_dir
    rows, command   = [], None

    for name in wavs:
        src                 = os.path.join( directory, name )
        dst                 = os.path.join( out_dir, os.path.splitext( name )[ 0 ] + ".ogg" )
        rate, channels, dur = _probe_wav( src )
        command             = build_opus_command( src, dst, rate, _OPUS_BITRATE, _OPUS_APPLICATION )
        subprocess.run( command, check=True, capture_output=True, text=True )

        wav_kb  = os.path.getsize( src ) / 1024
        opus_kb = os.path.getsize( dst ) / 1024
        rows.append( {
            "file"      : name,
            "rate_hz"   : rate,
            "channels"  : channels,
            "seconds"   : dur,
            "wav_kb"    : wav_kb,
            "opus_kb"   : opus_kb,
            "shrink_x"  : ( wav_kb / opus_kb ) if opus_kb else 0.0,
            "wav_path"  : src,
            "opus_path" : dst,
        } )

    return rows, command


def _print_encode_table( rows, command, out_dir ):
    """Print the encode summary: the exact ffmpeg line, then a row per recording."""
    print( "\nENCODE — WAV → mono Ogg/Opus" )
    print( f"  command : {' '.join( command )}" )
    print( f"  output  : {out_dir}\n" )

    header = f"{'file':<34}{'secs':>7}{'rate':>8}{'ch':>4}{'wav kB':>10}{'opus kB':>10}{'shrink':>9}"
    print( header )
    print( "-" * len( header ) )
    for row in rows:
        print(
            f"{row[ 'file' ][ :33 ]:<34}{row[ 'seconds' ]:>7.1f}{row[ 'rate_hz' ]:>8}"
            f"{row[ 'channels' ]:>4}{row[ 'wav_kb' ]:>10.1f}{row[ 'opus_kb' ]:>10.1f}"
            f"{row[ 'shrink_x' ]:>8.1f}x"
        )

    total_wav  = sum( row[ "wav_kb" ]  for row in rows )
    total_opus = sum( row[ "opus_kb" ] for row in rows )
    print( "-" * len( header ) )
    print(
        f"{f'TOTAL {len( rows )} files':<34}{sum( row[ 'seconds' ] for row in rows ):>7.1f}"
        f"{'':>8}{'':>4}{total_wav:>10.1f}{total_opus:>10.1f}"
        f"{( total_wav / total_opus if total_opus else 0.0 ):>8.1f}x"
    )


def _print_accuracy_table( rows, corpus_wer, total_ref ):
    """Print the per-file word error table, the corpus line, then the word-level diffs."""
    print( "\nACCURACY — Opus transcript vs WAV transcript (WAV is the reference)\n" )

    header = f"{'file':<34}{'wav wds':>9}{'opus wds':>10}{'sub':>6}{'del':>6}{'ins':>6}{'WER':>9}"
    print( header )
    print( "-" * len( header ) )
    for row in rows:
        print(
            f"{row[ 'file' ][ :33 ]:<34}{row[ 'wav_words' ]:>9}{row[ 'opus_words' ]:>10}"
            f"{row[ 'subs' ]:>6}{row[ 'dels' ]:>6}{row[ 'ins' ]:>6}{row[ 'wer' ] * 100:>8.1f}%"
        )

    identical = sum( 1 for row in rows if row[ "wer" ] == 0.0 )
    print( "-" * len( header ) )
    print(
        f"{'CORPUS':<34}{total_ref:>9}{sum( row[ 'opus_words' ] for row in rows ):>10}"
        f"{'':>18}{corpus_wer * 100:>8.1f}%"
    )
    print( f"\nidentical transcripts: {identical}/{len( rows )}   threshold: {MAX_CORPUS_WER * 100:.1f}%" )

    print( "\nWORD-LEVEL DIFFS" )
    for row in rows:
        if not row[ "diff" ]:
            print( f"  {row[ 'file' ]}: identical" )
            continue
        print( f"  {row[ 'file' ]}  WER {row[ 'wer' ] * 100:.1f}%" )
        for line in row[ "diff" ]: print( line )


def test_opus_transcribes_as_well_as_wav( recordings_dir, ffmpeg_with_libopus, auth_headers, tmp_path ):
    """
    The switch-the-recorder criterion: 32 kbps Opus must not change what the server hears.

    Requires:
        - LUPIN_OPUS_ACCURACY_DIR names a directory of real .wav recordings
        - ffmpeg with libopus on PATH, and a live server at BASE_URL

    Ensures:
        - each recording is encoded once and both versions go through the same door
        - a per-file table, a corpus word error rate and a word-level diff are printed
        - fails naming the worst file when the corpus WER exceeds MAX_CORPUS_WER
    """
    out_dir      = str( tmp_path / "opus" )
    os.makedirs( out_dir, exist_ok=True )
    rows, command = _encode_all( recordings_dir, out_dir )
    _print_encode_table( rows, command, out_dir )

    print( f"\nTRANSCRIBE via {_TRANSCRIBE}  ({2 * len( rows )} uploads)" )
    for row in rows:
        wav_text  = _transcribe( row[ "wav_path"  ], "audio/wav", auth_headers )
        opus_text = _transcribe( row[ "opus_path" ], "audio/ogg", auth_headers )

        reference, hypothesis          = words( wav_text ), words( opus_text )
        wer, subs, dels, ins           = word_error_rate( reference, hypothesis )
        row[ "wav_text"   ]            = wav_text
        row[ "opus_text"  ]            = opus_text
        row[ "wav_words"  ]            = len( reference )
        row[ "opus_words" ]            = len( hypothesis )
        row[ "wer"        ]            = wer
        row[ "subs"       ]            = subs
        row[ "dels"       ]            = dels
        row[ "ins"        ]            = ins
        row[ "diff"       ]            = word_diff( reference, hypothesis )

    corpus_wer, total_ref, total_err = corpus_word_error_rate( rows )
    _print_accuracy_table( rows, corpus_wer, total_ref )

    assert total_ref > 0, (
        "every WAV transcript came back empty — the door returned no words at all, so there "
        "is nothing to compare and a pass here would mean nothing"
    )

    worst = max( rows, key=lambda row: row[ "wer" ] )
    assert corpus_wer <= MAX_CORPUS_WER, (
        f"Opus is not accurate enough to switch the recorder (row 9b1f7701): corpus WER "
        f"{corpus_wer * 100:.1f}% over {len( rows )} recordings exceeds the "
        f"{MAX_CORPUS_WER * 100:.1f}% criterion ({total_err} word errors in {total_ref} "
        f"reference words). Worst file: {worst[ 'file' ]} at {worst[ 'wer' ] * 100:.1f}% "
        f"({worst[ 'subs' ]} sub / {worst[ 'dels' ]} del / {worst[ 'ins' ]} ins)\n"
        f"  wav : {worst[ 'wav_text'  ]}\n"
        f"  opus: {worst[ 'opus_text' ]}"
    )
