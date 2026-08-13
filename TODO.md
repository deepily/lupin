# TODO

## ⚖️ RULED 2026-08-12 (Rick) — ship the tutor FLEET-WIDE; the teaching question stays OPEN

**The ruling**: *"Let's ship the tutor fleet-wide and leave teaching open."* Take the word saving now
— it is certain and needs no experiment — and stop trying to buy the teaching answer in the same move.

**What ships**: the tutor on every DM at the ruled trigger of **>6 claims**, runtime-configurable, **no
output gate** (also runtime-configurable, default off). Expected: the average DM goes from ~8 sentences
/ 123 words to **4 sentences / 62 words — half of every word the fleet sends**, on ~1,634 calls per
2,951 DMs.

**What is NOT built**: no third arm, no recipient randomization, no assigner, no ledger. The two-arm
`blind`-vs-`rejecting` block is set aside as its **own finished question** — analyse and report it
standalone (does refusing an over-long DM make senders write shorter), never folded into the tutor's.

### 🔓 OPEN — does reading short DMs teach you to write them?

Unanswered, deliberately. **Every cheap route to it is closed**, and that is why it is parked rather
than queued:

- **Before/after against the existing corpus is dead.** María's phase 1 (the sentence rule in global
  `CLAUDE.md` + the spawn rider) shipped 2026-08-12, so any post-tutor comparison confounds the doc
  rewrite with the tutor, inseparably. The baseline is also not untaught — 1,136 of 1,945
  in-experiment rows were sent under the `rejecting` arm, which is itself a treatment.
- **Day-level noise is large** even on the clean slice (blind + legacy `signal_only`, 2,001 rows):
  SD of daily medians **31.6 words**, and only 7 usable baseline days — capping a pre-post design at
  roughly a 40-word MDE no matter how long the "after" side runs.
- **The design that would work** is recipient-randomized, costs ~5 weeks at MDE ~17 words, halves the
  word saving while it runs, and needs `in_reply_to` + `context_epoch` + a disclosure change.
  → `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.12-recipient-randomized-teaching-experiment.md`

**If it is ever reopened**: run it against a **post-doc-change** baseline so the instruction lever is
already pulled on both sides. And note the ceiling — the tutor cannot teach across a re-spin, so
anything durable has to ride the memento or the spawn brief, not the tutor.

### Implementation order when the fleet-wide ship is picked up

1. Wire `rewrite_dm()` into `execute_dm_send` (`dm.py:1008`) — it exists and is fail-closed; nothing calls it.
2. Record **submitted** and **delivered** on the corpus row (`_persist_dm_row` takes one `body_text`, two call sites) plus `tutor_fired` / `tutor_outcome`, recorded not re-derived.
3. Tests to the 100% gate at every tier.

---

## ☀️ FIRST THING 2026-08-12 — resume the DM tutor (Rick's word, 2026-08-11 ~23:15)

**Rick read the implementation record and greenlit continuing.** His words: *"this is insanely
good news… let's return to this tomorrow first thing."* **This is the queued first item; start here
before anything else on the board.**

He also confirmed the short-band result reads as expected, not as a defect: *"obvious that DMs
shorter than 80 words compress the least — no surprise there."* So **the `<80` band's 76% is
understood behaviour**, and the open question below is about whether the tutor should *run* there
at all, not about why it compresses poorly.

**Pick up with the two rulings still owed** (below), then the small open items.

---

## 🌙 EOD 2026-08-11 (Mr. Radio 🦉 `c74141d6`, with María 🌸) — DM tutor agent built, two rulings owed by Rick

### FIRST THING — two things wait on Rick, neither is code

1. **Keep or veto the CDATA prompt line.** The plan said no prompt rewording; I added one requirement line to `dm-tutor.txt`, copied from `dm-compression.txt:34`. **Without it the agent cannot parse any DM whose prose contains an angle bracket** — that killed the first live call (`git show HEAD:<file>`). My argument: it is format plumbing for the standard path, the same category as the `{{PYDANTIC_XML_EXAMPLE}}` marker, not a change to what the model is asked to say. If vetoed, the prompt cannot ride `AgentBase` and that becomes the finding.
2. **His read of the 40 sample pairs** — still owed from earlier, and now the 200-run adds more. Every check we own is structural: slots present, pointer verbatim, word counts. **Whether a rewrite quietly reverses a meaning is the one question no harness answers.** Stamped doc: `/tmp/dm-tutor-samples-2026.08.11-1945.md` (⚠️ `/tmp` is swept nightly; regenerate with `tutor_sample_run.py`).

### What landed

`dm.txt` → `DmTutorAgent` on `AgentBase`, with `rewrite_dm()` as the fail-closed seam Rick asked for
(*"a DMTutor agent object that can be used within the DM send calls"*). 99 unit tests, 100% lines and
branches, full gate 13,529 green, 200-run 387/400 delivered, 250+ band compresses to **17%**.

→ `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.11-dm-tutor-agent-implementation-record.md`

### Open, and small

- **The path checker is too strict.** `pointer in body` fails a value the model legitimately composed from several real paths. Should test each comma/semicolon-separated element and strip a leading label word. Until fixed its `NOT IN DM` count reads as a hallucination rate and **is not one** — all 9 were verified as real literals.
- **The prompt never says "exactly one" pointer.** "The most relevant" gets read as "the relevant ones" on long messages. One-word fix, but item 1 above should rule first.
- **The `<80` band barely compresses** (76% delivered). Worth asking whether the tutor should run on short messages at all — 3.1s to remove a quarter of a 60-word message may not pay.
- **Send-path integration is NOT done.** `rewrite_dm()` exists; nothing calls it. That is the "greater experiment" and was not in this cut.

### Carried, not mine

María 🌸 retracted her own headline on the stop sentinel after seeing n=200 (195 vs 192, floor of 4).
Her probe was not confounded — it varied the sentinel cleanly — but the sentinel and CDATA guard the
same failure, so once CDATA is in place the sentinel has nothing left to catch. **One message cannot
tell you which of two overlapping guards did the work.**

---

## 🌙 EOD 2026-08-10 (Mr. Radio 🦉 `df4207f2`) — pick up here tomorrow

**Two commits, both pushed**: `481f6a8d` (arbiter fleet-loop fix + deploy gate + loop liveness) and `af406cc9` (arbiter venv out of the deploy tree). 121 tests green.

### FIRST THING — one unverified claim

**The VM was powered down mid-check**, so the restart onto the new light venv at `$HOME/.venvs/lupin-arbiter` was never confirmed. Everything up to it passed: provisioning ran clean and its own import gate approved that venv (12 modules, DB closure correctly not required). The unit is enabled, so it should come up on boot.

