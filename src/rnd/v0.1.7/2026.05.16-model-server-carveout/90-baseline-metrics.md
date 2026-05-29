# Pre-Carve-Out Baseline Metrics

**Author**: Rio ⚡ (session `0025f917`)
**Captured**: 2026-05-16, ~14:45 EDT
**Purpose**: Quantify the current state of GPU memory, container memory, and request latency BEFORE the model-server carve-out lands, so the post-carve-out delta can be measured rigorously.
**Companion**: [`01-design.md`](01-design.md) — the carve-out plan this baseline serves
**Host**: 2 × NVIDIA GeForce RTX 4090 (24 GB each), driver 535.104.05, host kernel Linux 5.15
**Branch**: `wip-v0.1.7-2026.04.22-spit-and-polish-for-cjflow-tfe-and-bfe`

---

## Section 1 — Host GPU Memory (`nvidia-smi`)

```
Index | Name              | Total      | Used       | Free
------+-------------------+------------+------------+----------
  0   | GeForce RTX 4090  | 24,564 MiB | 23,167 MiB | 1,050 MiB  ← 94.3% full, 1 GB headroom
  1   | GeForce RTX 4090  | 24,564 MiB | 19,788 MiB | 4,429 MiB  ← 80.6% full, 4.3 GB headroom
```

**Headline**: GPU 0 is **critically saturated** (1 GB free). Any large allocation by any process can OOM the GPU. GPU 1 has comfortable headroom.

---

## Section 2 — GPU Memory Per Process

```
PID    | Process                                                          | VRAM        | Notes
-------+------------------------------------------------------------------+-------------+--------------------------------
2407   | python3                                                          |  3,202 MiB  | lupin-rest-test FastAPI worker
9384   | /mnt/DATA01/.../vllm-pip/.venv/bin/python                        | 16,664 MiB  | external vLLM project (NOT Lupin)
9607   | /mnt/DATA01/.../vllm-pip/.venv/bin/python                        | 19,768 MiB  | external vLLM project (NOT Lupin)
47795  | /opt/venv/bin/python3                                            |  3,274 MiB  | lupin-rest-dev FastAPI worker
```

### Lupin's contribution

| Container | VRAM | What's in it |
|---|---|---|
| `lupin-rest-dev` (PID 47795 outside, PID 7 inside) | **3,274 MiB ≈ 3.20 GB** | Whisper + CodeRankEmbed + nomic-embed-text-v1.5 |
| `lupin-rest-test` (PID 2407) | **3,202 MiB ≈ 3.13 GB** | Same three models, loaded independently |
| **Lupin subtotal** | **6,476 MiB ≈ 6.33 GB** | Doubled across dev + test |

### Non-Lupin GPU consumers (out of scope)

| Project | VRAM | Notes |
|---|---|---|
| vLLM-pip × 2 processes | 36,432 MiB ≈ 35.6 GB across both GPUs | Rick's external LLM-serving project |

**Carve-out expected delta**: Lupin's footprint drops from **~6.33 GB across 2 containers** to **~3.16 GB in one model-server container**. Frees ~3.2 GB total (most of which lands on whichever GPU the model-server pins to). If the model-server pins to GPU 1, GPU 0 reclaims its half (~1.6 GB) and headroom triples from 1 GB to 2.6 GB.

---

## Section 3 — Container Memory + CPU

```
Container ID    | Name              | Memory (RSS)         | CPU %    | Net I/O
----------------+-------------------+----------------------+----------+----------
9bc6bfab2519    | lupin-rest-dev    | 30.64 GiB / 251.5    | 201.34 % | 28.7 MB / 22.8 MB
f5bf5de0bdbe    | lupin-rest-test   |  6.96 GiB / 251.5    |   0.40 % | 151 KB / 83.6 KB
c3c8b4e7d45b    | lupin-postgres    |  68.76 MiB / 251.5   |   0.00 % | 3.57 MB / 4.16 MB
```

Notes:
- `lupin-rest-dev` is showing high CPU (201%) because of active development churn — Claude Code edits + reloads + tests in flight during baseline capture
- `lupin-rest-test` is idle (0.4% CPU)
- 30 GB RSS in dev is dominated by Python heap + tensor allocations + HuggingFace caches loaded into memory; this is the budget the carve-out reduces (the model tensors are part of that)
- Memory limit is 251.5 GB (host RAM), no per-container cap

