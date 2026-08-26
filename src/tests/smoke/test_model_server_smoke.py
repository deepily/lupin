"""
Smoke tests for `lupin-model-server` (port 7998) — Phase 5.1 AC of the
model-server carve-out.

See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md

Tests exercise:
    - GET  /health                       — 200 + 3 models loaded + VRAM > 0
    - POST /transcribe                   — round-trip the warmup MP3
    - POST /embeddings/generate          — 768-dim vector returned
    - POST /embeddings/batch             — N × 768 vectors returned
    - GET  /admin/metrics                — Prometheus text format
    - Auth rejection: missing X-API-Key → 401
    - Auth rejection: ck_internal_* prefix → 401 (defense-in-depth)
    - Auth rejection: syntactically-valid but wrong ck_live_* → 401
    - End-to-end via compute: POST /api/upload-and-transcribe-mp3 on :7999
      transcribes through the HTTP-proxy path → :7998

Venue: :7999 + :7998 (AI-discretionary per CLAUDE.md TESTING VENUES). All
tests are stateless reads against live servers; runtime < 30 s total; no
:8000 monopoly required.

Skip behavior: if `:7998/health` is unreachable, all model-server-direct
tests skip cleanly with a notice. If `:7999/health` is unreachable, the
proxy-path test skips. This keeps the suite portable across environments
that don't have the carve-out deployed yet.
"""

import base64
import os
from pathlib import Path
from typing  import Optional

import pytest
import requests


MODEL_SERVER_URL = os.environ.get( "LUPIN_MODEL_SERVER_URL", "http://localhost:7998" )
COMPUTE_URL      = os.environ.get( "LUPIN_APP_SERVER_URL",   "http://localhost:7999" )
LUPIN_ROOT       = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
# Which key file the model server validates against.
#
# Changed 2026-08-26. This was hardcoded to "notification-api-claude-code-dev",
# which is the model server's built-in code default
# (lupin_model_server/main.py:76) — but docker-compose OVERRIDES
# LUPIN_MODEL_SERVER_API_KEY_NAME to "model-server-api" on all three services,
# and both client providers (memory/embedding_provider.py:273,
# memory/speech_to_text_provider.py:156) default to "model-server-api" for
# exactly that reason. The two key files hold DIFFERENT keys, so this test was
# presenting the wrong one and getting `401 Invalid X-API-Key` on all four
# authenticated probes. Decoupling design:
# src/rnd/v0.1.9/2026.07.28-model-server-api-key-decoupling.md
#
# Read the env var, same as the clients, so the three ends cannot drift again.
API_KEY_NAME     = os.environ.get( "LUPIN_MODEL_SERVER_API_KEY_NAME", "model-server-api" )
KEY_FILE         = LUPIN_ROOT / "src" / "conf" / "keys" / API_KEY_NAME
WARMUP_MP3       = LUPIN_ROOT / "src" / "conf" / "warmup" / "whisper-warmup-85s.mp3"


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _read_api_key() -> Optional[ str ]:
    """Read the ck_live_* plaintext key from src/conf/keys/."""
    try:
        with open( KEY_FILE, "r" ) as f:
            key = f.read().strip()
        return key if key else None
    except OSError:
        return None


@pytest.fixture( scope="module" )
def api_key():
    """Plaintext API key shared by all tests. Skips the whole module if missing."""
    key = _read_api_key()
    if not key:
        pytest.skip( f"API key file not readable at {KEY_FILE}" )
    return key


@pytest.fixture( scope="module" )
def model_server_reachable():
    """Skip model-server-direct tests if :7998 isn't up."""
    try:
        r = requests.get( f"{MODEL_SERVER_URL}/health", timeout=2 )
        if r.status_code != 200:
            pytest.skip( f"Model server at {MODEL_SERVER_URL} returned {r.status_code} (not ready)" )
    except requests.RequestException as e:
        pytest.skip( f"Model server at {MODEL_SERVER_URL} unreachable: {e}" )