```
gcloud compute ssh lupin-host-test --zone=us-central1-a --project=hello-world-foo-423219 --tunnel-through-iap \
  --command='systemctl --user is-active lupin-arbiter-app.service;
             journalctl --user -u lupin-arbiter-app.service --since "5 min ago" --no-pager | grep -o "interpreter .*" | tail -1;
             curl -s http://127.0.0.1:8001/health'
```

Expect: `active` · interpreter `/home/admin_rickruiz_altostrat_com/.venvs/lupin-arbiter/bin/python` · `degraded: false` with all four loops `alive`. **That last check is the light-venv proof** — the new venv has never had SQLAlchemy, so a live fleet loop on it proves the gate works in production, not just in a control.

If it comes up on the OLD interpreter, the legacy symlink is winning — remove `/mnt/lupin-data/lupin/.venv` and `/mnt/lupin-data/lupin/.venv-arbiter` (provisioning prints both commands rather than deleting them for you).

### Still open from tonight

- **`live_notify_disabled` at every arbiter boot** — `Environment 'development' not found in ~/.lupin/config`. The VM arbiter cannot send live notifications. Found, not scoped.
- **8 provider keys still absent from the VM** (`openai`, `gemini`, `groq`, `huggingface`, `kagi`, `mistral`, `google`, `anthropic-api-key-firewalled`). Each will fail exactly like `eleven11` did, and only in a log. Worth a preflight check that names them.
- **The deploy still chowns the tree to uid 1001**, a user that does not exist on that box. The arbiter venv is out of the way now; anything else living in that tree is not.
- Row `970002f1` stays open until the pickup check above passes.

---

## ⚖️ RULED 2026-08-07 (Mr. Radio 🦉 `61c3d613`, with María 🌸) — Arm 4 compression: FAILED EXPERIMENT, closed

**Rick's ruling**: *"Let's mark this down to a failed experiment. Even the larger models are unable to compress these messages…"*

**Measured**: 600 live compressions, three runs of 200. **3.0% of DM tokens saved where the economics needed 38%** — ~2,537 tokens/day against the plan's 32,028 (7.9%) — at 49 min/day of added delivery latency, which is a **floor** because recipient fan-out is uncounted.

**What is now excluded as the cause**:
- ~~the model~~ — larger models tried by hand against the committed prompt samples, no material improvement
- ~~the prompt's ratio instruction~~ — arm B named each message's exact target; 3.0% → 3.1%, and mildly counterproductive
- ~~placeholders as *the* cause~~ — density hurts (delivery 28% → 18%) but near-placeholder-free messages still fail 72% of the time

**Still open, and the one experiment that would settle it**: are these DMs compressible *at all* by a free-rewriting model? Most carry code, logs, citations and enumerated findings — material with little redundancy to remove. **The test**: run the compressor on *unfrozen* bodies, compare compression on the same messages, ignore the fidelity loss. Compression jumps → placeholders were the ceiling. Compression flat → the ceiling is the material. **Not run** — ruled closed. → `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.07-arm-4-phase-2-findings-and-recommendation.md` §7

**NOT reverted, and should not be**: Phase 1's freeze protocol. Zero corrupted messages across all 600, and fail-closed is why these numbers can be trusted. Two verify-tier classes caught corruptions a single-tier design would have shipped.

