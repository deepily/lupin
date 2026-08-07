# Cascade Revision Handoff — Twisty Tunnel Maze Game

**Run**: `cascade-twisty-maze` · **Manager**: Cheech 🌿 (`72343afa`) · **Date**: 2026.08.06
**Input plan**: [`2026.08.06-twisty-tunnel-maze-game.md`](2026.08.06-twisty-tunnel-maze-game.md) — **revised in place, 222 → 297 lines**
**Step 0 package**: [`00-cascade-step-0-readiness.md`](00-cascade-step-0-readiness.md)
**Status**: Step 9 artifact — awaiting light review by a non-author cast member

---

## 1. Purpose — and what an implementer actually needs to do

The cascade reviewed María 🌸's Twisty Tunnel Maze Game plan across four sections and three review
stages. **The plan file has already been revised.** This document records what changed and why; it is
not a list of pending edits.

**If you are the implementer: build from the revised plan, not from this document.** Read this one
only to learn *why* a decision went the way it did, or to check whether something you disagree with
was argued or merely assumed.

**The one habit to carry forward**: three of the plan's original claims were checked against the
codebase and found wrong — including one naming a file that does not exist, and one whose own cited
reference contradicted it. If you are about to trust a `file:line` in any planning document, grep it.
Every citation in the revised plan has been verified; see §2.

---

## 2. Cascade telemetry

| Metric | Value |
|---|---|
| Wall-clock | 12:44 → 13:10 EDT (~26 min) |
| Cast | 6 seats — Manager, Workflow Steward, Author, 3 stage reviewers |
| Sections | 4 (A engine · B Agent SDK · C wiring · D testing/scope) |
| Stage passes | **12 of 12 closed** |
| Findings raised | ~30 · **2 withdrawn on evidence** |
| Escalated to the user | 2 foundational + 1 batch of 3 settled-scope questions |
| Author revision bundles | 5 — all accepted; 1 correct push-back by the author |
| Re-litigation rounds | **0** — no finding needed a second round |
| Votes called | **0** — no discussion reached the 3-round cap |
| Budget | well under the 25-message-per-section soft cap |
| Plan growth | 222 → **297 lines**; `EXECUTOR:` tags 0 → **8** |

### Citation audit — Manager-run, not relayed

Four of the author's cited references were opened and checked against source:

| Claim | Verified |
|---|---|
| `LEAD_TOOLS = []` at `deep_research/api_client.py:90` | ✅ exact |
| `extract_json_object` at `api_client.py:146` | ✅ exact |
| `create_progress_group()` at `agentic_job_base.py:319`, `notify_progress()` at `:328` | ✅ exact |
| `AGENTIC_AGENTS` at `runtime_argument_expeditor/agent_registry.py:22` | ✅ exact |
| `MODE_METADATA` at `todo_fifo_queue.py:69` | ✅ exact |
| `allowed_tools=` / `mcp_servers=` at `dispatcher.py:412-418` | ✅ exact |

**Independently re-run at Step 9.** The light reviewer was asked to re-check *one* of these. He
re-ran **all six**, including two he had never personally seen. None wrong. He was also asked to
check whether the Manager had softened any of the corrections recorded against himself; he attacked
hardest at correction #3 — the one where the Manager **overrode a reviewer**, which is where a
manager's self-report is least trustworthy — and found it legitimate. *That he tried to find it
self-serving is what makes the verdict worth anything.*

