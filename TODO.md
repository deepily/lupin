# TODO

## ✅ CLOSED 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — Krishna's managed-bounce lane: all three items done, and the answer moved the target

*(The "FOR TOMORROW" version of this entry is kept below for the record — it was accurate when written and one of its own claims turned out to be wrong.)*

**All three landed** in `70a27d02` (item 1) and `066f04f8` (items 2–3), on Rick's ruling. Doc: `src/rnd/v0.1.9/2026.08.02-settle-deadline-arithmetic-30-vs-40.md`.

1. **`main.py` fallback** — was still 15 while the key read 30; now tracks the key, with a **call-site pin test** that reads the `default=` the code was actually called with rather than grepping the source. (Note: TODO line 171 in the entry below claimed this was "also fixed". It was not — it was still 15 this morning. A claim about a fix is a claim like any other.)
2. **The arithmetic is settled, and Krishna was right.** `self._attempt += 1` runs **before** the `min()`, so the first delay is `2^1` not `2^0` — wakes at **2/6/14/30/60**, his series, not my 1/3/7/15/31. Confirmed against ~63k printed reconnect delays, not just derived. Both live samples fall out **exactly** at a ~40s restart catching the t=60 wake (+18.6s, +20.4s).
3. **Jitter is ON — pointing DOWN**, and the cap came to 10, deadline to 15.

**🔴 The finding that outlives the three items — arrival is a SAWTOOTH in restart downtime.** A restart 11 seconds *faster* arrives 11 seconds *later* relative to gate start (D=30.1 → +29.9; D=41.4 → +18.6). Rachel's ~8s-downtime bounce would have arrived at +6s and 15 would have been fine — **the two nights' numbers never conflicted, they were different points on a sawtooth.** So the deadline can never be tuned by averaging observations, and 30 was not "measurement-backed" in any sense that survives: two samples cannot bound a sawtooth.

**What replaced measurement**: the deadline is now **derived**, not chosen. `SettleDeadlinePinTests` computes the requirement as `RECONNECT_MAX_DELAY + margin` and reds if the cap and the deadline drift apart **in either direction**. The 15→30→15 churn happened because the two values lived in different files and were picked independently by different people; that coupling is now a test.

**On jitter, and Rick was right to push back.** He asked *"jitter always helps smooth out the thundering herd, does it not?"* — yes, and that was never disputed. The narrower claim was that it helps the *herd* (load) and not the *gate* (last-arrival), since a coverage gate waits for the slowest session. Simulated over 20k bounces: symmetric ±50% jitter at the old cap takes the typical wait from 8.1s to 27.7s. **His pushback produced the better fix**: jitter has a *direction*, and applying it **downward only** spreads the fleet just as well while leaving the cap a real ceiling — which the deadline's derivation depends on.

**The instrument that was missing**, and the honest reason two competent readings stood unreconciled for a day: the reconnect line had **no timestamp** and sat outside the timestamped log path — zero timestamped reconnect lines in the entire 118 MB centralized log. The downtime had to be *inferred* from arrival times. Now routed through an overridable `_log`; gated by driving the real `run()` loop against a real file and asserting on **what landed on disk**, not by reading the chain.

### ⚠️ TRANSITION HAZARD — the next bounce is the lossy one, and it is unavoidable

The two halves of this fix land on **different processes at different times**:

- the **deadline (15s)** is server-side — live the moment `:7999` is bounced;
- the **cap (10s) + jitter** is in the **listener**, a long-lived host-side process that keeps its old code until it respawns.

So the **first** bounce after this commit runs a 15s deadline against listeners still on the 30s cap — the one combination that is worse than either state. Sessions alive right now will not have the new backoff until their listeners restart.

**Not a reason to revert, and not a reason to rush a bounce.** Options, for whoever takes it: accept one lossy all-clear (the warning still lands, and the warning text is self-limiting), or let the fleet turn over naturally first. **Flagged rather than decided — Mr. Radio did not bounce `:7999` on this.**

---

## 🗄️ FOR THE RECORD — the "FOR TOMORROW" entry as written 2026-08-02 00:12 (superseded by the entry above)

**Rick asked for a note that Krishna has work "still in flight and uncommitted." I checked the tree before writing it, and the second half is not true — so here is the accurate version, because a wrong note tomorrow costs more than no note.**

**NOTHING of Krishna's is uncommitted.** His tree work — deadline 15 → 30, the splainer rewrite, and the pin test — shipped in `416940e4`. `git status` shows no managed-bounce file dirty. He explicitly reverted a half-finished edit rather than leave the tree inconsistent under a deadline, and said so.

**What IS unfinished is work he never built.** Three items, in priority order:

1. **`main.py:472` still falls back to `15`.** The key is now 30, so if that config key ever goes missing the server silently reverts to the value we just measured as wrong. One line. This is the only *code* item.
2. **The deadline may need to be 40, not 30 — and the arithmetic to decide it is UNRECONCILED.** I ordered 40, then withdrew the order when I noticed my own objection cut both ways. The dispute: Krishna reads the listener backoff wake series as **2/6/14/30** from disconnect; I read `min(1.0·2^attempt, 30)` as **1/3/7/15/31**. Neither of us settled **the offset between the disconnect clock and the gate-start clock**, which is precisely what makes "+20.4s from gate start" and "a 30s wake from disconnect" non-comparable. 30 clears both *observed* samples by ~10s, so what shipped is defensible on measurement — but if the boundary reading is right, 30 races the wake it is waiting for.
3. **🔴 THE REAL FIX, and it needs Rick, not a worker.** The listener backoff in `src/cosa/agents/utils/proxy_agents/base_config.py` has **no jitter** and a 30s cap. Nine sessions waking within 8 milliseconds of each other is a thundering herd by construction. Jitter would make *any* deadline choice robust instead of boundary-sensitive, and a lower cap would stop pushing reconnection past every sane window. **Fleet-wide blast radius — deliberately not taken by the bounce-arc crew.**