**Prompt samples committed for anyone re-testing**: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/prompt-samples/` — four real DMs, one per band, verbatim prompts plus answer keys for scoring.

---

## 🌙 EOD 2026-08-06 (Cheech 🌿 `72343afa`) — crew harvested, two lanes landed, one design awaiting Rick

**Committed tonight**: Rio ⚡'s two lanes (`9c5dccd4` spawn-failure reason + dry-run tmux probe; `d5ecb753` presentation timing clamp now disclosed rather than reported as a measurement) and Tiberius 👑's `69fb89cd` polluter #1 fix. 365 targeted unit tests green; both worker lanes reviewed before staging. Crew reaped, memento verified on disk.

**Awaiting Rick's word** — the Mon–Sat three-arm week design (`2026.08.06-three-arm-week-design-for-ratification.md`). Nothing starts on it until he rules.

**New row** `0ab3c0cd` (P2) — the brief-length probe's bash half is `skipif`-gated on tmux, so it ships green and unverified on a box without tmux; and the probe's session name is shorter than the real spawn's, so the assembled command it measures is not the one that runs.

**Still open from tonight**: `69fb89cd` polluter #2 · `c9d3ddcb` ungated in-tree CoSA suite · `35d0a451` est_tokens omits refused drafts (bites Saturday's cost line).

**Left dirty, not mine**: María 🌸's arm-4 compression plan docs; `notifications.html`/`.js` (owner unknown, already dirty at 14:48).

## ⏳ SATURDAY 2026-08-08, after 19:00 EDT (Cheech 🌿 `72343afa`) — DM pilot final pull: report POOLED **and** Tue/Wed-only, side by side

**Rick's instruction, 2026-08-06 evening**: capture this before the tokens run out. 🤣

### The task

When the last extension slot closes **Sat 2026-08-08 19:00 EDT**, run `analyze_arms.py` on the
complete corpus and publish **two** sets of numbers, not one:

| Report | Days | Answers |
|---|---|---|
| **Pooled** | 08-04 → 08-08 (all five) | the best-powered estimate available |
| **Tue/Wed only** | 08-04, 08-05 | what the pilot said *before* it was extended |

### Why both — this is the point, not a formality

**The extension was authorized after the interim result was seen** (Rick, 2026-08-06 ~18:10).
That makes the stopping rule data-dependent, which is the classic way to manufacture
significance by accident. Publishing both is the defense:

- **They agree** → the extension tightened a result already pointing the same way. It sharpened
  the finding rather than creating it.
- **They disagree** → *that disagreement is the finding*, and the pooled number must be read
  with real suspicion.

Say plainly, in the report itself, that the extension was added mid-flight. Do not bury it.

### Contents

1. Both co-primaries (all attempts · first attempts only), exact p-values, ±46-word null band —
   pooled and standalone. **The estimator does not change**; nothing was re-specified after looking.
2. **Usable clock-hour pairs, pooled vs standalone.** This is where the extension earns its
   keep: it was **5 of 14** at extension time, with nine buckets one-armed or empty. The
   analyzer pools all days into 14 clock-hour buckets, so extra days fill gaps rather than
   raising the ceiling.
3. Cost / break-even recomputation against the Wednesday midpoint (46.4k est-token rewrite
   spend, 30.8% required vs 23.8% observed — **losing at both bounds**).
4. Row `35d0a451` still open: `est_tokens` omits refused drafts, so rewrite spend is
   understated — which pushes the loss further, not back. Quote it as a floor.

### ⚠️ Separate the blocks BY DATE, not by a field

`slot_id` carries the date: `2026-08-04*`/`08-05*` = original, `08-06*`/`07*`/`08*` = extension.
**The `block` field is `null` on every row** — it lives in the schedule JSON but
`dm_experiment._parse_slots` drops it (builds the slot dict from `slot_id`/`arm`/`local_hour`/
`start_utc` only). Deliberately not fixed mid-run: it would need a bounce inside a live slot and
would split the extension into rows-with and rows-without.

### ⚠️ Volume is the risk, not the schedule

The pilot measures DMs between **working** sessions. Volume tracks headcount: 13 senders → 962
rows Tuesday; 8 senders → 71 rows Thursday after the crew was reaped. The 19:00 slot Thursday
produced **one** row in its first 16 minutes, and that row was mine. **If Fri/Sat are quiet,
say so plainly** — "the extension was armed correctly and the fleet was idle" is a coverage
result, not a null result, and the two must not be reported as the same thing.

**Docs**: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.06-dm-pilot-schedule-extension.md`
(extension + caveat + §6a first-row confirmation) ·
`…/2026.08.06-three-arm-week-design-for-ratification.md` (Monday, awaiting Rick's ruling)

---

## ✅ RESOLVED 2026-08-06 (Cheech 🌿 `72343afa`) — the 08-05 "not diagnosed" quiet-corpus question, answered

The MIDPOINT entry below asked whether the stalled corpus was a **quiet fleet** or a **stopped
writer**, noting the two *"look identical from inside the corpus."*

**Answer: neither — the SCHEDULE EXPIRED.** It declared 28 slots covering Tue 08-04 and Wed
08-05 only, ending 2026-08-06T03:00Z. Outside a slot, `assignment_at()` returns `None` **by
design** and the row is written untagged. The pilot stopped accruing while traffic kept
flowing; the fail-safe worked exactly as specified.

⇒ **The distinguishing check is one line**: group the corpus by day **and by experiment tag**,
not by day alone. A coverage report that cannot say "zero tagged today" is not a liveness check.
Extended through Sat 19:00 EDT and confirmed producing (first tagged row 19:16, arm `blind`,
slot `2026-08-06T19`).

## ✅ SUPERSEDED 2026-08-05 morning (Mr. Radio 🦉 `2c3c8645`) — the crash was diagnosed and fixed the same night; this block was written before that and never updated

**What this block said**: *"Status at hand-off: NOT DIAGNOSED."* **That was true when written (~23:1x EDT) and false 15 minutes later.**

**The crash** (`pr-62254a7f`, 03:08:31 UTC — *"Outline generation returned no usable entries"*) was the plan-mode twin: `PRESENTATION_PERMISSION_MODE` was still `"plan"`. Fixed in `f67189c3` (committed 03:15:41 UTC), deployed at the 03:14:57 UTC bounce. **Proven fixed**: `pr-c07dbd3d` ran 03:20–03:30 UTC — 15 slides, PPTX 4844KB, `pres-56183c6e`.

⚠️ **But the proof came through the CARD path only.** The Q&A-card path failed 7 minutes *before* the fix deployed and has never been retried on fixed code — the two paths were never compared on the same code. **That gap is the live P0**, not the crash.

**Today's two P0s (Rick, 2026-08-05)** — SWE crew live: Tiffany 💍 Tester · Clayton 😎 Implementer · Rachel 🕊️ Reviewer.

1. **Q&A-card → presentation runs end to end** — Rick: *"I have to have it working for me today so I can hammer out various iterations of the presentation I'm giving tomorrow at noon."* Row `ffd46737` (P1). Spec: `src/rnd/v0.2.0/2026.08.05-qa-card-presentation-path-podcast-only-fences.md`. Three `fuzzy_file_match` features in `expeditor.py` are fenced to podcast only (L388–392 auto-resolve, L388–392 choice card, L422 present-but-unresolvable rescue), leaving presentation's `source` degraded.
2. **User-specified duration + slide count** — Rick: *"It's a 60-minute presentation and there's no way in hell I can cram all of that into 12 slides."* **María owns the architecture**; the crew builds after she and Rick agree. Clayton is on recon only until then.

### 🗳️ RULING 2026-08-05 ~11:37 EDT (Rick, on a 4-option menu with pros/cons) — build the two content fixes, hold the third

**His words**: *"Let's do both context fixes per your recommendation and hold the third for now. I'd love to have this working but I don't think I'm going to demo file matching for presentation jobs. I definitely want to implement it though, so perhaps later make note of it — but not now."*

| Item | Ruling | State |
|---|---|---|
| **Raise the 30,000-char source clip** → one shared INI ceiling, all 3 sites in one commit (`narrative.py:178`, `elaboration.py:171`, podcast `script_generation.py:262`) | ✅ **GO** | Clayton building |
| **Land the dropped `audience_context`** (`job.py:249-256` copies 4 args and skips it; `config.py` has no field) | ✅ **GO** | Clayton building |
| Generalize the expeditor podcast-only fences | ⏸️ **HELD — not dropped** | Row `5bc22180`; proposal written + Rachel-passed, needs only a GO |
| María's T1/T2 (explicit slide count; the *"close to 12"* vs *"exactly 15"* prompt contradiction) + T2b drift warning + Gate-1 `human_feedback` | ✅ **GO** — Rick ruled directly to María at 11:38, **Scope B: soft target with a drift warning, not hard exactly-N** | **Cheech 🌿** owns the build (spun up by Rick, outside Mr. Radio's crew). Doc: `src/rnd/v0.2.0/2026.08.05-presentation-slide-count-control.md` |

**⚠️ Two crews, one file — ordering ruled 2026-08-05 ~11:43 (Mr. Radio).** Clayton and Cheech both change the **signature of `get_narrative_analysis_prompt`** (his configured source-ceiling param; her `human_feedback` + budget param). A genuine conflict, not line-proximity: git merges lines 153-156 and 178 quietly and leaves callers half-updated, so **it fails at call time, not at merge time.** **Clayton lands first; Cheech rebases**, doing all of T1's plumbing outside `narrative.py` first and touching that file last. Rachel gates both and re-derives the complete call-site set at HEAD each time.