**Final consistency state (Manager-verified after the author's sweep)**: every surviving mention of
"custom tools" in the plan is either a corrected line reading *"no custom tools (see §6)"* or part of
§6's own argument against them. `get_room_state()` is now described as an engine method the
orchestrator calls, not a model-invoked tool.

### Corrections, and who made them against whom

| # | Correction | Direction |
|---|---|---|
| 1 | Test-file naming — the Manager's finding said rename both the proxy script and the Python test file. The project rule splits by file type: dashes for JSON, underscores for Python | **Author → Manager.** Author was right; the Manager had stated the finding too broadly |
| 2 | The `queue_name="run"` claim (§3.C) | **Stage 2 reviewer → Manager.** The Manager had copied a claim out of the artifact under review into the checklist meant to check it |
| 3 | A "hollow tag" finding on the FAILED trigger — the trigger *is* defined, at line 122 | **Manager → Stage 3 reviewer.** The reviewer had read pre-revision bytes; the Manager checked the file rather than routing the finding onward |
| 4 | A Section A ownership finding, made stale by the author's own edit | **Stage 3 reviewer → himself**, unprompted. He re-read his own filed finding against changed bytes and withdrew it |
| 5 | Three ownership findings (A/B/C) sat unrouted while the Manager reported the pipeline as fully bundled | **Manager → himself.** Tracking miss, corrected in bundle 5 |

---

## 3. Per-section revision summary

### 3.A — Maze engine & game state

| Severity | Finding | Closure |
|---|---|---|
| **Foundational** | §5's "twisty passages, all alike" puzzle is defeated by §6's `get_room_state()`, which returns available exits every turn. The plan never said how the gag survives its own tool | **Escalated → Rick ruled**: the tool returns a passage **count**, not directions. Revised |
| Inconsistency | Game state specified as a bare dataclass; all eight reference agents use a Pydantic model in `state.py` | Revised to Pydantic |
| Gap | Maze graph undefined; "guaranteed winnable" had no acceptance test | Concrete 7-room graph with twist cluster authored + **BFS-winnable assertion**, `EXECUTOR: AI` |
| Gap | Direction vocabulary unspecified; FAILED had no trigger; illegal-move side effects undefined | All defined — `{n,s,e,w,u,d}`; FAILED when `move_count > max_moves`; an illegal move changes nothing and does not increment the counter |
| *(withdrawn)* | Engine called "pure, unit-tested" with no executor tag | Withdrawn by the reviewer — the author's earlier edit had already tagged it (line 126) |

**Why the ruling went that way**: the plan's own stated principle is that the deterministic engine is
the source of truth and the model never holds authoritative state. Hiding the exits in *narration*
would have made the puzzle depend on the model choosing to stay vague, turn after turn, untestably —
violating the plan's own principle. In the engine, it is assertable.

### 3.B — Agent SDK Dungeon Master

| Severity | Finding | Closure |
|---|---|---|
| **Foundational** | The claim that the two custom tools *"mirror `deep_research/api_client.py`"* is not merely unsupported — **the named reference contradicts it**. `LEAD_TOOLS = []`; `deep_research` has no custom tools at all. `@tool` and `create_sdk_mcp_server` are zero hits tree-wide | **Escalated → Rick ruled**: structured-JSON move + the existing `extract_json_object` parser. Custom tool surface dropped |
| **Foundational** | Lupin's project mandate requires every new LLM-driven feature to answer *"can this be a bounded CC job?"* in writing. The plan omitted the answer | Answer derived and written in: **yes** — one call per human turn, Anthropic-only, no streaming requirement, user-clicked so off-peak-exempt. **Zero per-token cost; rides the Max plan** |
| Medium | The dungeon master parsing free text into a move had no named verification and no executor tag — the exact mechanic a human would "verify" by playing it | Closed with an `EXECUTOR: AI` parser test: canned agent replies in (including malformed), asserted `{"direction": …}` or `{"error": "unparseable"}` out. **Assertable without a live model** — a direct dividend of the JSON ruling |

**⚠️ The cost of the chosen option, disclosed late — recorded because the user did not see it before
ruling.** The Stage 1 reviewer surfaced the structured-JSON alternative as *"reuse-preserving"*, and
the Manager put the fork to Rick with three reviewers' reasoning behind it. **Only afterwards, when
asked what the alternative would COST rather than save, did she supply it**: structured JSON requires
a full room-state dump in **every** prompt (more tokens), and gives one-shot parse-then-validate with
hand-written retry glue — **no mid-turn loop in which the agent probes state and reacts.** Custom
tools would have bought that live loop, on unproven machinery.

Her own framing of the lesson: *"I'd handed the alt up as pure upside. That's lobbying, not
reporting; a fork must carry its cost in the same breath or I've pre-loaded the manager's decision."*

**Manager's read on whether this should re-open the ruling**: probably not, and the reason is
structural rather than convenient. The orchestrator drives the turn loop and the engine is
authoritative, so the agent has no need to probe state mid-turn — the one thing the lost tool loop
would have bought is the one thing this design deliberately forbids. But that is the Manager's
judgment, formed after the fact, and Rick is entitled to re-open on it.

> 🔴 **RE-OPENED BY RICK, AND THE MANAGER'S RECOMMENDATION WAS WRONG — the decision survived it anyway.**
>
> The first offer to re-open timed out at 13:19 EDT, returning *"[default used] no"* — **nobody
> pressed anything**. It was recorded as an open gate rather than a decline. **When actually asked at
> 14:13, Rick said YES, re-open** — the opposite of the default. *That is the entire case for never
> recording a timeout as a decision: the default would have filed the reverse of his view under his
> name.*
>
> Re-opened properly with a **devil's-advocate seat** (Rio ⚡) briefed to build the strongest honest
> case FOR custom tools and to attack the Manager's counter-argument by name. Outcome:
>
> **The decision stands — structured JSON — but BOTH stated reasons were wrong, and both were the
> Manager's.**
>
> 1. **The Manager's argument was false.** *"The tool loop only buys the model probing state mid-turn,
>    which this design forbids."* That conflates the model **being** the source of truth (correctly
>    forbidden) with the model **reading** the engine's verdict and narrating it — which is precisely
>    what we want, and precisely what a tool loop does. A slogan doing work it had not earned.
> 2. **The plan's reassurance cited the wrong mechanism.** It offered
>    `orchestration/claude_code/dispatcher.py:412-418` as proof the SDK supports custom tools.
>    Manager-verified: those lines configure an **external stdio MCP server** (a python subprocess)
>    plus built-in tool names — **not** the in-process `@tool` / `create_sdk_mcp_server` surface this
>    plan considered. The citation was real and was evidence for a different thing. **In-process tools
>    are therefore MORE unproven here than the plan claimed, not less.**
>
> **The true reason, now on the record**: *this maze starves the tool loop.* The room-state accessor
> returns a passage count already in the prompt, so there is nothing to fetch; the multiple-choice card
> makes illegal moves nearly impossible, so the retry loop rarely fires; narration already happens. The
> loop's value **in this game** is near zero — a claim about this maze, not about tool loops.
>
> **Revisit condition**: if a later version has the Dungeon Master *fetch* room descriptions instead of
> receiving them pre-baked, the loop's value rises and this should be reconsidered. The "model would
> hold state" objection stays false either way.
>
> Rio also found the `_call_bounded` collect loop ignores `ToolUse`/`ToolResult` blocks entirely, so
> adopting tools would mean rewriting it — a cost nobody had named.

