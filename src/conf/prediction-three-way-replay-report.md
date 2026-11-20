# Three-way challenger: read-only replay on the frozen cohort

Measured by Sam. Read-only: no database write, no model call, stored vectors, cosine 0.5, top k 10.
Cohort: the 1,302 replayable asks in `src/conf/prediction-before-replayable-ids.txt` (all-ids sha256 `5faab7b3dc7f343cfc228a6424ef7206cba7d794a8c1f84e096b915122e5fd06`, checked equal to the freeze).
Switch off is the margin rule. Switch on is the three-way challenger. Windows are the freeze's: tune 911, final 391, of which yes/no 364 and 215.

## Control

The replay reproduces the freeze before the challenger is read: 177 final-window correct over all types, 163 on yes/no. The script asserts both.
A first run replayed every ask that now has a stored vector, 3,608 in all. It gave 398 and 374, so it did not measure the freeze and was discarded.

## Final window, yes/no, 215 asks

| comparison | challenger right | other right | only challenger right | only other right | McNemar exact p | floor of 10 met | verdict |
|---|---|---|---|---|---|---|---|
| challenger against always-yes | 173 | 173 | 0 | 0 | 1.0 | no (0 discordant) | not decisive |
| challenger against the margin rule | 173 | 163 | 10 | 0 | 0.00195 | yes (10 discordant) | challenger better |

The challenger forecast yes on all 215 final asks, so it ties always-yes ask for ask. The margin rule gave no forecast on 10 final asks. The challenger beats it on 10 asks, and the margin rule is right alone on none. Both counts are measured; this report does not trace whether they are the same 10 asks.
Verdict by the report's rule: not decisively better than always-yes, so it stays in shadow and the labelled always-yes baseline stays on display.

## Minority stances, yes/no

| window | yes/no asks | answered no | answered neither | challenger said yes | challenger said neither | challenger right on no or neither | false alarms |
|---|---|---|---|---|---|---|---|
| tune | 364 | 12 | 55 | 363 | 1 | 1 | 0 |
| final | 215 | 9 | 33 | 215 | 0 | 0 | 0 |
| all replayable | 579 | 21 | 88 | 578 | 1 | 1 | 0 |

The challenger found 1 of the 109 no or neither answers (one neither, in the tune window) and raised no false alarm. Its record is always-yes plus that one neither, so on the final window it cannot differ from always-yes. On the final window the margin rule found none of them (genuine no 0, genuine neither 0); its tune-window counts were not read.

Raw output: not committed; produced by a scratchpad script that wraps `three_way_report.build_report` over the cohort above.
