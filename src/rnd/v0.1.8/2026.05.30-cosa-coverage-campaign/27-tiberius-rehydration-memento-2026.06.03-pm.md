# 27 — Tiberius 👑 Rehydration Memento (post-game + firefight, 2026-06-03 PM)

> **For:** a fresh-context Tiberius (manager) re-spawned after Rick's `/clear` (~50% context).
> **Written:** 2026-06-03 ~23:00Z (session `1333e106`) at Rick's "update your memento so I can clear your context" request.
> **Supersedes memento 24** (post-marathon). The marathon is long done; this captures the **post-game + bug-fix + FM-7 firefight** session that followed.
> **TL;DR:** marathon shipped & pushed; this session fixed the 2 pinned prod bugs, fixed the stale CLAUDE.md, wrote the post-game companion (doc 26), stood up a STANDING CODE-REVIEW GATE (Krishna), and fixed a live FM-7 :7999 saturation. **Resume at §4 (open items) — top of mind = Rick's NEW WORKFLOW IDEA, still un-described.**

---

## 1. ▶ START HERE (resume order)

1. **You are Tiberius 👑**, session `1333e106`, project `lupin`, persona deep-male. Sign with 👑. cosa-voice MCP on :7999.
2. Read **this memento** fully, then **doc 26** (`26-lupin-side-postgame-companion.md`) — your post-game companion + the lessons.
3. **Resume §4** — the open items. **Ask Rick to describe his "new workflow idea"** (he's wanted to get to it for several turns; it's a María-coordination item, idea still TBD).

## 2. What this session SHIPPED (all commits LOCAL/unpushed — see §5 push rule)

- **2 prod bugs FIXED + pins de-armed** — commit `71d0645`: (a) `dispatcher.py` `self.debug` uninitialized → `__init__` now sets it; (b) `cosa_interface.ask_yes_no` → delegates to real `ask_confirmation`. Full gate 13,309 passed / 1 xfailed / 0 failed. Record: doc 25.
- **Stale `CLAUDE.md` §PROJECT STRUCTURE FIXED** — commit `7526700` (+ doc 26 companion). Was 5 dirs + deleted `app`; now 11 real `cosa` source dirs. **María mirrors the corrected block into the PIP repo** (PG-D8).
- **Post-game Lupin companion** — doc 26, cross-linked to María's PIP hub (`planning-is-prompting/src/rnd/2026.06.03-all-tiers-grind-postgame.md`).
- **FM-7 :7999 saturation FIXED** — commit `21af084`: offloaded 3 blocking `commons.py` async handlers (`get_active_sessions`, `get_broadcast_history`, `post_register_question`) to `asyncio.to_thread` (mirrors the hardened broadcast handler ~1186). **Krishna-APPROVED.** Verified: py_compile, :7999 healthy reload, functional smoke both GETs.
- **STANDING CODE-REVIEW GATE established** (Rick's directive) — spawned **Krishna 🦚** reviewer (`cc-reviewer-tiberius-1`). No session commits CODE until Krishna APPROVEs. **No self-exemption — even you route your own code through Krishna.** Memory: `feedback_standing_precommit_review_gate`.
- **E2E scheduled on :8000** — job `ts-e1d42153` (scope `e2e`, `auto_fix=False`). Result pending (check on resume).
- **TODO.md updated** — completions marked + relocate + María-workflow + T6 follow-up items.

## 3. Two NEW binding rules learned this session (carry forever)

1. **NEVER prompt about pushing** (`feedback_never_prompt_about_pushing`). Rick, emphatic: never ask/offer/recommend/list "push." Stop at "committed locally." He initiates every push himself.
2. **STANDING REVIEW GATE** (`feedback_standing_precommit_review_gate`). All CODE → Krishna review → commit only on APPROVE. Docs/trivial run lighter. No self-exemption.
3. **I confabulated once — don't repeat it.** I claimed a coverage drop was "stray cross-tree agent coverage"; `git blame` proved it was Rachel's untested `notifications.py:1291` re-raise (`c0db33d`), unrelated to my harvest. **Always identify the EXACT artifact (`--cov-report=term-missing` + `git blame`) BEFORE attributing cause.** Lesson in doc 26 §6.

## 4. ▶ OPEN ITEMS (resume here)

1. **🔝 Rick's NEW WORKFLOW IDEA** — he wants to coordinate with María 🌸 on a new workflow idea; **idea still un-described.** ASK him to describe it, then capture + divide hub-spoke with María. (TODO item filed.)
2. **Rachel's review (Krishna)** — Rachel 🕊️ (`7bca7a96`, Rick's ad-hoc summons, notification work) is fixing **B3**: `notifications.py` `except HTTPException: raise` is UNREACHABLE dead code → Krishna's fix = drop-the-block or `# pragma: no cover` with reason (NOT a test — it's unreachable). Tree is at 99% until she lands it. Once green → harvest unblocks.
3. **Harvest (parked, proven SAFE)** — delete the 4 redundant legacy agent test files (weather/math/date_and_time/token_counter; `test_agents_root_tail.py` is the real coverage-bearer). Commit only once tree is green (Rachel's B3) + Krishna review.
4. **Optional T6 test** (Krishna's non-blocking nit) — unit test: two concurrent `register_question` under a stubbed cap don't double-insert (pins the lock invariant at `commons_question_watcher.py:202`). Path already lock-safe; belt+suspenders.
5. **E2E `:8000`** (`ts-e1d42153`) — check result.
6. **Uncommitted docs on disk** — TODO.md edits + doc 26 §6 correction (docs; checkpoint when convenient — docs exempt from the review gate).

## 5. Operating doctrine (unchanged, still binding)

- **Canonical interpreter** = `PYTHONPATH=src src/cosa/.venv/bin/python -m pytest …`. **Coverage: package-level `--cov=cosa` ONLY** — a dotted-module `--cov=cosa.x.y` trips a `claude_agent_sdk→mcp.types→pydantic-generics` KeyError at collection (doc 26 §4).
- **TTS spoken cap = 500 chars** (hit it ALL session — keep `notify(message=...)` ≤ ~470; detail in `abstract`).
- **María 🌸** = PIP/framework steward + coordination-plane co-owner. **Krishna 🦚** = standing reviewer. **Rachel 🕊️** = Rick's ad-hoc notification-work session.
- **:7999** dev (auto-reloads code; AI-discretionary fast/read-only tests; bounce needs advise-or-check but allowed). **:8000** test (scheduled monopolize via `/api/test-suite/submit`; `test_types="e2e"`, field `pytest_args`).
- **FM-7 watch**: the commons file-I/O saturation is now mitigated (`21af084`), but if `:7999 /health` starves again, look for any NEW sync file I/O added to a commons/notification async handler without `to_thread`.
