# Layer 2: Phi-4 14B Intent Extraction + Claude Code Headless Fallback

**Status**: IMPLEMENTATION COMPLETE — 73 unit tests passing, zero regressions
**Phase**: 2 of 4
**Depends on**: Layer 1 (storage + schemas + CRUD + XML models) — COMPLETE
**Date**: 2026-02-06

---

## Context

Phase 1 (Storage Layer) is **complete**: 5 source files, 107 tests passing, 4 config keys added. Phase 2 builds the agent that connects the existing COSA voice pipeline to the Phase 1 CRUD operations. The agent extracts intent from natural language via Phi-4 14B (through the existing LLM factory), dispatches to `crud_operations`, and formats results for TTS.

**Key Design Decisions**:

1. **Override both `run_prompt()` and `run_code()`** — `run_prompt()` parses the LLM response directly into a `CRUDIntent` object via `CRUDIntent.from_xml()` (Pydantic XML), skipping the `XmlParserFactory` flat-dict intermediate. `run_code()` dispatches the intent to CRUD operations. `do_all()` is NOT overridden so `RunningFifoQueue._handle_base_agent()` works unchanged.

2. **Error-based fallback via `CodeGenerationFailedException`** — Do NOT use confidence to trigger fallback. If Phi-4 intent dispatch **throws an error**, fallback to Claude Code headless. If both paths fail, raise `CodeGenerationFailedException` (`agent_base.py:21`) — the same error the queue handles via `_handle_error_case()`.

3. **Subclass-per-domain architecture** — `CrudForDataFramesAgent` is the base. `TodoCrudAgent` and `CalendarCrudAgent` are thin subclasses with domain-specific prompts and formatting. Eventually replaces `TodoListAgent` and `CalendaringAgent`.

4. **Direct Pydantic XML parsing** — No `xml_response_tag_names`. The LLM response is parsed directly into a `CRUDIntent` via `from_xml()`, consistent with the `BaseXMLModel` pattern used by `ExpeditorResponse` and the Phase 1 CRUDIntent model. The prompt XML example is generated from `CRUDIntent.get_example_for_template().to_xml()`.

---

## Architecture: Subclass-Per-Domain

```
                    AgentBase (agent_base.py)
                         |
              +----------v-----------+
              | CrudForDataFramesAgent|
              |  * run_prompt() -> CRUDIntent.from_xml()
              |  * run_code()  -> dispatch()
              |  * run_formatter() -> format_result_for_voice()
              |  * Claude Code fallback
              +------+--------+------+
                     |        |
            +--------v-+  +--v----------+
            |TodoCrud   |  |CalendarCrud |
            |Agent      |  |Agent        |
            | * schema  |  | * schema    |
            |   ="todo" |  |   ="calendar|
            | * custom  |  | * custom    |
            |   prompt  |  |   prompt    |
            +-----------+  +-------------+
```

**Migration path**: Phase 3 swaps queue routing from `TodoListAgent`/`CalendaringAgent` to the new subclasses using the same routing commands.

---

## XML Lifecycle (Pydantic Direct Path)

```
    +-----------------------------------------------------+
    | 1. PROMPT BUILD                                      |
    |    CRUDIntent.get_example_for_template()             |
    |      .to_xml( root_tag="intent" )                    |
    |    -> XML example injected into prompt template       |
    +------------------------+----------------------------+
                             |
    +------------------------v----------------------------+
    | 2. LLM RESPONSE                                      |
    |    Phi-4 returns: <intent><operation>add</operation>  |
    |    <target_list>groceries</target_list>...</intent>   |
    +------------------------+----------------------------+
                             |
    +------------------------v----------------------------+
    | 3. PARSE (override run_prompt)                        |
    |    raw_response = llm.run( self.prompt )               |
    |    xml_text = extract_intent_xml( raw_response )       |
    |    self.crud_intent = CRUDIntent.from_xml( xml_text,   |
    |                          root_tag="intent" )           |
    |    -> Fully validated Pydantic object with all          |
    |      convenience methods (get_fields_dict(), etc.)     |
    +------------------------+----------------------------+
                             |
    +------------------------v----------------------------+
    | 4. DISPATCH (override run_code)                       |
    |    result = dispatch( self.crud_intent, self.storage ) |
    +-----------------------------------------------------+
```

**No `xml_response_tag_names`** — the Pydantic model IS the schema. No flat dict intermediate.

---

## Fallback Strategy: Error-Based with `CodeGenerationFailedException`

