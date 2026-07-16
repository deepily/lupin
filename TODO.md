# TODO

Last updated: 2026-07-16 (session da517b03, Mr. Radio 🦉 — GCP deployment arc + 4-merge bug-fix sprint; end-of-session commit+push)

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
