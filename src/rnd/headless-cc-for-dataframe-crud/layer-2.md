# Layer 2: Phi-4 14B Intent Extraction + Claude Code Headless Fallback

**Status**: NOT STARTED
**Phase**: 2 of 4
**Depends on**: Layer 1 (storage + schemas + CRUD + XML models)

## Overview

Local Phi-4 14B model extracts CRUDIntent from natural language. Claude Code headless mode provides fallback for complex/ambiguous queries.

## Components (Planned)

- Intent extraction prompt template
- Phi-4 14B integration via existing Deepily LLM infrastructure
- Claude Code headless fallback for complex queries
- Confidence threshold routing (Phi-4 vs Claude Code)

## Architecture Reference

See: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
