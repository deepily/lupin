# Decision-stage annotation of the 23 re-spin evidence rows

Plan: `src/rnd/v0.2.4/2026.11.17-principle-learner-research/2026.11.23-answer-signal-experiment-plan.md`, section 3, "Re-annotating the 23 evidence rows". Store row 2d0b6d9d. The re-score reads these files later.

## The 23 rows, and the query that finds exactly 23
Source: `archive.sqlite` in the durable copy `/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/principle-learner/io/phase4-archive-run-2/` (read-only; `MANIFEST.sha256` verified, 0 mismatches, before reading).

```sql
select e.* from preference_evidence e join notifications n on n.id = e.notification_id
where e.principle_id = '4615b6f95e9d41ba9035f4d1ce4753d7' and n.title like '%context ceiling%'
order by e.answered_at, e.id;   -- 23 rows
```

The principle is "Do not let an agent at its context ceiling re-spin itself with /clear by default, even when the owner is away". It has 27 evidence rows; 23 sit on re-spin cards (title contains "context ceiling"). This is the population the paper's page calls "the 23 evidence rows for the re-spin principle that sit on re-spin cards".
Other counts found, for the record: the second re-spin principle (`2668eeb4…`) has 26 rows and 21 on re-spin cards; the same principle also has exactly 23 `supports` rows, a different 23 by coincidence of count. `extract_rows.py` refuses to run if the count is not 23.

## Order of work (timestamps UTC, 24 Nov 2026)
1. `extract_rows.py` wrote the label-free input and, separately, the labels. The labels went to a scratch file I did not open.
2. Annotated from `label-free-input.json` only. `annotation.json` written, sha256 taken at 16:11:57.
3. Labels file sha256 taken at 16:12:03, after the annotation sha, then copied here as `labels.json`.

**Disclosure.** Before step 1, while finding the population, I read aggregate relation tallies for these principles (the paper scripts' output: 23 supports and 4 refines on the principle's 27 rows). I did not read any per-row relation, and the per-row labels were opened only after step 2.

| File | sha256 |
|---|---|
| `label-free-input.json` | `bb9cac034058b65ee1c50fa5d0522724a153694ae615bd83eb89f898e6088b86` |
| `annotation.json` | `fa0b4d59174c3fc1df32002c2658817213ef1ca610498bf3414b629e28ec53ac` |
| `labels.json` | `750adb65f42ddcce24dc6289b8d4cc5cdb40f4a6af48d192638b7f0413c36697` |

## Result
All 23 rows are annotated `what_to_do_once_asked`. Every card is the same ask ("<seat> is at their context ceiling. Re-spin <seat> now?", the same abstract, default yes), and no answer states a rule about who decides or whether to ask first. Four answers (rows 4, 5, 8, 16) carry a precondition on the act ("record this before you re-spin"); they are flagged `answer_has_precondition` and are still at the asked stage.
So the annotation cannot separate these rows by stage: it fixes the stage of the card, not a difference between rows. The `who_decides` value has no instance in this population.

The annotator is one AI seat (John); no second reader checked it.
