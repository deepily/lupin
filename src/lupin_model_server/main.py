"""
Lupin Model Server — FastAPI app hosting Whisper + 2 text encoders on `:7998`.

This container is FROZEN — code here doesn't evolve. Compute containers
(`lupin-rest-dev` + `lupin-rest-test`) call out over HTTP for transcription
and embedding work. See:
    src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md

Endpoints:
    GET  /health                       — 503 until all 3 models loaded; 200 with VRAM count once ready (no auth)
    POST /transcribe                   — audio → text (X-API-Key ck_live_* required)
    POST /embeddings/generate          — text → vector (X-API-Key ck_live_* required)
    POST /embeddings/batch             — texts → vectors (X-API-Key ck_live_* required)
    GET  /embeddings/info              — model metadata (X-API-Key ck_live_* required)
    GET  /admin/metrics                — Prometheus text format (X-API-Key ck_live_* required)

Auth model (post-2026-05-16 simplification per María's brief):
    The model-server reuses Lupin's existing `ck_live_*` API key namespace
    (no parallel `ck_internal_*` ecosystem). At lifespan boot it reads the
    plaintext key from `/var/lupin/src/conf/keys/<LUPIN_MODEL_SERVER_API_KEY_NAME>`
    (bind-mounted from the host's `src/conf/keys/` dir), bcrypt-hashes it
    once, and stores the hash in `_state.api_key_hash`. Each incoming
    request is validated via `bcrypt.checkpw(incoming, _state.api_key_hash)`
    — functionally identical security posture to the DB-backed validator at
    `cosa/rest/middleware/api_key_auth.py:34-79`, just allowlisted to one
    known-good key instead of walking a DB row set. Plaintext is purged from
    process memory after the boot-time hash (only the hash is retained).

Configuration is env-var driven (no ConfigurationManager dependency, keeps the
container self-contained and frozen):
    LUPIN_MODEL_SERVER_API_KEY_NAME — name of the key file in KEYS_DIR (default `notification-api-claude-code-dev`)
    LUPIN_MODEL_SERVER_KEYS_DIR     — default "/var/lupin/src/conf/keys"
    LUPIN_MODEL_SERVER_DEVICE       — default "cuda:0" (per memory rule: Lupin models ALWAYS GPU 0)
    LUPIN_MODEL_SERVER_WHISPER_ID   — default "distil-whisper/distil-large-v3"
    LUPIN_MODEL_SERVER_CODE_EMBED   — default "nomic-ai/CodeRankEmbed"
    LUPIN_MODEL_SERVER_PROSE_EMBED  — default "nomic-ai/nomic-embed-text-v1.5"
    LUPIN_MODEL_SERVER_WARMUP_MP3   — optional warmup audio path
    LUPIN_MODEL_SERVER_PORT         — default 7998
"""

import asyncio
import gc
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from typing      import Annotated, List, Optional

import bcrypt
import torch
from fastapi          import FastAPI, Header, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
)
from pydantic import BaseModel, Field


# ── Configuration (env-var-driven, no ConfigurationManager) ─────────────────

DEVICE          = os.environ.get( "LUPIN_MODEL_SERVER_DEVICE",      "cuda:0" )
WHISPER_MODEL   = os.environ.get( "LUPIN_MODEL_SERVER_WHISPER_ID",  "distil-whisper/distil-large-v3" )
CODE_EMBED      = os.environ.get( "LUPIN_MODEL_SERVER_CODE_EMBED",  "nomic-ai/CodeRankEmbed" )
PROSE_EMBED     = os.environ.get( "LUPIN_MODEL_SERVER_PROSE_EMBED", "nomic-ai/nomic-embed-text-v1.5" )
WARMUP_MP3_PATH = os.environ.get( "LUPIN_MODEL_SERVER_WARMUP_MP3",  "" )
PORT            = int( os.environ.get( "LUPIN_MODEL_SERVER_PORT", "7998" ) )

# API key namespace — reuses the canonical Lupin `ck_live_*` namespace per
# María's brief (2026-05-16). The model-server reads the plaintext key file
# named here at boot, bcrypt-hashes it once, and validates incoming
# X-API-Key headers via bcrypt.checkpw against that in-memory hash.
# The key file path resolves to {KEYS_DIR}/{LUPIN_MODEL_SERVER_API_KEY_NAME}
# inside the container (compose bind-mounts the host's src/conf/keys/).
API_KEY_NAME    = os.environ.get( "LUPIN_MODEL_SERVER_API_KEY_NAME", "notification-api-claude-code-dev" )
KEYS_DIR        = os.environ.get( "LUPIN_MODEL_SERVER_KEYS_DIR",     "/var/lupin/src/conf/keys" )