---

## Section 4 — Image Footprint

```
Repository                               Tag                        Size
lupin                                    1.0.0                      31.7 GB
lupin                                    1.0.0-pytest-cov           31.7 GB
lupin                                    1.0.0-bcrypt-4.3.0         31.7 GB
lupin                                    1.0.0-fonts                31.7 GB
```

The `lupin:1.0.0` image is **31.7 GB**. `Dockerfile:208-210` pre-downloads:
- `distil-whisper/distil-large-v3` (~3 GB)
- `nomic-ai/CodeRankEmbed` (~0.6 GB)
- `nomic-ai/nomic-embed-text-v1.5` (~0.6 GB)

**Carve-out expected delta**: After the carve-out, the lupin image can drop these three downloads → image shrinks by ~4 GB (estimated), to ~27.7 GB. A new lean `lupin-model-server` image is added (~10-12 GB estimated, mostly torch + cu124 toolkit + the 3 models).

---

## Section 5 — HuggingFace Model Cache (volume-mounted)

Contents of `/var/external-projects/models/hub/` (bind-mount visible to lupin-rest-dev):

```
models--Qwen--Qwen3-4B-Base
models--bert-base-uncased
models--kaitchup--Qwen2.5-Coder-32B-Instruct-AutoRound-GPTQ-4bit
models--meta-llama--Llama-3.2-3B-Instruct
models--microsoft--Phi-4-mini-instruct
models--mistralai--Mistral-7B-Instruct-v0.2
models--mistralai--Mistral-7B-v0.1
models--nomic-ai--CodeRankEmbed
models--nomic-ai--nomic-bert-2048
models--nomic-ai--nomic-embed-text-v1.5
... (truncated)
```

Lupin loads only 3 of these (`distil-whisper/distil-large-v3` + `CodeRankEmbed` + `nomic-embed-text-v1.5`). The others are external (vLLM, etc.) and don't affect Lupin's footprint. The carve-out doesn't change this cache layout — the model-server container reuses the same volume-mounted cache.

---

## Section 6 — Process Tree Inside `lupin-rest-dev`

```
PID    | PPID | CMD
-------+------+------------------------------------------------------
   1   |   0  | /bin/bash /var/lupin/src/scripts/run-fastapi-lupin.sh
   7   |   1  | python3 -m fastapi_app.main           ← original uvicorn supervisor (2h 19m CPU)
  73   |   7  | multiprocessing.resource_tracker
4906   |   7  | multiprocessing.spawn fork            ← current worker after uvicorn --reload (1h 17m CPU)
```

PID 7 is the supervisor; PID 4906 is the current reload-worker. This is the supervisor/worker structure that the doom loop attacks — when PID 4906 dies and a new worker spawns, the new worker can't `cuInit()` (cu124 forward-compat fragility, Layer 1 in the doom-loop diagnosis). After the carve-out, neither PID 7 nor PID 4906 will touch CUDA, so reload becomes safe.

---

## Section 7 — Round-Trip Latency Baseline (`/health`)

5 sequential samples each (no auth, no body), measured from the host against the docker-exposed ports:

| Sample | :7999 (dev)  | :8000 (test) |
|---|---|---|
| 1 | 1.321 ms | 1.238 ms |
| 2 | 0.797 ms | 0.790 ms |
| 3 | 0.779 ms | 0.767 ms |
| 4 | 0.755 ms | 0.763 ms |
| 5 | 0.751 ms | 0.762 ms |
| **median** | **0.779 ms** | **0.767 ms** |

This is the floor for the FastAPI request-handling overhead (no model work, no auth). The carve-out's expected impact: an additional HTTP hop from FastAPI → `lupin-model-server` adds **~0.8-1.5 ms** per call on the same-host docker bridge network (estimated based on similar topologies — actual will be re-measured post-carve-out).