**Scope grew to FOUR clip sites, ruled on evidence.** Clayton flagged a 50k twin at podcast `script_generation.py:198` rather than silently widening; Rachel pre-read it independently and reached the same verdict — an arbitrary literal with only boilerplate justification, same shape as `:262`. Folded in, because leaving a known 50k clip two functions above the 30k one we were fixing would have been *us* creating the fix-one-twin pattern, knowingly, in the same commit. Final: **2 presentation (30k) + 2 podcast (50k analysis, 30k script) → one neutral key `agent source content max chars`, `[Lupin: Baseline]`, default 200000.** The commit must state that both podcast clips **changed number** — a silent unification is a behaviour change wearing a refactor's clothes.

### ✅ LANDED 2026-08-05 12:40–12:44 — both authorized fixes, verified before announcing

| Sha | What | Verification |
|---|---|---|
| **`934b364b`** (Clayton 😎) | Shared ceiling `agent source content max chars = 200000` replacing bare literals at **all 4 clip sites** (`narrative.py`, `elaboration.py`, podcast `script_generation.py` ×2) + `audience_context` onto `PresentationConfig` + all 4 `getattr` defaults → explicit access | 15 files, 215/37. Zero `target_slide_count`/`_slide_budget` additions. Isolated-worktree touched-tests **247/247**. Rachel PASS 6/6 at the committed bytes |
| **`f41aa1fe`** (Mr. Radio 🦉) | `d55f2f87` — **24 disambiguation tests were gate-reachable by nobody**, and the gated suite had *zero* choice-card coverage. Moved into the gated suite, not allowlisted | 24 pass in new location; census **31 passed** (was 1 failed). Pure rename, no production code |

| **`8de931f8`** (Cheech 🌿 / María 🌸 spec) | T1/T2/T2b — author-set `target_slide_count` overriding the duration formula, across INI/CLI/REST/voice; `_slide_budget()` collapsing three duplicated sites; drift warning gated on an explicit count; Gate-1 `human_feedback` param | 14 files, +352/−9, **zero** foreign content, index empty. 696 passed on the committed sha |
| **`54421d01`** (Mr. Radio 🦉) | **Seven R&D docs were untracked** while the code they specified was landing — including María's spec, the governing document for `8de931f8`. Caught by Cheech verifying her own commit | Docs only. Index verified empty before staging, contents after |
| **`c6f7b45f`** (Clayton 😎) | The two podcast clip-pins in the **ungated** `src/cosa/tests/` tree still asserted the old 50k/30k literals against his intended change. Now parametric on the **configured** ceiling + a `None`-no-clip companion each | 1 file, 26/5. File 46/46. Whole-tree sweep for old clip literals across **both** test trees: clean |

⇒ **Rick's 77,621-char source now reaches the model in full**, dictated `audience_context` lands, and slide count is author-settable instead of inferred from duration.

**⚠️ The regression that only the full run could find.** `934b364b` shipped red on two tests nobody's gate collected: they live in `src/cosa/tests/`, which **no gate-invocable runner reaches**. Clayton's touched-tests run missed them; Rachel's gate missed them; **only Tiffany's 9,000-test both-roots pass found them.** Second time in one day that tree hid something — the first was the 24 doc-choice tests. ⇒ **`src/cosa/tests/` is a standing blind spot and deserves its own row after the demo.**

**HEAD is now the composed tree** — `c6f7b45f → 54421d01 → 8de931f8 → f41aa1fe → 934b364b → 9b7abc98`, both crews plus both manager commits. Clayton's background both-roots run off `c6f7b45f` therefore **is** the composed-tree unit verification (row `ee679014`), by accident of ordering; Tiffany owns the live end-to-end half.

### 🔴 THE COST OF TWO CREWS ON ONE TREE — worth more than the code

**`git commit --only -- <paths>` commits the WORKING-TREE version of the named paths and IGNORES a clean index.** Clayton's index was verifiably clean (215/37, zero T1 by grep); `--only` bypassed it and re-bundled the other crew's work as `0d390b11`. He caught it himself from a 291-vs-215 file-stat mismatch, `reset --soft`, re-committed as `934b364b`. **The flag that sounds exactly like "commit only my paths" is the one that silently takes the working tree** — and this fleet's parallel-session doctrine actively points people at it.

**`git diff -U0` cannot split two crews' CONTIGUOUS new lines** — hunk boundaries come from the pre-image, so a 61-line pure insertion authored by two people is one hunk with nothing to cut on. The INI split cleanly (13 lines apart, separated by originals); one test file took three rounds. **Class membership is not hunk separability.**

**The rule neither manager had**: *"stage nothing" governs the index; **don't edit inside another crew's unlanded structure** governs the edit.* Perfect staging discipline does not save you from nested authorship.

**Partial staging buys correct authorship at the cost of an untested artifact** — every test ran against a working tree holding both crews' code, while the commit held one crew's. Gate the committed artifact (`git show <sha>:<file>`, read whole), never the dirty tree.

**`LUPIN_ROOT` must point at the worktree for isolated runs** — subprocess tests resolve `__main__.py` and config through it and will false-red off the dirty main tree. Cost Clayton one false red; not discoverable from the failure text.

### 🪞 FOUR FACES OF ONE PATTERN — wrong instrument, not wrong thinking

