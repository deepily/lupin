# Row 011f1f90 — sweep of the stray repo-root holds: live re-verification (READ-ONLY)

**Clayton, 2026-08-06 ~22:00 EDT.** No file deleted or minted — this is the evidence for the go/no-go.

## Authoritative count (my own detector, real root list)
`report_hold_files(base_dirs=_default_hold_roots())` → **33 misplaced** of 37 seen; `location_zone` resolves
to `…/projects-data` (judged, not fail-closed). Breakdown — **14 lupin + 1 google/harvey-labs + 18 pip**.
This matches Rachel's live 33 (her "15 lupin" folds the harvey-labs one into the non-pip group). My earlier
`find -maxdepth 2` under-counted (missed harvey-labs — a separate root; a `.claude/worktrees` hold is
SKIPPED by the sweep, not misplaced).

## Population 1 — lupin repo root: the enumerated **14** (Rick's straight-DELETE ruling)
All 14 are **dead** (no bridge resolves) and **expired** (age ≫ TTL, 57–144h vs 0.5–12h TTLs).

| sid8 | ttl(s) | age(h) | work_owed | persona | cargo hint |
|---|---|---|---|---|---|
| 0c0452ff | 1800 | 58.8 | **True** | Clayton | peer:mr radio bounce-done ping |
| 174025cc | 7200 | 143.6 | **True** | Tiffany | peer:Cheech |
| 2c74cbd8 | 1800 | 72.0 | **True** | tiberius | peer:arnold |
| 2dd26e69 | 43200 | 70.5 | False | mr radio | crew_wound_down |
| 3d4f89c5 | None | 144.3 | **True** | Tiffany | peer:Rachel |
| 4829ab05 | 3600 | 95.9 | False | mr radio | gate store-deferred to 09:00 |
| 5f746e59 | 3600 | 57.0 | **True** | Rachel | paused_by_user |
| 6813280b | 3600 | 77.9 | **True** | rachel | test-run:ts-c54c3113 |
| 6fb9464f | 3600 | 71.8 | **True** | Tiffany | peer commits / pilot-window |
| 7b5f098e | 3600 | 127.2 | **True** | Rio | peer:tiffany re-spin |
| 93f75e9c | 7200 | 70.5 | False | Cheech | none |
| 94da8f37 | 7200 | 98.1 | False | Rachel | none |
| aaaf2ac2 | 3600 | 71.6 | False | arnold | none (overturned+recorded) |
| acd26ce4 | 1800 | 73.5 | False | mr radio | presentation e2e headline |

- ⚠️ **`work_owed` is NOT the delete predicate — REFUTED by Mr Radio 2026-08-06.** It says whether the
  SESSION owed work, not whether the FILE holds content existing nowhere else. Counterexample: `2dd26e69`
  (his own, `work_owed=False`) carried a verbatim STAGE-RISK note in `open_for_tomorrow` — a client proxy
  can auto-answer Rick's gate, "not yet filed as its own row" — the only copy. He minted it as `a89026bd`.
  A cargo HINT (this table's last column) is a sample, not a read.
- None are **live-parked** (all dead) → nothing to escalate under Rachel's is-parked-now recheck. But
  dead ≠ safe-to-delete: the file may still hold the only copy of something unfiled.

## Population 2 — google/harvey-labs: **1** (session 2c9b09b5) — OUTSIDE the 14
A separate repo, not in Maria's enumerated 14. Needs its own scope decision.

## Population 3 — planning-is-prompting: **18** (row cited only 2) — OUTSIDE the 14
Oldest **2026-06-23** (~44 days). Separate, larger population in a **separately-managed repo**. Rick never
ruled on it.

## The fork + the per-population gate (Rachel, with Mr Radio)
- Rachel's protocol: per file, **is-parked-now recheck → mint cargo to a store row → CONFIRM the row exists
  → THEN delete**; escalate any live-parked one; per-file receipt `{sid, cargo keys, live/dead, minted row
  id, deleted}`. Rachel verifies each population's table + that minted rows exist before she passes it.
- Rick's ruling: **straight delete, no archive** — scoped to the **14 lupin only**.
- Tension (only for the 8 `work_owed=True`): minting 6-day-stale **dead-session** owed-work into NEW store
  rows would resurface phantom work the live crew already superseded. "No archive" vs "mint first."
- **No bundling across the ruling boundary** (Rachel): pip 18 + harvey-labs 1 must NOT ride the 14's
  ruling — they need their own explicit go from Rick via Mr Radio.

## RULING (Mr Radio 2026-08-06) — supersedes my earlier work_owed-based recommendation
1. **Read all 14 lupin in FULL, every key** — not a hint sample. Rick's straight-delete stands, but it
   does NOT license deleting UNREAD. `work_owed` split above is data, NOT the delete criterion.
2. **Mint anything unfiled to a store row, CONFIRM the row exists, THEN delete** — per Rachel's protocol.
   Per-file receipt `{sid, full-key read, unfiled?, minted row id, deleted}`; Rachel verifies before pass.
   Already minted: `2dd26e69` → `a89026bd`.
3. **harvey-labs 1 + pip 18** → stay OUT; separate Rick go via Mr Radio. No bundling across the boundary.

**Owner: Tiffany** (assigned by Mr Radio 22:03). Clayton stood down from the sweep; this doc is the handoff.