Net per-request latency change estimate:
- `/api/embeddings/generate`: today ~5-15 ms in-process → after ~7-17 ms via proxy (1-2 ms overhead, dominated by tokenization + encode)
- `/api/embeddings/batch`: today ~20-200 ms (batch size dependent) → after ~22-202 ms (proxy overhead is tiny relative to batch work)
- `/api/upload-and-transcribe-mp3`: today seconds (audio upload + Whisper inference) → after seconds + ~1 ms (negligible)

---

## Section 8 — Endpoint Latency Baselines (TBD — needs follow-up data-gathering pass)

These require auth + real payloads; they're outlined here so a dedicated baseline-capture session can produce the numbers before the carve-out lands.

| Endpoint | Test method | Today's expected range | Post-carve-out delta | Status |
|---|---|---|---|---|
| `POST /api/embeddings/generate` (single short text) | Auth + 50-word payload; 20 samples | 5-15 ms | +1-2 ms HTTP overhead | TBD |
| `POST /api/embeddings/batch` (batch=10) | Auth + 10 × 50-word payloads; 20 samples | 20-50 ms | +1-2 ms | TBD |
| `POST /api/embeddings/batch` (batch=100) | Auth + 100 × 50-word payloads; 20 samples | 100-300 ms | +1-2 ms (negligible) | TBD |
| `POST /api/upload-and-transcribe-mp3` (85s warmup MP3) | Auth + the existing `src/conf/warmup/whisper-warmup-85s.mp3`; 10 samples | 8-12 s | +1-2 ms (negligible) | TBD |

Test fixture pattern: use existing `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` credentials, POST against `:7999` (dev) for the baseline pass, then re-run post-carve-out and compare.

---

## Section 9 — Doom-Loop Frequency Baseline (TBD — observational)

Today, the doom loop fires after any edit under `reload_dirs` (`fastapi_app`, `cosa`, `lib`, `lupin_cli`, `lupin_mcp`) that causes uvicorn to spawn a new worker that can't `cuInit()`. Need an observational baseline:

| Metric | Method | Status |
|---|---|---|
| Reloads per active session | Grep `docker logs lupin-rest-dev` for `StatReload detected` | TBD — observe over next 3-5 sessions |
| Doom-loop fires per active session | Grep `docker logs lupin-rest-dev` for `RuntimeError: No CUDA GPUs are available` | TBD |
| Mean time from reload to next failure | Timestamp analysis of logs | TBD |
| Recovery actions per day (`docker restart lupin-rest-dev`) | Self-report or scripted counter | TBD |

Post-carve-out target: doom-loop fires per session = **0**.

---

## Section 10 — Cold-Start Time Baseline ✅ CAPTURED 2026-05-16, ~14:50 EDT

**Permission**: Rick granted explicit verbal go-ahead to bounce `lupin-rest-dev` for this measurement.
**Method**:
```bash
T0=$(date +%s.%N)
docker restart lupin-rest-dev
while ! curl -s -f -o /dev/null http://localhost:7999/health; do sleep 0.1; done
T1=$(date +%s.%N)
echo "Cold-start: $(echo "$T1 - $T0" | bc -l)s"
```

### Result

| Phase | Time |
|---|---|
| `docker restart lupin-rest-dev` returned | **10.95 s** |
| `/health` returned 200 after | **178 polls × 100 ms = ~17.8 s** of additional waiting |
| **TOTAL cold-start (T0 → first /health 200)** | **29.52 seconds** |

### Breakdown (rough attribution)

| Phase | Estimated duration | Notes |
|---|---|---|
| Docker stop + container init | ~10-11 s | `docker restart` returns when the container is back up but FastAPI isn't yet ready |
| FastAPI process spawn + Python import | ~3-5 s | Heavy import chain (torch, transformers, sentence-transformers) |
| Whisper + 2 encoders load to GPU | ~10-13 s | Three `.to("cuda:0")` calls + warmup MP3 inference at `main.py:619-657` |
| Lifespan completion + uvicorn bind | ~1 s | Final hookup |

**Floor cost of restarting `lupin-rest-dev` today: ~30 seconds.**

### Pre-bounce vs post-bounce GPU snapshot