# Existing Lupin api_key_auth.py regex — matches `ck_live_<64+ base64url>`.
_CK_LIVE_RE     = re.compile( r"^ck_live_[A-Za-z0-9_-]{64,}$" )


# ── Application state ────────────────────────────────────────────────────────

class _State:
    """Mutable singleton tracking model load progress + handles for inference."""

    def __init__( self ):
        self.started_at        : float            = time.time()
        self.whisper_pipeline                     = None
        self.code_engine                          = None
        self.prose_engine                         = None
        self.models_loaded     : List[ str ]      = []
        self.load_errors       : List[ str ]      = []
        # bcrypt hash of the expected API key; computed once at lifespan boot
        # from the plaintext key file (None until lifespan runs OR if the key
        # file is missing → all auth-protected endpoints 503).
        self.api_key_hash      : Optional[ bytes ] = None

    def is_ready( self ) -> bool:
        """All 3 models successfully resident in VRAM."""
        return len( self.models_loaded ) == 3 and not self.load_errors


_state = _State()


def _load_api_key_plaintext() -> Optional[ str ]:
    """
    Read the plaintext API key from `{KEYS_DIR}/{API_KEY_NAME}`.

    Mirrors `cosa.utils.util.get_api_key()` semantics (the canonical Lupin
    helper) but inlined here so the model-server stays self-contained — no
    cosa dependency, freeze property preserved.

    Ensures:
        - Returns the stripped key string when the file exists + is readable
        - Returns None on any failure (file missing, read error, empty)
        - Never raises
    """
    path = os.path.join( KEYS_DIR, API_KEY_NAME )
    try:
        with open( path, "r" ) as f:
            key = f.read().strip()
        return key if key else None
    except OSError:
        return None


# ── Prometheus metrics ───────────────────────────────────────────────────────

_registry = CollectorRegistry()

_REQUESTS_TOTAL = Counter(
    "model_server_requests_total",
    "Total requests received per endpoint",
    [ "endpoint" ],
    registry=_registry
)
_REQUEST_DURATION = Histogram(
    "model_server_request_duration_seconds",
    "Request duration in seconds per endpoint",
    [ "endpoint" ],
    registry=_registry
)
_VRAM_USED_MB = Gauge(
    "model_server_vram_used_mb",
    "Current VRAM usage in MB (per nvidia-smi)",
    registry=_registry
)
_MODELS_LOADED = Gauge(
    "model_server_models_loaded",
    "Number of models successfully loaded (0-3)",
    registry=_registry
)
_UPTIME = Gauge(
    "model_server_uptime_seconds",
    "Process uptime in seconds",
    registry=_registry
)


# ── Auth dependency (X-API-Key ck_live_*) ────────────────────────────────────

def require_api_key( x_api_key: Annotated[ Optional[ str ], Header() ] = None ) -> str:
    """
    Validate the X-API-Key header carries a `ck_live_*` value matching the
    bcrypt hash computed at lifespan boot from the existing
    `notification-api-claude-code-dev` plaintext key file.

    Reuses the canonical Lupin `ck_live_*` namespace per María's 2026-05-16
    brief — model-server does NOT fork the namespace. It just bcrypt-checkpw's
    incoming keys against a hash it computed once from the same plaintext
    file the FastAPI compute containers send. Functionally identical security
    to the DB-backed `cosa/rest/middleware/api_key_auth.py:34-79` validator
    (same bcrypt path; just allowlisted to one known-good key instead of
    walking a DB row set).

    Requires:
        - x_api_key is non-empty + matches `^ck_live_[A-Za-z0-9_-]{64,}$`
        - `_state.api_key_hash` is populated (lifespan ran successfully)

    Ensures:
        - Returns the raw key string on success
        - Raises 401 on missing header
        - Raises 401 on wrong format (regex mismatch)
        - Raises 401 on hash mismatch
        - Raises 503 if the model-server never loaded the key file at boot
          (e.g., bind-mount missing, file unreadable)
    """
    if _state.api_key_hash is None:
        raise HTTPException(
            status_code=503,
            detail=f"Model server not configured: API key file {API_KEY_NAME!r} not loaded at boot"
        )
    if not x_api_key:
        raise HTTPException( status_code=401, detail="Missing X-API-Key header" )
    if not _CK_LIVE_RE.match( x_api_key ):
        raise HTTPException(
            status_code=401,
            detail="Invalid API key format. Expected ck_live_{64+ chars}."
        )
    if not bcrypt.checkpw( x_api_key.encode( "utf-8" ), _state.api_key_hash ):
        raise HTTPException( status_code=401, detail="Invalid X-API-Key" )
    return x_api_key


# ── Model loading helpers ────────────────────────────────────────────────────

def _load_whisper():
    """Eager-load distil-whisper pipeline to GPU 0."""
    from transformers import pipeline                              # pragma: no cover — exercised in live container
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    return pipeline(                                               # pragma: no cover
        "automatic-speech-recognition",
        model       = WHISPER_MODEL,
        torch_dtype = torch_dtype,
        device      = DEVICE
    )


