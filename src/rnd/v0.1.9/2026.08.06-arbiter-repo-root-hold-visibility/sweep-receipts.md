# Row 011f1f90 — stray repo-root hold sweep: RECEIPTS (Tiffany, 2026-08-06)

**Owner:** Tiffany 💍 (assigned by Mr Radio 22:03). **Scope:** the **14 lupin-root** holds ONLY.
**Result:** all 14 read in FULL (every key), only-copy content minted + confirmed, then deleted. **0 remain.**
harvey-labs (1) + planning-is-prompting (18) **untouched** — separate Rick go, no bundling.

## Protocol applied per file
Run-time is-parked recheck → read full → mint anything only-copy + `task_get`-CONFIRM the row → then `clear_hold`.
Deletion via the module verb `heartbeat_hold.clear_hold(sid, base_dir=".")`, never raw `rm`.

**Run-time recheck (2026-08-07T02:04Z):** all 14 `fresh=False` / `honored=False` → **none live-parked**, nothing escalated.
`work_owed` was NOT the delete predicate (Mr Radio's ruling) — every file judged on "does anything live ONLY here?".

## Receipts table

| sid8 | persona | cargo keys (non-schema) | live/dead | minted / captured-by | deleted |
|---|---|---|---|---|---|
| 0c0452ff | Clayton | next_action_on_wake | dead | none — superseded (ae7fdc9f done + e0bb5a94 queued); Clayton ruled DROP | ✓ |
| 174025cc | Tiffany | role | dead | none — metadata | ✓ |
| 2c74cbd8 | tiberius | next_chase_ts | dead | none — memento committed 5d5cf224 | ✓ |
| 2dd26e69 | mr radio | crew_wound_down, open_for_tomorrow, honesty_notes, my_board, evidence, role, project | dead | **a89026bd** (Mr Radio — only-copy stage-risk) + committed memento mirror; my_board/open_for_tomorrow = existing rows | ✓ |
| 3d4f89c5 | Tiffany | task_id | dead | none — row 4c49cde4 done | ✓ |
| 4829ab05 | mr radio | deferred_user_gates_see_store, open_findings | dead | none — 1fc7889e done + be56bff8 done | ✓ |
| 5f746e59 | Rachel | held_actions_pending_unpause, paused_by_user, self_corrections, note, lane | dead | none — Rachel ruled NO mint (dedup inverted: e0bb5a94 is the live survivor, d31ed491 done; re-park ae7fdc9f moot/done) | ✓ |
| 6813280b | rachel | accountable_manager | dead | none — metadata | ✓ |
| 6fb9464f | Tiffany | on_resume, done_this_session, role | dead | **a8db5010** (Mr Radio — pilot items 7+8 never ran, only copy) | ✓ |
| 7b5f098e | Rio | task_id | dead | none — row 9f09cba1 done | ✓ |
| 93f75e9c | Cheech | role | dead | none — metadata | ✓ |
| 94da8f37 | Rachel | role | dead | none — metadata | ✓ |
| aaaf2ac2 | arnold | next_chase_ts (null) | dead | none — memento committed 3647ab6f | ✓ |
| acd26ce4 | mr radio | delivered_this_session, do_not_do, open_for_rick, the_headline, unassigned_and_deliberately_so, staffing_note, project | dead | none — 19328449 done + all referenced rows filed; commits/headline historical | ✓ |

## Minted rows to verify exist (Rachel's gate)
- **a89026bd** — "Client decision proxy can auto-answer Rick's gate…" (queued, mr radio) — CONFIRMED via task_get.
- **a8db5010** — "DM pilot items 7+8 never ran…" (queued, mr radio) — CONFIRMED via task_get.

Both were minted by Mr Radio reading the file in full before deletion, per the ruling. No other file held only-copy content.

## Notes
- Deliverable (c) — the "use the VERB, never hand-write the hold JSON" doctrine pointer — landed in `CLAUDE.md` (§ Declaring a hold), authored on this row.
- Optional follow-up (Rachel, not blocking): a one-line cross-ref on e0bb5a94 that d31ed491 was its now-done duplicate. Left to Rachel.
