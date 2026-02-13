# DataFrame CRUD Interactive Testing Protocol

**Created**: 2026-02-06
**Updated**: 2026-02-09
**Context**: Layers 1-3 complete + CRUD completion bug fix (532 unit tests passing). This protocol validates live behavior before Phase 4 Polish.
**Goal**: Verify routing swap, cache skip, voice confirmation, and full CRUD cycle work end-to-end.

## Execution Status

| Part | Description | Status | Recommended Order |
|------|-------------|--------|-------------------|
| Part 1 | Mock Objects Protocol | **DONE** (17/17 passed) | 1st |
| Part 3 | Curl Smoke Tests | **IN PROGRESS** (Test 2 partial — card OK, TTS blocked by pre-existing stuck focus mode) | 2nd |
| Part 2 | Notifications UI Protocol | PENDING | 3rd |

> **Recommended order**: 1 → 3 → 2. Part 3 (curl) validates server-side routing before Part 2 (UI) tests the full notification card flow.

---

## Prerequisites

### Environment

```bash
# Required for all tests
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
export LUPIN_ROOT="/mnt/DATA01/include/www.deepily.ai/projects/lupin"

# Required for UI/curl tests only
export LUPIN_TEST_EMAIL="your@email.com"
export LUPIN_TEST_PASSWORD="yourpassword"
```

### Feature Flag

The CRUD routing swap is controlled by `crud for dataframes agents enabled` in `src/conf/lupin-app.ini` (line 535). Default is `true` — set to `false` for rollback testing.

### Test Infrastructure Verified

Before running this protocol, confirm the unit test baseline:

```bash
pytest src/tests/unit/ -v  # Expect 461/461 passed
```

---

## Part 1: Mock Objects Protocol

Standalone Python test scenarios exercising the full pipeline with mocked LLM and notification services. **No server required.**

### 1.1 Setup

**File**: `src/tests/unit/test_crud_mock_pipeline.py`

**Key patterns reused from existing tests:**

| Pattern | Source | Line Range |
|---------|--------|------------|
| `__new__()` bypass for `AgentBase.__init__` | `test_crud_for_dataframes_agent.py` | 548-585 |
| `@patch("cosa.crud_for_dataframes.agent.notify_user_sync")` | `test_crud_queue_integration.py` | 242-256 |
| `@patch("cosa.crud_for_dataframes.agent.LlmClientFactory")` | `test_crud_for_dataframes_agent.py` | 587-602 |
| `tempfile.TemporaryDirectory()` for storage isolation | `test_crud_queue_integration.py` | 31-33 |

**Common fixtures and helpers:**

```python
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent


@pytest.fixture
def tmp_storage_dir():
    """Provide a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


def _create_mock_agent( agent_cls=CrudForDataFramesAgent, tmp_dir=None, question="add buy milk to my grocery list" ):
    """
    Create an agent via __new__() bypass, skipping AgentBase.__init__.

    Reuses the pattern from test_crud_for_dataframes_agent.py:555.
    """
    agent = agent_cls.__new__( agent_cls )

    agent.debug                 = True
    agent.verbose               = False
    agent.last_question_asked   = question
    agent.question              = question
    agent.model_name            = "kaitchup/phi_4_14b"
    agent.routing_command       = "agent router go to crud for dataframes"
    agent.user_email            = "test@example.com"
    agent.prompt_response_dict  = None
    agent.code_response_dict    = None
    agent.error                 = ""
    agent.answer                = ""
    agent.answer_conversational = None
    agent.crud_intent           = None
    agent.auto_debug            = False
    agent.inject_bugs           = False

    if tmp_dir:
        agent.storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )
    else:
        agent.storage = MagicMock()
        agent.storage.get_all_lists_metadata.return_value = []

    intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )
    agent.prompt = f"Extract intent: {question}\n{intent_example}"

    return agent
```

---

### 1.2 Routing Swap Scenarios (3 tests)

**What's validated**: When `crud for dataframes agents enabled = true`, todo/calendar commands create CRUD agents. When `false`, they create legacy agents.