Recorded for the post-game; **graduation to `workflow/` deliberately withheld** (María's boundary — four faces in one morning from seats all in this room is one day of evidence; the qualifying instance must come from outside).

| Face | What it produced |
|---|---|
| A grep count answering "what matches", not "what breaks if it's gone" | A 16-line delete list that was really 13 — three sat in a method whose removal breaks two live callers |
| `git log --since="2026-08-05 15:00:00"` in EDT | A **future** window that cannot contain anything, returning a confident zero indistinguishable from a quiet branch |
| A grep of `src/cosa/tests/` for tests living in `src/tests/` | An **empty result from the wrong tree**, which reads as "the tests don't assert this" |
| A correct read of a method body, then a cited symbol that doesn't exist | *"The read was real, the citation was invented"* — a fabricated receipt passes every reader who trusts it and fails only the one who greps |

**And the manager's own**: two correct observations of the same repo contradicted each other because a branch pointer moved between them — `0d390b11` went dangling, so `git log` showed one seat nothing while another had read the commit directly.

### 🛟 DEMO-EVE SAFETY — row `ee679014` (P1), raised unprompted 2026-08-05 ~11:47

**KNOWN-GOOD SHA: `9b7abc98`** — recorded **before** the tree moves. It is the last commit proven to produce a deck end to end, twice: `pr-a10a55aa` (Q&A path, PPTX 5,462 KB) and `pr-c07dbd3d` (card path, 4,844 KB). **If 2026-08-06 morning is broken, this is the number to go back to.** Reconstructing "what was good" from a git log at 9am on demo day is not a plan.

**The gap nobody owned**: two crews land 4+ commits into the presentation path today. Each verifies its own diff; Rachel gates each. **Nobody measures the tree they jointly produce** — the same shape that has burned this fleet all week, a green measured somewhere other than where it has to hold.

**Countermeasure**: after BOTH crews' commits are in and both passed, Tiffany runs **one live end-to-end pass on the composed tree** — freshly bounced, served bytes verified, whole user-observable chain (submit → expeditor → arc → outline → elaborate → render → PPTX). Acceptance: a finished PPTX **plus** the tail-reached probe green, which is what proves the ceiling took effect end to end rather than only in a unit test. It belongs to neither crew; it belongs to the manager.

**Verification trap recorded (Rachel → María, step 6): the slide-count run must be LIVE, never `--dry-run`.** Dry run mocks every LLM call (`job.py:_execute_dry_run`, mock outline at `orchestrator.py:804-830`), so it returns the *mock's* count and measures the harness instead of the model — a green that proves nothing about the thing under test.

**The reasoning that split them**: fixes 1-2 change what the **model** sees — a better deck, with no change to the flow Rick rehearses tonight. Fix 3 changes what **Rick** sees, the day before he presents. Same low risk, different exposure.

### ✅ P0-1 CLOSED — the Q&A-card path runs end to end

`pr-a10a55aa` (Tiffany 💍, `:7999`, current code, test user): **PPTX 5,462 KB, 15 slides**, full chain expeditor → outline → elaborate → YAML → Marp → 14 visuals → export. **Phase 3 — the step that killed `pr-62254a7f` last night — cleared in 22 seconds.** Writeup: `src/rnd/v0.2.0/2026.08.05-qa-presentation-path-e2e-verification.md`.

### 🔍 What the morning found that nobody was looking for

- **61% of Rick's source never reached the model.** His outline is 77,621 chars; the clip is 30,000, in *both* the arc and content phases. Every deck he has generated from it was built from the first 39%.
- **`audience_context` is silently discarded.** He dictated *"presenting to forward deployed engineers at Google"*; it was stored on the job and never copied to the config the orchestrator reads.
- **The same clip exists in podcast** (Rachel found it) — so the fix uses a shared key and podcast becomes a one-line follow-up instead of next month's twin-miss.
- **The two prompts contradict each other**: narrative says *"close to 12"*, outline says *"exactly 15"*. No test covers the formula at all.
- **Gate 1's "Revise" is a no-op** — feedback is stored but the prompt builder has no parameter to receive it, so it re-rolls the identical call and burns a revision.
- **Two same-named files** — `src/rnd/…` at 48,473 and `io/deep-research/…` at 77,621. That collision produced a real disagreement between two seats' measurements; cite the full path or measure the wrong document.

**The lesson this block earned**: a status line records what was true when written. This one sat at the top of TODO.md all night asserting "NOT DIAGNOSED" about a bug that was fixed, committed and verified before midnight — the same defect `history.md`'s own header names about its health stamp. **Nothing re-derives a stamp.**

---

## 📋 DECISIONS LOG 2026-08-04 evening (Mr. Radio 🦉 `7802a03f`) — the demo works; scope for the last two days

**D6 — Verify only before Thursday; change no code.** *Ruled by Rick, 20:5x EDT, on a menu with pros/cons.*
Rick's podcast ran end to end and he listened to it — the demo path is proven once, by hand. Remaining work is split into *verify* and *fix*, and only verify is authorized. Two runs go ahead: `3171c9dd` (the demo path through the automated harness — repeatable proof, not one good run) and `68198c9f` (a **vague** file description, the closest thing to how Rick will actually speak on stage). **The error-string fix `e0bb5a94` is explicitly NOT taken**, though it is small and genuinely valuable — it edits the demo path two days out, unreviewed, and today already showed what that costs. **Why**: today's failures all shared one shape — a green measured somewhere other than where it had to hold. More measurement helps; more change does not.

**D7 — Spawn one fresh reviewer for the adversarial read.** *Ruled by Rick, same sitting.*
`a4521768` has sat untouched all day; its owner Rio was reaped and nobody has ever read the demo path hostilely. Rick chose a **fresh** worker over me doing it — correctly: I got the routing safety-net wrong, reported audio rendering after the job had died, and had Spanish backwards an hour earlier. **Scope**: demo path only, findings and evidence, **no fix proposals** — which keeps it inside D6. Anything it finds is Rick's call, not an automatic change.

**D8 — Spanish stays off, and the reason on record was wrong.** *Correction, Rick 2026-08-04.*
I wrote in `lupin-app.ini` that English-only was about "doubling the work and adding a failure surface", and told Rick restoring Spanish was one config line. **Both were wrong.** The real reason is bug `0913bb90`: the translation step intermittently returns the **English** text unchanged, and two masking layers shipped it as a fake `es-MX` podcast — Rick got two English podcasts. Krishna's fix makes that **fail loud**; it does **not** make translation succeed, and the distinguishing run that would size how often it fires was deferred and never executed. So the odds are unmeasured. The config comment has been rewritten to say so. **Gates on Spanish**: fix `0913bb90`'s root cause, then run the N=5 distinguishing run.

**D9 — The disambiguation card ships, and D6's "change no code" is superseded for it.** *Ruled by Rick, ~21:33 EDT, after a traced walkthrough.* Watching the path where two files both match "the KISS protocol", Rick asked what happens — the answer was a blank *"Which document should I use?"* with the candidates known and thrown away, because auto-resolve accepts only an exactly-one result. His words: *"if that works, it would be a very compelling demo of disambiguation"*, with the binding constraint *"a standard multiple choice UI that is used for all other lists of options. We want maximum reuse of code."* Shipped as `2d6de739`. **D6 still governs everything else** — this is one named exception granted explicitly, not a general re-opening. **Why it was safe to take two days out**: it was reviewed before a line was written (which caught a real defect in my plan), gated behind a caller-passed flag so the presentation path is untouched by construction, and proven by a live run that captured the card off the WebSocket rather than by unit tests alone.

**D10 — English-only is FINAL for Thursday.** *Ruled by Rick, 22:2x EDT, on a menu with the measurement option offered and declined.* Ratifies D8 with one thing D8 did not say: there are **three** outcomes, not two. Beyond real Spanish and a visible "Translation Failed", a valid parse whose segments are still English **ships silently as a normally-titled es-MX script**, because nothing compares the translation to its source. Rick declined the N=5 distinguishing run rather than spend the night sizing a risk he had already decided not to take. **Gates on Spanish unchanged**: fix `0913bb90`'s root cause, then measure.

---

## 📋 DECISIONS LOG 2026-08-04 (Mr. Radio 🦉 `7802a03f`, five-worker crew) — Thursday demo: the line was refuted, replaced, and the root cause found

**D1 — Chase a wording fix AND a code fix in parallel.** *Ruled by Rick, 12:43 EDT, on a menu with pros/cons.*
The demo line `"make me a podcast on KISS"` routed correctly and then **crashed** — `FileNotFoundError: Research document not found: KISS`. Rick declined to bet on either fix alone. Rachel took the wording lane, Clayton the code lane. Both landed. **The wording fix won the race**, so the code fix stopped being the critical path and became durability.

**D2 — Prosody: file it, do not touch the audio path before Thursday.** *Ruled by Rick, 12:04 EDT.*
Rick asked for the translation to preserve prosody cues. Investigation showed the request pointed at the wrong layer: translation **already** preserves them (148 verified in the Spanish text), and the **text-to-speech engine strips every marker before synthesis, for every language including English**. So the cues have never been audible. Making translation "keep" them changes nothing. Real work is a TTS change; deferred rather than touching the one component whose failure means no podcast at all.

**D3 — HOLD the `topic → research` alias drop until after Thursday.** *Ruled by me; raised to Rick to overrule.*
⚠️ **My first justification was wrong and is recorded as such on row `bd0ce120`.** I called it "a behaviour change of unknown risk." Rachel's contrast then showed the presentation pair already does it the correct way — so it is *"match a proven-correct sibling"*, not a novel design. **The hold stands on redundancy** (Clayton's fix already covers Thursday), **not on risk.**

