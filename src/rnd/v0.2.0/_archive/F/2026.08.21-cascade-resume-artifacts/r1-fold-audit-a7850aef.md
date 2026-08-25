# R1 fold audit — `a7850aef`, the mechanical pass

**Tiberius 👑, 2026-08-21.** Read-only. Third fold audit, same method.
`83e81f85..a7850aef`, **+67 / −15**.

---

## Headline: 13 of 13 corrected at the carrying line. The pass ran.

**Deletion map** — every deletion landed on a checklist line number: `535-537` (Files rows), `540`
(reuse), `640-643` (tally), `655-658` (parity), `661` (pre-merge). Additions at `57` (orphans), `596`
/ `600` (step 5, step 3), `900` (replay `primary_error`). **First fold where the deletions sit on the
lines an implementer reads rather than inside the author's own new prose.**

| # | verdict |
|---|---|
| 11 parked-rename | ✅ needs-input `parked` **left alone**, only `Outcome.status` renamed, with the `v2_ask.py:57` contract note and a line recording that the earlier draft said the opposite |
| 12 stale Files row | ✅ "BOTH v1 cache stages go" |
| 6 asserted+disclaimed scope | ✅ split — `:313` in scope, `:953` **PENDING Q4** |
| 1 reuse list | ✅ single CRUD-aware resolver, notes the old target is now backwards |
| 9 2b call sites | ✅ `flow.py:111` and `:182` named |
| 10 missing `fifo_queue.py` row | ✅ added with `:83-110`, `:125-138`, smoke block `:683`/`:700`/`:743`/`:840-848` |
| 3 step 5 reindent | ✅ stated, **and correctly left as a choice** — say-it-plainly or move after the switch |
| 5 replay reports `routing_command` | ✅ owed inside step 3 |
| 2 tally | ✅ definition changed first, then recounted |
| 7 "stay green unchanged" | ✅ stated, **per-suite list left open** |
| 8 pre-merge | ✅ serial bridge guard added; through-path test named as owed |
| 14 replay `primary_error` | ✅ now at the carrying line |
| 13 orphans | ✅ new section naming all three, with the `user_id`/ownerless consequence |

### One residual in the corrected tally — its list and its number disagree

The new text names **7** commits and concludes **six**: voice group `{6c, 7b, step 5}` plus API group
`{2b, 6-pre, 6a, 6b}`. **Six is the right number; `step 5` is the wrong member.** The plan proves
elsewhere that the two-turn branch has **zero production callers**, so deleting it changes nothing a
user can perceive — the prompt Rick hears is the synchronous ask at `todo_fifo_queue.py:636`, which
**7b** removes. Dropping step 5 from the list makes the membership match the number.

---

## Add-on: what `admin.py:810` actually is

**`GET /api/admin/snapshots/search`** — admin-role-gated (`Depends( require_admin )`), a similarity
search over snapshots.

**It is a live `get_snapshots_by_question` call site and it is NOT a replay path.** It returns
`SnapshotSearchResult` — `id_hash`, `question_preview`, `question_gist`, `created_date`, `score`.
**No answer field, no `run_code`, no `run_formatter`, nothing enqueued.** It is a human inspecting the
store.

⇒ **The one-home claim stands**, with one qualification worth folding:

> **Put the guard at the replay decision, not inside `get_snapshots_by_question`.** A guard placed in
> the shared lookup helper would also filter this endpoint — hiding unconfirmed rows from the one
> person whose job is to look at them, and doing it silently. The guard's question is *"may this row
> be SERVED AS AN ANSWER"*, which is a question only the replay path asks.

---

## Decision 1 — step 5 placement. My position: **move it after the switch.**

Three reasons, strongest first.

1. **Step 5's own justification points at code another step deletes — the original defect, still
   there.** Step 5 says nothing replaces the two-turn dialogue because *"the synchronous yes/no at
   `:636` already IS the live confirmation."* `:636` is inside the block **7b** removes. Moving 5
   after 7b dissolves that dependency instead of documenting around it.
2. **Step 5 is not observable, so "it lands alone because Rick hears it" is not a reason to keep it
   early.** Zero production callers of `push_blocking_object`; `_accepting_jobs` never goes false;
   the `:541` pop is inert. Nothing it deletes can be perceived.
3. **The reindent gets cheaper.** ~330 lines of `else:` body unindent either way, but after 6c that
   block is no longer the live path, so a whitespace-dominated diff is reviewed against dead code
   rather than against the code every spoken question runs.

**What would change my mind**: a reason the dead branch must not survive alongside the new flow — for
instance if 6c's wiring would otherwise re-enter it. It cannot: `is_accepting_jobs()` never goes
false, so the branch at `:507` is unreachable regardless of what calls `push_job`. **If María has a
different reason it must stay early, I will take the say-it-plainly wording instead** — my objection
is to the plan asserting a four-line delete, not to the placement as such.

---

## Decision 2 — parity-test disposition, concrete

"Step 5 breaks two suites" is true but coarse. Measured, it is **one deletion, one fixture edit, and
two rewrites that belong to other steps.**

| test | file:line | disposition | step |
|---|---|---|---|
| `test_not_accepting_jobs_confirmation_runs_snapshot` | `test_todo_fifo_queue_coverage.py:311-321` | **DELETE** | 5 |
| `ConfirmationDialogue` import | `…coverage.py:16` | **EDIT** — the symbol dies with the branch | 5 |
| `_blocking_object` / `_accepting_jobs` fixture lines | `test_crud_queue_integration.py:410-411` | **EDIT, 2 lines** | 5 |
| `test_refactor_skips_snapshot_search` | `…coverage.py:323-330` | **REWRITE** | **7b**, not 5 |
| `resolve_voice` call | `…coverage.py:227` | **REWRITE** | **2b** |
| `assert "resolve_voice(" in source` | `test_registry_voice_binding.py:214-217` | **REWRITE TWICE** | **2b**, then **6c** |

**Reasoning per row.**
- The first is a **true deletion**: it exercises only `push_blocking_object` → `ConfirmationDialogue`
  → `_queue_best_snapshot`, every mechanism of which step 5 removes. There is nothing to rewrite it
  into — the behaviour is gone by ruling, not relocated. Under the coverage mandate that is fine: the
  code it covered no longer exists. Its replacement is the plain-language comment step 5 already owes.
- `test_crud_queue_integration.py:410-411` is **fixture scaffolding, not coverage** — the suite builds
  a `RunningFifoQueue` via `__new__` and hand-sets what `FifoQueue.__init__` would. When the fields go,
  the two lines go. **No test intent changes**, which is worth saying plainly so this row is not read
  as parity loss.
- `test_refactor_skips_snapshot_search` asserts `get_snapshots_by_question.assert_not_called()` for the
  `"refactor "` DEMO KLUDGE skip — that lives in the search-and-ask block **7b** deletes, and step 5
  never touches it.
- The **source-text pin is invalidated twice** — 2b changes which resolver `push_job` calls, then 6c
  stops it resolving at all. Better said once in the plan than discovered twice in the build.