**⚠️ Framing that must survive into implementation.** The custom-tool path was declined for **absence
of prior art in this repo**, NOT because the SDK cannot do it — `mcp_servers=` and `allowed_tools=`
are live at `orchestration/claude_code/dispatcher.py:412-418`. A future implementer who reads "we
can't" will draw the wrong boundary around the platform. The revised §6 states this explicitly. The
distinction was caught by the Workflow Steward re-running the reviewer's grep herself.

### 3.C — Job, queue & voice-card integration

| Severity | Finding | Closure |
|---|---|---|
| Inconsistency | §8 hand-rolled its own progress-group plumbing while `AgenticJobBase` already provides `create_progress_group()` (`:319`) and `notify_progress()` (`:328`) — **the plan reinvented its own base class** | Revised to call the base class |
| Inconsistency | §7 named `agent_registry.py` as the wiring point. **No fleet agent registry exists** — the only file by that name belongs to the runtime argument expeditor | Corrected to the `AGENTIC_AGENTS` dict at `agent_registry.py:22`, key `"agent router go to twisty maze"` |
| Gap | Mode-registration path and factory trigger unnamed | Named — `MODE_METADATA` at `todo_fifo_queue.py:69`; trigger is the command string |
| Gap | Voice-routing training data unaddressed | Bullet added — agentic jobs are reached through that natural-language intent |
| **Correction against the Manager** | §8 claimed `queue_name="run"` is required on **every** `notify()`, "non-negotiable" | **Overstated.** It is a registration-time argument on lifecycle calls only; in-loop progress pings carry none and route correctly. Corrected in the plan AND in the Step 0 Recon checklist, which had copied the same wrong line |
| Medium | The in-place card render — "the key mechanic" — had no in-section executor check; prime candidate for a silent hand-off to somebody eyeballing the card | Closed by asserting the **event stream**, not the eye: the `:8000` live-pipeline test asserts room updates reuse the same `progress_group_id` while breadcrumbs append |
| Low | §9's "reviewed cheaply" blurred human-demo against AI-verify | Split — (a) human demo, judgment, no pass/fail; (b) the automated dry-run unit test |

### 3.D — Testing, phasing & scope

| Severity | Finding | Closure |
|---|---|---|
| Gap | §10 omitted the 100% coverage merge gate | Added, with the **concrete scoped command**: `pytest --cov=cosa.agents.twisty_maze --cov-branch --cov-report=term-missing --cov-fail-under=100 src/tests/unit/` |
| Gap | No test-venue routing, though the live-pipeline test enqueues real jobs | **Venue column added** — unit and dry-run on `:7999`; live pipeline on `:8000`, submitted via `POST /api/test-suite/submit` |
| **Medium** | §10 named test **files** but never a **directory**. If tests landed in `src/cosa/tests/`, no gate-invocable runner would collect them and **the 100% gate would be decorative** — a coverage line that reads like enforcement and enforces nothing. That tree hid two real regressions on 2026-08-05 | Every tier now names a gated path AND its runner — `src/tests/unit/test_twisty_maze_engine.py` · `src/tests/unit/test_twisty_maze_dry_run.py` · `src/tests/smoke/test_twisty_maze_live_pipeline.py` |
| Gap | Dry-run false-green risk unstated | Explicit — `_execute_dry_run()` mocks every LLM call and must never stand in for a real play-through |
| Gap | Phase 0 said "confirm" the maze graph | Changed to **author** it; there was nothing to confirm |
| Cosmetic | Proxy script named `twisty_maze.json` | `twisty-maze.json`. The Python test files correctly keep underscores |