**D4 — Split a landed fix from its unbounded follow-up.** *Ruled by me, on Krishna's question.*
Closed the proxy-port fix on its receipts; minted the back-contamination audit as its own row. An open row hides that the fix landed, and unbounded forensics does not belong bundled with a one-line change.

**D5 — Closing a latent gap does not outrank the demo.** *Ruled by me, on Tiffany's `:8000` fix.*
Her diff touched the **podcast submit endpoints** — Rick's demo path, two days out, on a row that is not demo-blocking. Ruling: prove a normal submit is identical before and after, or drop those endpoints. She proved it with a **differential** (disable the stamps → only the 2 lineage tests red, all 48 normal-submit paths identical either way). Kept in the pass.

### 🔎 THE ROOT CAUSE, and it traces to a bug we fixed the same morning

The podcast command's **1200 training rows all emit a topic; zero emit file paths.** The registry then aliases that topic into `research`, **a file-path argument**. So the extractor did exactly what it was taught, and the registry put the answer in the wrong slot.

It was **trained as "podcast from a topic" — the old, inverted label — and implemented as a file reader.** The label inversion fixed at 10:58 was never cosmetic; it had already propagated into the training data. The crash was that same mistake surfacing at runtime, hours after we thought we'd fixed it.

**Scope checked, not assumed** (Rachel): the presentation pair is clean — 879/1200 real paths, no topic alias. **Isolated, not systemic.** A negative result worth as much as a positive.

### 🪞 THE PATTERN THE DAY KEPT REPEATING — worth reusing

**Five separate claims today were measured somewhere other than where the thing has to work**, and every one read as green:

| Claim | Measured where | Where it had to hold |
|---|---|---|
| "Resolves to Rick's file 3/3" | The matcher, fed directly | The live flow — where the matcher is never called |
| "473 tests pass" | A subset | The merge |
| "21,562 passed" | An earlier run | The committed code |
| "Prompt auto-submits after 5s" | A config field | An observed submission — there was none |
| "Spanish loses its cues" | A metadata list | The translated text — the cues were there |

Three of those were mine. The countermeasure that actually worked, every time, was **someone re-deriving the claim from the other end** — Rio refusing a subset, Clayton reading the consumer, Tiffany finding her own harness in the logs, Krishna retracting his own report.

**Standing rule adopted from this**: a receipt must name **which run produced it**, and a "probably fine" gets answered with a differential, not a paragraph.

---

## 📊 MIDPOINT 2026-08-05 evening (Cheech 🌿 `f8754825`) — DM pilot: the break-even moved, and the bounds stopped bracketing zero

Doc: `src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.05-dm-two-arm-pilot-midpoint-status.md` (sequel to the 08-04 break-even doc, now a sibling in the same subdir).

| | Tuesday | Tue + Wed (partial) |
|---|---|---|
| required first-try reduction | 22.4% | **30.8%** |
| observed | 26.8% | 23.8% |
| full-credit bound | −3,147 tok (saving) | **+10,558 tok (loss)** |
| no-credit bound | +16,115 tok | **+46,421 tok** |

The observed gap barely moved; the **requirement** rose, because rewrites nearly tripled while first tries not quite doubled. Behaviour still moves and reads as restraint (157.4 → 126.3 words/attempt; co-primary B answerable at last, n=5, same direction as A) but nothing is significant — p = 0.375 / 0.438 on a ±46-word null band.

**Two things a later seat should not have to rediscover**: the effect is in **words**, every cost figure is in **chars÷4 est-tokens** (never a tokenizer), and they are not interchangeable. And bunching in \[140,149\] went 4.4% → 11.1% — senders steering *to* the threshold, not away.

### ⏳ Still open on this row

- ~~**Wednesday is 7 of 14 slots**, and no rows have landed since 16:10 EDT. **Not diagnosed** — quiet fleet and stopped writer look identical from inside the corpus.~~ ✅ **ANSWERED 2026-08-06 — the schedule expired** (28 slots, Tue/Wed only). Neither candidate was right; see the RESOLVED entry at the top of this file.
- Row `35d0a451` (published metric omits refused drafts) is still queued — today's data widens the gap it describes (published −33.2% vs all-in +7.4%), so quoting either figure alone is now more misleading than it was Tuesday.

## 📋 DECISIONS LOG 2026-08-03 (Cheech 🌿 `2c73cb48`) — DM verbosity pilot, live-gate verification

**D1 — Prove the reject path with a real schedule slot, not the arm override.** *Ruled by me on Tiffany 💍's refutation, 2026-08-03.*

I planned to pin `dm experiment arm override = rejecting` and bounce. Tiffany refused to run it and cited `dm.py:1037`: the gate executes only when `assignment_at` returns a slot, and `override_arm` **re-labels a matched slot — it cannot create one**. Outside the Tue/Wed window `assignment_at` returns `None`, so the smoke would have returned an ordinary 201 and I would have called the gate proven.