```
    User query -> run_prompt() -> CRUDIntent
                                    |
                          +---------v----------+
                          |  run_code()         |
                          |  try:               |
                          |    dispatch()       |---- Success -> return_code: 0
                          |  except:            |
                          |    v error          |
                          +---------+----------+
                                    |
                          +---------v----------+
                          |  Claude Code -p     |
                          |  -> CRUDIntent      |
                          |  dispatch() again   |---- Success or
                          |                     |     raise CodeGenerationFailedException
                          +--------------------+
```

**In `run_code()`:**
```python
from cosa.agents.agent_base import CodeGenerationFailedException

def run_code( self, auto_debug=None, inject_bugs=None ):
    try:
        result = dispatch( self.crud_intent, self.storage, debug=self.debug )
        if result.get( "status" ) == "error":
            raise ValueError( result[ "message" ] )
        self.code_response_dict = { "return_code": 0, "output": result }
        self.error = None

    except Exception as e:
        if self.debug: print( f"Phi-4 dispatch failed: {e}. Falling back to Claude Code..." )
        fallback_intent = extract_intent_via_claude_code( ... )

        if fallback_intent is not None:
            try:
                result = dispatch( fallback_intent, self.storage, debug=self.debug )
                if result.get( "status" ) == "error":
                    raise ValueError( result[ "message" ] )
                self.code_response_dict = { "return_code": 0, "output": result }
                self.error = None
            except Exception as fallback_error:
                raise CodeGenerationFailedException(
                    f"CRUD dispatch failed after Phi-4 and Claude Code: {fallback_error}"
                )
        else:
            raise CodeGenerationFailedException(
                f"CRUD dispatch failed: Phi-4 error [{e}], Claude Code returned None"
            )

    return self.code_response_dict
```

---

## Files to Create (6 new files)

### 1. `src/cosa/crud_for_dataframes/agent.py` — CrudForDataFramesAgent (base)

**Constructor** (follows MathAgent pattern):
```python
class CrudForDataFramesAgent( AgentBase ):
    def __init__( self, question="", question_gist="", last_question_asked="",
                  push_counter=-1,
                  routing_command="agent router go to crud for dataframes",
                  user_id="ricardo_felipe_ruiz_6bdc", user_email="", session_id="",
                  debug=False, verbose=False, auto_debug=False, inject_bugs=False ):

        super().__init__(
            df_path_key=None,
            question=question, question_gist=question_gist,
            last_question_asked=last_question_asked,
            push_counter=push_counter, routing_command=routing_command,
            user_id=user_id, user_email=user_email, session_id=session_id,
            debug=debug, verbose=verbose, auto_debug=auto_debug,
            inject_bugs=inject_bugs
        )

        # Initialize per-user storage
        self.storage = DataFrameStorage( user_email=user_email, config_mgr=self.config_mgr, debug=debug )

        # Build prompt with dynamic CRUDIntent XML example + user's list context
        available_lists = self.storage.get_all_lists_metadata()
        intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )
        self.prompt = self.prompt_template.format(
            query=self.last_question_asked,
            available_lists=self._format_lists_for_prompt( available_lists ),
            intent_example=intent_example
        )

        # CRUDIntent parsed from LLM response (set in run_prompt)
        self.crud_intent = None

        # NO xml_response_tag_names — using CRUDIntent.from_xml() directly
```

**Method overrides:**
- `run_prompt()` — Calls LLM, extracts `<intent>` XML from response, parses into `CRUDIntent.from_xml()`. Stores `self.crud_intent`.
- `run_code()` — Dispatches `self.crud_intent` to CRUD operations. Error-based fallback with `CodeGenerationFailedException`.
- `run_formatter()` — Uses `format_result_for_voice()` directly (no extra LLM call).
- `restore_from_serialized_state()` — `NotImplementedError` (standard pattern).
- `_format_lists_for_prompt()` — Formats list metadata as text for prompt.

### 2. `src/cosa/crud_for_dataframes/todo_crud_agent.py` — TodoCrudAgent

Thin subclass. Sets `routing_command="agent router go to todo list"`, `default_schema_type="todo"`. Uses todo-specific prompt and voice formatting.

### 3. `src/cosa/crud_for_dataframes/calendar_crud_agent.py` — CalendarCrudAgent

Thin subclass. Sets `routing_command="agent router go to calendar"`, `default_schema_type="calendar"`. Uses calendar-specific prompt and voice formatting.

### 4. `src/cosa/crud_for_dataframes/dispatcher.py` — Intent Dispatch + Voice Formatting

**Functions:**
- `dispatch( intent, storage, debug=False )` — Routes CRUDIntent -> `crud_operations` function by operation name.
- `format_result_for_voice( result, operation )` — Converts result dicts to TTS strings.
- `extract_intent_xml( raw_response )` — Regex extracts `<intent>...</intent>` from raw LLM response (handles markdown fences, preamble). Used by `run_prompt()`.

