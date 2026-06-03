# 24 — Tiberius 👑 Post-Marathon Rehydration Memento (coverage DONE → post-game phase)

> **For:** a fresh-context Tiberius (manager) re-spawned after Rick's `/clear`, at the **post-game** point.
> **Written:** 2026-06-03 ~15:00Z (session `1333e106`), by Tiberius, at Rick's "set a memento so I can reset your context" request.
> **Supersedes memento 21** (which was pre-grind / fleet-spawn gate; the grind is now COMPLETE, certified, and PUSHED).
> **TL;DR:** the CoSA coverage marathon is DONE — `cosa` is certified+ratified **100% line+branch+function**, all commits **pushed to origin**, fleet reaped. You are now in the **post-game-analysis** phase, coordinating with María. Resume at §4.

---

## 1. ▶ START HERE (resume order)

1. **Read doc 23** (`23-overnight-grind-certified-complete.md`, this dir) — the certified-complete record + Rick's full morning-gate checklist. This is the authoritative outcome doc.
2. **Read doc 22** (findings — prod bugs + pollution ledger) and **doc 90** (io_files non-repro watch-note) for detail.
3. **Resume the post-game** (§4) — coordinate with María (PIP steward) on one prioritized writeup, doc-18 pattern.

## 2. What's DONE (committed + PUSHED — origin synced)

- **`cosa` = 100% line+branch+function tree-wide**, certified on the committed tree: 412 files, 38,447 stmts / 0 miss, 11,172 branches / 0 partial; gate 13,300 passed / 0 failed / 2 xfailed (both xfails proven pre-existing — honest 100%, María git-verified). Krishna 8/8 batches, 0 hollow.
- **12 commits PUSHED** to `origin/wip-v0.1.8-2026.05.29-preparing-for-gcp-deployment` (`15827df..da4d296`): 11 grind (`d75bb69`→`e70e02e`) + session-end docs (`da4d296`). Branch synced, nothing ahead.
- **Fleet reaped clean** (Rachel/Cheech/sam/Krishna — `dismiss_sessions(None)`, mementos written, 0 orphans, 0 zombies).
- **Session-end ritual complete**: history.md + TODO.md updated; LoC delta (Jun 2 + Jun 3) computed + CSV at `io/git-loc-delta/`.

## 3. Open items = Rick's gate (NOT yours to do unprompted)

1. **2 prod bugs** — pinned, NOT fixed (prod-logic = Rick's call): (a) `dispatcher.py` uninitialized `self.debug`; (b) `cosa_interface.ask_yes_no` → missing `_dispatcher.ask_yes_no` (Bug #12, strict-xfail-pinned).
2. **Harvest-block deletions** — superseded smoke/`__main__` blocks + redundant shallow legacy agent tests; one consolidated pass.
3. **Global hermetic-config autouse fixture** (FM-21 systemic kill) — design + isolation-verify, else defer (María's verified-or-deferred ruling).
4. **Stale CLAUDE.md §PROJECT STRUCTURE** — `src/cosa/app/` no longer exists.
5. **Optional `:8000` integration/E2E tier** — all-tiers beyond unit; needs Rick's slot.
6. **Hygiene:** `.claude-session.md` (412KB) + `TODO.md` (273KB) badly bloated — dedicated size-management.
7. **Backup** (session-end Step 5) — offered, awaiting Rick's dry-run-vs-write word.

## 4. ▶ NEXT: the POST-GAME analysis (current task)

Rick greenlit a post-game (broadcast 2026-06-03). **Coordinate with María** (PIP, committed+pushed `6b9f5f6`; her global cross-repo LoC roll-up is **held pending Rick's explicit go**). Produce **one descending-priority deliverable** (doc-18 pattern), cross-linked Lupin↔PIP. The lessons to formalize:

**What worked (keep):** disjoint-lane partition (collision-free commits) · per-batch adversarial reviewer-gate · green-before-commit · no-confab discipline (verify-before-catalog; no skip/xfail-to-green; tripwire-pin prod bugs) · harvest-not-reauthor (io_models 215 relocated → 100%, 0 new lines).

**Failure modes → improvements:**
- **Stale planning baselines** (projected ~12k lines, real ~2.3k) → fresh tree-wide `--cov` gap-map as **Step 0** before any spawn.
- **FM-21 cross-test pollution** (config/registry `sys.modules` bleed; isolation-green/full-red; recurred) → global hermetic-config autouse fixture + standing isolation-AND-full-tree gate. **io_files = candidate FM-22** (order/loop-state nondeterminism) — María holds the name until a recurrence WITH a captured `--tb=long`.
- **Classifier friction** (spawn blocked on "do not stop" framing; push blocked — won't accept an MCP-menu answer as authorization) → pre-stage `spawn_sessions` + `git push` allow-rules at campaign start.
- **Keep-alive gap** (no heartbeat poker — owner_id unresolvable while Rick slept; María on manual ~10-min push-ping) → fix the owner_id resolver OR ship the per-instance poker (turn-key self-poke folded into runbook §7).
- **Reap discipline** — I parked the fleet instead of reaping (mis-read "don't stop until I tell you"); reap-when-done is **unconditional** once work is complete.
- **Blank-broadcast bug** — Rick's overnight directive reached the fleet only via María's manual relay (per-session injection dropped the body); the 2026-06-03 broadcasts came through intact (intermittent or fixed).

## 5. Operating doctrine to carry (unchanged, still binding)

- **Canonical interpreter = cosa `.venv`** (py3.11/pytest9): `PYTHONPATH=src src/cosa/.venv/bin/python -m pytest src/tests/unit/ src/cosa/tests/unit/ -q`.
- **TTS spoken cap = 500 chars** (live) — headline + one takeaway spoken; detail in `abstract`; doc-links in `abstract` only.
- **María = framework steward** (cross-session). Coordinate the post-game with her; she ratifies + catalogs FMs.
- **Never auto-push** — Rick's explicit per-act word (he authorized this push by saying "push"; the classifier won't accept MCP-menu picks).
- **Persona-sign** with 👑 (Tiberius). Reviewer this run was Krishna 🦚; authors Rachel 🕊️ / Cheech 🌿 / sam 🎙️ (all reaped).