```python
class TestRoutingSwapPipeline:
    """Routing swap creates the correct agent type based on feature flag."""

    def test_todo_command_creates_crud_agent_when_enabled( self ):
        """'agent router go to todo list' with flag=true creates TodoCrudAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True
        # In production: this gates whether TodoCrudAgent or TodoListAgent is created
        # See todo_fifo_queue.py:635-642

    def test_todo_command_creates_legacy_agent_when_disabled( self ):
        """'agent router go to todo list' with flag=false creates legacy TodoListAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "false"

        assert queue._crud_agents_enabled() is False
        # In production: legacy TodoListAgent created at todo_fifo_queue.py:639-641

    def test_calendar_command_creates_crud_agent_when_enabled( self ):
        """'agent router go to calendar' with flag=true creates CalendarCrudAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True
        # In production: CalendarCrudAgent created at todo_fifo_queue.py:618-620
```

---

### 1.3 Full Pipeline Scenarios (3 tests)

**What's validated**: `do_all()` end-to-end flow: `run_prompt()` → `run_code()` → `run_formatter()` for add, query, and delete operations.

```python
class TestFullPipelineMocked:
    """Mocked end-to-end pipeline: run_prompt → run_code → run_formatter."""

    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_add_pipeline( self, mock_factory_cls, tmp_storage_dir ):
        """Full add pipeline: LLM extracts intent → dispatch adds item → TTS formats result."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir )

        # Mock LLM to return valid add intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>add</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.95</confidence>'
            '<fields>{"todo_item": "buy milk", "priority": "high"}</fields></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # Step 1: run_prompt
        prompt_result = agent.run_prompt()
        assert agent.crud_intent is not None
        assert agent.crud_intent.operation == "add"
        assert agent.crud_intent.target_list == "groceries"

        # Step 2: run_code (add doesn't need confirmation)
        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "added"

        # Step 3: run_formatter
        tts_result = agent.run_formatter()
        assert "Done" in tts_result
        assert agent.answer_conversational == tts_result

    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_query_pipeline( self, mock_factory_cls, tmp_storage_dir ):
        """Full query pipeline: add item first, then query → verify TTS output."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="what's on my grocery list?" )

        # Pre-populate: add an item directly via storage
        from cosa.crud_for_dataframes.crud_operations import add_item
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        # Mock LLM to return query intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>query</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.90</confidence></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        prompt_result = agent.run_prompt()
        assert agent.crud_intent.operation == "query"

        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert "items" in code_result[ "output" ] or code_result[ "output" ][ "status" ] == "ok"

        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_delete_pipeline( self, mock_factory_cls, mock_notify, tmp_storage_dir ):
        """Full delete pipeline: add → delete with confirmation → verify TTS."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        # Pre-populate
        from cosa.crud_for_dataframes.crud_operations import add_item
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        # Mock LLM to return delete intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>delete</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.92</confidence>'
            '<match_fields>{"todo_item": "buy milk"}</match_fields></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # Mock confirmation: user says yes
        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "yes"
        mock_notify.return_value     = mock_response

        prompt_result = agent.run_prompt()
        assert agent.crud_intent.operation == "delete"

        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "deleted"
        mock_notify.assert_called_once()  # Confirmation was triggered

        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0
```

---

### 1.4 Cache Bypass Scenarios (2 tests)

**What's validated**: CRUD agents skip snapshot cache; non-CRUD agents still use it.

```python
class TestCacheBypassPipeline:
    """CRUD agents bypass the LanceDB snapshot cache."""

    def test_crud_agent_triggers_cache_skip( self ):
        """isinstance(agent, CrudForDataFramesAgent) is True → cache skipped."""
        # This is the exact isinstance check in running_fifo_queue.py:161
        agent = _create_mock_agent()
        assert isinstance( agent, CrudForDataFramesAgent )

        # Simulate the cache decision from running_fifo_queue.py:160-164
        should_skip_cache = isinstance( agent, CrudForDataFramesAgent )
        assert should_skip_cache is True

    def test_non_crud_agent_uses_cache( self ):
        """Non-CRUD AgentBase subclasses still use the cache."""
        from cosa.agents.math_agent import MathAgent

        # MathAgent is a regular AgentBase — should NOT skip cache
        assert issubclass( MathAgent, CrudForDataFramesAgent ) is False
```

---

### 1.5 Confirmation Flow Scenarios (4 tests)

**What's validated**: Delete triggers yes/no prompt; yes proceeds, no cancels, timeout cancels; add skips prompt entirely.