### 5. `src/cosa/crud_for_dataframes/intent_extractor.py` — Claude Code Headless Fallback

**Functions:**
- `extract_intent_via_claude_code( query, available_lists_text, debug=False )` — Calls `claude -p`, parses response into `CRUDIntent`. Returns `CRUDIntent` or `None`.
- `build_claude_prompt( query, available_lists_text )` — Builds Claude Code prompt with operations, schemas, output format.

### 6. `src/tests/unit/test_crud_for_dataframes_agent.py` — Unit Tests

Tests covering:
- **Dispatcher**: `dispatch()` all 9 operations, `format_result_for_voice()` all result types, `extract_intent_xml()` edge cases
- **Agent** (mocked LLM): Constructor, prompt includes CRUDIntent XML example + available lists, `run_prompt()` produces validated CRUDIntent, `run_code()` dispatches, `run_formatter()` produces conversational string
- **Error-based fallback**: dispatch error -> Claude Code mock -> success
- **`CodeGenerationFailedException`**: Both paths fail -> exception raised
- **Subclasses**: TodoCrudAgent/CalendarCrudAgent default schema types
- **XML parsing**: `CRUDIntent.from_xml()` with clean XML, partial XML, malformed XML

---

## Files to Modify (2 files)

### 7. `src/conf/prompts/crud-for-dataframes/intent-extraction.txt`

Replace the hardcoded XML example with `{intent_example}` placeholder (generated from `CRUDIntent.get_example_for_template().to_xml()`). Add `{available_lists}` placeholder:

```
## Output Format
Respond with XML in this exact format:
{intent_example}

## Your User's Current Lists
{available_lists}

## User Query
{query}
```

### 8. `src/cosa/crud_for_dataframes/__init__.py`

Add Phase 2 exports:
```python
from cosa.crud_for_dataframes.dispatcher import dispatch, format_result_for_voice
```

---

## NOT Modified in Phase 2

- `todo_fifo_queue.py` — Queue routing swap is **Phase 3**
- `lupin-app.ini` / `lupin-app-splainer.ini` — Config keys already exist from Phase 1
- `running_fifo_queue.py` — `_handle_base_agent()` already handles `CodeGenerationFailedException`

---

## Reuse Reference

| Pattern | File | What to Reuse |
|---------|------|---------------|
| AgentBase | `src/cosa/agents/agent_base.py:74` | Constructor, `do_all()` |
| CodeGenerationFailedException | `src/cosa/agents/agent_base.py:21` | Error for failed dispatch |
| code_ran_to_completion() | `src/cosa/agents/runnable_code.py:122` | Checks `return_code == 0` |
| CRUDIntent | `src/cosa/crud_for_dataframes/xml_models.py` | `from_xml()`, `to_xml()`, `get_example_for_template()` |
| DataFrameStorage | `src/cosa/crud_for_dataframes/storage.py` | Per-user parquet I/O |
| crud_operations | `src/cosa/crud_for_dataframes/crud_operations.py` | All 9 CRUD functions |
| LlmClientFactory | `src/cosa/agents/llm_client_factory.py` | Standard LLM client |
| MathAgent | `src/cosa/agents/math_agent.py` | Agent constructor reference |

---

## Implementation Order

1. **`dispatcher.py`** — Pure functions, no deps beyond Phase 1. Testable immediately.
2. **`intent_extractor.py`** — Claude Code fallback. Testable with mocked subprocess.
3. **`intent-extraction.txt`** — Update prompt template with `{intent_example}` and `{available_lists}`.
4. **`agent.py`** — Base agent with overridden `run_prompt()`, `run_code()`, `run_formatter()`.
5. **`todo_crud_agent.py`** + **`calendar_crud_agent.py`** — Thin subclasses.
6. **`__init__.py`** — Add exports.
7. **Unit tests** — Full coverage for all new modules.

---

## Verification Plan

### Unit Tests
```bash
pytest src/tests/unit/test_crud_for_dataframes_agent.py -v
```

### Regression Check
```bash
pytest src/tests/unit/test_crud_for_dataframes_storage.py -v  # Phase 1
pytest src/tests/unit/ -v                                      # Full (335 tests)
```

### Smoke Test (agent.py __main__)
```python
agent = CrudForDataFramesAgent(
    question="add buy milk to my grocery list",
    user_email="test@example.com", debug=True
)
result = agent.do_all()
print( result )  # Conversational TTS string
```

---

## Architecture Reference

- Original design: `src/rnd/2026.02.05-headless-cc-for-dataframe-crud.md`
- Implementation plan: `src/rnd/2026.02.05-crud-for-dataframes-implementation.md`
- Layer 1 (complete): `src/rnd/2026.02.04-headless-cc-for-dataframe-crud/layer-1.md`
