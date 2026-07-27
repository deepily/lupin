# TODO

Last updated: 2026-07-27 afternoon (Clayton 😎 `34474b66` — six-worker crew day: five rulings logged below, incl. two requirements corrected by measurement; `7ee5b646` still open for Rick, and `5bf28e07` timed out to default with no ruling)

---

## ⏳ PENDING DECISION 2026-07-26 (Mr. Radio 🦉 `9a63d597`) — `7ee5b646`: the HWM janitor switch

**Status**: OPEN, awaiting Rick. Store row `7ee5b646` (decision, `gate_class=operator`).

**The situation**: the DM-inbox bookmark janitor shipped with `arbiter enable hwm deletion = False`, which **diverges from his "let the janitor drain them" ruling**. I flipped it to OFF after measuring that the plan's safety claim was inverted — reaping a live session's bookmark does not duplicate its DMs, it **silently swallows the un-surfaced ones** (a missing file reads as never-seeded, so the reconcile records the inbox as already-seen and surfaces nothing). That re-creates bug `59f355e0`.

**What Rick decides**: whether to turn it on. The 7-day window is already his ruling and needs no change. Nothing drains until the INI key flips.

---

## 📋 DECISIONS LOG 2026-07-27 afternoon (six-worker crew, recorded by Clayton 😎 `34474b66`) — five rulings, and a pattern worth reusing

**2026-07-27 — VM dual-stack ordering → KEEP the one-commit rule, MOVE the load-bearing half to a per-file compose `name:`.** Sam and Mr Radio ruled that de-hardcoding `container_name` must land with the socket-volume split, on the premise that the hardcoded name is the only thing preventing stack 2's init from deleting stack 1's live socket. **The premise held only across distinct compose projects, which this repo never supplies** — no top-level `name:`, no `-p` at any call site, `COMPOSE_PROJECT_NAME` nowhere, both files at one root ⇒ `/var/lupin` resolves to project `lupin` for both. Measured: same project ⇒ compose does not conflict, it **recreates** — socket deleted, `rm` run twice, and stack 1's app container destroyed. ⇒ The deletion is **already armed**; the gating act is the first `compose up` of a second stack, not a commit. Premise withdrawn by Mr Radio; rule kept.

**2026-07-27 — Vertex data-sharing (OSQ C-1) → OPTIONAL, and the paid probe is CANCELLED.** Phase 1.1's own rule was *"config without `dataSharingEnabledProvider`, issue one request, rejection ⇒ required."* That experiment had already run on 07-13 and succeeded. Confirmed live at zero cost: config present, field absent, 509 anthropic invocations in 14 days. ⇒ Gate `31f6d447` gets the OPTIONAL question. **The probe is now more dangerous than when designed** — `setPublisherModelConfig` is a full-object SET and would clobber a live logging config that did not exist on 07-13.

**2026-07-27 — tier-run attestation → TAMPER-EVIDENCE, not tamper-proofing.** The requirement was "write it where the tests cannot write." Measured, that is unachievable: `job.py`'s pytest Popen uses `env={**os.environ, …}`, so the subprocess inherits every credential the orchestrator holds; the `TFE_/BFE_/LUPIN_TEST_` allowlist filters only the **caller-supplied** dict, not inheritance, **though it reads as if it does**. ⇒ Anyone may append, nobody may rewrite: `prev_sha256` chain, verifier names the first broken index. **Building to "cannot write" would have shipped a receipt store whose guarantee is a promise** — the defect the row was filed about, one layer up. Requirement corrected by its author on the measurement.

**2026-07-27 — two dated regressions → one was the FIX, one was the TEST.** `69295c25` (the `8b93bcf5` lying-zero fix) moved `readline()` into a reader thread whose `finally` posted the EOF sentinel on **any** exit, so a crashed reader read as clean EOF and a dead tier reported **`exit_code 0`** — worse than the `0/0/0/1` it was filed to fix, because it reads as green. The fix was wrong. Separately, `test_this_revision_is_a_head` was **stale by construction**: had the CoSA tree been gated it would have blocked **every migration ever added**. The test was wrong. ⇒ Rule applied: *measure which before touching either.*

**2026-07-27 — a stale COUNT is a second authority → assert the property, never re-pin the number.** `test_vertex_env.py` pinned `== 15` after the tuple was re-harvested to 16. **Bumping to 16 only moves the expiry date on a population the vendor controls**, and it was already a second authority on a fact `test_vertex_env_completeness.py` owns by re-harvesting from the binary every run. ⇒ Now asserts *every key in the tuple is in `HOSTILE_ENV_KEYS`*, per key; **what belongs IN the tuple defers to the single authority that measures it.** The test's NAME said "fifteen" too — **a stale name is a claim**, so renaming was part of the fix.

### ⭐ PATTERN TO REUSE — an exemption with an EXPIRY CONDITION, not a reason

`test_attestation.py` is unreachable by any gate **because `src/cosa/tests/**` is referenced by none** — the exact condition decision `5bf28e07` is open to rule on, not a property of the file. Its allowlist entry therefore records an **expiry condition** rather than a justification: *"remove this line when `5bf28e07` is ruled, either way."*

⇒ **An exemption that dissolves when the condition it rests on resolves cannot rot into a permanent one**, and the ruling disposes of it automatically with no separate decision. Prefer this shape wherever an exemption exists because of an open question rather than because of the thing itself.

### ⚠️ COUNTING YOUR OWN VISIBILITY AND REPORTING IT AS THE TREE

The day was briefed to Rick as ~20 commits; the reviewer measured **48**; the branch since midnight holds **55**. **48 and 55 are both correct** — `da1a5ed8..59038897` is a review range, `--since` is a day — but ~20 was one manager's own visibility reported as the repository's state. Same shape as the three blind instruments in `691d49db`: **a clean number answering a narrower question than the one asked.** Always state the predicate with the count.

---

## 📋 DECISIONS LOG 2026-07-27 (Mr. Radio 🦉 `951a4459`) — `2b20a6d6` RULED, both arms

**2026-07-27 — which remedy for backend-blind test isolation → (1b) fix the three production call sites FIRST, then RAISE at construction, then land the guard test.** Why: a raise is unaffordable while three live sites still pass an ignored `db_path`; once they are reconciled the raise costs nothing and covers unswept code. Re-verified against the artifact this session — `responder.py:256-260` and `prediction_engine.py:163-165` have **no guard at all** (the row said "not guarded by the backend flag"; they are not guarded by *any* flag), and `prediction_engine.py` **hardcodes** its path rather than reading config. Only `main.py:512-520` gates, and on a second authority (`solution snapshots manager type`) with no comparator against `vector store backend`. Target shape: `routers/system.py:272-289`.

**2026-07-27 — what happens to the six existing test offenders → ALL SIX isolated or removed. No exemptions, no known-bad list.** Rick, verbatim: *"I absolutely do not want any test touching a live dev data store! If it's not isolated then it needs to be removed or fixed."* This **overrode all four options offered** — I had proposed re-scoping the two `test_prediction_*_e2e` tests to *declare* that they use real data, on the reasoning that they point at the real store on purpose and are therefore honest. Rick rejects the premise: intent does not launder the contact. If isolating a test makes it vacuous, it is removed. Standing rule now in auto-memory `feedback_no_test_touches_a_live_dev_data_store.md`.

**Follow-on opened**: three weeks of unisolated runs left unknown junk in `lupin_db_test` — contaminated data in a live dev store, needing its own cleanup call. Whether the six *write* or merely *construct* is now a cleanup-sizing question, not a disposition question.

---

## ⏳ ~~PENDING DECISION~~ ✅ RULED 2026-07-27 — `2b20a6d6`: backend-blind test isolation (kept for the record)

**Status**: ✅ **CLOSED 2026-07-27** — both arms ruled by Rick; see the Decisions Log entry immediately above. Store row `2b20a6d6` carries both rulings as amendments. Original framing retained below.

**The situation**: nine `cosa/memory/*` classes route on the ambient `vector store backend` flag and silently discard any `db_path` handed to them. `postgres` has been live since 2026-07-07 with no per-block override, so a test that constructs one believing it is isolated is reading and writing the shared store. One module (`test_answer_is_correct`) is fixed — commit `e4113d64`. Six more in `src/tests/integration/` are not.

**What Rick decides**: which remedy, and what happens to the six.

**My recommendation, revised after measuring**: fix the three production call sites first, THEN raise at the source, then add the guard test. The original recommendation said "raise" outright; checking its stated risk showed **three live sites pass `db_path` under postgres** (`main.py:512`, `responder.py:260`, `prediction_engine.py:165`), so a raise breaks them today. `routers/system.py:272` is the one good citizen — it asks the flag before building a path, and is the shape the others should take.

**Why I did not just do it**: the six live on the gated `:8000` suite; a change there cannot be verified without monopolizing the test server, which is the second half of what this decision decides. Also worth naming — `main.py` gates on `solution snapshots manager type`, a **second authority for the same fact** with nothing comparing the two. Reconciling that belongs to whichever remedy wins.

**Related**: `d621b111` (the bug + full sweep) · `d6f11dfd` (closed) · `cfcbb703` Family B (the allowlist that missed this) · `d8a23fca`

---

## 📥 BACKLOG 2026-07-25 (Rick's idea, captured by Mr. Radio 🦉 `43ff094e`) — ASR warm-up endpoint to pre-heat Cloud Run

**Status**: possible FUTURE performance improvement. Not owed work, no store row, not scheduled. Rick's framing: *"I want to be able to warm up cloud run before I actually use the app. And a voice to text warm up endpoint would be great."*

