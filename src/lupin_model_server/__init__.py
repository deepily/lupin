"""
Lupin Model Server — frozen-code container hosting Whisper + 2 text encoders.

Carves the GPU-resident model loads out of the main Lupin FastAPI app so the
compute containers (`lupin-rest-dev` :7999 + `lupin-rest-test` :8000) can use
uvicorn `--reload` safely without re-initializing CUDA on every reload.

See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
"""

__version__ = "0.1.0"
