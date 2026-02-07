# Layer 3: Queue Integration + Voice Confirmation

**Status**: COMPLETE
**Phase**: 3 of 4
**Depends on**: Layer 2 (intent extraction + agent)

## Overview

Layer 3 wires the CRUD DataFrame agents into the live voice pipeline by replacing
`TodoListAgent` and `CalendaringAgent` in the queue routing, adding cache/serialization
exclusions for mutable CRUD data, and adding voice confirmation for destructive operations.

## Components Implemented

### Step 1: Feature Flag Config
- **File**: `src/conf/lupin-app.ini` — `crud for dataframes agents enabled = true`
- **File**: `src/conf/lupin-app-splainer.ini` — matching explainer
- Instant rollback to legacy agents by setting flag to `false`

### Step 2: Producer-Side Routing Swap
- **File**: `src/cosa/rest/todo_fifo_queue.py`
- Added imports for `TodoCrudAgent` and `CalendarCrudAgent`
- Feature-flag-gated elif branches for calendar and todo commands
- `_crud_agents_enabled()` helper reads flag from ConfigurationManager
- Legacy agents remain as fallback path

### Step 3: Consumer-Side Cache Skip + Serialization Exclusion
- **File**: `src/cosa/rest/running_fifo_queue.py`
- CRUD agents skip snapshot cache (mutable data goes stale instantly)
- CRUD agents excluded from `SolutionSnapshot` serialization
- Matches existing exclusion pattern for `ReceptionistAgent` and `WeatherAgent`

### Step 4: Voice Confirmation for Destructive Operations
- **File**: `src/cosa/crud_for_dataframes/agent.py`
- Confirmation check in `run_code()` before dispatch
- Uses `notify_user_sync` + `NotificationRequest` + `ResponseType.YES_NO`
- 30s timeout, defaults to "no" (safe)
- Cancelled operations return `{"status": "cancelled"}` — handled by `run_formatter()`
- Triggers for: delete, delete_list, update (all destructive ops)

### Step 5: Unit Tests
- **File**: `src/tests/unit/test_crud_queue_integration.py`
- 26 tests across 3 test classes
- `TestCrudQueueRouting` (8): Feature flag, agent creation, constructor args
- `TestCrudCacheBehavior` (5): isinstance checks, serialization exclusion
- `TestCrudConfirmationFlow` (13): needs_confirmation, yes/no/timeout/error, cancelled formatting

## Architecture Reference

See: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