Chosen instead: a temporary `rejecting` slot dated **2026-08-03** (outside the pilot window, so its rows can never enter the Tue/Wed analysis), live for the smoke, then removed and the mirror re-verified from the live policy. Rejected: forcing the override active in code (a code change to prove a code path), and shipping on the in-process tier alone (no live proof before go-live).

**Why it matters beyond this row**: an override that only re-labels looks identical, from the caller's side, to one that arms. The distinguishing evidence was in the source, not in the response.

**D2 — Exclude `TEMP-` slots in code, not by remembering to delete them.** *Ruled by María 🌸, adopted 2026-08-03.*

María did not object to the temp slot; she objected to its containment being **deletion-dependent**. Landed at `analyze_arms.eligible_rows()` — the single chokepoint feeding co-primaries, secondaries and counts — with two unit tests, so co-primaries, secondaries and counts all drop `TEMP-` rows whether or not the slot was ever removed. Same reasoning that put a janitor on the scratch project instead of a "delete when done" rule.

**D3 — Wait out a running job rather than force the bounce.** *Ruled by Rick, 2026-08-03.* `bounce-dev-server.sh` exited 4 on `inflight_agentic_jobs=1` (his podcast job). Options were wait, `--force` (destroys the job), or skip live verification. He chose wait; there were ~11 hours of margin against a ten-minute remainder. The guard's refusal was the correct behaviour and is worth keeping in mind as *the* precedent: a dirty tree is recoverable, an in-flight job is not.

### ⏳ Still open on this row

- **The pilot has not RUN yet.** Build is complete and committed; Tuesday 09:00 ET opens the window. Store row `a3666252` (P1) carries items 7 (in-window audit of both arms) and 8 (23:00 counts) so they survive the tester's seat.
- **Not pushed.** `2c73cb48` and everything before it sit on `wip-v0.2.0-2026.08.03-present-and-demo` with no upstream. Rick's call.
- **`history.md` at 16.0k tokens** — past the 17k warning on the next entry. Next seat should archive.

## 📋 DECISIONS LOG 2026-08-02 (Cheech 🌿 `13459df0`) — embedding regeneration scope + venue

**D1 — Regenerate EVERY row, not the subset that looks wrong.** *Ruled by Rick, 2026-08-02.*

I proposed regenerating only the 79,318 rows whose vectors read norm 1.0, treating the other 209,468 as already correct. Rick's ruling: *"We are replacing all of those values not a segment because they represent the results of embeddings created by two different embedding spaces, two different training sets, two different services."*

**Why my version was wrong, in one line**: a norm measures whether a vector was *normalized*, not which model produced it. It separates OpenAI from local only because those two happen to differ in normalization, and it cannot see any boundary *inside* the local era — a model version, training set, service endpoint, or prose/code engine choice could all change without moving the norm. "Already correct" asserted a provenance nothing had measured.

The invariant is one space, one model, one pass. Partial regeneration leaves a mixed space **and leaves it undetectable**, which is how the original defect survived two and a half months. Scope: 158,666 → **578,364** calls. Selection predicate is now "has source text".

**D2 — The fill runs against `:7999` off-peak.** *Ruled by Rick, 2026-08-02.* Rejected `:8000` (monopolize-mode; a multi-hour fill would block every scheduled test suite, and this is not a test suite) and in-process (conflicts with the standing never-grab-a-GPU rule + GPU-0 pinning). Rick added: measure one batch of 256 first and extrapolate, rather than scheduling against a guess.

**D3 — Unload the other GPU models before the run.** *Rick, 2026-08-02.* GPU 0 is a 24,564 MiB card with **23 MiB free**: 7,416 MiB is the embedding model server itself (must stay) and 16,754 MiB is a vLLM instance (pid 9710) that can be unloaded, taking free memory to ~17 GiB. This invalidated the hardcoded batch budget. Resolved by making the budget adaptive (grows on success, halves on refusal) rather than scaling a constant by a chars-per-MiB rate I have no data for. ⚠️ Open question for the walkthrough: unloading that vLLM may interact with row `357c283f` (router-model 404), which is also a vLLM question.

### ⏳ Still open on this row — nothing is blocked, but nothing writes until these are settled

- **Runtime is HALF measured.** Embedding: 0.41s per 256-batch, ~16 min for all 578,364 — and that measurement found a CUDA OOM on long-text batches that would have killed the run (fixed, `0310aa05` + `d7e02562`). The **DB write side remains unmeasured** — 288,932 UPDATEs plus reads, very likely the dominant term. Measuring it needs the clone rehearsal or a bounded shadow-column fill, both behind the walkthrough.
- **Rollback undecided.** Once swapped, the old vectors are gone unless the shadow columns are kept or a `pg_dump` of the two tables is taken first. Real disk. Needs a ruling before step 5.
- **Full walkthrough not yet held.** Rick's standing constraint: no writes to `input_and_output` "until you and I discuss the entire process from beginning to end." D1 and D2 settled scope and venue; the end-to-end walkthrough has not.

## 🗳️ RULING 2026-08-02 (Rick, via Mr. Radio 🦉 `4829ab05`) — a closed row may now be amended

**Decision**: allow `task_amend` on a terminal row, flagged as a post-terminal addendum. Chosen over adding a `ready-for-gate` status (too much surgery for a P3) and over writing down the process rule (rules get forgotten — this fleet chose a janitor over a "delete when done" instruction for exactly that reason).

**Why it was asked**: a worker self-closes, then the manager runs the gate — and the store refused every write verb on a closed row, so the verdict had nowhere to go. Maria hit it twice in one hour; on row `700a6330` her gate **failed the first pass** and none of that reached the row.

**Landed**: row `3c569786`, commit `310aa290`. The block names the status at write and says it is not a reopening; the event is `amended_post_terminal`. `transition` / `edit` / `correlate` stay refused — a closed row stays closed.

**Not recovered**: the verdicts already lost on `ddcc40c2` / `700a6330` / `49a76406`. The capability now exists to write them late, but they are Maria's to write — reconstructing them from her DMs would put words in her mouth on a durable record.

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

## 🅿️ PARKED 2026-08-02 (María 🌸 + Mr. Radio 🦉) — the mirroring test: is odd phrasing TRANSMITTED between seats, or does each seat drift alone?

**⛔ NOT BEFORE THURSDAY'S DEMO — Rick, 2026-08-02: actionable bug fixes only.** Nothing here is a bug and nothing blocks the demo. Parked deliberately so it is not lost, not because it is next.

**The claim under test.** Drift says each seat degrades on its own. **Mirroring** says each seat learns the register from the last one — which is what would explain a house style that is consistent *across* seats rather than personal to each, and how DMs creep past 1000 words.