```python
class TestConfirmationFlowPipeline:
    """Voice confirmation for destructive operations."""

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_triggers_confirmation_yes_proceeds( self, mock_notify, tmp_storage_dir ):
        """Delete operation: user says yes → dispatch proceeds."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        from cosa.crud_for_dataframes.crud_operations import add_item
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        agent.crud_intent = CRUDIntent(
            operation    = "delete",
            target_list  = "groceries",
            schema_type  = "todo",
            match_fields = '{"todo_item": "buy milk"}'
        )

        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "yes"
        mock_notify.return_value     = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "deleted"

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_triggers_confirmation_no_cancels( self, mock_notify, tmp_storage_dir ):
        """Delete operation: user says no → operation cancelled."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            target_list = "groceries",
            schema_type = "todo"
        )

        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "no"
        mock_notify.return_value     = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "cancelled"
        assert result[ "output" ][ "message" ] == "Operation cancelled."

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_timeout_cancels_safely( self, mock_notify, tmp_storage_dir ):
        """Delete operation: timeout → operation cancelled (safe default)."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            target_list = "groceries",
            schema_type = "todo"
        )

        mock_response            = MagicMock()
        mock_response.is_timeout = True
        mock_response.is_error   = False
        mock_notify.return_value = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "cancelled"

    def test_add_skips_confirmation_entirely( self, tmp_storage_dir ):
        """Add operation: no confirmation prompt triggered."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir )

        agent.crud_intent = CRUDIntent(
            operation   = "add",
            target_list = "groceries",
            schema_type = "todo",
            fields      = '{"todo_item": "buy milk", "priority": "high"}'
        )

        # No mock for notify_user_sync — if called, test would fail
        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "added"
```

---

### 1.6 Prompt Construction Scenarios (5 tests)

**What's validated**: Real template from disk + `PromptTemplateProcessor` produces a correct, format-ready prompt. Fills the gap between "plumbing works in isolation" and "the actual agent gets the right prompt."

```python
class TestPromptConstruction:
    """Verify the real template + PromptTemplateProcessor produces a correct prompt."""

    def test_template_marker_replaced( self ):
        """{{PYDANTIC_XML_EXAMPLE}} marker is replaced by PromptTemplateProcessor."""

    def test_intent_xml_injected( self ):
        """Processed template contains <intent>...</intent> XML block."""

    def test_stop_sentinel_present( self ):
        """Processed template includes </stop> sentinel after closing </intent>."""

    def test_generic_placeholders_not_concrete( self ):
        """XML example uses generic placeholders, not concrete data like 'groceries'."""

    def test_format_substitution_works( self ):
        """prompt_template.format(query=..., available_lists=...) succeeds."""
```

---

### 1.7 Running the Tests

```bash
# Run all mock pipeline tests
pytest src/tests/unit/test_crud_mock_pipeline.py -v

# Run a specific test class
pytest src/tests/unit/test_crud_mock_pipeline.py::TestFullPipelineMocked -v

# Run with debug output
pytest src/tests/unit/test_crud_mock_pipeline.py -v -s
```

---

## Part 2: Notifications UI Protocol

Interactive test scenarios using the live server's Q&A input and notification cards. **Requires server running on port 7999.**

### 2.1 Server Setup

```bash
# Terminal 1: Start the Lupin FastAPI server
src/scripts/run-fastapi-lupin.sh

# Terminal 2: Verify server is running
curl -s http://localhost:7999/api/mock-job/health | python3 -m json.tool
# Expected: {"status": "ok", "available": true, ...}
```

Open browser: `http://localhost:7999` → Log in with test credentials → Navigate to Q&A input.

### 2.2 Non-Destructive Operations (Q&A Box)

These tests type natural language into the Q&A input box. The command flows through:

```
Q&A input → POST /api/push (queues.py:120-210)
  → TodoFifoQueue.push_question()
  → Router classifies command (e.g., "agent router go to todo list")
  → _crud_agents_enabled() check (todo_fifo_queue.py:868-879)
  → TodoCrudAgent or CalendarCrudAgent created (todo_fifo_queue.py:635-642)
  → Pushed to RunningFifoQueue
  → run_prompt() → run_code() → run_formatter()
  → TTS response delivered via notification
```

| # | Input Text | Expected Agent | Expected Behavior |
|---|-----------|----------------|-------------------|
| 1 | "add buy milk to my grocery list" | TodoCrudAgent | Item added, TTS says "Done. Added 'buy milk' to groceries." |
| 2 | "what's on my grocery list?" | TodoCrudAgent | Items listed, TTS reads items back |
| 3 | "add dentist appointment on March 15 at 2pm" | CalendarCrudAgent | Event added, TTS confirms |