def _load_code_engine():
    """Eager-load CodeRankEmbed via sentence-transformers."""
    from sentence_transformers import SentenceTransformer          # pragma: no cover
    return SentenceTransformer( CODE_EMBED, device=DEVICE, trust_remote_code=True )  # pragma: no cover


def _load_prose_engine():
    """Eager-load nomic-embed-text-v1.5 via sentence-transformers."""
    from sentence_transformers import SentenceTransformer          # pragma: no cover
    return SentenceTransformer( PROSE_EMBED, device=DEVICE, trust_remote_code=True )  # pragma: no cover


def _update_vram_gauge():
    """Snapshot current GPU memory usage into the Prometheus gauge."""
    if torch.cuda.is_available():
        _VRAM_USED_MB.set( torch.cuda.memory_allocated() / ( 1024 * 1024 ) )
    else:                                                          # pragma: no cover — CPU-only smoke path
        _VRAM_USED_MB.set( 0 )


# ── Lifespan: load 3 models eagerly ──────────────────────────────────────────

@asynccontextmanager
async def lifespan( app: FastAPI ):                                # pragma: no cover — exercised in live container
    """Eager-load Whisper + 2 encoders. /health returns 503 until all 3 are in VRAM."""
    print( f"[lupin-model-server] starting; device={DEVICE}" )

    # Boot-time API key load — read plaintext from the bind-mounted
    # `src/conf/keys/` dir + bcrypt-hash once, store hash in state.
    # Per María's 2026-05-16 brief: reuse the existing `ck_live_*` namespace
    # (default `notification-api-claude-code-dev`); the model-server's
    # validator allowlists ONE key (no DB walk needed). Hash-once-at-boot
    # keeps plaintext out of process memory for the lifetime of the worker.
    plaintext_key = _load_api_key_plaintext()
    if plaintext_key:
        _state.api_key_hash = bcrypt.hashpw( plaintext_key.encode( "utf-8" ), bcrypt.gensalt() )
        del plaintext_key  # purge plaintext from memory; only hash retained
        print( f"[lupin-model-server] API key loaded + hashed from {API_KEY_NAME}" )
    else:
        _state.load_errors.append(
            f"api_key: file {API_KEY_NAME!r} missing or unreadable in {KEYS_DIR!r} — "
            f"all auth-protected endpoints will return 503"
        )
        print( f"[lupin-model-server] WARNING: API key file {API_KEY_NAME!r} not loaded" )

    try:
        _state.whisper_pipeline = _load_whisper()
        _state.models_loaded.append( "whisper" )
        if WARMUP_MP3_PATH and os.path.exists( WARMUP_MP3_PATH ):
            _state.whisper_pipeline( WARMUP_MP3_PATH, chunk_length_s=30, stride_length_s=5, return_timestamps=False )
    except Exception as e:
        _state.load_errors.append( f"whisper: {type( e ).__name__}: {e}" )
    try:
        _state.code_engine = _load_code_engine()
        _state.code_engine.encode( [ "def hello(): return 'world'" ] )
        _state.models_loaded.append( "code_rank_embed" )
    except Exception as e:
        _state.load_errors.append( f"code_engine: {type( e ).__name__}: {e}" )
    try:
        _state.prose_engine = _load_prose_engine()
        _state.prose_engine.encode( [ "What is the meaning of life?" ] )
        _state.models_loaded.append( "nomic_embed_text_v1_5" )
    except Exception as e:
        _state.load_errors.append( f"prose_engine: {type( e ).__name__}: {e}" )

    _MODELS_LOADED.set( len( _state.models_loaded ) )
    _update_vram_gauge()
    print( f"[lupin-model-server] ready; models_loaded={_state.models_loaded} errors={_state.load_errors}" )
    yield
    print( "[lupin-model-server] shutting down" )


app = FastAPI( title="Lupin Model Server", version="0.1.0", lifespan=lifespan )


# ── Pydantic request/response models ─────────────────────────────────────────

class EmbedRequest( BaseModel ):
    text         : str = Field( ..., min_length=1 )
    content_type : str = Field( "prose", pattern=r"^(code|prose)$" )


class EmbedBatchRequest( BaseModel ):
    texts        : List[ str ]
    content_type : str = Field( "prose", pattern=r"^(code|prose)$" )


# ── /health (no auth) ────────────────────────────────────────────────────────