| Source | Pre-bounce | Post-bounce | Δ |
|---|---|---|---|
| Host GPU 0 used | 23,167 MiB | **23,015 MiB** | −152 MiB (slight defrag) |
| Host GPU 0 free | 1,050 MiB | **1,202 MiB** | +152 MiB |
| Host GPU 1 used | 19,788 MiB | 19,788 MiB | unchanged |
| Lupin dev PID | 47795 → **109902** (new worker) | – | – |
| Lupin dev VRAM | 3,274 MiB | **3,122 MiB** | −152 MiB |
| Lupin test VRAM | 3,202 MiB | 3,202 MiB | unchanged |

The −152 MiB reduction is mild defragmentation from the fresh process — not a fix, just a side-effect. Whisper + 2 encoders re-loaded into VRAM as expected.

### Doom-loop status this bounce

✅ **First-process bounce succeeded cleanly** — cu124 forward-compat shim engaged on the freshly-recreated container, as the doom-loop diagnosis predicted. The doom loop is a **second-process-and-beyond** failure (uvicorn-reload spawns), not a first-process-after-`docker restart` failure. This measurement confirms the diagnosis but does NOT reproduce the doom loop. Reproducing the doom loop requires triggering uvicorn `--reload` on a file under `reload_dirs`.

### Predicted post-carve-out cold-start

After the carve-out, `lupin-rest-dev` no longer loads Whisper or the two encoders. Phase breakdown becomes:

| Phase | Predicted duration |
|---|---|
| Docker stop + container init | ~10-11 s (unchanged) |
| FastAPI process spawn + Python import | ~3-5 s (lighter — no torch model load) |
| Model loads | **0 s** (deferred to `lupin-model-server`) |
| Lifespan completion + uvicorn bind | ~1 s |
| **Total** | **~14-17 s** (estimated) |

**Predicted delta: ~13-16 seconds shaved off every `lupin-rest-dev` bounce.** Plus the doom loop is structurally eliminated (Layer 3 — eager GPU pre-warm — no longer runs).

The `lupin-model-server` container's OWN cold-start would land somewhere in the same ~25-30 s range (same model loads, fresh process). But that container restarts **rarely** — only on infrastructure work, not on code edits.

---

## Section 11 — Reload Latency Baseline (TBD)

| Metric | Method | Status |
|---|---|---|
| Edit → reload → first `/health` 200 (healthy case) | Touch a file under `reload_dirs`, time the recovery | TBD |
| Edit → reload → doom-loop entry (failure case) | Same, but capture the `RuntimeError` | TBD |

Post-carve-out target: reload always healthy, ~0.5-2 s.

---

## Summary — What This Baseline Documents

| Dimension | Today (measured) | Post-carve-out (predicted) |
|---|---|---|
| Lupin VRAM total across containers | **6.33 GB** (dev 3.20 GB + test 3.13 GB) | **~3.16 GB** (one container only) |
| GPU 0 headroom | **1,050 MiB** (≈1 GB, 94% saturated) | **~2.6 GB** (if model-server pins to GPU 1) |
| `lupin:1.0.0` image size | **31.7 GB** | **~27.7 GB** (drop 3 model pre-downloads) |
| New `lupin-model-server` image size | n/a | **~10-12 GB** (estimated) |
| `/health` median latency `:7999` | **0.779 ms** | **~0.78 ms** (no change for non-model endpoints) |
| Doom-loop fires per session | **>0** (observe to quantify) | **0** (structural fix) |
| **Cold-start time `:7999`** | **29.52 s** (captured 2026-05-16) | **~14-17 s** (estimated, no model loads in compute container) |
| Per-request HTTP overhead for model endpoints | n/a (in-process today) | **~1-2 ms** (LAN docker bridge) |

---

## Follow-Up Tasks

- [ ] Capture Section 8 endpoint latency baselines (auth + real payloads, 20 samples each)
- [ ] Begin Section 9 doom-loop frequency log-grep observation over next 3-5 sessions
- [x] **Schedule a `:7999` bounce window with Rick to capture Section 10 cold-start time** — DONE 2026-05-16, ~14:50 EDT, cold-start = **29.52 s**
- [ ] Capture Section 11 reload-latency baselines (touch a file, time recovery — needs to reproduce doom loop too)
- [ ] Re-run all of the above after each carve-out phase ships to track incremental impact