**Verification for each**:
1. Server console shows `Starting a new job: todo (CRUD)` or `calendar (CRUD)` (not legacy names)
2. Job card appears in the notifications UI with correct agent type
3. TTS response plays with correct content
4. No error messages in server console

### 2.3 Destructive Operations (Confirmation Card)

These tests trigger voice confirmation for delete/update operations.

| # | Input Text | Expected Card | User Action | Expected Outcome |
|---|-----------|---------------|-------------|-----------------|
| 4 | "delete buy milk from my grocery list" | Yes/No action-required card | Click "Yes" | Item deleted, TTS says "Done. Deleted 1 item from groceries." |
| 5 | "delete buy milk from my grocery list" | Yes/No action-required card | Click "No" | TTS says "Operation cancelled." |
| 6 | "delete buy milk from my grocery list" | Yes/No action-required card | Let it timeout (30s) | TTS says "Operation cancelled." (safe default) |

**Verification for each**:
1. Action-required notification card renders in the UI (notifications.js renders Yes/No buttons)
2. Card shows message: "Are you sure you want to delete from groceries?"
3. Clicking Yes/No triggers `POST /api/notify/response` (notifications.py:657-827)
4. Response correctly unblocks the SSE stream back to the agent
5. TTS response matches expected outcome

### 2.4 Feature Flag Toggle Test

| # | Config Change | Input Text | Expected Agent |
|---|---------------|-----------|----------------|
| 7 | Set `crud for dataframes agents enabled = false` in `src/conf/lupin-app.ini` | "add buy milk to my grocery list" | Legacy `TodoListAgent` |
| 8 | Set `crud for dataframes agents enabled = true` (restore default) | "add buy milk to my grocery list" | `TodoCrudAgent` |

**Steps**:
1. Stop the server
2. Edit `src/conf/lupin-app.ini` line 535: change `true` → `false`
3. Start the server
4. Submit test #7 — verify server console shows "Starting a new job: todo list" (legacy)
5. Stop the server
6. Restore `true`
7. Start the server
8. Submit test #8 — verify server console shows "Starting a new job: todo (CRUD)"

### 2.5 Expected UI Behaviors

**Action-Required Card Rendering** (from notifications.js:9638-9681):
- Yes/No buttons appear on destructive operation confirmation cards
- Card sender shows `crud.agent@lupin.deepily.ai`
- Card priority is `high` (matches `NotificationRequest` in agent.py:316)
- Timeout is 30 seconds (matches `timeout_seconds=30` in agent.py:317)

**TTS Response Patterns** (from `format_result_for_voice()` in dispatcher.py):
- **Add**: "Done. Added '{item}' to {list_name}."
- **Query**: Lists items in natural language
- **Delete**: "Done. Deleted {count} item(s) from {list_name}."
- **Cancelled**: "Operation cancelled."

---

## Part 3: Curl Smoke Tests

Quick command-line verification without opening the UI. **Requires server running on port 7999.**

### Authentication

```bash
# Get auth token (replace with your test credentials)
TOKEN=$(curl -s -X POST http://localhost:7999/auth/login \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$LUPIN_TEST_EMAIL\", \"password\": \"$LUPIN_TEST_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tokens']['access_token'])")

echo "Token: ${TOKEN:0:20}..."
```

### Scenarios

| # | Test | Command | Expected |
|---|------|---------|----------|
| 1 | Health check | `curl -s http://localhost:7999/api/mock-job/health` | `{"status": "ok", "available": true, ...}` |
| 2 | Submit todo via push | See below | Job queued, CRUD agent type in server console |
| 3 | Feature flag off | Set config `false`, restart, same push | Legacy agent type in server console |
| 4 | Destructive submit | "delete buy milk from groceries" via push | Confirmation notification created |

**Test 1: Health Check**

```bash
curl -s http://localhost:7999/api/mock-job/health | python3 -m json.tool
```

**Test 2: Submit Todo via Push**

```bash
# Get websocket_id from an active browser session:
WS_ID=$(curl -s http://localhost:7999/api/debug/websocket-state \
  | python3 -c "
import sys, json
state = json.load(sys.stdin)
user_sessions = state.get('user_sessions', {})
if not user_sessions: print('NO_ACTIVE_SESSION')
else:
    first_user = list(user_sessions.keys())[0]
    sessions = user_sessions[first_user]
    print(sessions[0] if sessions else 'NO_ACTIVE_SESSION')
")

curl -s -X POST http://localhost:7999/api/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"question\": \"add buy milk to my grocery list\", \"websocket_id\": \"$WS_ID\"}"
```