@app.get( "/health" )
def health():
    """503 while loading; 200 with VRAM + models_loaded once ready."""
    _REQUESTS_TOTAL.labels( endpoint="/health" ).inc()
    _UPTIME.set( time.time() - _state.started_at )
    _update_vram_gauge()
    body = {
        "status"         : "ready" if _state.is_ready() else "loading",
        "models_loaded"  : list( _state.models_loaded ),
        "vram_used_mb"   : int( _VRAM_USED_MB._value.get() ) if hasattr( _VRAM_USED_MB, "_value" ) else None,
        "uptime_seconds" : int( time.time() - _state.started_at ),
        "load_errors"    : list( _state.load_errors )
    }
    status_code = 200 if _state.is_ready() else 503
    return JSONResponse( content=body, status_code=status_code )


# ── /transcribe (auth required) ──────────────────────────────────────────────

@app.post( "/transcribe" )
async def transcribe(                                              # pragma: no cover — needs live Whisper
    request : Request,
    audio   : UploadFile = File( ... ),
):
    """Receive audio bytes, return text. Wraps the existing Whisper retry logic."""
    require_api_key( request.headers.get( "x-api-key" ) )
    if not _state.is_ready():
        raise HTTPException( status_code=503, detail="Model server still loading" )

    with _REQUEST_DURATION.labels( endpoint="/transcribe" ).time():
        _REQUESTS_TOTAL.labels( endpoint="/transcribe" ).inc()
        audio_bytes = await audio.read()
        tmp_path = f"/tmp/transcribe-{secrets.token_hex( 8 )}.bin"
        with open( tmp_path, "wb" ) as f:
            f.write( audio_bytes )
        try:
            try:
                result = _state.whisper_pipeline( tmp_path, chunk_length_s=30, stride_length_s=5 )
            except torch.cuda.OutOfMemoryError:
                gc.collect()
                torch.cuda.empty_cache()
                result = _state.whisper_pipeline( tmp_path, chunk_length_s=30, stride_length_s=5 )
        finally:
            try:
                os.remove( tmp_path )
            except OSError:
                pass
    return JSONResponse( content={ "text": result.get( "text", "" ) } )


# ── /embeddings/* (auth required) ────────────────────────────────────────────

def _select_engine( content_type: str ):
    """Route content_type to the right encoder; 503 if not loaded."""
    if content_type == "code":
        engine = _state.code_engine
    else:
        engine = _state.prose_engine
    if engine is None:
        raise HTTPException( status_code=503, detail=f"{content_type} engine not loaded" )
    return engine


@app.post( "/embeddings/generate" )
def embeddings_generate( body: EmbedRequest, request: Request ):   # pragma: no cover — needs live engine
    require_api_key( request.headers.get( "x-api-key" ) )
    with _REQUEST_DURATION.labels( endpoint="/embeddings/generate" ).time():
        _REQUESTS_TOTAL.labels( endpoint="/embeddings/generate" ).inc()
        engine = _select_engine( body.content_type )
        vector = engine.encode( [ body.text ] )[ 0 ].tolist()
    return JSONResponse( content={ "embedding": vector, "dim": len( vector ) } )


@app.post( "/embeddings/batch" )
def embeddings_batch( body: EmbedBatchRequest, request: Request ): # pragma: no cover — needs live engine
    require_api_key( request.headers.get( "x-api-key" ) )
    if not body.texts:
        raise HTTPException( status_code=400, detail="texts must be non-empty" )
    with _REQUEST_DURATION.labels( endpoint="/embeddings/batch" ).time():
        _REQUESTS_TOTAL.labels( endpoint="/embeddings/batch" ).inc()
        engine = _select_engine( body.content_type )
        vectors = engine.encode( body.texts ).tolist()
    return JSONResponse( content={ "embeddings": vectors, "count": len( vectors ), "dim": len( vectors[ 0 ] ) if vectors else 0 } )


@app.get( "/embeddings/info" )
def embeddings_info( request: Request ):
    require_api_key( request.headers.get( "x-api-key" ) )
    _REQUESTS_TOTAL.labels( endpoint="/embeddings/info" ).inc()
    return JSONResponse( content={
        "code_model"     : CODE_EMBED,
        "prose_model"    : PROSE_EMBED,
        "code_loaded"    : "code_rank_embed" in _state.models_loaded,
        "prose_loaded"   : "nomic_embed_text_v1_5" in _state.models_loaded,
    } )


# ── /admin/metrics (auth required, Prometheus text format) ───────────────────

@app.get( "/admin/metrics" )
def admin_metrics( request: Request ):
    require_api_key( request.headers.get( "x-api-key" ) )
    _REQUESTS_TOTAL.labels( endpoint="/admin/metrics" ).inc()
    _UPTIME.set( time.time() - _state.started_at )
    _update_vram_gauge()
    return Response( content=generate_latest( _registry ), media_type=CONTENT_TYPE_LATEST )


if __name__ == "__main__":                                         # pragma: no cover — runtime entry
    import uvicorn
    uvicorn.run( app, host="0.0.0.0", port=PORT )