**The problem**: `lupin-model-server` is a scale-to-zero L4 Cloud Run service (`minScale=0`, deliberate — Rick 2026-07-25: *"cloud run should not be warm during the day… I don't want to pay for it sitting there doing nothing"*). So the FIRST voice interaction of a session eats the cold start. Measured today: **32.0s** wall clock for the first authenticated call, versus **4.1s** for a transcribe against an already-warm instance. That ~28s is paid by whoever speaks first.

**Design note that makes this cheap — measured, not assumed.** The warm-up does NOT need to send audio. The model server eager-loads its pipelines at startup (`_load_whisper()`, "Eager-load distil-whisper pipeline to GPU 0"), so ANY request that causes an instance to start also loads the models. Receipt from today's cold start:
```
GET /health  →  HTTP 200 in 32.0s
{"status":"ready","models_loaded":["whisper","code_rank_embed","nomic_embed_text_v1_5"],
 "vram_used_mb":2496,"uptime_seconds":25,"load_errors":[]}
```
`uptime_seconds: 25` on a 32s call ⇒ that call STARTED the instance, and by the time it answered the models were already resident. **An authenticated `GET /health` is a complete warm-up.** No audio round-trip, no `/transcribe`, no upload — which also means the warm-up costs nothing beyond the instance-start it is deliberately buying.

**Sketch** (whoever picks this up should re-derive, not trust this):
- A Lupin endpoint (e.g. `POST /api/asr/warm`) that fires the authenticated `GET {LUPIN_MODEL_SERVER_URL}/health` and returns promptly — the caller wants "I started it", not "I waited for it".
- Fire-and-forget / non-blocking, so the UI can trigger it on page load or on mic-button focus without stalling.
- Idempotent + cheap to call repeatedly; a warm instance answers in ms.
- Honest reporting: return whether the instance was already warm (`uptime_seconds`) vs just started, so the UI can say "ready" vs "warming, ~30s".
- ⚠️ **Cost coupling** — this is the one thing to think hard about. A warm-up trigger wired to something automatic (page load, a poll, a heartbeat) re-creates by the back door exactly the always-warm billing Rick just rejected. It should be USER-INTENT-driven (mic focus, an explicit button) or explicitly rate-limited, and that constraint belongs in the design, not in a comment.

**Related**: today's STT 401 (row `30198303`, closed) and `src/cosa/utils/secret_drift.py`. The warm-up path would exercise the same auth chain, so it doubles as an early-warning probe for key drift — but see the `unknown`-is-not-a-pass rule in that module before treating a warm-up failure as a health signal.

---

## 🔴 P0 FOR TOMORROW (2026-07-25) — VM persona-404: APPLY the code-route fix on the VM

**Repo side is DONE + green** (session b46c77e3, `wip-v0.1.9`): `atomic_write_json` fchmod-0660-before-replace, `register_session.py` explicit `chmod 2770` (setgid) sessions dir, 3 new mode tests, 252 unit tests pass. Design in `src/rnd/v0.1.9/2026.07.24-vm-persona-bridge-mount-uid-divergence.md` **FINAL PLAN v3** (approved by two independent reviewers — Sam 🎙️ + local LLM expert — GO-WITH-CHANGES, all folded).

**Morning steps (VM only, NOT yet applied):**
1. `cloud-gpu.env`: add `LUPIN_HOST_SESSIONS_DIR=/home/admin_rickruiz_altostrat_com/.claude/sessions` + `LUPIN_BRIDGE_GID=1721846087`.
2. `docker-compose.cloud-gpu.yml` `rest` service: long-form bind (`create_host_path: false`) of sessions dir + `group_add: ["${LUPIN_BRIDGE_GID:?...}"]` — verify via `compose … config | grep sessions` (never `sudo`).
3. VM: `chmod 2770 ~/.claude/sessions`; backfill `chgrp 1721846087 + chmod 660 ~/.claude/sessions/cc-*.json`.
4. Push repo change to VM (`./src` bind covers container + host hook); recreate `--env-file cloud-gpu.env --no-deps --force-recreate lupin-rest`.
5. **Bidirectional runtime test** (the crux): host writes bridge → container `set_voice_persona()` → assert numeric owner 1001 / group 1721846087 / mode 0660 → host rewrites → container reads again. Then fresh session `request_persona()` → allocated (not 404); confirm `notify()`/OAuth/health survive; `docker inspect` both mounts.
6. VM `lupin-host-test` is currently STARTED (running); `acl` pkg was installed during diagnosis (now moot — code route chosen).

---

## 📋 DECISIONS LOG 2026-07-22 (Mr. Radio 🦉 `2c24d27b` + María 🌸 `f5ed59fd`, two-seat SWE crew) — four assertions that could not fail

