# Context comparison report

- commit of the scorer: c617d07bc788f7efcd79487a66cb160c383b444b
- discordant floor: 6 pairs, stated before the run
- per-ask files: src/conf/prediction-context-arm-*-per-ask.json, each with its own command, code sha and start time
- generated: 2026-11-19T22:20:28.323097+00:00
- command: LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5 PYTHONPATH=/mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5/src python mkreport.py /mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/seat-cc-author-mr-radio-5

## Coverage

| arm | asks | with its section | no context | arm input empty |
|---|---|---|---|---|
| Q | 3608 | 3608 | 0 | 0 |
| Q+A | 3608 | 3567 | 41 | 0 |
| Q+O | 3608 | 2200 | 1408 | 0 |
| Q+P | 3608 | 3585 | 23 | 0 |
| Q+H | 3608 | 2576 | 447 | 585 |

## Reconciliations

- **Cohort size**: All 3,608 frozen ids are scored for every arm; the report scores the final window of 1,083 asks, the cut the retune makes.
- **Always-yes**: Always-yes has no answer to a multiple-choice ask, so it is compared on the yes/no asks only; the pooled comparison is not reported.
- **Seven asks differ from the export**: Seven asks have a different context state than the raw export gives, because the export lacks their earlier rows.
- **45 asks lack context**: Of the 45 asks, 5 are newer than the export; the other 40 are an unexplained gap, named and not bridged.
- **Retune finals**: Per-ask correct counts equal the retune finals: Q 392, Q+A 384, Q+O 392, Q+P 358, Q+H 389 of 1,083.

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