**María's test** (she proposes ~1 hour; the corpus is already on disk, nothing to build): pull the coined terms from one week of DMs, count how many appear in more than one seat, and check whether B's first use postdates A's. Shared **and** sequential ⇒ mirroring. Personal **and** simultaneous ⇒ the word dies.

**🔴 ONE CONTROL IS REQUIRED FIRST, or the test cannot fail.** *Shared-and-sequential* is also exactly what you get when both seats read the same source. Our own `CLAUDE.md` coins **WaHH · MoPEP · NoJP · TLH · NoDrama · 3LoL · NoMC C2C · NoAA** — every one appears in multiple seats' DMs, and every one is sequential by construction, because somebody had to type it first. **The test as written scores all of them as mirroring when they are plain instruction-following.**

**The fix is cheap**: exclude any term that appears in a committed instruction file, doc, or broadcast **before** its first DM use. What survives that filter is genuinely transmitted seat to seat — which is the claim. Without it, every result confirms the hypothesis and the run proves nothing.

**Status of the exchange**: María accepted the walkthrough offer and quoted the coherency-drift line into the KISS explainer (Act 13). My reply naming the control is **drafted but UNSENT** — cosa-voice lost its tool bindings in session `1bf47c18` and there is no CLI for `dm_send`. Draft + the walkthrough DM are held in that session's scratchpad; whoever has a live binding can send them, or they go out after a re-spin.

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

## ⏳ PENDING DECISION 2026-07-26 (Mr. Radio 🦉 `9a63d597`) — `7ee5b646`: the HWM janitor switch

**Status**: OPEN, awaiting Rick. Store row `7ee5b646` (decision, `gate_class=operator`).

**The situation**: the DM-inbox bookmark janitor shipped with `arbiter enable hwm deletion = False`, which **diverges from his "let the janitor drain them" ruling**. I flipped it to OFF after measuring that the plan's safety claim was inverted — reaping a live session's bookmark does not duplicate its DMs, it **silently swallows the un-surfaced ones** (a missing file reads as never-seeded, so the reconcile records the inbox as already-seen and surfaces nothing). That re-creates bug `59f355e0`.

**What Rick decides**: whether to turn it on. The 7-day window is already his ruling and needs no change. Nothing drains until the INI key flips.

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

## 📋 DECISIONS LOG 2026-07-15 (Mr. Radio 🦉, session bf549da1) — tmux fleet-killer cascade close-out

- **Cascade `cascade-tmux-fleet-killer` COMPLETE** (the P0 below, EXECUTED): 3 sections × 3 stages, 34 findings (0 foundational, 0 votes, 0 user escalations), ~55 min. Plan final-current on disk; Step-9 revision-handoff doc: `src/rnd/v0.1.9/2026.07.15-cascade-tmux-fleet-killer-revision-handoff.md`.
- **OSQ-1 CONFIRMED (Rick, /plan-decide one-touch, 03:26Z)**: execve kill-tracer ships, ordered LAST in §10 — install-only-on-request preserves the sudo gate.
- **Implementation = FULL SWE-team workflow (Rick, voice, via María relay 03:27Z)**: `/spin-up-swe-team` crew (Implementer + Reviewer + Tester), implementer seat cold-context-briefed on the handoff doc + plan ONLY.
- **OSQ-4 ruled by concurrence**: env-strip sufficient, `-S`/`-L` NOT adopted; AC5 = standing precedence canary. **OSQ-5**: vertex WIP lane orphaned (creator c8a18353 died 9 s after launching its own killer pytest) — cleared for edit+restore; vertex-lane continuity store task `bd0b728b` minted.
- [ ] **v1.N candidate: cascade-tmux-fleet-killer workflow-guidance batch (19 items)** (cascade cascade-tmux-fleet-killer, Manager Mr. Radio 🦉, filed 2026-07-15). Five manager moves ran ahead of the codified playbook (forward cross-section folds under a ratified ownership map · ownership-map-at-ratification · conditional ratify-by-concurrence · carried-items handoff field · probe-before-declare with delivery-clock); full 19-item all-seats index in handoff doc §6. Proposed fold targets: plan-review-cascaded.md §Step 5/§decomposition, common.md §Step 5/§Heartbeat Handling, defaults.md §Severity-tag metadata schema. Source: kind: manager_self_audit_sweep post on cascade-tmux-fleet-killer at 2026-07-15T03:33:43Z.

## 📥 BACKLOG 2026-07-07 PM (Tiberius 👑, session 4e12c586) — post-switchover live-voice E2E pulled off the board (Rick voice order)

**Rick (voice, 2026-07-07 ~22:35 EDT): "push this task item into the to-do queue — it does not belong on the board: ee23fca8."** Store item `ee23fca8` DROPPED with this backlog entry as its durable landing pad. Context: the item was the post-switchover live-voice E2E for `766bb609` (persona voice_id honored per session), blocked on the lane-1 flip; Rick killed the flip the same evening with a global multiplexer-parity verdict ("still ugly, still incomplete for the MVP" — logged HIGH in intake `603d9275`), so the E2E has no near-term trigger.

**Resume-when**: the multiplexer reaches Rick's MVP layout/functionality-parity bar AND the lane-1 flip (multiplexer = live TTS client) actually lands.

**Scope at resume (verbatim from the store item)**: E2E driving ≥2 sessions with distinct voice personas; assert each `/api/get-speech-elevenlabs` POST carries that session's `voice_id` (present→honored) and a persona-less notification omits the key → server default voice, consuming server seam `speech.py:558`. Cite reviewed commit `76946d9a` + merge `a9dd6f41`. Prereq receipt: playback consumer `4f14d38f` is DONE. Also-owed cosmetic sweep bundled in the old item body: `wireTtsPlayback` comment names default voice "(Sam)" but the real default is config key `elevenlabs tts default voice id` — comment-only.

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
- [`todo-history/2026-06-25-to-2026-07-31-todo.md`](todo-history/2026-06-25-to-2026-07-31-todo.md) — 21 sections (2026-06-25 → 2026-07-31), cut at the 2026-08-01 boundary, archived 2026-08-06 (Session 72343afa, Cheech 🌿). Reclaimed ~11.2k tokens. Sections carrying an open-work marker (⏳ 🅿️ PENDING BACKLOG 🔴 P0, or any open `[ ]` bullet) were KEPT in TODO.md regardless of age — this sweep archived by disposition, not by age alone.

⚠️ **TODO.md is still ~27.9k chars-over-4 after this cut, above the 25k limit.** The remaining bulk is this week's decision and finding blocks, which are too live to sweep by date. Closing it further is a disposition question, not an age question — someone has to rule which of the 08-01→08-06 blocks are settled.