**Retro**: [post-game — assertions that cannot fail](src/rnd/v0.1.9/2026.07.22-swe-crew-post-game-assertions-that-cannot-fail.md). Commits `4bec617b` + `b65191ec`, both HELD (push is Rick's).

- **🔴 THE PRACTICE — an assertion is not a guard until you have DELETED the thing it guards and watched it go red.** Twelve assertions shipped across two commits, all twelve verified that way. FOUR other checks written the same day — by both engineers, reviewed by both, agreed by both — **could not fail**, and not one was caught by reading. A check that agrees with the code on the sampled input is *indistinguishable in its output* from a passing test; there is no signal in green that separates them.
  - **The strongest evidence available**: the fourth instance was written **immediately after both engineers had named the pattern to each other in writing, in the same thread.** ⇒ **naming it does not defend against it. Only reverting does.**
  - The four: fixture margin (±6h) wider than the masking quantity (a 4h offset) · two banner triggers sharing one dependency on `total` · a test asserting against a state dict it built itself · a pin whose input made both branches of the target function coincide.
- **🔴 A GUARD KEYED ON COMMITTED STATE IS STRUCTURALLY BLIND TO A PRE-COMMIT RUN.** `test_notifications_task_list_token_not_stale_vs_css` resolves the CSS date from `git log`. `4bec617b` shipped a stale `?v=` token — returning browsers would have served the cached sheet and **none** of the new styles would have rendered. Green pre-commit, red on the very next sweep, because the guard's input did not exist yet. ⇒ *"I ran the suite before committing"* is **not a claim about that guard at all**. Generalizes to migration heads, changelog freshness, tag/version alignment, any file-date coupling.
- **RULED (Rick, verbatim) — muting the poke is SILENCE AT THE WORKER, HONESTY ON THE CARD.** *"I also want the momentarily idle output pushed to me via notification API to reflect the contents of the default poke disabled message. I want to see what the workers see."* A muted stop skips the obligations lookup by design, so `owed=False` was a default standing in for a lookup that never ran — every muted worker's card published *"idle — nothing owed."* Fixed to report UNKNOWN, naming the mute rather than blaming a healthy store. **Not** widened to `config_error`/disabled: pinned legacy contracts, neither a live-fleet switch, with a discriminator test making that narrowness a decision.
- **RULED — where a canonical shared predicate exists, MIRROR IT TERM FOR TERM; do not rule fresh.** Both engineers reasoned independently about parked-ness and both got a term wrong; `park_is_active()` (`task_store_owed.py:184`, three existing readers) settled it against both. It keys on **`status == "parked"`, not `park_reason`**, and a null/unparseable/past chase is **NOT** park-active — *"fail-loud-toward-owed"*. The panel was about to become that module's fourth reader, which is exactly where the divergence it exists to prevent would have entered. Corollary (María, self-reported): *do not recommend a field you have not read* — `park_reason_stale` answers quote-drift, not chase expiry.
- **RULED — the defect was the SILENCE, not the number.** The task panel pulled 1,171 rows against a `limit` hard-capped at 500: 671 dropped, newest-first, so the evicted rows were the OPEN ones the panel exists to show — while both call sites carried a comment promising the view was *"never silently truncated."* Rick ruled **drop terminal rows**, not pagination and not a raised cap. But 139-under-500 is **headroom, not a guard**, so the fix also reads the `has_more`/`total` the server was already publishing and both consumers were discarding.
- **FILED `a5f4eb3f`** (P2, owner Mr. Radio) — `/api/tasks` row-cap overflow sets neither `truncated` nor a `warnings[]` entry while the char budget sets both. A caller checking **the field named for exactly this** is told "no" with 57% missing: an alarm gated on the healthy value.
- **⏳ PATTERN-WATCH, NOT DOCTRINE — `revert-to-verify`.** Four instances in one day is a strong *within-session* pattern, not a cross-session one. Per Rick's standing rule it is captured with receipts and logged here; **nothing written to `workflow/`**. The next session to hit it should confirm or kill it, citing the retro. **Rick graduates it, not us.**

---

## 📋 DECISIONS LOG 2026-07-21 (Mr. Radio 🦉, session 56a74d7b) — fleet burn cut to zero + the arbiter stopped CC-ing peer managers

- **Rick: cut the fleet.** 9 seats → 0 across two waves. Wave 1 reaped 5 idle/blocked seats immediately; wave 2 let 4 finish the task in front of them, then stood down. Every seat mementoed, session-qualified where the persona name is re-grantable. **The default is finish-then-stop, not park.**
- **RULED — case 9 STAYS `TIER_RICK_AND_MANAGERS`; only case 14 flips to Rick-only.** The two rationales are near-verbatim ("leaderless crew" / "leaderless-in-waiting"), so the basis is the **detector, not the wording**: case 9 fires on MEASURED ABSENCE (manager down + holding), case 14 on INFERRED SILENCE (45 min, still rostered, four false-positive suppressors in its own path). **Falsifier recorded**: if that distinction fails, case 9 flips too — case 14 does not stay.
- **Mini-plan 04 REVERSES a considered carve-out, it does not complete a sweep.** My draft claimed the latter; `f48f089d`'s own author had named case 14 and deliberately distinguished it. Reversal still correct — Rick outranks the comment — but the doc argues it on merits so the next reader doesn't revert us with that sentence.
- **🔴 DOCTRINE — a coverage gate CANNOT SEE a change to a data literal.** 100% on `arbiter_routing.py` with **zero** of the changed lines executable: the table entry is a dict-literal continuation counted as one statement, green for any value including garbage. Every table-driven routing/config/dispatch change in this repo is invisible to the 100% mandate. **Mutation is the only instrument that answers "would a wrong value be caught."**
- **DOCTRINE — a peer-silence assertion keys on the RECIPIENT (`s[0]`), never the MESSAGE (`s[1]`).** A message-keyed absence check goes silent the moment the message is renamed, while the thing it forbids keeps happening. Found by an adversarial rename probe against our own new control.
- **The arbiter bounce is MANAGER authority.** I asked Rick's permission and was corrected directly. Restart at discretion, announce after.
- **Persona names are not project-scoped.** `b9f2f8e9` (project `parallel-search`) sat on a lupin board firing an open user-gate at Rick every tick because its `owner_persona` string matched mine. Dropped, not parked — a park would have kept it here with a timer.

---

## 📋 DECISIONS LOG 2026-07-20 evening (Mr. Radio 🦉, session 26409c0c) — `task_edit` shipped; two defects killed at the gate

- **Rick ratified the verb shape: Option A — `task_edit(task_id, updates={field: value, …})`**, a dict of fields (atomic multi-field, one `patched` event). Option B (one field per call) is a strict subset; Option C (overload `task_amend`) was REJECTED — `task_amend` is append-only, and overloading it would collide an immutable audit-append with a mutable overwrite.
- **Rick DESCOPED the audit-identity dict-smuggle guard on deadline grounds** — *"I don't care about that, we gotta ship."* The basic actor stamp-last is retained (free, already built); the `authority`/`reason` smuggle-reject arms were NOT built. Any future hardening needs its own row.
- **Owner-refusal KEPT despite the descope** (María required, Krishna concurred): `task_edit` refuses `owner_persona`/`accountable_manager` → `task_reassign`. Rationale accepted — it makes the verb do *less*, both reviewers had approved it, and the tester already covered it, so keeping it was the FASTER path. ⚠️ It is an **MCP-layer** guard, NOT inherited: a raw PATCH still accepts owner fields.
- **`062659f2` will NOT be closed on measurement alone.** A `~/.claude/…/MEMORY.md` edit has **no whitelisted receipt** (no commit; `doc_path`/`log_line` reject on scope), so "done, verified by measurement, no repo artifact" is unexpressible. Ruled: leave queued for a deliberate trim; the wall was logged as a live dated instance on `86ce4c43` rather than papered over with a caveat-close.
- **`3b0f3923` DROPPED as stale** — the mandate to seed every Krishna spawn with `krishna-ff761722.md` is superseded; he was spawned unseeded tonight, ran a full adversarial review, and wrote a fresh memento.

---

## 📋 DECISIONS LOG 2026-07-20 (Mr. Radio 🦉, session 65a43c6c) — three-plan arc + a provenance defect in our own decision channel

- **Rick ordered three fixes, in order, each with its own plan → review gate → full SWE team**: `c191be39` (Stop-hook owed-status seam) → `4288dd53` (fetch-by-ID) → `eab1d7da` (I3 kind-differentiated chase). **Three separate plans ruled**, not one unified.
- **Rulings banked (8)**: three separate plans · fix the seam AND revive `todo_unstarted` · expired-parked reports as `pending` · `breakdown` always-returned (scoped to the `count_only` branch, grounded in a caller census on Rick's instruction) · `c191be39` raised P2→P1 · I3 remedy = **chase required only for PEER blockers**, not user/item · `eab1d7da` kept third **on honesty grounds, explicitly NOT poke reduction** · fetch-by-ID = **single-row `task_get` only**, no batch filter.
- **Plan 1 APPROVED for build** (María, source-verified independently). Plans 2 + 3 drafted/drafting.
- **🔴 `eab1d7da`'s headline benefit was RETRACTED before it could mislead the build** (amendment, event `3829`): arbiter suppression is `all`, not `any` — `arbiter_job.py:3088` suppresses a persona only when **every** non-terminal row they own is user-gated. Typing 4-5 rows correctly on a board of 16 changes the poke cadence **not at all**. The schema fix makes the board honest; it does not make the pokes stop.
- **⚠️ ROUTED FROM RIO ⚡ — `ask_multiple_choice` discards the answered-vs-defaulted signal.** `src/lupin_mcp/cosa_voice_mcp.py:1653` returns a bare `{"answers": default}` on timeout — **byte-identical in shape to a real selection**. `converse` sets the correct precedent at `:1174` (`"[default used] "` prefix). The response object carries **both** `default_used` and `is_timeout`; the multiple-choice path throws them away. Proposed one-line additive fix: `return { "answers": default, "default_used": True }`. Leads (unverified by Rio): `ask_yes_no` `:1419` and `ask_open_ended_batch` may share the pattern.
  - **Cost already paid**: Rio's 5-decision walkthrough for Rick this morning — every ask backgrounded at 120s and returned the recommended label, which was also his default. `parallel-search/TODO.md` now carries a **provenance caveat on five ratified rulings**, unrecoverable after the fact.
  - **This session's 8 rulings are NOT affected, and the reason is mechanical, not hopeful**: no `default` was passed on any ask, so a timeout returns `{"error": "timeout", "timeout": true}` — structurally distinguishable. **The control fired live**: ask `kcmn92g1r` timed out and surfaced exactly that error dict. Every other ruling returned `{"answers": …}`, which under this call shape can only come from a keypress.
  - **Standing practice until fixed**: do NOT pass `default` to `ask_multiple_choice` when the answer will be treated as a ruling. A default converts an unanswered question into an unfalsifiable answer.
- **🔴 STALE-RECORD PATTERN, 2nd instance, banked**: María's 07-19 loop deletion left three artifacts describing the deleted mechanism in the present tense — one of them (`task_store_client.py:196`) sat **77 lines above** the docstring that documents the deletion, so a top-down reader met the retired shape first. Candidate rule: **when deleting a mechanism, grep for its BEHAVIOUR DESCRIPTION, not just its call sites.** All three fixed + green (198 passed) before implementation. Related generalization (mine): **a plan section citing a docstring as authority inherits every other docstring in that file as a competing authority.**

---

## 🔴 P0 FOR TOMORROW (2026-07-17) — Task-board state classification: finish the analysis

**Priority: 0 (HIGHEST). Assignee: Mr. Radio 🦉. Filed: 2026-07-16 (session 1a52ceb2, Rick's session-end directive).**

- **[LUPIN] Task-board state classification for workflow analysis — the doc + its amendment.**
  - **Document**: `src/rnd/v0.1.9/2026.07.16-task-board-state-classification-for-workflow-analysis.md` (commits `78854959` report + `5e8373c1` amendment)
  - **⛔ READ THE AMENDMENT FIRST — the report's central causal claim is REFUTED by my own measurement.** The amendment outranks the report. Do not re-ship the retracted claims:
    - ⛔ *"the board grows BY CONSTRUCTION (receipts gate on exit, none on entrance)"* — mechanism real, **effect ABSENT**.
    - ⛔ *"the board only grows"* — **FALSE as a steady state** (07-13 closed 46/46).
  - **Measured truth** (store Postgres direct, read-only — `task_items` + `task_events`): **all-time closure 861/925 = 93.1%** · **oldest OPEN item = 4 days, ZERO older than a week** · **40 of 64 open rows are <1 day old** · 3-day burst **158 arrived / 101 (64%) closed** · **52% of the open board belongs to the crew reaped at 22:11** ⇒ **the board didn't rot, it was DECAPITATED MID-SPRINT** · **I am the single largest minter of the burst I catalogued** (35 rows / 3 sessions).
  - **Findings that SURVIVE the refutation** (these are the real work): **C1** zombie items N≥4 (owner already reaped at mint time) · **C3** chase-expired ≥7 · **C4/C5** · **C7: 41 P1 / 65% — priority carries no information** · **the Stop-hook owed-work oracle LIES** (told me "2 in-progress" when the store said 0; told María "10" when the store said 2 — N=2, two seats, one hour) · **THE FILTER DEFECT: §6 mandates scoped queries, and a scoped query CANNOT show you that half the board is someone else's. I declared "board clean" 3× — each TRUE OF MY FILTER.** (María owns the §6 fix; finding is mine.)
  - **The meta-lesson, banked**: *a finding that CONFIRMS the boss's suspicion passes a checkpoint that a contradicting one never would.* Rick was angry; my catalog agreed; I never ran the one number my own report called "the number that actually proves it." María sent it back. **Agreement is not a checkpoint — it is the absence of one.**
  - **Next actions**: (1) drive the surviving findings (C1/C3/C7 + the Stop-hook oracle + the filter defect) to filed, owned store items; (2) reconcile with María's workflow analysis — this doc was written *for* her lane; (3) decide whether the retracted framing needs a correction anywhere it was already relayed.

---

## 📋 DECISIONS LOG 2026-07-17 (Mr. Radio 🦉, session b526cb36) — M1 demo shipped + board cleanup via Rick's guided walkthrough

- **GCP work DEMOTED from P0 (Rick, 2026-07-17 ~10:20 EDT).** *"Until the 2 Monday-07-20 demos are ready, skills-distillation + a new demo TBD are the ONLY focus. Only Rick lifts the mandate."* GCP readiness (`97c12d68`) + dependents (`53bac23a`, `f3b5ecf3`, `1b6331b8`) PARKED. Body-amended; the priority FIELD still reads P0 — Rick demotes via admin UI. (Finding: no MCP verb demotes priority, but `PATCH /api/tasks` does — the mechanical root of C7's P1-inflation.)
- **M1 skills-distillation demo = the sole P0, SHIPPED.** `df3f80c9` done, commit `0d01cbe` (verified firsthand). Converged recommendation: `src/rnd/v0.1.9/2026.07.17-converged-p0-demo-recommendation.md`. **POC-2 undefined — Rick's input pending; both POCs must be demo-ready before Rick lifts the mandate.**
- **Backlog cleanup — Rick's GUIDED WALKTHROUGH (D1–D5 + 9318af31); María ran it, Mr. Radio implemented.** Decisions doc: `plan/src/rnd/2026.07.17-backlog-clear-decisions-for-signoff.md`.
  - **D1** drop C6 records after re-home → **collapsed to ZERO drops** on body-read (all live doctrine / real bugs / others'-owned).
  - **D2** drop clean dups/superseded; `c9dd0cc3` = Rick closes his own gate.
  - **9318af31 = SCOPE-SPLIT (Rick, informed re-ask on Mr Radio's firsthand dig)**: PRESERVE the *"route GCP via Mr Radio"* spend-coordination rule (do NOT retire — fleet's only soft coordination point on real GCP spend, more relevant with 2 POCs going live); DROP only the dead CoT half (witnessed safe on the wire, `d84d60e`). Its title still mis-describes it (5a8aa45b) — a clean re-title/re-file is the follow-up.
  - **D3** reconcile 3 zombies → dropped w/ reap-reason receipts (`4e20520d`, `2695f5ad`, Sam's `06a3f031`).
  - **D4** NO demotes (hide-work risk; drops do the real reduction).
  - **D5** Sam's records → his own harvest.
  - **Net board reduction = 3 zombie reconciles.** Finding: the catalog's *"~60 noisy rows"* was over-counted from TITLES — bodies show live work, not a graveyard. **Both drafts title-listed live doctrine as droppable; the body-read rule (`73f397d2`) caught it on both sides.**
- **Board catalog's §4#3 UN-RETRACTED** — Rick's no-chasing experiment is the control arm the report lacked; María's receipt: **closure 0.98→0.725 when Rick withdrew 07-14.** The backpressure hole is at *filing*; Rick was plugging it by hand.
- **Kept-as-bug** (real defects, no seat can fix, `c191be39` shape): `6f8adc13` (auto-mode classifier wedge) + `74a3ff4d` (offline-user rule prescribes unbuilt `defer_to_chase`/`make_gate`).
- **Held live doctrine (NOT dropped)**: `73f397d2` (graduation-eligible, held for Rick's wording review) · `2ce26609` (pattern-watch) · `5a8aa45b`+`74c16374` (Sam's s-d, held per POC-2 margin).

---

## 📋 DECISIONS LOG 2026-07-15 EVENING (Mr. Radio 🦉, session da517b03) — GCP deployment arc + bug-fix sprint

- **⏳ GCP Cloud-VM config-block naming — DECIDED, IMPLEMENTATION DEFERRED TO MORNING (Rick, voice, 2026-07-15 ~22:30 EDT).** Two named blocks: **`[Lupin: Cloud VM Development]`** for daily dev on **:7999** (the current cloud-gpu stack) · **`[Lupin: Cloud VM Testing]`** for **:8000** (future, when the test stack is stood up). **Impl plan (NOT YET DONE — first thing AM):** add `[Lupin: Cloud VM Development]` to `src/conf/lupin-app.ini` inheriting `Lupin: Testing-GCS` + overriding ONE key `model server url = https://lupin-model-server-um6r4fv7nq-uc.a.run.app` (Cloud Run; https ⇒ port 443 implicit, no separate port key); repoint `docker-compose.cloud-gpu.yml` `config_block_id` → **`Lupin:+Cloud+VM+Development`** (⚠️ ConfigurationManager decodes `+`→space at `src/cosa/config/configuration_manager.py:151`, so spaces in the block name become `+` in the CLI arg) AND **drop** its `LUPIN_MODEL_SERVER_URL: ${...:?...}` env line (env wins over INI — the override must go for the block to be authoritative). `cloud-test` stays on `Testing-GCS` until the :8000 work reconceptualizes it as Cloud VM Testing (tracked `f3b5ecf3`). Full runbook + ground truth: `src/rnd/v0.1.9/2026.07.15-gcp-vm-getting-started-runbook.md` §0.5/§3.
- **GCP architecture confirmed (verified live):** two deployment targets — Cloud Run `lupin-model-server` (1 GPU, `minScale:0`/`maxScale:1` scale-to-zero → $0 GPU when idle; cold-starts on call) + VM `lupin-host-test` FastAPI on :7999 (**no GPU** — e2-standard-8; offloads inference to Cloud Run via `LUPIN_MODEL_SERVER_URL`). Rick's work CC routes through an **InTraffic adapter → Model-Garden Opus 4.8** (a Vertex path) — so the bare-slug Opus clamps ARE on the critical path; ⚠️ the $50/day clamp (500 out-TPM) will throttle that same traffic once granted → size to real work throughput. Readiness review: `src/rnd/v0.1.9/2026.07.15-gcp-pilot-readiness-review.md`.
- **Bug-fix sprint — 4 merges landed (local → pushed at session-end):** `ef10c5b6` focus-bar invisibility durable fix (Cheech) · `ee59d5ed` orphan-bridge reap-survival (Cheech; Change 2 arbiter sweep **DEFAULT-OFF** — Rick flips `arbiter orphan bridge sweep enabled` + restarts `lupin-arbiter-app.service` to activate fleet-wide) · `260dba16` vertex GCP-id guard greened, 3 offenders (Clayton) · `9fe8b80f` bare-unit/smoke config-collection floor in the parent conftest (Clayton). `ee59d5ed` CLOSED end-to-end (:8000 gate true-green, ts-1956de25).
- **Banked (optional):** Cheech's by-id AC-3 strengthening (`bcd34ba6`) — gate already honest+green; fold in next time the integration test is touched.
- **GCP deploy gaps tracked:** `f3b5ecf3` (bring up :8000 test server on VM — remap cloud-test to `8000:7999`) · `53bac23a` (provision + actuate :8001 arbiter on the VM, `provision-arbiter-on-vm.sh`).
- **Pending (Rick's action / gates):** flip the arbiter orphan-sweep flag (activates ee59d5ed Change 2) · part-2 bare-slug clamp paste · enforcement+cost canary · VM re-suspend · coexist-vs-single-stack on the VM · clamp sizing vs Model-Garden throughput · the config-block impl above.

---

## 📋 DECISIONS LOG 2026-07-15 (Mr. Radio 🦉, session bf549da1) — tmux fleet-killer cascade close-out

- **Cascade `cascade-tmux-fleet-killer` COMPLETE** (the P0 below, EXECUTED): 3 sections × 3 stages, 34 findings (0 foundational, 0 votes, 0 user escalations), ~55 min. Plan final-current on disk; Step-9 revision-handoff doc: `src/rnd/v0.1.9/2026.07.15-cascade-tmux-fleet-killer-revision-handoff.md`.
- **OSQ-1 CONFIRMED (Rick, /plan-decide one-touch, 03:26Z)**: execve kill-tracer ships, ordered LAST in §10 — install-only-on-request preserves the sudo gate.
- **Implementation = FULL SWE-team workflow (Rick, voice, via María relay 03:27Z)**: `/spin-up-swe-team` crew (Implementer + Reviewer + Tester), implementer seat cold-context-briefed on the handoff doc + plan ONLY.
- **OSQ-4 ruled by concurrence**: env-strip sufficient, `-S`/`-L` NOT adopted; AC5 = standing precedence canary. **OSQ-5**: vertex WIP lane orphaned (creator c8a18353 died 9 s after launching its own killer pytest) — cleared for edit+restore; vertex-lane continuity store task `bd0b728b` minted.
- [ ] **v1.N candidate: cascade-tmux-fleet-killer workflow-guidance batch (19 items)** (cascade cascade-tmux-fleet-killer, Manager Mr. Radio 🦉, filed 2026-07-15). Five manager moves ran ahead of the codified playbook (forward cross-section folds under a ratified ownership map · ownership-map-at-ratification · conditional ratify-by-concurrence · carried-items handoff field · probe-before-declare with delivery-clock); full 19-item all-seats index in handoff doc §6. Proposed fold targets: plan-review-cascaded.md §Step 5/§decomposition, common.md §Step 5/§Heartbeat Handling, defaults.md §Severity-tag metadata schema. Source: kind: manager_self_audit_sweep post on cascade-tmux-fleet-killer at 2026-07-15T03:33:43Z.

## ✅ P0 EXECUTED 2026-07-15 — cascaded review of the tmux fleet-killer fix plan (kept for the record)

**Priority: 0 (HIGHEST). Assignee: Mr. Radio. Filed: 2026-07-14 (session 2474504f, Rick voice directive).**

- **[LUPIN] Stand up a cascaded plan-review team — with María on it — to review the tmux fleet-killer fix plan.**
  - **Plan under review**: `src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md`
  - **Why P0**: the shared user tmux server died **5× on 2026-07-14** (14:12, 14:55, 19:21, 20:04, 21:13 EDT), each death **atomically killing every Claude Code session across all three projects** (lupin, planning-is-prompting, google-skills-distillation). This is an active, recurring fleet-wide outage.
  - **Root cause (proven, in the plan)**: `src/tests/smoke/test_vertex_launcher_server_taint.py`'s fixture teardown runs `tmux kill-server`; its `_tmux()`/`_launch()` inherit `$TMUX` from the pane, and on **tmux 3.2a `$TMUX` beats `TMUX_TMPDIR`** for socket selection (verified live via a read-only precedence probe — the file-history "TMUX_TMPDIR beats $TMUX" note was a non-pane false-green). So the "isolated" kill-server actually nukes the fleet's DEFAULT socket every time the test runs from inside a pane.
  - **Interim mitigation already in place**: the test is **quarantined** out of the collectable tree → `src/tmp/test_vertex_launcher_server_taint.py.QUARANTINED-2026.07.14` (gitignored, non-`.py`, pytest-uncollectable). It stops the bleeding but is NOT the fix. The latent class hazard (any bare `tmux` verb from a pane hits the default socket) persists until the conftest guard lands.
  - **Review shape**: sequential cascaded plan-review (REUSE → Pass 1 correctness → **Pass 2 ownership audit = María's lane**). The plan's §8 Q1–Q5 are the review agenda (attribution residual, other-tree guards, conftest shape, `-S`/`-L` defense-in-depth, and the ownership/collision check on the untracked peer-WIP test file).
  - **Rick's plan**: he will **kill this session and restart a fresh one under tmux + the cosa-voice MCP**, then **kick off the review himself** so he can manage it remotely via the notifications client. Mr. Radio's job is to have the review **team stood up (with María)** and ready to run.
  - **Hard gate**: **NO fix code until the cascaded review clears.** Diagnosis + plan + quarantine only, so far.

---

## 📋 DECISIONS LOG 2026-07-12 EVENING (Mr. Radio 🦉, session 446ce8a0) — GCP code-delivery doctrine + arbiter trilogy

- **Code-delivery DOCTRINE (Rick, voice, ratified + DEPLOYED same evening)**: testing containers ship with **NO app code baked in** — image = deps + runtime env only; code = bind-mounted static snapshot of a committed ref, materialized at deploy/re-spin, refreshed by re-materialize + restart (never image rebuild; deps stay the one rebuild axis). Fail-loud boot-without-mount is the *intended contract*. Canonical: `src/rnd/2026.07.12-gcp-bind-mount-revert-plan.md` §4b. LIVE on `lupin-host-test`: `lupin:1.3.0-codeless` @ `dbb4b307…`, four-proof verified, VM re-suspended.
- **Manual pull RATIFIED / VM-side GitHub remote DECLINED** (§5): archive+SCP sync from the dev box; zero new credential surface. **Prod code-shipping model POSTPONED** (§6) — deliberately undecided until prod is in view.
- **`BAKE_CODE` build-arg gate (default off)**: cloud-run-build.sh now produces CODELESS images by default; prod must pass `--build-arg BAKE_CODE=on`. Legacy baked path preserved behind the flag, not git history.
- **Sibling-gate lesson (arbiter trilogy, Krishna)**: every FP class fixed tonight = a correctness gate wired into ONE consumer of a signal but not its siblings; detection = read the journal until the arbiter contradicts itself on a single poll. Banked in `src/docs/fleet-liveness-and-task-store-architecture.md` §4. Companion rules: recovery-outcome membership = *beacons the session itself emits*; e5e33795's manager-only pin ruled blast-radius scoping (inverted with archaeology, not fought).
- **Optional (flagged, NOT scheduled)**: local `:8000` true snapshot isolation — materialize a snapshot dir (git archive) at re-spin and point the compose src mount there (§7); promote on Rick's word.
- **Deferred**: live calculator pipeline on the GCP VM (scope was code-delivery verification; feature regression stays on local :8000 suites).

## 📋 DECISIONS LOG 2026-07-11/12 EVENING (Mr. Radio 🦉, session 372f9dc9 re-spin) — arbiter-accuracy arc rulings

- **Arbiter-accuracy 3-layer stack**: L1 dedup (`ce13b134`→`ad0f6199`) + L2 designed-hold suppression (`cec10ef9`→`73378b09`) both LIVE via :8001 bounces; L3 stale holding_on-edge FPs (`1ff7be20`) PARKED overnight — the quiet advisory stream IS its verify-first evidence; staff morning 2026-07-12 w/ the overnight journal as first artifact.
- **Classifier wall ≠ authority ruling (Rick, direct)**: arbiter bounce is standing manager authority; a permission-layer denial whose rationale contradicts the manifest is a finding to surface, NEVER grounds to mint a Rick-gate. Memory `feedback_classifier_wall_is_not_an_authority_ruling` banked.
- **Wake-path is NOT a guarantee in either direction**: Krishna's review DM + 3 arbiter nudges buffered ~55 min without re-invoking me (manager side); Clayton's APPROVE staged Enter-immune (worker side, recovery: Escape→C-u→retype fresh→Enter). Sweep `dm_list` on every wake; memory corrected.
- **Suppression design invariant (ruled)**: fail-safe-to-ROSTER — every uncertain path (store hiccup / dead operator / mixed owed / deadlock cycle) keeps rostering; never hide a real stall. Uniform rule on both announce legs.
- **Stale-pending disposition review remains open**: 359 open bullets rode the TODO horizon sweep by AGE into `todo-history/2026-04-15-to-2026-06-16-todo.md` — item-level disposition pending Rick's convenience.

## 📋 DECISIONS LOG 2026-07-11 (Mr. Radio 🦉, session 372f9dc9) — lunch-window arc rulings banked at session-end

- **Monopolize family CLOSED end-to-end**: 3a14292b (Shape-A) + fe375cf6 (Shape-B) + 6d644465 (belt removal) all done w/ receipts; the caf58f71 "no-op placeholder" claim formally retired in code prose. The in-process pool_max=1 test is the DURABLE regression guard replacing the belt (guard-RED receipted). 67473d91's deferred E2E confirm satisfied by ts-dfc230a9.
- **Persona-key family CLOSED**: root fix at `canonical_persona_key` (separator runs → single space); board healed 13/13 via manager-run backfill on NEW code (ordering guardrail: apply-on-old-code would FUSE healable rows — banked in 951a22be record); derive_dm_topic new contract RATIFIED (Option A, zero-orphan inventory); soft-flag + class-scoped owner default live. Residual policy idea (hard-gate roster) reconsiderable only if a cross-project roster accessor ever exists.
- **Polluted-row cleanup DEFERRED (open)**: test-fingerprint rows in dev `prediction_decisions` (inventory in `src/rnd/2026.07.11-cfcbb703-unit-test-triage.md`) — fixture stopped the bleeding; the one-time targeted delete is a manager-run confirmed destructive op, batch with next hygiene window.
- **Persona-pool allocation WALKS (3× today)**: never trust `persona_preference` — verify the actual persona from the worker's check-in DM. Also: receipts schema is strict (commit = single hex, test_run = ts-<8hex> only).
- **TODO.md horizon archive still owed** (~2,250 lines; flagged 2026-07-06, deferred again this wrap per Rick's tight sequence) — run `/plan-todo archive` early next session. → ✅ **EXECUTED 2026-07-11 same-day re-spin** (this sweep: 2,292→178 lines, archive `todo-history/2026-04-15-to-2026-06-16-todo.md`, task 2a190fa2; stale-pending disposition review remains open).

---

## 📋 DECISIONS LOG 2026-07-07 PM (Mr. Radio 🦉, session 17e81460) — day rulings banked at session-end

- **No GPU-less GCP instance, EVER** (Rick, voice): the e2 downgrade path is dead; item `b8fa9b7d` dropped `user_direct`. Standing companion: **15-min stockout-retry reflex** on `ZONE_RESOURCE_POOL_EXHAUSTED` (g2 VM starts) — persistent duty, currently seeded in Clayton's memento.
- **Classifier reference case (5 walls today, 0 bypasses)**: the auto-mode classifier accepts user intent ONLY from Rick's own artifacts (settings rules, his shell) — never relayed words, ask-answers, or broadcasts. Walls hit: AR push ×2, VM start, Clayton ssh-read, TFE cancel-API. Delegation-to-manager requires ONE-TIME harness enactment via settings; Rick's 4-rule VM set (settings.local.json:500-503) is action-scoped only.
- **Phase-2 LanceDB FULL teardown (`4955d0b9`)**: Rick ruled TOMORROW after the 24h soak — the 2026-07-08 13:00Z chase is a **FIRE TIME, not a re-ask** (verify soak green → staff a FRESH author → go). Spec = `src/rnd/v0.2.0/2026.07.07-lancedb-teardown-prep-scoping.md` §4/§7/§5a; Phase-1 symbol rename already landed (`d1a681af`) — do NOT re-rename. Part-2 HNSW stays additionally gated on the flood-purge card.
- **Tiffany reaped no-respin** (Rick confirmed ask 22:30; unsubmitted-pane-text doctrine applied — surfaced before acting).
- **TFE `tfe-130826c7` completed naturally** — Rick's unexecuted kill MOOT; :8000 pool freed ~22:04.
- **67473d91 disposition**: DONE on unit-tier receipts (`d4aa722c`, 12/12); the :8000 E2E confirm is DEFERRED post-`30398595` — live-fire evidence tonight proved the monopoly-hold deadlock (ts-ad4670ec: the run's 7 spawned swe- jobs deferred by `[CONSUMER] Monopoly hold active`, all timed out → RED regardless of budget). NOTE: contradicts caf58f71's "monopolize=True is a no-op" finding — the hold IS active in the consumer (`[CONSUMER] Monopoly hold active` ×1916 in the run window; started_at flipped ONLY after monopoly release 22:43:23 → smoking gun). 30398595 turned out terminal(done) so the amend correctly 422'd — evidence filed as durable **bug `3a14292b`** (P2, accountable mr radio) w/ all receipts + cross-links (Clayton firsthand re-derive: RED 0/7).

---

## 📥 BACKLOG 2026-07-07 PM (Tiberius 👑, session 4e12c586) — post-switchover live-voice E2E pulled off the board (Rick voice order)

**Rick (voice, 2026-07-07 ~22:35 EDT): "push this task item into the to-do queue — it does not belong on the board: ee23fca8."** Store item `ee23fca8` DROPPED with this backlog entry as its durable landing pad. Context: the item was the post-switchover live-voice E2E for `766bb609` (persona voice_id honored per session), blocked on the lane-1 flip; Rick killed the flip the same evening with a global multiplexer-parity verdict ("still ugly, still incomplete for the MVP" — logged HIGH in intake `603d9275`), so the E2E has no near-term trigger.

**Resume-when**: the multiplexer reaches Rick's MVP layout/functionality-parity bar AND the lane-1 flip (multiplexer = live TTS client) actually lands.

**Scope at resume (verbatim from the store item)**: E2E driving ≥2 sessions with distinct voice personas; assert each `/api/get-speech-elevenlabs` POST carries that session's `voice_id` (present→honored) and a persona-less notification omits the key → server default voice, consuming server seam `speech.py:558`. Cite reviewed commit `76946d9a` + merge `a9dd6f41`. Prereq receipt: playback consumer `4f14d38f` is DONE. Also-owed cosmetic sweep bundled in the old item body: `wireTtsPlayback` comment names default voice "(Sam)" but the real default is config key `elevenlabs tts default voice id` — comment-only.

---

## ✅ EXECUTED 2026-07-07 AM (Mr. Radio 🦉, session 17e81460) — v0.2.0 pgvector migration swap-chain + CUTOVER LIVE

**Rick's morning GO ("finish the migration… coast is clear" + manager carte blanche) executed end-to-end, commit `0901984d`**: dev+test recreated onto `lupin:1.1.1-pgvector-candidate` → LIVE backfill 202,081 + 35 + 57 (truncate-then-load, twice: main + straggler re-run) → equivalence PASS (exact-scan PG == LanceDB byte-faithful) → **exact-scan ruling** (Rick ask: keystone is 97.2% duplicate vectors → HNSW recall pathologically broken; migration `e1f2a3b4c5d6` drops the index; exact `<#>` scan = guaranteed parity AND 2.7× faster than legacy ~1,293ms) → **INI `vector store backend = postgres` LIVE on BOTH servers** (Rick ask: flip now) → live-pipeline + WS smokes green; integration gate `ts-c94c514d` = final proof. Full record: `src/rnd/v0.2.0/2026.07.07-pgvector-swap-chain-execution.md`. **Open tails**: soak watch → LanceDB teardown (post-soak, P5); post-hoc adversarial review of `0901984d` (crew spin-up was Rick-held); GCP leg task `c845346a` (Rick-HELD until his GO); boot-log LanceDB banner cleanup (cosmetic).

---

## 🗓️ STATUS 2026-07-06 (Tiberius 👑, session a6553139) — evening: notification-flood P1 shipped + full board sweep (8 items)

Rick's 3000+ digest-flood question root-caused (arbiter re-announce × persist-on-fail × no idempotency; bug `e1bbe011`) and FIXED same evening (`87a1de61`, persist=false flood-guard, LIVE via arbiter bounce). Crew of 4 (Tiffany/Krishna/Rachel/Clayton) closed **8 store items** with git-verified receipts incl. the corrected E2E-gate classification (10 mux-introduced now fixed · **5** truly pre-existing · 0 functional regressions) and the between-suites DB-isolation hardening (`ea0e4428`). All crew reaped w/ mementos. **Rick's open card: 4.7k flood-row purge** (asks expired unanswered — no purge executed; re-offer on engagement). Deferred: `caf58f71` (P3 concurrent-writer class), `ee23fca8`/`603d9275` (by design). **Hygiene: TODO.md at ~2,250 lines — run `/plan-todo archive` (horizon sweep) next session.**

---

## 🗓️ STATUS 2026-07-06 (Mr. Radio 🦉, session 2352acab) — evening: 2 bug lanes shipped, 2 gates executed, arbiter payloads live

Both worker lanes DONE same-evening: **75f392c0** Stop-hook poke-storm relief valve (Cheech, merged `ecae99a0` + doctrine §8 `de355d84`) and **f1a21917** wedge remediation (Rio, merged `7b7f2977` — `MCP_TOOL_TIMEOUT=660000` for all new spawns + turn-age watchdog). Rick-gates executed: `7d50a03a`+`c90f24f4` (pgvector → `src/cosa/.venv`, 93/93 green) + wedge ratification. Arbiter double-bounced w/ Tiberius (Rick broadcast bcea4232 re-affirmed manager bounce authority): **Tiffany's flood fix + turn-age watchdog both LIVE**, first sweeps clean. `63c5d913` closed-verified (`--model` flag injects; stale-process root cause). History archived (22.5k→6.9k). Rick's still-open card: arbiter flood-row purge (on Tiberius's ask). María's `6fc8d78d` (P1 spurious-poke root-cause) remains hers.

---

## ✅ RESOLVED (was: FIRST THING 2026-06-30) — `d1bdb7ca` mux TTS architecture gate
**Rick RULED (2026-07-01): server-push stands — "server pushes audio, END OF STORY."** Decision `d1bdb7ca` DROPPED in the store; the client-initiate flip is dead scope. Do not resurface.

---

## 🗓️ STATUS 2026-07-03 (Mr. Radio 🦉, session 8a92b253) — end-of-session: pushed `24301068` + backup; v0.2.0 migration swap Rick-gated

**Session-end (Rick broadcast ~10:24):** pushed `wip-v0.1.9` → origin HEAD `24301068` (102 commits, incl. merged 73d2b589 wedge-guard suite + 25c7441c notify-turn-hold fix-design) + backup DATA01→DATA02 (16.67G); 3 workers (Arnold/Cheech/Tiffany) documented + reaped.

**RULING (auto-mode classifier, 2026-07-03):** the v0.2.0 pgvector migration RUN is **Rick-triggered, NOT autonomous-at-quiesce.** The 08:37 swap-chain reached the container-recreate step with all read-only gates green (quiesce verified, image `lupin:1.1.1-pgvector-candidate` present, rollback `lupin:1.1.0`, forensics snapshot) but the recreate `docker compose up -d --no-deps lupin-rest-dev` AND an autonomous resume-cron were BOTH classifier-denied. **Parked on operator gate `d93a1edb` (P1)** — Rick adds a docker permission rule + GO (then I run the chain: recreate → verify → alembic → Tiffany in-container backfill dry-run → LIVE 196k RUN → equivalence + flag-flip readiness), or runs the swap himself. **Flag-flip stays Rick-gated.** Sibling env gate `7d50a03a` (P2 — pgvector into `src/cosa/.venv`, latent hooks/MCP landmine, bug `c90f24f4`). Daylight bugs: `75f392c0` (Stop-hook re-ask loop) + María's `6fc8d78d` (Mr-Radio-path spurious pokes, same family). Zero breakage — :7999 untouched.

---

## 🔝 #1 PRIORITY for the `wip-v0.1.9` bug-fix branch (Rick, 2026-06-26) — Multiplexer → notifications-client LAYOUT-LEVEL parity

**Directive**: get the multiplexer's CC-notifications surface to *real layout-level parity* with the legacy notifications client. This is the **#1 priority for the current bug-fix development branch** (Rick, voice, 2026-06-26).

**Holder (all discrepancies live here)**: `src/rnd/v0.1.9/2026.06.25-notifications-to-multiplexer-migration-discrepancies/` — index `00-index.md`; the section-layout gap analysis is `01-mux-vs-legacy-notifications-section-gap-analysis.md`. New discrepancy docs (CSS/visual, behavior, event-wiring) land in this folder as found.

**Substrate — verified gap analysis** (doc 01 in the holder). Confirmed section-level reorder:
- **Intended (legacy)**: broadcast card *(with nested Recent-Activity history)* → focus bar *(TTS preview above it)* → sessions container.
- **Mux actual**: focus bar hoisted to top → TTS preview orphaned as a sibling below it → sessions → jobs → **broadcast exiled to the bottom** → Recent-Activity **de-nested** as a separate pane.
- Plus per-message regressions: pause/stop/proxy-ratify dropped.

**Remediation buckets (gap doc §6)**: B1 restore section order (broadcast **+ re-nested Recent-Activity** → focus-bar → sessions); B2 relocate TTS preview into/above the focus bar; B3 restore section-header controls (count/filter/history/clear-all); B4 restore per-message pause/stop; B5 CSS pass LAST.

**Design calls — ✅ ALL RESOLVED** (Rick `/plan-decide`, 2026-06-26; §Decisions Log): a/b/c (broadcast-at-top + re-nest Recent-Activity inside broadcast + restore per-message pause/stop) **plus** the audit-surfaced d/e/f/g — Action-Required **full-funnel restore** (+ rich responder), TTS-Queue **full 1:1 restore** (chrome + per-item queue), Task-List **kept as a documented superset**, and **port ALL 7 absent accordions → total 13/13 parity**.

**Build-plan corpus — ✅ DRAFTED & COMMITTED** (`995dc952`, NOT pushed): 11 plans in `…/05-build-plans/` (00-index + shared template; 01 CC-session B1–B5 keystone; 02–04 the 3 partials; 05–11 the 7 absent), plus the **F0 shared-`AudioStore` foundation** finding (gates plans 01/02/03/05) and the consolidated cascaded-review agenda (questions e′–m).

### 🟥 #1 ACTION — Saturday 2026-06-27: run the 11 build-plan drafts through CASCADED REVIEW
**#1 priority for Sat 2026-06-27 (Rick).** Run ALL 11 drafts in `src/rnd/v0.1.9/2026.06.25-notifications-to-multiplexer-migration-discrepancies/05-build-plans/` through the **cascaded plan-review** process (`/plan-review-cascaded`) on the **dev server** (not the laptop). Start with **F0 (AudioStore shared foundation)** + **plan 01 (CC-session keystone)**; settle the **e′–m** review agenda (esp. e′ TTS reorder = FIFO vs drag · j/k dev-pane gating · i WS-scope filtering · m the jobs-pane delete-routing bug). Implementation begins ONLY after review ratifies each plan (manage-don't-build · 100% L/B/F · visual rebaseline).

### ✅ STATUS 2026-06-29 (Mr. Radio 🦉, session 2f4feb0a) — Plan-01 keystone chain BUILT + PUSHED
The ratified **Plan 01 (CC-session B1–B5)** keystone chain is largely landed + **pushed** (`wip-v0.1.9` → origin, HEAD `f333b6c2`, green-gated tsc 0 + TS suite 1993/1993):
- **B1** section reorder + commons re-nest — `5906508f` ✅ · **B2** slider → header region — `f86efef3` ✅ · **B3** own-only filter + section-header controls — `0f6d9ba0` ✅ · **B4** keystone per-message ⏸/⏹ + proxy-ratify — `24298595` (merged `d89e3e20`) ✅ · **F0** AudioStore/TtsQueueStore foundation (00b a/b/c/e/f, gates 01/02/03/05) — `f2204db1` (merged `c2cfa731`) ✅ · **2 reds** (governance hermeticity, C2-b premise) — `e0b3be32`/`d3b668d3` ✅

**Remaining on the mux-parity arc**:
- [ ] **B5** — CSS single-source into the shared sheet + Layout-Parity Oracle T2/T3 + golden snapshot rebaseline (gated LAST; pins against B3's finalized selectors).
- [ ] **F0-d call-site** — DEFERRED on **decision `d1bdb7ca`** (mux TTS architecture: server-push vs client-initiate). The mux has NO client-initiate TTS path today; building one is Rick's architecture call, to pair with the 00c / Plan-01 speak-gesture lane. F0 foundation ships complete without it; B4's identity half is mock-verified until F0-d wires the real boot.
- [ ] **Plans 02–04** (Action-Required, TTS-Queue, Task-List partials) + **05–11** (the 7 absent accordions) — still pending build/review.

### ✅ STATUS 2026-06-30 (Mr. Radio 🦉, session ef70b5f4) — Mux MVP-FINISH remediation BUILT + INTEGRATED (push authorized; flip gated on Rick's visual sign-off)

The ratified **mux MVP-finish remediation** (6 items; plan `src/rnd/v0.1.9/2026.06.30-mux-mvp-finish-remediation-plan.md`) is **BUILT, reviewed, committed-held, and integrated** on `wip-v0.1.9` (HEAD `1351976f`). Execution log: `src/rnd/v0.1.9/2026.06.30-mux-mvp-finish-build-execution-log.md`.
- **L1** bugs `d9d8d651` · **L2** AR+PLY `f48b0bf0` · **L3** VIS `ce164056` · **L4** NAV `6c20b7c3` · **AudioRecorder c8** `8a2c421a` — all reviewed-green, merged clean (3 shared-file carve-outs composed).
- **Gates GREEN**: V-P6 3/3 · gate E4 · directory-wide c8 100% · merged suite 2051/2051 · WS smoke 50/50. Dist builds.
- **:8000**: E2E (`ts-55f92b50`) + integration (`ts-13e9fc86`) submitted — **results for AM review** (Rick: rerun in the morning is fine).

**☀️ 2026-07-01 AM — Rick action items:**
- [ ] **GCP: `terraform apply` the model-server → Cloud Run split** (Tiberius 👑 session eb4b105f). Committed-held `c89c31ea`, pushed in `df0c1edf`; reviewed GREEN (Tiberius adversarial + María #1-#4 SOURCE + Arnold dry-side; **F-T1 caught+fixed** — scale-schedule jobs `oidc_token`→`oauth_token` for the Cloud Run Admin API, else the min-toggle 403s and the warm window silently never activates). **Rick's go + `gcloud` login — real money.** ⚠️ Apply DURING 09:00-23:00 EDT (finding #8 first-apply overnight warm-leak) → then ping **Arnold 🪨** for the WITH-CREDS green-bar (embedding+STT 200 vs the live `…run.app`; #6 the true-green gate). Cross-repo: VM-side PGA + `*.run.app` DNS + suspend/resume IAM grant live in the `terraforming-vms` handoff (02-vm-downgrade-handoff.md). **Runbook: store task `c3fafac5`.** **DECISION (ratified 2026-06-30, Rick): BUY the split — ≈$527/mo, ~$96/mo (~15%) cheaper than always-on; weekday-only Mon-Fri 09:00-23:00 + VM SUSPEND-not-stop + monthly-only (CUD dropped).** Design: `src/rnd/2026.06.30-gpu-model-server-cloud-run-split/` (01-design + 03-cost-reprice).
- [ ] **`a5559b49` — visual-regression rebaseline**: env-drift (host↔container libfreetype AA), NOT code. `ce216d11` held (fonts-dejavu-core + fingerprint guard). Landing to true 37/37 via Cheech's treadmill-immune run (`auto_fix_on_failure=false`); 30+ rebaseline PNGs commit local-held. **If it didn't land tonight**: resume runbook in `src/rnd/v0.1.9/2026.06.30-visual-regression-env-drift-root-cause.md` §Phase-2 (pause completion-watchdog OR per-run `auto_fix_on_failure=false` → clear 4 persisted RED jobs → cold `--update`+compare all 36). Blocks nothing downstream. Follow-on: arbiter dual-false-positive bug `262c59f6` (RED-first).
- [ ] **Visual sign-off** on the :8000 E2E **visual-regression diffs** — they WILL diff on the INTENDED UI (new AR/PLY panels, nav bar, header polish, V9 strip-icon). The one EXECUTOR:HUMAN tier → then **golden rebaseline**.
- [ ] **The FLIP** (`lupin-app.ini:883` `legacy notifications redirect enabled=True`) — Rick's word, AFTER visual sign-off. Push landed the mux code DORMANT behind the un-flipped flag.
- [ ] **Oracle-held rows** — if the E2E Oracle geometry surfaces a target: V13 (stale-check), V6/V7 inline, V10a spacing, L2 Playing-N-vs-Queued-N redundancy + AR widget tint. Crew (Krishna 🦚 / Sam 🎙️ / Clayton 😎) held ALIVE on standby to fix fast.
- [ ] **6 admin NAV items** DEFERRED (L4 `TODO(post-MVP)` in `NavBarRenderer.ts`) — roles-claim shape unverified vs `jwt_service`; verify before porting admin-gating.

### Possible future enhancement (NOT a priority — Rick de-prioritized 2026-06-26; store task `69edd619` dropped)
- [ ] **[LUPIN] `reason` discriminator on `voice_persona_released`** — add `reason={exit|reassigned|borrowed_return|clear}` to the WS payload (emit `voice_persona.py:~570`; catalog passthrough `notifications.py:~609`; consumers: web notifications.js + mux + mobile). Retires the client-side debounce-guess for true-exit vs benign-release. Mobile ships fine on its 3-5s debounce without it. Revisit only when convenient.
- [ ] **[LUPIN] Fleet-status board: give the heartbeat-arbiter its own "infra" lane** — the board truncates session `lupin-arbiter-app-8001` → `lupin-ar` and files it under `(Unmanaged) … worker / unknown`, so the standing heartbeat/owed-work arbiter reads like a mystery idle worker. Give it a dedicated infra row (or show its full name + an "infra" tag) so it's not confused with crew workers. Cosmetic only — arbiter is healthy/alive, this is a renderer change. DEFERRED under the mux↔legacy-notifications UI parity freeze (Rick, 2026-06-26 — no changes to either UI until parity lands). Filed by María 🌸 (session `ae92e658`, 2026-06-26).

---

## ▶ 2026-06-25 — LanceDB Phase A REBUILD EXECUTED (session d6b35eb3, MCP off)

**DONE**: `input_and_output_tbl` **90.46GB → 1.07GB** (~89GB reclaimed; 176,877 rows preserved; clean chain @ v1; DATA01 100%/16G → 94%/107G free). In-container staged rebuild (transient `docker compose run` one-offs, lance 0.36.0 V2 core); both servers healthy post-bounce. Execution log: `src/rnd/v0.1.9/2026.06.24-lancedb-88gb-optimize-incident-remediation.md` §8. `rebuild_lancedb_table.py` modified (`--keep-rebuilt` + `drop-rebuilt`) — **committed-held, push stays Rick's word**. Supersedes the gated `5daf94a0`/`db1acda7` REBUILD-impl items.

**~~OWED next (Bucket 3)~~ — CANCELLED 2026-06-26 (Rick strategic decision, see below)**:
- [x] ~~Phase B standing compaction~~ — **CANCELLED**: Rick 2026-06-26 — "No need for any nightly compaction." LanceDB being abandoned; the entire compaction class is moot.
- [x] ~~Decision #6 amendments to the recovery script~~ — **CANCELLED**: LanceDB recovery tooling no longer maintained; superseded by the Postgres migration.

---

## ▶ DECISION (2026-06-26, Rick voice ruling) — ABANDON LanceDB → PostgreSQL + pgvector (v0.2.0)

**Ruling**: Move off LanceDB entirely. Adopt **PostgreSQL + an embeddings / similarity-search extension (pgvector)** as the vector store. **No nightly/standing compaction** — the whole incident class that drove Bucket 3 disappears with LanceDB. Rick: "I don't want to put any more effort into it." The 88GB-incident remediation items (`5daf94a0` + Phase B compaction) are **CLOSED as superseded** — Phase A rebuild already reclaimed ~89GB (commit `63bfb1b4`, 90.46GB→1.07GB), more than enough runway to coast until the migration lands.

### v0.2.0 backlog (new dev branch)
- [ ] **[LUPIN] v0.2.0: LanceDB → PostgreSQL + pgvector migration** — stand up a Postgres-backed vector store (pgvector embeddings + similarity search) replacing LanceDB for `input_and_output_tbl` (and any other LanceDB-backed tables). Encompasses: schema design, embedding column + index strategy (HNSW vs IVFFlat), data backfill from the current LanceDB store, repo/DAO swap, config keys + splainer, 100% line/branch/function tests, and a cutover + rollback plan. Targets the **v0.2.0 dev branch**. Supersedes ALL LanceDB compaction/rebuild work (Bucket 3, TODO 461/462/1668/1745).

### 🗄️ LONG-TERM (deferred, NOT scheduled) — LanceDB source-code teardown (Phase 2)
**Context (2026-07-08, Mr. Radio 🦉, session 98a1c238 — Rick voice ruling):** the LanceDB **on-disk store** was removed today — DATA01 working-tree copy deleted (30G reclaimed); DATA02 backup-drive mirror FROZEN as a rollback snapshot via a `rsync-exclude.txt` entry. The daily Postgres backup was verified to capture all tables (whole-DB `pg_dump`, 25/25 tables incl. every pgvector table). Store task `4955d0b9` CLOSED. **Rick's instruction: leave the LanceDB source code intact for now — defer removal to a future endeavor, not today.**
- [ ] **[LUPIN] LanceDB source-code teardown (rollback-killing full teardown)** — the Phase-2 deliverable set from `src/rnd/v0.2.0/2026.07.07-lancedb-teardown-prep-scoping.md §4`: (1) remove the `lancedb` dependency (`pyproject.toml:43` + `src/cosa/requirements.txt:105`) + all 8 top-level `import lancedb`; (2) strip both dispatch layers — Layer A `vector_store_backend.py` + `vector store backend` INI flag (the live rollback switch), Layer B `solution_manager_factory.py` `ManagerType.LANCEDB` + lancedb factory keys; (3) remove all `if not self._use_postgres` branches across the 8 memory modules + update ~12 test files; (4) rename module file `lancedb_solution_manager.py` → `solution_snapshot_manager.py` (class symbol already renamed in Phase 1); (5) retire the `engine.lancedb_table` PredictionEngine family (`DEFAULT_LANCEDB_TABLE`, decision_proxy `proxy_lancedb_table`, INI `prediction engine lancedb table` + `swe team trust proxy lancedb table`, `main.py:480`); (6) disposition the backfill utility + 6 lancedb scripts (§7 table). Large blast radius on the CBR core — 100% L/B/F gate, full test layers, DO NOT rush. **NOTE:** with the on-disk store now gone, flipping `vector store backend` back to `lancedb` would find no local data — code-level rollback is already effectively spent (DATA02 mirror + GCS + off-tree backfill tooling are the only nets), which lowers the risk of this teardown.

---

## Pending Decisions

> Queue for `/plan-decide` (the **guided-decision-walkthrough** skill). One-line topics; the skill frames each live with pros/cons + a recommendation, descending priority. Detail lives in the linked design docs.

**Messaging-coordination plane (P0)** — ✅ **ALL 7 RESOLVED 2026-06-02 via `/plan-decide`** (Rick ratified every recommendation). Source `src/rnd/v0.1.8/2026.06.02-messaging-coordination-plane-design.md` (§ Ratified Decisions). Rulings in the Decisions Log below.
- **Implementation queue — ✅ ALL 5 LEVERS COMPLETE:** A durable outbox · D pull-able inbox · B loop de-block · C express lane · E backpressure. In-process, no broker. **A ✅ · D ✅ (committed `722e624`, :8000 integration 2/2) · B ✅ · C ✅ · E ✅** — 990 unit tests green, no regressions. B/C/E committed in the wrap-up checkpoint.

**GCP test-VM operability — follow-on (opened 2026-07-22, session 2c24d27b):** source `src/rnd/2026.07.22-vm-git-sync-strategy-decision.md` §6.
- [ ] **[LUPIN] Add SSH agent-forwarding to `lupin-vm.sh shell`** (`--ssh-flag="-A"`) — interactive git-as-you on the VM, all repos, zero creds at rest. Recommended next step; trivial.
- [ ] **[LUPIN] Unattended VM self-update?** — if near-term, start GitHub App setup (short-lived per-repo tokens); machine-user is the lighter interim. Skip deploy key (single-repo ceiling).
- [ ] **[LUPIN] `push-bundle` default** — keep fetch-only (current, safer) or default `--checkout` (deploy semantic)?
- [ ] **[LUPIN] Optional: fold `--actuate` into `provision-arbiter-on-vm.sh`** — one-shot arbiter bring-up (linger + enable) behind an explicit opt-in flag.
- [ ] **[LUPIN] Unify the notification API key across deployments — or ratify that they diverge** (opened 2026-07-25, session b38f09bb). The VM's `:7999` container accepts `ccfc494d` and rejects `26e3c096`, which the 07-25 entry records as the re-minted app key for the **Secret Manager / Cloud Run STT** path. Provisioning had rsync'd the dev box's key onto the VM, where it read fine and authenticated nowhere. Decide whether the VM container's registry should be re-minted to match, or whether per-deployment keys are the intended design and the provisioning copy is the only thing to fix. Detail: `src/rnd/v0.1.9/2026.07.25-vm-dm-outbound-key-two-stacked-defects.md`.
- [ ] **[LUPIN] Provisioning should not copy `src/conf/keys/` wholesale to a remote host** (opened 2026-07-25, session b38f09bb). The VM held 10 dev credentials it never needed; removed on Rick's instruction. Whatever placed them there will do it again on the next provision — fix at the source.

**Task-store identity (opened 2026-07-25, session b38f09bb):**
- [ ] **[LUPIN] Store attributes items to the wrong persona** — a row created from session `b38f09bb` (Cheech 🌿) was stamped `owner_persona: "rachel"` / `created_by: "Rachel f3d7df6c"`, where `f3d7df6c` is the **background-job id**, not the MCP session id. The store resolves identity from a different source than the session bridge, so owed work can land under the wrong owner. Row `641942c0` is the live example.

**Messaging plane — follow-on (deferred design decision):**
- [ ] **[LUPIN] Lever B comprehensive sweep** — revisit moving ALL remaining sync DB/file I/O off the event loop (beyond the surgical hot-handler fix), after measuring whether colder paths still stall under load. Deferred per Rick 2026-06-02; surgical fix lands first.
- [ ] **[LUPIN] Full-REMOVAL of the legacy commons-DM path (revisit-later)** — note-to-revisit per Rick's 2026-06-15 ruling (comment-out now, full-delete deferred). After the dm_send cutover has soaked and telemetry shows zero legacy-path hits, DELETE the commented-out machinery: `commons_send_to`, `ask_async`/`ask_sync` DM-mode, `register-question` + `CommonsQuestionWatcher` + main.py lifespan, the 2 legacy listener handlers. KEEP polling-mode + broadcasts + presence + `_handle_broadcast_received`. Prereq already handled at comment-out time: arbiter `make_dm_push_fn` migrated to `/api/notify-peer`. Design: `src/rnd/v0.1.8/2026.06.13-cosa-voice-token-reduction/03-phase4-legacy-commons-dm-retirement-proposal.md`.

## Pending

### History Archive (Session 280)

### SWE Team Proxy: Workload Generator + Shadow-Mode Capture

### SWE Team Proxy Agent (HIGH PRIORITY)

### Disambiguate Database Names (Session 343-344)

### Before Branch Merge

### TTS Focus Mode Race Condition (Sessions 346-347)

### Future Considerations

- [ ] **[LUPIN] Add 60s safety timeout to TTS focus mode** - Prevent permanent stuck state when TTS queue items fail to play. **Partially addressed** (Session 164): Added staleness check on restore + exit in moveToRegularNotifications. Still need: runtime 60s timeout for cases where notification exists but user never responds and timeout doesn't fire. **File**: `src/lupin_app/static/js/notifications.js:9374-9393`
- [ ] **Silent flag for notifications**: Consider adding a `silent` parameter to the cosa-voice notification system to suppress TTS during automated testing. Would require changes to: router request models, job classes, voice_io wrappers, and core notification functions.
---


---

## 📦 Archived

- [`todo-history/2026-04-10-to-2026-05-01-todo.md`](todo-history/2026-04-10-to-2026-05-01-todo.md) — 21 CLOSED + 10 MIXED-excerpt sections, 198 closed bullets, archived 2026-05-01 (Session 92ece47c)
- [`todo-history/2026-04-14-to-2026-05-28-todo.md`](todo-history/2026-04-14-to-2026-05-28-todo.md) — 27 CLOSED sections (2026-04-14 → 2026-05-28), archived 2026-06-18 (Session 3364493b, Tiffany 💍; task 02f1e0d5)
- [`todo-history/2026-04-15-to-2026-06-16-todo.md`](todo-history/2026-04-15-to-2026-06-16-todo.md) — 98 sections (2026-04-15 → 2026-06-16 arcs + undated legacy queues), HORIZON sweep at the 2026-06-25 boundary, archived 2026-07-11 (Session 372f9dc9, Mr. Radio 🦉; task 2a190fa2). ⚠️ Contains 359 still-open [ ] bullets swept by age, NOT by disposition — stale-pending review open.
