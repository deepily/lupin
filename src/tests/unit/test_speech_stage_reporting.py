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


# The endpoint joins the REAL project root with this value. Patching
# get_project_root instead would break the ConfigurationManager, which reads
# src/conf/lupin-app.ini from that same root — the first attempt did exactly
# that and every test failed in "setup" for the wrong reason.
_TEST_RECORDING = "/io/_stage_reporting_test.mp3"


def _config_mgr():
    cfg = MagicMock()
    cfg.get = MagicMock( return_value=_TEST_RECORDING )
    return cfg


@pytest.fixture( autouse=True )
def _cleanup_recording():
    yield
    import cosa.utils.util as du
    import os
    stray = du.get_project_root() + _TEST_RECORDING
    if os.path.exists( stray ): os.remove( stray )


@pytest.mark.asyncio
async def test_post_transcription_failure_is_not_blamed_on_transcription( capsys ):
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
                config_mgr       = _config_mgr(),
                todo_queue       = MagicMock(),
            )

    assert exc.value.status_code == 500
    detail = exc.value.detail
    assert "post-processing" in detail
    assert "transcribed"     in detail, "detail should state transcription SUCCEEDED"

    logged = capsys.readouterr().out
    assert "MP3 transcription failed" not in logged, \
        "the mislabel that sent debugging to the model server must not reappear"
    assert "post-processing" in logged


@pytest.mark.asyncio
async def test_transcription_failure_is_still_reported_as_transcription( capsys ):
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
            config_mgr       = _config_mgr(),
            todo_queue       = MagicMock(),
        )

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
    bad_cfg.get = MagicMock( side_effect=KeyError( "path to audio recording file" ) )
    with pytest.raises( HTTPException ) as exc:
        await _endpoint()(
            request          = _request_returning( b"fake-audio" ),
            whisper_pipeline = None,
            provider         = provider,
            config_mgr       = bad_cfg,
            todo_queue       = MagicMock(),
        )

    logged = capsys.readouterr().out
    assert "setup" in logged
    assert "MP3 transcription failed" not in logged
    provider.transcribe.assert_not_called()