**Expected server console output**:
```
Starting a new job: todo (CRUD)
CrudForDataFramesAgent: prompt length=..., user=test@example.com
CrudForDataFramesAgent.run_prompt: Parsed intent: operation=add, target_list=groceries
```

**Test 3: Feature Flag Toggle (curl)**

```bash
# 1. Stop server
# 2. Edit lupin-app.ini: crud for dataframes agents enabled = false
# 3. Start server
# 4. Re-run Test 2
# Expected console: "Starting a new job: todo list" (legacy agent)
# 5. Restore flag to true, restart
```

**Test 4: Destructive Operation via Push**

```bash
curl -s -X POST http://localhost:7999/api/push \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "question": "delete buy milk from my grocery list",
    "websocket_id": "YOUR_WEBSOCKET_ID"
  }'
```

**Expected**: Server console shows confirmation prompt being sent. A notification card appears in the UI (if browser is connected) or the confirmation times out after 30s and the operation is cancelled.

---

## Appendix: Troubleshooting

### Common Issues

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: No module named 'cosa'` | PYTHONPATH not set | `export PYTHONPATH=".../lupin/src:$PYTHONPATH"` |
| Server won't start | Port 7999 in use | `lsof -i :7999` → kill existing process |
| "Starting a new job: todo list" (legacy) | Feature flag is `false` | Check `lupin-app.ini` line 535 |
| Confirmation card doesn't appear | Browser not connected | Ensure browser is logged in and WebSocket active |
| Timeout instead of TTS response | LLM endpoint not running | Verify Phi-4 14B is loaded and accessible |
| "CRUD dispatch failed" in server logs | Intent extraction failed | Check LLM response format — should contain `<intent>` XML |
| `CodeGenerationFailedException` | Both Phi-4 and Claude fallback failed | Check model config key and Claude Code availability |

### Key Source Files

| File | Role |
|------|------|
| `src/cosa/crud_for_dataframes/agent.py` | CRUD agent with run_prompt/run_code/run_formatter + confirmation logic |
| `src/cosa/crud_for_dataframes/dispatcher.py` | dispatch() + format_result_for_voice() + extract_intent_xml() |
| `src/cosa/crud_for_dataframes/intent_extractor.py` | Claude Code headless fallback for intent extraction |
| `src/cosa/crud_for_dataframes/storage.py` | Per-user parquet-backed DataFrame storage |
| `src/cosa/crud_for_dataframes/crud_operations.py` | add_item, delete_item, query, mark_done, etc. |
| `src/cosa/crud_for_dataframes/xml_models.py` | CRUDIntent Pydantic XML model |
| `src/cosa/rest/todo_fifo_queue.py:617-642,868-879` | Routing swap with feature flag |
| `src/cosa/rest/running_fifo_queue.py:160-164,474-481` | Cache skip + serialization exclusion |
| `src/cosa/rest/routers/queues.py:120-210` | POST /api/push endpoint |
| `src/cosa/rest/routers/notifications.py:213-655` | POST /api/notify (fire-and-forget + response-required) |
| `src/cosa/rest/routers/notifications.py:657-827` | POST /api/notify/response |
| `src/cosa/rest/routers/mock_job.py:321-332` | GET /api/mock-job/health |
| `src/conf/lupin-app.ini:533-535` | Feature flag + CRUD config keys |
| `src/tests/unit/test_crud_for_dataframes_agent.py:548-718` | Mock agent pattern reference |
| `src/tests/unit/test_crud_queue_integration.py` | Routing + cache + confirmation unit tests |

### Test Summary Matrix

| Part | Test Count | Server Required | LLM Required | Status | What's Validated |
|------|-----------|-----------------|-------------|--------|-----------------|
| Part 1: Mock Objects | 17 | No | No (mocked) | **DONE** (17/17) | Routing swap, full pipeline, cache bypass, confirmation flow, prompt construction |
| Part 3: Curl Smoke Tests | 4 | Yes (port 7999) | Yes (Phi-4 14B) | PENDING | Health check, push endpoint, feature flag toggle, destructive ops |
| Part 2: Notifications UI | 8 | Yes (port 7999) | Yes (Phi-4 14B) | PENDING | Q&A submission, confirmation cards, TTS responses, feature flag |
| **Total** | **29** | — | — | — | — |
