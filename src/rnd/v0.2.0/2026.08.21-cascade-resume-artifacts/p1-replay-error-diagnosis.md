# The 42% replay_error — diagnosed, read-only

**Row** `d8d019f6` (P1, in_progress, Tiberius 👑) · **2026-08-21** · no code changed, no server touched.
**Evidence**: `io/v2-flow/eval-2026-08-20-21-44-34/records.jsonl` (200 records from run `ts-e0311090`),
`io/v2-flow/trace-2026-08-21.jsonl`, and the code at HEAD.

## Headline

**The cache is not the defect. The cached CODE does not run, and two of the three reasons are
identified.** All 42 failures are tier-1 exact hits at similarity 100.0 — the lookup found exactly the
right row every time — and every one of them died inside `snap.run_code()`.

## How we know it is `run_code()` and not the formatter

`InlineExecutor._replay` marks each stage *before* the call it names:

| line | mark | then calls |
|---|---|---|
| `executor.py:102` | `t_replay_code` | `snap.run_code()` |
| `executor.py:104` | `t_replay_format` | `snap.run_formatter()` |

All 42 failing records carry `t_replay_code` and **none** carry `t_replay_format`. All 21 successful
replays (`route_reason=exact_hit`) carry both. The failure is inside `run_code()`, before the
formatter is ever reached.

## The distribution, and why it matches

| expected_command | replayed OK | replay_error |
|---|---|---|
| calculator | 17 | 0 |
| math | 4 | 14 |
| todo | 0 | 19 |
| none (receptionist) | 0 | 9 |

## Cause 1 — codeless snapshots that are not CalculatorAgent (9 of 42, the `none` rows)

`solution_snapshot.py:883` short-circuits `run_code()` for `agent_class_name == "CalculatorAgent"`
only, returning the cached answer. Every other codeless snapshot falls through to the guard at
`:895`, which raises `ValueError( "Cannot execute empty code list — snapshot has no executable code" )`.
Receptionist snapshots have no Python to save, so every one of them raises on replay. This is exactly
the failure the 2026-04-28 fix documented at `:860-863` — and that fix was written for CalculatorAgent
alone, so the class of bug survived for every other codeless agent.

## Cause 2 — the todo dataframe path is matched against a command string nothing emits (19 of 42)

`run_code()` picks the data file by exact string match at `solution_snapshot.py:897`:

```python
if self.routing_command == "agent router go to todo list":
    path_to_df = "/src/conf/long-term-memory/todo.csv"
```

The registry's canonical command is the **short** form — `registry.py:123`,
`AgentSpec( "agent router go to todo", TodoListAgent, aliases=( "todo", "todo list" ) )`. v1's queue
accepts both forms (`todo_fifo_queue.py:771`), so nothing upstream ever noticed. A snapshot written
with the canonical short form therefore gets `path_to_df = None`, and its saved pandas code runs with
no dataframe.

## Cause 3 — math, 14 of 20, not yet explained

Math snapshots carry real generated code and 4 of them replay fine, so neither cause above covers it.
Needs the error text, which is exactly what is currently thrown away — see below.

## 🔴 Why none of this was visible, and it is a gap the plan already knows about in another branch

`InlineExecutor._replay` returns `Outcome( status="failed", error=str( e ) )` at `executor.py:108`,
carrying the real exception. **The call site discards it**: `flow.py:102` reads

```python
return self._receptionist( trace, question, ctx, "replay_error" )
```

— no `primary_error`. So the payload's `error` field is `null` for every replay failure whose
receptionist then succeeded, and the trace row carries no error field at all (verified on
`trace_id=d0ad525c2e054cb6822ff67a0055b32e`). The non-null errors that DO appear in the records are the
receptionist's own XML-parse failures, not the replay's.

**This is the identical gap the cascade plan documents for `router_error` at `flow.py:110`** — and the
plan's stated fix ("wrap the routing call; on failure pass a `primary_error` that names it") is scoped
to the router only. The replay branch is the highest-volume failure path in the measured run, 42 of
100 warm requests, and it would stay silent after that fix lands. → cascade finding 14.

## What to do, in order

1. **Instrument before fixing** — pass `primary_error` at `flow.py:102`. One line, and it is what
   makes cause 3 readable instead of guessed at.
2. Widen the codeless short-circuit at `solution_snapshot.py:883` from a `CalculatorAgent` name check
   to "no code and an answer present", or refuse to write codeless snapshots at all.
3. Resolve the todo command-string mismatch at `solution_snapshot.py:897` — match the registry rather
   than a literal, since the registry already owns the aliases.
4. Re-run the paired eval. Causes 1 and 2 together are 28 of the 42; recovering them plus the
   mode-switch discriminator fix (`f6c69a3e`, committed and still unexercised) is what plausibly lifts
   the intersection from 10 toward María's 30-pair floor.

**Nothing above was implemented.** Rick's standing order is that nobody builds until the open
questions close, and this seat is read-only for the cascade review.

## Bearing on the plan under review

The plan's step 3 treats the replay branch as healthy and needing only to accept `waiting`. On the
measured evidence the replay branch fails 42% of the time on live-shaped traffic and reports nothing
about why. Wiring the voice path to `AskFlow` (step 6c) puts every spoken question through that
branch.