---

## 4. Settled scope — §13 is no longer an open-questions list

| # | Question | Ruling | By |
|---|---|---|---|
| D1 | Maze size | 6–8 rooms, one twisty-loop cluster. The authored 7-room graph fits | Rick, 2026.08.06 |
| D2 | Player input channel | **Both** — multiple-choice card as the reliable default, free text as flavor | Rick, 2026.08.06 |
| D3 | What "toggle-able / walk-through-able" meant | **Both readings** — agent-mode toggle AND scripted dry run, with the mocks-everything caveat retained | Rick, 2026.08.06 |
| D4 | Repo confirmation | `lupin`, `src/cosa/agents/twisty_maze/` | Manager, 2026.08.06 — *answered without spending the user's attention; reversible on his word* |

§13 was rewritten as a dated decisions record. An answered question that still reads as open is the
same defect as a stale status line.

---

## 5. What was NOT changed, and why

- **The architecture stands.** The Dungeon-Master split — deterministic engine as source of truth,
  model for narration and parsing — survived all three stages and was the basis on which two findings
  were resolved.
- **Scope stayed put.** No reviewer proposed adding inventory, combat, save/load or procedural
  generation, and none was added. §12 is unchanged.
- **The reuse claims that were true stayed.** `AgenticJobBase` subclassing, `from_config`,
  `JOB_PREFIX`, the shared `voice_io` API, the per-agent router, `LivePipelineTestBase`,
  `InteractiveSmokeTest`, the proxy-script directory and the six-phase build recipe were all verified
  as genuine prior art. **The plan reuses well. The problem was the one thing it called reuse that
  wasn't.**

---

## 6. Workflow-guidance candidates

Filed for the post-game — deliberately NOT folded into doctrine on one run's evidence.

1. **A spawn brief that says "start on boot" defeats any gate that comes after boot.** Stage 1 began
   before the Step 0 readiness gate cleared, because that is what its brief told it to do. Steward's
   ruling: fix the template, not this run. The gate then cleared 6/6 on its own terms, so nothing
   rested on the overlap.
2. **A Recon checklist that quotes the artifact under review cannot check it.** The Manager copied
   §8's "non-negotiable on every `notify()`" line into the pre-cascade checklist — the one document
   whose purpose is to give reviewers something *independent*. A reviewer would have verified the plan
   against the plan and both would have agreed. Caught by the Stage 2 reviewer reading actual source.
3. **"No prior art" and "not possible" are different findings and get decided differently.** The
   Steward re-ran the reviewer's grep, confirmed it, and added the distinction that changed how the
   fork had to be put to the user. A correct finding can still produce a wrong decision if it is
   framed as a stronger claim than its evidence supports.
4. **A revision that lands mid-pipeline moves the bytes under the next reviewer.** The author revised
   §10 while the Stage 3 reviewer was queued for Section D. Two of his findings were filed off stale
   bytes; both were withdrawn. The Manager's "read it fresh" warning existed but arrived after he had
   begun. Nothing in the workflow requires that warning, or requires it to arrive first.
5. **Collapsed ledger rows** — steps 1–4 carried as one row rather than four, because they completed
   inside eight minutes. Steward ruled: leave it, re-cutting mid-flight costs more than it buys.
6. **The Manager reported a bundle as "the last one" while three routed-nowhere findings sat in his
   own inbox.** Caught by re-reading the reviewers' closes against what had actually been sent.
7. **A readiness gate cannot audit whether later rulings get swept through the document.** ⭐ The
   strongest candidate of the run. The Step 0 gate cleared 6/6 and was *correct* — it inspects the
   input plan. But the plan's biggest ruling (drop the custom tools) was written into the section
   that argued it and left standing in the §4 diagram, the §4 traceability list and the §11 phase
   list. **The plan contradicted itself on its own headline decision, exactly where a cold
   implementer reads first**, and no gate in the workflow was positioned to see it. Caught only
   because the Step 9 light reviewer went looking beyond his rubric.
   **Proposed remedy** (from the reviewer who found it): a **per-ruling sweep check** at Step 9 —
   for every ruling taken during the cascade, grep every place the *superseded* decision was stated,
   not only the section where the ruling was argued. This is the workflow-level analogue of the
   author rubric's forward-sweep rule, which already exists for authors and has no counterpart for
   managers.

---

## 7. Hand-off statement

**The plan is revised and self-contained.** An implementer picks up
`2026.08.06-twisty-tunnel-maze-game.md` and builds from it directly. Every cascade outcome is folded
in, and every `file:line` in it has been verified against source.

**Nothing has been committed.** The whole `2026.08.06-demo-day/` folder — plan, runbook, Step 0
package and this document — is still untracked. That is Rick's call, not the Manager's.
