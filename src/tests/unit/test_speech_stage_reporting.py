"""
Unit tests for stage-accurate failure reporting in the MP3 transcribe endpoint.

THE DEFECT (2026-07-25, GCP VM): a single `except Exception` spanned setup,
transcription AND post-processing, and reported all three as
"[ERROR] MP3 transcription failed". A missing contact-information.map printed
that line immediately AFTER the log had printed "Processed text: [...]" —
i.e. it blamed transcription on the line after proving transcription worked.
Debugging went to the model server and the Cloud Run key for an hour; the
fault was a config file.

These tests pin that the handler names the STAGE, so a post-transcription
fault can never again be reported as an ASR failure.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _endpoint():
    from cosa.rest.routers.speech import upload_and_transcribe_mp3_file
    return upload_and_transcribe_mp3_file


def _request_returning( payload: bytes ):
    req = MagicMock()
    req.body = AsyncMock( return_value=base64.b64encode( payload ) )
    return req


# The endpoint writes each upload into `speech upload temp dir` (row 27bcdd79),
# so every config key this fake is asked for answers with a per-test directory.
# A test that did not reach the save step would fail in "setup" for the wrong
# reason, which is why the two post-setup tests also check the file was written
# and then removed.
def _config_mgr( upload_dir ):
    cfg = MagicMock()
    cfg.get = MagicMock( return_value=str( upload_dir ) )
    return cfg


@pytest.mark.asyncio
async def test_post_transcription_failure_is_not_blamed_on_transcription( capsys, tmp_path ):
    """
    Transcription SUCCEEDS, post-processing raises. The log and the HTTP detail
    must both say post-processing — never 'transcription failed'.
    """
    provider = MagicMock()
    provider.transcribe = MagicMock( return_value="  testing one two three  " )

    with patch( "cosa.rest.routers.speech.mmm.MultiModalMunger",
                side_effect=FileNotFoundError( 2, "No such file or directory",
                                               "/var/lupin/src/conf/contact-information.map" ) ):
        with pytest.raises( HTTPException ) as exc:
            await _endpoint()(
                request          = _request_returning( b"fake-audio" ),
                whisper_pipeline = None,
                provider         = provider,
                config_mgr       = _config_mgr( tmp_path ),
                ask_flow         = MagicMock(),
                current_user     = { "uid": "u1", "email": "t@t.com" },
            )

    assert str( tmp_path ) in provider.transcribe.call_args.args[ 0 ], "setup must have saved the upload"
    assert list( tmp_path.iterdir() ) == [ ], "the upload must be removed after a post-processing failure"
    assert exc.value.status_code == 500
    detail = exc.value.detail
    assert "post-processing" in detail
    assert "transcribed"     in detail, "detail should state transcription SUCCEEDED"

    logged = capsys.readouterr().out
    assert "MP3 transcription failed" not in logged, \
        "the mislabel that sent debugging to the model server must not reappear"
    assert "post-processing" in logged


@pytest.mark.asyncio
async def test_transcription_failure_is_still_reported_as_transcription( capsys, tmp_path ):
    """
    The complement — without this, 'never say transcription failed' would be
    satisfiable by never naming transcription at all, which would be a
    different lie. A real ASR fault MUST still say so.
    """
    provider = MagicMock()
    provider.transcribe = MagicMock( side_effect=RuntimeError( "whisper exploded" ) )

    with pytest.raises( HTTPException ) as exc:
        await _endpoint()(
            request          = _request_returning( b"fake-audio" ),
            whisper_pipeline = None,
            provider         = provider,
            config_mgr       = _config_mgr( tmp_path ),
            ask_flow         = MagicMock(),
            current_user     = { "uid": "u1", "email": "t@t.com" },
        )

    assert list( tmp_path.iterdir() ) == [ ], "the upload must be removed after a transcription failure"
    assert exc.value.status_code == 500
    assert "transcription failed" in exc.value.detail.lower()
    assert "post-processing" not in exc.value.detail

    logged = capsys.readouterr().out
    assert "transcription" in logged


@pytest.mark.asyncio
async def test_setup_failure_names_setup_not_transcription( capsys ):
    """A fault BEFORE transcription must not be credited to it either."""
    provider = MagicMock()

    bad_cfg = MagicMock()
    bad_cfg.get = MagicMock( side_effect=KeyError( "speech upload temp dir" ) )
    with pytest.raises( HTTPException ) as exc:
        await _endpoint()(
            request          = _request_returning( b"fake-audio" ),
            whisper_pipeline = None,
            provider         = provider,
            config_mgr       = bad_cfg,
            ask_flow         = MagicMock(),
            current_user     = { "uid": "u1", "email": "t@t.com" },
        )

    logged = capsys.readouterr().out
    assert "setup" in logged
    assert "MP3 transcription failed" not in logged
    provider.transcribe.assert_not_called()
