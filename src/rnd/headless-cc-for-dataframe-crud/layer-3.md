# Layer 3: Dispatcher with Semantic Caching + Voice I/O

**Status**: NOT STARTED
**Phase**: 3-4 of 4
**Depends on**: Layer 2 (intent extraction)

## Overview

Dispatcher routes voice commands through intent extraction, executes CRUD operations, and returns voice-friendly responses. Semantic caching avoids redundant LLM calls for repeated patterns.

## Components (Planned)

- FIFO queue integration for per-user request serialization
- Semantic cache for intent patterns
- Voice I/O integration (STT input, TTS response)
- Confirmation flows for destructive operations

## Architecture Reference

See: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
