# Before and after: regenerated question vectors

Change 1 to 2 is the effect of the regenerated vectors alone. Change 2 to 3 is the effect of the added asks. Change 3 to 4 is the effect of scoring only before's final window.

- Columns 1 and 2 agree because the regenerated vectors equal the stored ones on these 1,302 asks. The cosine is at least 0.99999999999, by Chloé's check of the side file. So change 1 to 2 is the effect of the new vectors alone, and it is nil here.
- Column 3 replays all 3,608 frozen asks at its own best settings, threshold 0.5 and top k 5. Column 4 is that replay scored only on column 1's 391 final-window asks.
- Column 4's calibration is fitted on column 3's tune window without column 1's final asks. Its tune figures read n/a.
- The four columns are src/conf/prediction-before-after-column-1.json to -4.json. The control run is src/conf/prediction-before-control-report.json.

| column | label | commit | vector source | asks | scored | produced by |
|---|---|---|---|---|---|---|
| 1 | 1 Before: stored vectors | `8d748e033` | stored vectors, read from each case row | 1302 | 1302 | the committed baseline 8d748e033, the checkpoint report on the 3,608 frozen asks; re-derived on stored vectors by the column runner at 0a4f392e6, which reproduces its 177 final-window correct; control run commit 4ea4581cc |
| 2 | 2 Same asks, regenerated vectors | `0a4f392e64f7b07ca665efe3966c224a21fdbfb1` | nomic-ai/nomic-embed-text-v1.5 @ e9b6763023c676ca8431644204f50c2b100d9aab | 1302 | 1302 | commit 0a4f392e6, side file sha256 f3475c6b5ca5, `python -m cosa.research.preference_replay.before_after_columns --out /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col2.json --label 2 Same asks, regenerated vectors --threshold 0.5 --top-k 10 --vectors /mnt/DATA01/include/www.deepily.ai/projects/lupin/io/question-vectors/2026.11.19-vectors.jsonl --only-ids src/conf/prediction-before-replayable-ids.txt` |
| 3 | 3 All asks, regenerated vectors | `0a4f392e64f7b07ca665efe3966c224a21fdbfb1` | nomic-ai/nomic-embed-text-v1.5 @ e9b6763023c676ca8431644204f50c2b100d9aab | 3608 | 3608 | commit 0a4f392e6, side file sha256 f3475c6b5ca5, `python -m cosa.research.preference_replay.before_after_columns --out /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col3.json --label 3 All asks, regenerated vectors --threshold 0.5 --top-k 5 --vectors /mnt/DATA01/include/www.deepily.ai/projects/lupin/io/question-vectors/2026.11.19-vectors.jsonl --only-ids src/conf/prediction-checkpoint-cohort.jsonl --rescore-from /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col1.json --rescored-out /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col4.json --rescored-label 4 All asks as neighbours, Before's final asks` |
| 4 | 4 All asks as neighbours, Before's final asks | `0a4f392e64f7b07ca665efe3966c224a21fdbfb1` | nomic-ai/nomic-embed-text-v1.5 @ e9b6763023c676ca8431644204f50c2b100d9aab | 3608 | 391 | commit 0a4f392e6, side file sha256 f3475c6b5ca5, `python -m cosa.research.preference_replay.before_after_columns --out /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col3.json --label 3 All asks, regenerated vectors --threshold 0.5 --top-k 5 --vectors /mnt/DATA01/include/www.deepily.ai/projects/lupin/io/question-vectors/2026.11.19-vectors.jsonl --only-ids src/conf/prediction-checkpoint-cohort.jsonl --rescore-from /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col1.json --rescored-out /mnt/DATA01/include/www.deepily.ai/projects-data/lupin/tiffany-step8-9/col4.json --rescored-label 4 All asks as neighbours, Before's final asks` |

| figure | 1 Before: stored vectors | 2 Same asks, regenerated vectors | 3 All asks, regenerated vectors | 4 All asks as neighbours, Before's final asks | change 1 to 2 | change 2 to 3 | change 3 to 4 |
|---|---|---|---|---|---|---|---|
| asks | 1302 | 1302 | 3608 | 3608 | +0 | +2306 | +0 |
| threshold | 0.5000 | 0.5000 | 0.5000 | 0.5000 | +0.0000 | +0.0000 | +0.0000 |
| top k | 10 | 10 | 5 | 5 | +0 | -5 | +0 |
| tune asks: multiple_choice | 547 | 547 | 1596 | n/a: scored only on the final-window asks of column 1 | +0 | +1049 | n/a |
| tune asks: yes_no | 364 | 364 | 929 | n/a: scored only on the final-window asks of column 1 | +0 | +565 | n/a |
| final asks: multiple_choice | 176 | 176 | 604 | 176 | +0 | +428 | -428 |
| final asks: yes_no | 215 | 215 | 479 | 215 | +0 | +264 | -264 |
| tune correct: multiple_choice | 10 | 10 | 48 | n/a: scored only on the final-window asks of column 1 | +0 | +38 | n/a |
| tune correct per 100: multiple_choice | 1.8 | 1.8 | 3.0 | n/a: scored only on the final-window asks of column 1 | +0.0 | +1.2 | n/a |
| tune correct: yes_no | 277 | 277 | 699 | n/a: scored only on the final-window asks of column 1 | +0 | +422 | n/a |
| tune correct per 100: yes_no | 76.1 | 76.1 | 75.2 | n/a: scored only on the final-window asks of column 1 | +0.0 | -0.9 | n/a |
| final correct: multiple_choice | 14 | 14 | 24 | 14 | +0 | +10 | -10 |
| final correct per 100: multiple_choice | 8.0 | 8.0 | 4.0 | 8.0 | +0.0 | -4.0 | +4.0 |
| final correct: yes_no | 163 | 163 | 368 | 163 | +0 | +205 | -205 |
| final correct per 100: yes_no | 75.8 | 75.8 | 76.8 | 75.8 | +0.0 | +1.0 | -1.0 |
| yes_no vs always-yes: predictor correct | 163 | 163 | 368 | 163 | +0 | +205 | -205 |
| yes_no vs always-yes: baseline correct | 173 | 173 | 387 | 173 | +0 | +214 | -214 |
| yes_no vs always-yes: predictor only right | 0 | 0 | 0 | 0 | +0 | +0 | +0 |
| yes_no vs always-yes: baseline only right | 10 | 10 | 19 | 10 | +0 | +9 | -9 |
| yes_no vs always-yes: McNemar exact p | 0.0020 | 0.0020 | 0.0000 | 0.0020 | +0.0000 | -0.0019 | +0.0019 |
| yes_no vs always-yes: verdict | baseline better | baseline better | baseline better | baseline better | same | same | same |
| calibration multiple_choice\|cbr_majority_vote | not fitted | not fitted | n/a | n/a | same | n/a | n/a |
| calibration multiple_choice\|cold_start: Brier raw | 0.0000 | 0.0000 | 0.0000 | 0.0000 | +0.0000 | +0.0000 | +0.0000 |
| calibration multiple_choice\|cold_start: Brier calibrated | 0.0000 | 0.0000 | 0.0000 | 0.0000 | +0.0000 | +0.0000 | +0.0000 |
| calibration yes_no\|cbr_majority_vote: Brier raw | 0.2239 | 0.2239 | 0.2116 | 0.2252 | +0.0000 | -0.0123 | +0.0136 |
| calibration yes_no\|cbr_majority_vote: Brier calibrated | 0.1728 | 0.1727 | 0.1585 | 0.1658 | -0.0001 | -0.0142 | +0.0073 |
| calibration yes_no\|cold_start | not fitted | not fitted | not fitted | not fitted | same | same | same |
| calibration multiple_choice\|cbr_majority_vote: Brier raw | n/a | n/a | 0.1189 | 0.1273 | n/a | n/a | +0.0084 |
| calibration multiple_choice\|cbr_majority_vote: Brier calibrated | n/a | n/a | 0.1435 | 0.1522 | n/a | n/a | +0.0087 |
