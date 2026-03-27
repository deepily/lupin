# Layer 1: DataFrame CRUD Storage Layer

**Status**: IN PROGRESS
**Phase**: 1 of 4
**Started**: 2026-02-06

## Overview

Per-user parquet-backed DataFrames with CRUD operations, schema definitions, and CRUDIntent XML model.

## Components

| Component | File | Status |
|-----------|------|--------|
| Schemas | `src/cosa/crud_for_dataframes/schemas.py` | In Progress |
| XML Models | `src/cosa/crud_for_dataframes/xml_models.py` | In Progress |
| Storage | `src/cosa/crud_for_dataframes/storage.py` | In Progress |
| CRUD Operations | `src/cosa/crud_for_dataframes/crud_operations.py` | In Progress |
| Unit Tests | `src/tests/unit/test_crud_for_dataframes_storage.py` | In Progress |
| Smoke Tests | `src/tests/smoke/test_crud_for_dataframes_smoke.py` | In Progress |

## Key Decisions

### Date/Time Representation
- **LLM boundary**: ISO 8601 strings (CRUDIntent XML)
- **Storage layer**: Native `datetime64[ms]` (parquet)
- **Display/TTS**: Natural language

### Schema Design
- Column names aligned with existing `events.csv` and `todo.csv`
- Explicit `dtype` per column: `str`, `date`, `time`, `datetime`
- Common columns: `id`, `list_name`, `created_at`

## Architecture Reference

See original design docs:
- `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
- `src/rnd/2026.02.05-crud-for-dataframes-implementation.md`