**Where the context lives**: Krishna's memento (`.claude-memento-krishna-50c3680b.md`) carries all three plus the backoff finding; store row `251a42d0` (done) carries the full arc; his session was reaped clean on Rick's word.

---

## 📥 FINDING 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — a listener loads the WORKING TREE at spawn, so it can pick up HALF an edit

**Status**: measured on boot #8, **no store row** (Rick's no-new-rows order stands). Sharper than the transition hazard filed above, and it partly replaces it.

**How it surfaced**: boot #8's reconnect lines were inconsistent with each other. Four listeners printed the old bare format; one printed **timestamped** lines — my instrument, committed at 13:43 — while *also* showing a **16.0s** delay at attempt 4, which the new 10s cap forbids. Timestamp present, cap absent. That combination exists in no commit.

**Cause**: listeners run `python -m lupin_cli...` straight out of `/src` (verified: the module resolves to the working tree, not site-packages). They import **whatever is on disk at the moment they spawn**. My two edits were saved ~15 minutes apart; a session that started between them loaded one and not the other.

```
3e328792  12:51   no timestamped lines
1bf47c18  12:53   no
b07d59ac  13:04   no
9fec7c53  13:20   FOUR  <- spawned between the _log edit and the cap edit
55eae7a8  14:06   (not yet reconnected)
```
A clean split at exactly the edit boundary — this is the mechanism, not a coincidence.

**🔴 Why it matters beyond this change.** `:7999` has the rule "a saved file is not a served file — you must bounce." **For listeners the inverse holds: a saved file IS served, to the next listener that spawns, with no bounce and no announcement.** An editing session therefore deploys *intermediate* states to the fleet without anyone acting. The fleet can hold several code versions at once, and none of them need correspond to a commit.

**Not proposing a fix here** — the options (spawn from an installed copy, stamp each listener with a git sha at spawn, or accept it and make the version legible in the log) have real trade-offs and this is fleet-shaped. Naming the mechanism so the next confusing log is diagnosed in a minute rather than an hour.

**Refines the transition-hazard entry above**: it is not "old code vs new code" — there is no single old version. Any listener alive across an editing session may hold a mix.

---

## 📥 FINDING 2026-08-02 (Mr. Radio 🦉 `1bf47c18`) — session gists have been degraded fleet-wide since the Mistral cutover

