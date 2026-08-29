# Carrying-line checklist — the mechanical pass, ready to run

**Tiberius 👑, 2026-08-21.** Line numbers are as of **`83e81f85`** (doc: 1,264 lines). Read-only.
**Purpose**: make the fold-discipline pass verifiable — one row per finding, the line that carries
it, and what has to become true. **The replacement wording is María's; this states the constraint,
not the prose.**

| # | line | what it says now | what must become true |
|---|---|---|---|
| **11** | **535** | Files table, flow.py row ends *"rename the needs-input `parked`"* | The needs-input `parked` is **left alone** — Rick ruled it keeps its name (doc ~L240-245), and it is the value documented on the live endpoint at `v2_ask.py:57`. Only `Outcome.status` is renamed. **Highest priority: an implementer working from this row breaks the `/api/v2/ask` contract.** |
| **12** | **536** | todo_fifo_queue row: *"whichever cache stage Rick's ruling removes"* | Rick ruled **both** stages go. The conditional phrasing predates the ruling. |
| **6** | **537** | running_fifo_queue row: *"in scope, not conditional"* for `:313` **and** `:953` | `:953` is open question 4 and still unruled. The row must not assert scope the document elsewhere disclaims — split `:313` (in scope) from `:953` (pending Q4). |
| **1** | **540** | *"Reuse, do not rebuild: `registry.resolve_voice()`"* | Step 2b **deletes** `resolve_voice()`. The reuse target is the single CRUD-aware resolver. |
| **2** | **642** | *"Three observable commits out of ten"* | Six observable, of 13 steps / 17 commits — **and the definition has to change first**: observable = visible on **any live surface**, not voice-visible. 2b, 6-pre, 6a, 6b are all observable on `/api/v2/ask`. A recount under the old definition returns three again. |
| **7** | **657** | the five parity suites *"must stay green **unchanged**"* | Unsatisfiable as written: step 5 deletes what two of them exercise (`test_todo_fifo_queue_coverage.py:311-316` calls `push_blocking_object` and patches `ConfirmationDialogue`; `test_crud_queue_integration.py:410-411` sets `_blocking_object`/`_accepting_jobs`). The section must say which tests are rewritten and which are deleted. |
| **8** | **661** | Pre-merge: *"unit + cosa"* | The project merge gate also requires the **serial bridge guard** before websocket smoke. Separately, the section states the through-path rule and names no through-path test. |
| **14** | **900** | *"What lands"*: **"Wrap the routing call"** | The correct instruction is already written at **L270-271** — Rick's fail-loud ruling covers **all six** degrade paths, so `primary_error` and the spoken failure extend to the **replay** branch at `flow.py:102`. Two folds running, the correction sits 630 lines from the line it corrects. |
| **3** | step 5 | *"the dead block, the two methods, the gate, and `:541`"* | The branch is `if run_previous_best_snapshot:` at `todo_fifo_queue.py:507`; the live path is its `else:` at `:538` running to `:866`. The step is a **~330-line reindent**, or it moves after the switch. |
| **5** | step 3 / `flow.py:100-101` | replay branch reports `command=lookup.snapshot.routing_command` | After route-first a real routed command exists; the nullable column the plan condemned at L638 should not still feed `_finish`. |
| **9** | step 2b | no call sites listed | Folding the resolvers changes `resolve()`'s signature ⇒ `flow.py:111` and `:182` both change and the flow reads the CRUD flag. Neither is in the step or the Files table. |
| **10** | Files table | no `fifo_queue.py` row | Step 5 deletes `push_blocking_object`/`pop_blocking_object` (`:83-110`) and `is_accepting_jobs` (`:125-138`) **there**, and reddens its `quick_smoke_test()` at `:683` (asserts at `:700`, `:743`, `:840-848`). |
| **13** | STATE AT STOP L46, L50 | `user_id` fail-loud listed SETTLED and cleared-to-build | It has no step, no Files-table row, no Verification line. Same for **step 0** and the **`snapshotable=False`** fix. |

## How to verify the pass actually ran

Re-run the deletion map: `git diff <prev> <new> -- <plan>` and check the deletions land on the line
numbers above. **A fold whose deletions all sit inside its own new sections has not corrected
anything an implementer reads** — that is what the last two folds did, and it is visible in one
command before any prose is read.
