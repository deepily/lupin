# Context comparison report

- code sha of this report: 040d1148f735bed3269dc391a15210b35bb4a995
- discordant floor: 10 pairs; source: remediation plan section 6 question 4
- per-ask files scored on code: Q dfc19edd7, Q+A dfc19edd7, Q+O dfc19edd7, Q+P eb4ca4a1a, Q+H eb4ca4a1a
- generated: 2026-11-19T22:31:03.672646+00:00
- command: `python -m cosa.research.preference_replay.context_arms_report --per-ask-dir /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf --side-file-prefix /mnt/DATA01/include/www.deepily.ai/projects/lupin/io/question-vectors/2026.11.19-arm- --notes-file /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf/prediction-context-arms-report-notes.txt --floor 10 --floor-source remediation plan section 6 question 4 --out /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src/conf/prediction-context-arms-report.md`

## Coverage

| arm | asks | with its section | no context | arm input empty |
|---|---|---|---|---|
| Q | 3608 | 3608 | 0 | 0 |
| Q+A | 3608 | 3567 | 0 | 41 |
| Q+O | 3608 | 2200 | 0 | 1408 |
| Q+P | 3608 | 3585 | 0 | 23 |
| Q+H | 3608 | 2576 | 447 | 585 |

## Reconciliations

- **Window**: All 3,608 frozen ids are scored for every arm. The results use the final window of 1,083 asks, the cut the retune makes.
- **Always-yes**: Always-yes has no answer to a multiple-choice ask. It is compared on the yes/no asks only.
- **Retune finals**: Per-ask correct counts equal the finals in the committed retune reports: Q 392, Q+A 384, Q+O 392, Q+P 358, Q+H 389 of 1,083.
- **Q+P setting is a tie**: Q+P top k 3 ties top k 5 on the tune window, 27.5644 each. The tie rule takes the higher threshold, then the smaller k. On the final window k 3 gives 358 and k 5 gives 378 (Krishna's check).
- **Retune driver differs by arm**: The Q+P and Q+H retunes ran retune_run.py as of commit 560a4e382. The Q+A and Q+O retunes ran an earlier copy. The differences are refactors (Krishna's check).

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
