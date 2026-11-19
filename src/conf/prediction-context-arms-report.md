# Context comparison report

- code sha of this report: e011f7a4a1fd4c6685ec6b73a6443ae9425906e3
- discordant floor: 6 pairs, stated before the run; source: assert_floor_pre_stated refuses a floor under 6 in the dm-rewrite checks
- per-ask files scored on code: Q dfc19edd7, Q+A dfc19edd7, Q+O dfc19edd7, Q+P eb4ca4a1a, Q+H eb4ca4a1a
- generated: 2026-11-19T22:23:05.432912+00:00
- command: `python -m cosa.research.preference_replay.context_arms_report --per-ask-dir /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf --inputs /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf/prediction-context-arms-report-inputs.json --floor 6 --floor-source assert_floor_pre_stated refuses a floor under 6 in the dm-rewrite checks --out /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf/prediction-context-arms-report.md`

## Coverage

| arm | asks | with its section | no context | arm input empty |
|---|---|---|---|---|
| Q | 3608 | 3608 | 0 | 0 |
| Q+A | 3608 | 3567 | 41 | 0 |
| Q+O | 3608 | 2200 | 1408 | 0 |
| Q+P | 3608 | 3585 | 23 | 0 |
| Q+H | 3608 | 2576 | 447 | 585 |

## Reconciliations

- **Window**: All 3,608 frozen ids are scored for every arm; the results use the final window of 1,083 asks, the cut the retune makes.
- **Always-yes**: Always-yes has no answer to a multiple-choice ask. It is compared on the yes/no asks only, and the pooled comparison is not reported.
- **Seven asks differ from the export**: Seven asks have a different context state than the raw export gives, because the export lacks their earlier rows.
- **45 asks lack context**: Of the 45 asks, 5 are newer than the export; the other 40 are an unexplained gap, named and not bridged.
- **Retune finals**: Per-ask correct counts equal the retune finals: Q 392, Q+A 384, Q+O 392, Q+P 358, Q+H 389 of 1,083.
- **Q+P setting is a tie**: Q+P top k 3 ties top k 5 on the tune window, 27.5644 each. The documented tie rule picks the higher threshold, then the smaller k. On the final window k 3 gives 358 and k 5 gives 378.
- **Retune driver differs by arm**: The Q+P and Q+H retunes ran retune_run.py as of commit 560a4e382. The Q+A and Q+O retunes ran an earlier copy. The differences are refactors, and the replay and retune code are unchanged. Krishna's check: arm_scoring at the committed code reproduces 358 and 389.

## Results

| arm | multiple_choice correct per 100 (asks) | yes_no correct per 100 (asks) | vs Q: arm only | vs Q: Q only | vs Q: p | vs Q: verdict | vs always-yes (yes/no only): arm only | yes only | p | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| Q | 4.0 (604) | 76.8 (479) | - | - | - | - | 0 | 19 | 0.0000 | baseline better |
| Q+A | 4.1 (604) | 74.9 (479) | 13 | 21 | 0.2295 | no difference | 1 | 29 | 0.0000 | baseline better |
| Q+O | 4.0 (604) | 76.8 (479) | 1 | 1 | 1.0000 | not decisive | 0 | 19 | 0.0000 | baseline better |
| Q+P | 3.5 (604) | 70.4 (479) | 7 | 41 | 0.0000 | baseline better | 1 | 51 | 0.0000 | baseline better |
| Q+H | 4.0 (604) | 76.2 (479) | 10 | 13 | 0.6776 | no difference | 0 | 22 | 0.0000 | baseline better |

## Against Q by answer type

| arm | answer type | arm only | Q only | p | verdict |
|---|---|---|---|---|---|
| Q+A | multiple_choice | 1 | 0 | 1.0000 | not decisive |
| Q+A | yes_no | 12 | 21 | 0.1628 | no difference |
| Q+O | multiple_choice | 1 | 1 | 1.0000 | not decisive |
| Q+O | yes_no | 0 | 0 | 1.0000 | not decisive |
| Q+P | multiple_choice | 0 | 3 | 0.2500 | not decisive |
| Q+P | yes_no | 7 | 38 | 0.0000 | baseline better |
| Q+H | multiple_choice | 0 | 0 | 1.0000 | not decisive |
| Q+H | yes_no | 10 | 13 | 0.6776 | no difference |