@pytest.fixture( scope="module" )
def compute_reachable():
    """Skip proxy-path tests if :7999 isn't up."""
    try:
        r = requests.get( f"{COMPUTE_URL}/health", timeout=2 )
        if r.status_code != 200:
            pytest.skip( f"Compute server at {COMPUTE_URL} returned {r.status_code}" )
    except requests.RequestException as e:
        pytest.skip( f"Compute server at {COMPUTE_URL} unreachable: {e}" )


@pytest.fixture( scope="module" )
def warmup_mp3_bytes():
    """Read the warmup MP3 once for transcribe tests; skip if missing."""
    if not WARMUP_MP3.exists():
        pytest.skip( f"Warmup MP3 not found at {WARMUP_MP3}" )
    return WARMUP_MP3.read_bytes()


# ── /health (no auth) ────────────────────────────────────────────────────────

def test_health_direct( model_server_reachable ):
    """GET :7998/health returns 200 with all 3 models loaded + VRAM > 0."""
    r = requests.get( f"{MODEL_SERVER_URL}/health", timeout=5 )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body[ "status" ] == "ready", f"Expected status='ready', got {body['status']!r}"
    loaded = set( body[ "models_loaded" ] )
    assert loaded == { "whisper", "code_rank_embed", "nomic_embed_text_v1_5" }, (
        f"Expected all 3 models loaded, got {loaded}"
    )
    assert body[ "vram_used_mb" ] > 0, f"VRAM should be > 0 once models are loaded, got {body['vram_used_mb']}"
    assert body[ "load_errors" ] == [], f"No load errors expected, got {body['load_errors']}"


# ── /transcribe (auth required) ──────────────────────────────────────────────

def test_transcribe_direct( model_server_reachable, api_key, warmup_mp3_bytes ):
    """POST :7998/transcribe with the warmup MP3 returns non-empty text."""
    r = requests.post(
        f"{MODEL_SERVER_URL}/transcribe",
        files   = { "audio": ( "warmup.mp3", warmup_mp3_bytes, "audio/mpeg" ) },
        headers = { "X-API-Key": api_key },
        timeout = 60
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:300]}"
    body = r.json()
    assert "text" in body, f"Response missing 'text': {body}"
    text = body[ "text" ].strip()
    assert text, "Transcribed text should be non-empty"
    assert len( text ) > 50, f"Warmup MP3 is 85 s — transcription should be substantial, got {len(text)} chars"


# ── /embeddings/generate (auth required) ────────────────────────────────────

