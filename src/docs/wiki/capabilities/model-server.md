---
capability: model-server
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_model_server.main.lifespan@0393cbf19b
  - lupin_model_server.main.require_api_key@6fa99107ab
  - lupin_model_server.main.health@c4a1f59126
  - lupin_model_server.main.transcribe@55357c6093
  - lupin_model_server.main.embeddings_generate@5eaa3796e5
  - lupin_model_server.main.embeddings_batch@8e459f27e1
  - lupin_model_server.main.admin_metrics@461a1ce807
---
# Model server

A standalone FastAPI app in `src/lupin_model_server/main.py` that holds Whisper and two text encoders on one GPU. Compute containers call it over HTTP. Client routing is in [[speech-to-text-routing]] and [[embedding-pipeline]]; container lifecycle is [[dev-server-lifecycle]].

## What it does
- `lifespan` installs the API key, then loads Whisper, the code encoder and the prose encoder in turn. A failed load is recorded in `load_errors`; the app still starts.
- `health` needs no key. It answers 200 only when all three models are loaded and `load_errors` is empty; otherwise 503, with the error list in the body.
- `transcribe` takes an uploaded `audio` file and returns `{"text": ...}`. On a CUDA out-of-memory error it frees the cache and retries once.
- `embeddings_generate` takes `text` and `content_type` (`code` or `prose`, default `prose`) and returns `embedding` and `dim`. `embeddings_batch` takes `texts` and returns `embeddings`, `count` and `dim`.
- `/embeddings/info` reports the two model names and whether each is loaded. `admin_metrics` serves Prometheus text.
- Settings are env vars read at import: `LUPIN_MODEL_SERVER_DEVICE`, `_WHISPER_ID`, `_CODE_EMBED`, `_PROSE_EMBED`, `_WARMUP_MP3`, `_PORT`, `_KEYS_DIR` and `_API_KEY_NAME`. The Dockerfile starts it with uvicorn on 7998.
- `speech_to_text_provider.py` and `embedding_provider.py` in `src/cosa/memory` call it. Both read `LUPIN_MODEL_SERVER_URL`, then the INI key `model server url`. In model-server mode only, `src/lupin_app/main.py` also reads the URL and polls `health` at startup. It waits up to 60 s, the code default, then logs a timeout and continues.

## Don't
- Don't call it without `X-API-Key`. Every route except `health` and FastAPI's own docs routes runs `require_api_key`, which gives 401 for a missing, mis-shaped or wrong key. A request with an invalid body gets 422 before that check.
- Don't expect auth to work after a bad key file. A missing or malformed file leaves no hash, so those routes return 503 instead of 401.
- Don't send an empty `texts` list to the batch route. It returns 400.
- Don't read the key from the code default. `lifespan` uses the code default `notification-api-claude-code-dev`, but compose sets `model-server-api`, and both clients default to that.
- Don't read the shipped INI as "everything remote". Its Development section sets `speech to text provider = model-server` but `embedding provider = local`.

## Invariants
- `require_api_key` matches the `ck_live_` format, then checks the key with `bcrypt.checkpw` against one hash made at boot. The plaintext is deleted after hashing.
- `health` serves a short sha256 fingerprint of the loaded key, so two instances can be compared. It is null when no key was loaded.
- `transcribe` checks the key first, then returns 503 if the models are not all ready. It deletes its temp audio file even on failure.
- The embedding routes do not check overall readiness. They return 503 when the chosen encoder is missing, or from `require_api_key` when no key hash was loaded.