**Status**: found incidentally while reading listener logs, **not fixed** — a model-server bounce and GPU work are outside what I take unilaterally. No store row (Rick's no-new-rows order stands).

**What the server serves** (`GET :3001/v1/models`): `kaitchup/Phi-4-AutoRound-GPTQ-4bit`.
**What the config asks for** (since the 07-31 cutover `5499fdbf`, 29 references renamed): `ConfidentialMind/Mistral-Small-3.2-24B-Instruct-2506-GPTQ-AutoRound-TextOnly`.

Every Gister call 404s. **102 degraded gists today**, most recent 17:14. The listener is honest in the log — *"DEGRADED: gist unavailable — emitting 5-word prefix fallback … This is NOT a model-generated gist"* — but a 5-word prefix still *looks* like a gist in the UI, which is why nobody filed it.

**Same shape as "a saved file is not a served file."** The 07-31 session verified Mistral with a real inference call on its own dedicated venv/port. What was never verified is that **`:3001` — the port the Gister actually calls — was moved to it.**

**Two ways out**: bring `:3001` up on Mistral (what the cutover intended; venv + `svllmm` alias already exist), or revert the 29 config references to Phi-4. Rick's call.

---


Last updated: 2026-08-02 (Rachel 🕊️ `0d6df7b6` — bounce-button: served ≠ saved, and a whole press pressed)

---

## 📥 FINDING 2026-08-02 (Rachel 🕊️ `0d6df7b6`) — the bounce button was 404 on the running server; auth-401 + whole-press now proven; the endpoint tests were ungated

**No store row** — Rick's no-new-rows order tonight. Three jobs for María 🌸 (`2b9feb77`) on commit `5f40de15` (Managed bounce R2). Same shape three times: a saved file that was not a served/gated file.

**Job 2 finding (biggest) — committed ≠ deployed.** `POST /api/system/bounce` returned **404 on the live :7999**: the endpoint committed at 20:52 but the container last started 20:25 and reload is OFF, so the button was DEAD on the running server. María's own rule — "a saved file is not a served file" — broken within the hour of R2 being called done. Fixed by driving the sanctioned sequence: `bounce-dev-server.sh` (load the endpoint; 404→401 confirmed live) → `install-bounce-watcher.sh` (the watcher was NOT running — no `io/bounce` heartbeat → a press would 503; now a systemd --user unit, heartbeat fresh at 1s) → **the real authenticated press**.

**Whole press proven end-to-end (first time):** click → `202 triggered` at t=0 → watcher claimed the trigger + set `bounce.inprogress` at t=2s → :7999 DOWN at t=20s → HEALTHY at t=28s (all-clear). Observe loop only accepts "healthy" AFTER first seeing "down", so a pre-restart 200 cannot false-green it. Corroborated independently by María: container `StartedAt` moved 21:16:45 → 21:20:51.

**Job 1 — the auth-401 branch was untested.** `test_system_bounce.py` proved 409/503/202 but called the endpoint with a **fake `current_user`**, bypassing the auth dependency, so the 401 the commit names never ran. Closed by new `test_system_bounce_auth.py` (2 passed): drives the REAL chain (`HTTPBearerWith401` → `get_current_user`); unauth AND malformed-Bearer both 401 (a custom 401 subclass, not FastAPI's default 403 — the commit's "401" claim verified). Red-proof (documented): removing `Depends(get_current_user)` → unauth reaches the body → 503/202, not 401.

**Job 3 — those tests were invisible to the gate.** Both files lived in `src/cosa/tests/unit/rest/`, but the unit gate runs `pytest src/tests/unit/` only (`src/tests/run-unit-tests.sh`), so **0 were collected** — green locally, never in CI. Relocated both into `src/tests/unit/` (where sibling `test_bounce_watcher*.py` already live); verified by RUNNING the gate: `run-unit-tests.sh -k system_bounce` → **13 passed, 12142 deselected**. Chose relocate over allowlist deliberately.
- **SYSTEMIC (worth a real look):** no runner I could find collects `src/cosa/tests/` at all — `pyproject.toml` references it only to EXCLUDE it from coverage — yet it holds **~415 test files**. A whole tree of unit tests may be green-locally / ungated. Same failure shape as the 404, at scale.

**Uncommitted for the crew (Sam gates, María/Cheech commit):** `src/tests/unit/test_system_bounce_auth.py` (new), the `git mv` of `test_system_bounce.py` into `src/tests/unit/`, and the D2/D3 test files from the prior legs.

---

## 📥 STASHED 2026-08-02 (Cheech 🌿 `7edf6e5e`) — a review that stops at the process boundary passes an inert fix

**Not filed as a row, per Rick's board-to-zero directive tonight.** Recorded here because it is the second instance in one day, in different code, by different people.

**What happened.** Bug `f433fbae` D1 committed as `fd11cd30`: `ask_multiple_choice` now passes `response_default`, so an offline read should return the default instead of a 503. Sam reviewed it and PASSED it — he confirmed the 503 had drifted to `notifications.py:1068-1069`, reverted the plumb himself, and got the exact predicted failure text. A careful review by any normal standard.

Then Clayton, chasing an unrelated ruling about marking defaults, found the fix **delivers nothing**:

- the server's offline branch returns a plain `JSONResponse`, not a `data:` SSE frame the client parses;
- `OfflineEvent` requires a `response` field the server never sends — the default goes into `default_used` instead;
- so client validation fails and drops to an error dict. Honest, not forged. But the default never lands.

Sam retracted his own pass unprompted and named the miss himself: *"I gated the server emit and the plumb, never traced the client consume — the exact different-process seam."*

**Why it matters.** This is the same shape the late-answer-handback cascade caught four hours earlier: a dedupe ledger whose writer lived in a different process from its reader, whose test would have gone green while production failed. Different file, different people, same seam. A unit-level negative control proves the **plumb**, not the **delivery** — and the control is what makes the review feel finished.

**The rule that came out of it, now binding on this crew:** do not gate a cross-process fix by reading the chain. Reading is how it passed the first time. Execute it — drive a real call against a server forced into the failing state and assert on **what the caller actually receives**, provenance intact.

---

## 📥 SCOPED 2026-08-02 (Clayton 😎 `99913b08`) — bug f433fbae D2 does NOT fix the symptom Rick reported

**No store row** — Rick's no-new-rows order tonight. Two caveats, so D2 is never read as closing a complaint it doesn't touch.

**What D2 landed.** The blocking-ask verbs (`ask_yes_no` / `ask_multiple_choice` / `converse` / `ask_open_ended_batch`) now stamp an `idempotency_key`, and the server's response-required path re-attaches to the original notification on a repeat key instead of minting a second card. This closes the **in-process same-key re-POST** duplicate — `notify_user_sync`'s `retry_on_timeout` loop and any durable resend.

**Caveat 1 — a bounce still duplicates.** `_ask_idempotency_index` is an in-memory `OrderedDict`; a :7999 bounce wipes it, so the same key re-POSTed *after* a bounce misses and mints a new card. The existing fire-and-forget idempotency cache has the identical limitation. **Fix (deferred):** add an `idempotency_key` column to the `notifications` table (a migration on the hot table — none exists today, and the row has no spare metadata field) and look up by key so the dedup survives a process restart.

**Caveat 2 (the bigger finding, stated bluntly) — D2 does NOT fix the symptom Rick reported.** Rick's "re-answer the same question" came from **three separate ask INVOCATIONS**, each minting a *fresh* idempotency_key. No idempotency key — in-memory or DB-backed — dedups distinct invocations; only content-hashing the ask would, and nobody has ratified that. D2 fixes the retry-loop case, not the re-invocation case. The reload-OFF policy change (2026-08-01) plus D1's marked-default are what actually reduce the reported storm; D2 is defense-in-depth on top.

**Follow-up (D1 offline test) — pre-existing failure, must move to the SSE contract when fixed.** `src/tests/unit/test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_offline_with_default` **already fails at the pre-tonight base** (`fd11cd30^`) — an empty-body test-harness issue, independent of D1. It is NOT a D1 regression. BUT: D1 changed the response-required offline path from a `JSONResponse` to an SSE `StreamingResponse` (ack + OfflineEvent frame). So whoever fixes that test's harness must **also** update it to assert the SSE contract (`response.status_code == 200`, `text/event-stream`, parse `data:` frames → `status: offline` / `response` / `default_used: true`) — a `response.json()` assertion on that path is now wrong by design. Same applies to `test_notify_response_required_open_ended_batch_accepted` if it exercises the offline path.

---

## 📥 FINDING 2026-08-02 (Tiberius 👑 `f63d0e28`) — the handback bounce-e2e can't be a :8000-scheduled job

**Status**: measured, resolved for THIS test, worth a venue-rule note. **No store row** — Rick's no-new-rows order tonight.

**The finding**: the two execution rules in my brief can't both hold for the late-answer handback e2e.
- **A :8000-scheduled test cannot bounce :8000.** The test-suite runner `Popen`s pytest as a *child of the :8000 server process* (`src/cosa/agents/test_suite/job.py`). A test that restarts :8000 to wipe the in-memory `pending_responses` waiters kills its own runner mid-run → deadlock, no results.
- **Bouncing the real :7999 is worse**, not a fallback: it's the live fleet server, and seeding+answering notification rows there writes to `lupin_db_dev` — the "no test touches a live dev data store" mandate.

**Resolution (Cheech green-lit 2026-08-01 20:32)**: the handback e2e stands up its **own uvicorn on a throwaway migrated DB** and bounces *that* via a genuine kill+restart. Real process-lifetime seam (in-memory waiters wiped, durable PG row survives), isolated, reproducible, no fleet disruption, no live-DB write. No manual :7999 bounce tonight.

**Also measured**: `lupin_db_dev` is already migrated — `answer_delivered_at` column + `idx_notifications_answer_owed` index present, `alembic_version = 3da5c0d1eee6`. So Rachel's deferred "live round-trip" precondition (deferred until the shared DB carries `3da5c0d1eee6`) is satisfied for the dev DB.

**LANDED 2026-08-02**: `src/tests/e2e/test_ask_answer_handback.py` (+ `_handback_e2e_server.py`) — THREE scenarios GREEN, 57s.
- (a) stream-death, server alive → answer reaches the asker via the re-attach poll → `responded`, no re-ask.
- (b) orphaned waiter (stream death) → answer OWED → travels via `answer_catchup.surface_owed_answers`; ack empties owed → surfaces once. Proves the catch-up path only.
- (c) **LIVE waiter wiped by a real restart** — hold the stream OPEN (waiter live), assert in-flight, restart (process death), then answer → travels via catch-up. Rick's mid-question-bounce case.
- **Sam's catch (2026-08-02)**: (b) alone oversold — closing the client stream makes uvicorn cancel the generator, whose `finally` DELETES the waiter, so the restart wiped nothing live (deleting it stayed green). Fixed: (b) renamed + descoped to orphaned-answer travel; (c) added for the live-waiter case.
- Falsifications EXECUTED (predicted text confirmed, restored): (1) inverted the owed predicate → catch-up empties → red; (2) neutralized (c)'s restart → the live waiter is woken (delivered), owed stays 0 → red. (2) proves (c)'s restart is load-bearing.
- Venue: own uvicorn (real notifications+websocket routers) on a throwaway migrated DB, bounced by kill+restart. Never touched :7999/:8000/`lupin_db_dev`.

**Finding worth the design owners' eyes (stale-PID bridge → NULL persona)**: `_voice_persona_for_sender_id` resolves the bridge via `find_session_by_id`, which **skips any bridge file whose filename PID is not a live process** (stale-session guard). So a session whose bridge is stale/dead at answer-persist time stamps `sender_persona = NULL` on the ask row — and that late answer becomes **unretrievable by persona**, the same §4.4 accepted gap as a persona-less session, but reached by a *different* door (a dead-PID bridge, not a failed allocation). Bounded + already-audible (the `[NOTIFY] ⚠️ … NO voice persona` warning fires), but the runbook gap is currently framed as "allocation failed" only; a dead bridge at persist time hits it too. Not a blocker; noting so the gap's framing is complete.

---

## 📥 FINDING 2026-08-02 (Tiffany 💍 `0768c103`) — two notification tests assert the pre-SSE offline contract; NOT "pre-existing", 40 minutes old

**Status**: reproduced and root-caused by me, **not fixed** — it is the f433fbae campaign's lane, not mine. **No store row** per Rick's no-new-rows order.

```
FAILED test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_offline_with_default
FAILED test_notifications_api.py::TestNotifyResponseRequired::test_notify_response_required_open_ended_batch_accepted
        json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**Cause**: `1cd795c7` ("Bug f433fbae D1 (server half)") deliberately changed the offline branch from a plain `JSONResponse` to a `StreamingResponse` emitting two SSE frames. That is the correct fix and the commit is sound — it updated *its own* test. It did not update these two **twins in a different file**, which still call `.json()` on a response that is now an SSE stream.

**🔴 THE LABEL MATTERS.** These were reported to me as "pre-existing failures, not in my diff." The first half is right, the second is misleading: **I ran this exact class at 00:38 tonight and all five passed.** They broke at ~00:55. "Pre-existing" invites everyone to route around them; "someone changed the contract 40 minutes ago and two twins were missed" tells the owner it is theirs and still warm.

**Fix direction — assert the NEW contract, do NOT restore the JSON blob.** Drain the generator and assert both frames, `response=<default>`, `default_used=True`, exactly as `1cd795c7` did for its own test. This is the third instance tonight of the same shape (podcast tests `20c70793`, DM-judge `60bbb6ce`): a campaign moves a contract, a twin in another file keeps asserting the old one, and the cheapest green is the wrong one.

**Verified not caused by the bridge-guard work**: both still fail with `-o addopts=""`, so the `pytest.ini` marker change is exonerated.

---

## 📥 BACKLOG 2026-08-02 (Tiffany 💍 `0768c103`) — the all-clear's real blocker is the reconnect WINDOW, not the predicate

**Status**: measured tonight, NOT built, NOT ruled. **No store row** — Rick's broadcast ordered no new task items tonight, so this is stashed here deliberately.

**Context**: bug `784d4a2e` replaced the all-clear settle gate's plateau predicate with roster-coverage (Rick's direct ruling, 2026-08-02 ~00:20). The predicate change is right and is committed work. This entry is about what the fix EXPOSED rather than solved.

**The measurement** — a real `:7999` bounce at 00:25 ran the new gate:
```
all-clear FIRED on DEADLINE EXPIRY (boot #3): reached 10 recipient(s) after 15.3s;
reconnect curve 0→0→1→1→1→1→…→1   [29 polls flat at ONE]
10 session(s) had NOT rejoined and got NO all-clear (accepted loss, no re-fire): [10 ids]
```

**🔴 CORRECTED TWICE. Read both corrections — the second one partly restores the first, and that is the lesson.**

*First version*: "reconnection is slower than the 15-second window" (1 of 11 sockets back at fire time). *Correction 1*: I called that wrong and replaced it — the roster and the live-socket set were **never the same id space** (roster holds `0768c103-eb8d-…`, the socket registry holds `cc-listener-0768c103`), so the comparison could not match at all and the gate was **blind, not coarse**. Fixed under `784d4a2e`.

*Correction 2, measured on boot #4 with the fix live*: **both defects were real and stacked.** The id-space bug was masking a genuine timing problem, and now that the gate can actually see returning sessions, the timing problem is exposed and finally has a number under it. My first explanation was not wrong — it was **incomplete, and I called it wrong**. Over-correcting is its own error: a second story that fits the evidence does not automatically retire the first.

**🎯 THE NUMBER, measured on boot #4 (2026-08-02 01:17, `d96f59ce` live):**
```
01:17:08.404  all-clear FIRED on DEADLINE EXPIRY — 15.5s, curve 0→0→0→1→1→…→1
              9 session(s) named as missed
01:17:11.506  cc-listener-0768c103   ┐
01:17:11.511  cc-listener-7edf6e5e   │  ALL NINE of the "missed"
01:17:11.511  cc-listener-9056b85b   │  reconnect 3.1s LATER,
01:17:11.512  cc-listener-0d6df7b6   │  within 8 MILLISECONDS
01:17:11.513  cc-listener-f63d0e28   │  of each other
01:17:11.513  cc-listener-8a09f41c   │
01:17:11.513  cc-listener-5b2b4545   ┘  (+ 2 more)
```

**What this establishes, and it is the first hard evidence in this whole arc:**
- The fleet does **not** trickle back — it returns in one synchronized burst at **~18.6s after the gate starts**, roughly 3 seconds past a 15-second deadline. That looks like a fixed reconnect/backoff interval, not load-dependent scatter.
- **The deadline is the lever now, and it is short by about 3 seconds.** Every one of the 9 sessions named as an accepted loss was actually back moments later — and got nothing, because re-fire is barred.
- The gate itself is behaving correctly: it named exactly the sessions that genuinely had no socket at fire time. The instrument is sound; the window is wrong.

**✅ SECOND SAMPLE ARRIVED — boot #5, a peer's bounce minutes later. It CONFIRMS the burst and widens the spread:**
```
boot #4   fire 01:17:08.404 (15.5s)  →  9 listeners at 01:17:11.506   = +3.1s   (within 8ms)
boot #5   fire 01:21:14.801 (15.4s)  →  9 listeners at 01:21:19.813   = +5.0s   (within ~70ms)
```
Reconnection completes **~18.6s and ~20.4s** after the gate starts. **The 15s deadline misses it both times.** Two independent bounces, both a synchronized burst, both a total delivery loss.

**Worth noting how the second sample was obtained**: I asked Rick whether to fire two controlled bounces for measurement — a deliberate fleet disruption at 1am — and the ask timed out because a peer's bounce dropped it. That bounce *was* the sample. The question answered itself at zero cost to the fleet.

**Next, in order:**
1. **DELEGATED (Krishna, spawned 01:22)** — raise the deadline 15 → **30**, not 25: two samples at 18.6 and 20.4 are 1.8s apart at n=2, so leave real headroom rather than hugging the larger one. Splainer twin must state the measurements *and* that n=2 — it currently admits "15 is a GUESS", and the replacement must not read as more certain than two samples support. Plus a test that goes red if anyone tidies it back to 15.
2. **✅ ANSWERED — and it makes 30 the wrong number.** Krishna traced the burst to the listener's exponential backoff in `src/cosa/agents/utils/proxy_agents/base_config.py`: `RECONNECT_INITIAL_DELAY=1.0`, `BACKOFF_FACTOR=2.0`, `MAX_DELAY=30.0`, **no jitter** — which is exactly why all nine wake within 8ms of each other. The fleet lands on the **30-second cap wake**. So a 30s deadline *races the wake it is waiting for* — a coin flip, and the same "don't hug the sample" error I gave him, reappearing one level up. **Corrected to 40**, clear of the boundary. (Arithmetic being reconciled first: his series is 2/6/14/30, mine is 1/3/7/15/31 from `min(1.0·2^attempt, 30)`; we are choosing a config value against those boundaries, so the exact series and the offset between the disconnect clock and the gate clock have to be settled, not assumed.)

3. **🔴 THE REAL FIX IS JITTER, and it is Rick's call — fleet-wide blast radius.** Nine sessions waking within 8 milliseconds is a textbook thundering herd; the lockstep is a property of the backoff having no randomization. Adding jitter would spread the reconnects and make *any* deadline choice robust instead of boundary-sensitive. Also worth pricing: a 30s cap means a listener that misses early attempts waits half a minute, which is what pushes reconnection past any sane all-clear window in the first place. **Not touched** — a launch-wide backoff change is not something a bounce-arc worker should land unilaterally.

4. **Also fixed**: `main.py:472`'s fallback default was still 15. A fallback that disagrees with the key silently reverts to the known-wrong value if the key ever goes missing.
3. Only then consider the warning-phase ack list as a tighter roster — it may be unnecessary if the window is simply correct.

⚠️ **The roster over-count is real and still costs us**, independent of the id bug: the 00:25 warning was acked by only 2 distinct sessions while the roster listed 10. Krishna was **reaped at ~15:50** and his bridge file is still on the roster nine hours later — a session that will never reconnect, holding the gate to the deadline on every bounce.

⚠️ **A second, upstream collision** (Arnold, not fixable in the gate): the two id spaces meet at `session_id[:8]`, because the socket key carries only 8 characters. Two sessions sharing 8 leading characters would mark a real straggler as covered. That lives in how listeners are named, not in the gate.

---

## 📥 STASHED 2026-08-01 night (Mr. Radio 🦉 `9056b85b`) — two findings NOT filed as rows, per Rick's board-to-zero directive

Rick's broadcast `0152e7b0`: *"stop posting new task list items. NONE… stash it in the to-do file and we'll come back to it on another day."* Both of these would otherwise be store rows. Neither blocks anything.

**1. Tone's evidence sometimes hands back the whole message instead of the phrase it judged.**
Measured properly in commit `a09a2327` (probe + 31 tests). On the four probe bodies the behaviour is clean and defensible: the two *plainly-written* bodies (tone +2) get the whole body quoted — when prose is uniformly plain there is no offending phrase to point at, so "all of it" is a fair answer — while the two *jargon* bodies (tone −2/−1) get aimed quotes, 6/6. **The anomaly is on live DMs, not probe bodies**: two of mine scored tone **−1** and still echoed whole. On a negative grade there *is* something specific to point at, so the probe's pattern does not predict it. n=2. Not a grading defect — the weights are right — an evidence-quality one. Next step if picked up: run the tone grader against bodies that are plain-but-flawed, which is the cell the 2×2 does not contain.

**2. `io/mementos/tiberius.md` is a bare slot that nobody can clear.**
The last surviving `memento_io verify` finding on this repo. Its content is **byte-identical** to `tiberius-legacy-2026.07.14-193034.md`, so the data-loss window is already closed — what remains is a label, not a risk. Clearing a bare slot needs `write --persona <p> --session-id <sid>`, and Tiberius's seat is gone, so the session id would have to be invented. That is exactly what `BARE_SLOT_EXEMPTIONS` in `memento_io.py` exists for, and three slots already sit in it for this reason. **It is a planning-is-prompting change, not a Lupin one**, and adding a fifth entry deliberately reds `test_exemptions_are_exactly_the_ruled_set` so a human has to notice — which is the design, not an obstacle. Deliberately not done from this repo tonight.

---

## 📥 BACKLOG 2026-08-01 evening (Rick's idea, captured by Mr. Radio 🦉 `9056b85b`) — reject over-long DMs at a hidden, randomized word limit

**Status**: idea captured, NOT built, NOT ruled. No store row yet — this is a design Rick floated, not owed work.

**Rick's proposal, in his framing**: tell everyone up front that exceeding the word limit produces an **error and the DM is not sent**. Do **not** tell them what the limit is, and draw it **randomly between 150 and 250** so it cannot be gamed. The published advice is simply to stay within the recommended limits.

**Why the lever is right.** A grade is advisory. The judge published 👎s all evening and nobody was blocked by one, which is exactly how a ~1000-word DM still went out (Rick's broadcast `d8099c6c`). A rejection forces the rewrite — a different instrument, not a louder version of the same one.

**Why the randomization is smarter than it first reads.** A known limit of 200 puts everyone at 199 — compliance, but it parks all traffic at the ceiling. A threshold drawn from 150–250 turns the cliff into a **slope of rejection probability**: ~10% at 160 words, ~90% at 240. The risk-averse response is to go well under 150 rather than hug the edge, and that behaviour falls out of the mechanism instead of out of asking nicely.

**🔴 THE ONE CHANGE I'd insist on — seed the threshold on a HASH OF THE BODY, not a fresh random per call.** As drafted, a rejected DM retried *unchanged* succeeds about half the time, which teaches **"retry beats editing"** — the one gaming vector the randomization itself introduces. Hashing keeps every property wanted (unknowable in advance, unguessable, spread over 150–250) and adds the one needed: the same text always gets the same verdict, so a rejection sticks until the words actually change. It also keeps the send path reproducible for debugging and tests.

**Two things to settle before it ships**
1. **What counts as a word.** A pasted stack trace, code block, JSON blob or long URL blows any limit — and those are sometimes what a DM legitimately carries. Strip fenced blocks from the count, or the rule punishes the wrong messages.
2. **What the error says.** That message is the *entire* teaching surface. It should name the ~60-word target, say the limit is variable so nobody burns a cycle reverse-engineering it, and point at the doc-link pattern for anything genuinely long. "Too long" alone produces guessing.

**Interaction with the open bug rows**: this largely retires `0fc5b8f0` (the −2 length grade saturating at 250) for *enforcement* — nothing that long gets sent at all — but the saturation still distorts the audit history, so that row stays open rather than closing on this.

---

## 📋 DECISIONS LOG 2026-08-01 (Cheech 🌿 `7edf6e5e` + María 🌸 `2b9feb77`) — late-answer-handback cascade post-game

**Retro**: `io/post-games/2026.08.01-late-answer-handback-cascade-post-game.md` (local corpus, gitignored). Cascade telemetry: 15 stage-reviews, 5 sections, 43 min, 51 findings, 0 rejected, 0 escalations, no code under Rick's gate. Cast reaped 16:54; post-game opened 16:58.

**R-1 — the deposits carried the harvest through a reap-before-harvest, and that is a receipt, not a mechanism claim.** 18 rolling deposits from 4 of 4 cascade seats, every one carrying provenance; the reap cost the retro almost nothing. **María, cross-examined, refused the causal version**: *"with one run I cannot separate 'a mechanism made it hold' from 'four diligent seats made it hold.' Diligence is the confound and we did not control for it."* Accepted verbatim — headline the receipt, drop the causation.

**R-1b — two runs now point the same way, on different tiers.** 2026-07-27 measured the *teardown-time* deposit (memento element 9) → 1 of 6. 2026-08-01 measured the *during-run* deposit → 4 of 4. Consistent with `post-game.md` §3.4 ranking tier 2 above tier 3, and the first positive control that ranking has. Still not a controlled comparison — the seats differ.

**R-1c — PENDING RICK.** The 2026-07-27 ruling R1 (*"every stand-down instruction must name element 9"*) is a *"remember to do this"* rule — the anti-pattern `post-game.md` §7 names by name. Proposal: demote it to a backstop under a headline of *rely on the during-run deposit*, the same demotion §3.3 applied to the reap gate. **Not applied — and the decision row was RETIRED the same evening** (`20efd445`, dropped). Rick: *"explain or retire."* The honest explanation is that it should not have been minted. The post-game workflow says open threads become store items rather than sitting in prose; I applied that to an *observation*, which already lived in two better places (the retro and the corpus README standing note). The result was a row that **read** as owed work while nothing was blocked on it and nobody was doing the wrong thing.

It also failed the bar I had just set for everything else in the same retro: both pattern candidates stay candidates until **cross-day** recurrence, yet I routed this one — two runs, different tiers, diligence uncontrolled by María's own refutation — to the operator queue anyway. Applying my own bar retires it. The July rule stands as a belt beside today's suspenders; keeping both costs nothing, and a third run re-surfaces it with evidence attached.

**R-2 — Candidate 1 (an artifact belonging to no section goes un-updated) stays a CANDIDATE at four instances.** Tiberius 👑 refuted the promotion *from his own deposit, before anyone asked*: "count causes, not symptoms before you let evidence promote a rule." María: "Nothing moves it. Four instances, one cause, one run." A reaped seat winning an argument with a live manager is what the provenance field is for.

**R-3 — Candidate 2 (a close check scoped to its author's own conditions) stays a CANDIDATE, and María's self-contradicting crew brief is NOT folded in to reach two.** Her ruling: same *family*, different *mechanism*; folding it in inflates the evidence. What it adds is a second author and a different engagement. **Promotion bar: cross-DAY recurrence.**

**R-4 — on "0 rejected across 51 findings": the asymmetry is the finding, not the zero — now supported by a sample of two.** Tension was real on the manager axis (reviewers refuted the manager 4×; two reviewers disagreed substantively; one retired her own concern on evidence) and absent on the author axis (51 for 51 conceded, never once defended). María supplied the discriminator — *"was any ACCEPTED finding wrong? Nobody re-derived one"* — and it was run rather than argued: two accepted findings re-derived cold, both hold at the exact cited lines (`emit_to_session` has no `return` statement at all; the ORM partial-index prior art sits at `postgres_models.py:227-231`). **2 of 51 is a spot check.** Hypothesis → supported, not proven.

**The day's through-line, from the design under review straight into the review of it**: *a value that cannot distinguish "I know" from "I don't know" was used as a gate.* A send read as a receipt · a stored default read as a given answer · "returns nothing" read as a proof · "the same ledger" read as one process · a headline count read as its own tables. **The manager reported ~70 findings upward all afternoon against a true 51 — and the moderator of this very post-game announced 20 deposits against a true 18, one hour after reading a memento whose headline finding is that exact defect.** Both corrected in flight and left visible rather than scrubbed.

---

## ⏳ PENDING — 2026-08-01 (Cheech 🌿 `070d88a5`) — podcast E2E blocked on container Claude Code re-auth

**Status**: OPEN, needs Rick first thing in the morning. Store row `bff6bc6c` (bug, owner `rick`, next_chase 2026-08-01 06:45 UTC).

**What shipped tonight (done, no action needed)**: podcast generator hosts renamed Nora→Maria, Quentin→"Mr. Radio" across config/code (commit `1935089d`, reviewed, 337/337 green), plus a fix so a failed AI call now fails loudly instead of faking an empty script (commit `419174ed`, reviewed, 30/30 green).

**What's still blocked**: the `lupin-rest-dev` container's Claude Code login is revoked (401 "OAuth access token has been revoked"). Rick ran `claude auth login` once tonight — `claude auth status` reported success, but a real call still 401'd immediately after, so the login didn't actually take. **`claude auth status` is unreliable in this container — verify with a live call** (`docker exec lupin-rest-dev claude -p "reply PONG"` and confirm it actually returns PONG), not just the status field. Until this is genuinely fixed, no bounded-CC job (podcast, BFE, TFE, deep research, presentation) can run in that container.

**Next step**: Rick re-authenticates, verifies with the live-probe method above, then re-run the real podcast job against `src/rnd/v0.1.9/2026.07.19-brevity-mandate-injection-riders.md` to get the actual rendered episode with Maria/Mr. Radio dialogue.

---

## 📋 DECISIONS LOG 2026-07-31/08-01 (Mr. Radio 🦉 `7846bfcb`) — DM Quality Judge toggle standing ON

**2026-08-01 — Rick: `dm quality judgment enabled` is standing ON, not the usual one-DM-then-revert.** Verbatim: "flip the toggle to true I want the judge to grade DMs. And let's leave it there until I say otherwise." Do NOT assume it's back to the ini-default `False` in a future session — check `src/conf/lupin-app.ini` directly. Live audit (`/api/dm/quality-audit`) was at count=8 when this session ended.

**2026-08-01 — 3 bugs fixed in `DmQualityJudge`, one caught mid-fix.** Maria diagnosed a prompt self-contradiction, a missing unclosed-tag fallback, and a missing garbage-output guard. Her suggested fix for bug 1 regressed live discrimination (verified 3/3); fixed differently (deleted the contradicting prompt line, left the injected example unchanged) and confirmed the regression is gone. See history.md 2026.08.01 checkpoint for the full account.

---

## ⏳ PENDING DECISION 2026-07-26 (Mr. Radio 🦉 `9a63d597`) — `7ee5b646`: the HWM janitor switch

**Status**: OPEN, awaiting Rick. Store row `7ee5b646` (decision, `gate_class=operator`).

**The situation**: the DM-inbox bookmark janitor shipped with `arbiter enable hwm deletion = False`, which **diverges from his "let the janitor drain them" ruling**. I flipped it to OFF after measuring that the plan's safety claim was inverted — reaping a live session's bookmark does not duplicate its DMs, it **silently swallows the un-surfaced ones** (a missing file reads as never-seeded, so the reconcile records the inbox as already-seen and surfaces nothing). That re-creates bug `59f355e0`.

**What Rick decides**: whether to turn it on. The 7-day window is already his ruling and needs no change. Nothing drains until the INI key flips.

---

## 📋 DECISIONS LOG 2026-07-28 (Mr. Radio 🦉 `951a4459`) — the key split, and three rulings

**2026-07-28 — Rick: the two keys get PURPOSE names, and the name was part of the cause.** Verbatim: *"the original was called `notification-api-claude-code-dev`, literally because that was how it was designed to be used — calling the notifications API, by Claude Code, by a developer. That scope has broadened… The key we use to call the model server should be called by its purpose in life: `model-server-api`."* ⇒ **This is a diagnosis, not cosmetics.** `docker-compose.yml:90` read *"Model-server **reuses the existing** … key"* — and that reads as sensible thrift **only because the name doesn't say who the key is for.** Evidence it's right rather than merely tidier: eight of nine credentials in `src/conf/keys/` are named by purpose alone; the outlier carried three claims (API · caller · environment), and `-dev` was **actively false** — the VM, not a dev host, held a file so named. **PHASE 2 (renaming consumer A → `notification-api`) is DEFERRED as its own change**: that name is *generated* by `create_service_account.py`, exists on every host and in Secret Manager, and `outbound_api_key.py:30` holds it as a module constant gating MCP auth fleet-wide. Renaming it beside an outage fix would trade a one-service outage for an all-hosts one.

**2026-07-28 — the mount pin lands in TERRAFORM, never `gcloud`.** I had offered Rick `gcloud run services update` for `6cc52525`. Wrong: `cloud-run-model-server-deploy.sh:10-24` records finding #4 — a second deploy authority produced state drift and a secret mount path diverging from what the app reads. ⇒ **Module DEFAULTS moved too**, not just `envs/test`: that env passed one of three variables and silently inherited the shared key for the other two. **Leaving the defaults would let any future env re-create this bug by omission.**

**2026-07-28 — rotation ORDER is the safety property, and it is what the pin buys.** `_install_api_key()` hashes at BOOT ⇒ new secret version → `terraform apply` → **only then** distribute to callers. Reverse it and every caller 401s until instances recycle. **With `latest` unpinned there is no controlled moment for step 2** — instances pick it up whenever they cold-start. ⇒ The real argument for pinning is not "prevents silent drift", it is **"makes the re-hash an event you can schedule."** *(Recorded because I moved the client before the server on dev and broke embeddings for a few minutes — the exact ordering, violated by the author of the warning.)*

**⏳ STILL OPEN — Rick's, deliberately not assumed**: the model server holds **one** hash, so every rotation is a hard cutover with a disagreement window. Accepting **two** hashes during a rotation window removes it, at the cost of a second live key to revoke. Written so it stays an additive change to `_install_api_key`.

**⏳ STILL UNRULED — crew posture.** Asked twice on 2026-07-27, answered oppositely (`860c57ee` "cap the crew at us two", `bf033a65` "let it run"), then settled by Rick as **"Neither — ask me again when I am not being asked four things at once."** ⇒ **No spawning until he rules.** An automated heartbeat "staff up this tick" does not launder that into authorization.

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