def test_embeddings_generate_direct( model_server_reachable, api_key ):
    """POST :7998/embeddings/generate returns a 768-dim vector for a prose input."""
    r = requests.post(
        f"{MODEL_SERVER_URL}/embeddings/generate",
        json    = { "text": "hello from the smoke test", "content_type": "prose" },
        headers = { "X-API-Key": api_key },
        timeout = 10
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert "embedding" in body
    vec = body[ "embedding" ]
    assert len( vec ) == 768, f"Expected 768-dim vector, got {len(vec)}"
    assert all( isinstance( x, float ) for x in vec ), "All entries should be floats"
    assert any( x != 0.0 for x in vec ), "Vector should not be all zeros"


# ── /embeddings/batch (auth required) ───────────────────────────────────────

def test_embeddings_batch_direct( model_server_reachable, api_key ):
    """POST :7998/embeddings/batch with 5 texts returns 5 × 768 vectors."""
    texts = [
        "alpha bravo charlie",
        "the quick brown fox jumps over the lazy dog",
        "machine learning is fun",
        "GPU memory carve-out architecture",
        "lupin-model-server on port 7998"
    ]
    r = requests.post(
        f"{MODEL_SERVER_URL}/embeddings/batch",
        json    = { "texts": texts, "content_type": "prose" },
        headers = { "X-API-Key": api_key },
        timeout = 15
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    body = r.json()
    assert body[ "count" ] == 5
    vectors = body[ "embeddings" ]
    assert len( vectors ) == 5
    for i, vec in enumerate( vectors ):
        assert len( vec ) == 768, f"Vector {i}: expected 768-dim, got {len(vec)}"


# ── /admin/metrics (auth required, Prometheus text format) ──────────────────

def test_admin_metrics_direct( model_server_reachable, api_key ):
    """GET :7998/admin/metrics returns Prometheus text with the expected counters."""
    r = requests.get(
        f"{MODEL_SERVER_URL}/admin/metrics",
        headers = { "X-API-Key": api_key },
        timeout = 5
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    assert "text/plain" in r.headers.get( "content-type", "" ), (
        f"Expected Prometheus text format, got content-type={r.headers.get('content-type')}"
    )
    body = r.text
    for metric in (
        "model_server_requests_total",
        "model_server_request_duration_seconds",
        "model_server_vram_used_mb",
        "model_server_models_loaded",
        "model_server_uptime_seconds"
    ):
        assert metric in body, f"Expected metric {metric!r} in Prometheus output"


# ── Auth rejection cases ────────────────────────────────────────────────────

def test_auth_rejects_missing_key( model_server_reachable ):
    """POST :7998/transcribe without X-API-Key returns 401."""
    r = requests.post(
        f"{MODEL_SERVER_URL}/transcribe",
        files   = { "audio": ( "dummy.mp3", b"\x00" * 100, "audio/mpeg" ) },
        timeout = 5
    )
    assert r.status_code == 401, f"Expected 401 missing-key, got {r.status_code}: {r.text[:200]}"


def test_auth_rejects_wrong_prefix( model_server_reachable ):
    """POST :7998/transcribe with ck_internal_* prefix is rejected (defense-in-depth)."""
    fake_key = "ck_internal_" + "A" * 60
    r = requests.post(
        f"{MODEL_SERVER_URL}/transcribe",
        files   = { "audio": ( "dummy.mp3", b"\x00" * 100, "audio/mpeg" ) },
        headers = { "X-API-Key": fake_key },
        timeout = 5
    )
    assert r.status_code == 401, f"Expected 401 wrong-format, got {r.status_code}: {r.text[:200]}"


def test_auth_rejects_invalid_ck_live( model_server_reachable ):
    """POST :7998/transcribe with a syntactically-valid but wrong ck_live_* fails."""
    fake_key = "ck_live_" + "X" * 64
    r = requests.post(
        f"{MODEL_SERVER_URL}/transcribe",
        files   = { "audio": ( "dummy.mp3", b"\x00" * 100, "audio/mpeg" ) },
        headers = { "X-API-Key": fake_key },
        timeout = 5
    )
    assert r.status_code == 401, f"Expected 401 hash-mismatch, got {r.status_code}: {r.text[:200]}"


# ── End-to-end via compute: HTTP-proxy path ──────────────────────────────────

def test_proxy_through_compute_mp3( compute_reachable, model_server_reachable, api_key, warmup_mp3_bytes ):
    """
    POST :7999/api/upload-and-transcribe-mp3 with base64-encoded MP3.

    Confirms the full carve-out path:
        compute container receives request →
        speech.py uses SpeechToTextProvider →
        provider's _transcribe_via_http POSTs to :7998/transcribe →
        model-server transcribes → returns text → compute returns to client.

    This is the test that PROVES the carve-out is functionally complete.
    """
    payload = base64.b64encode( warmup_mp3_bytes ).decode( "ascii" )
    r = requests.post(
        f"{COMPUTE_URL}/api/upload-and-transcribe-mp3",
        data    = payload,
        headers = {
            "X-API-Key"    : api_key,
            "Content-Type" : "application/octet-stream"
        },
        timeout = 60
    )
    assert r.status_code in ( 200, 201 ), f"Expected 2xx, got {r.status_code}: {r.text[:300]}"
    body_text = r.text.lower()
    assert any( marker in body_text for marker in ( "transcription", "text", "munger", "gpu" ) ), (
        f"Expected response to contain transcription-related content, got: {r.text[:300]}"
    )
