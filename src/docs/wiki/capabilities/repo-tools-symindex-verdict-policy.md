---
capability: repo-tools-symindex-verdict-policy
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.verdict.malformed_reason@1f1669771a
  - cosa.repo.symindex.verdict.call_facts@0611654fde
  - cosa.repo.symindex.verdict.malformed_reason_provides@3187133a79
  - cosa.repo.symindex.verdict.decide_provides@2955e362d5
  - cosa.repo.symindex.labelled_set.check_band@89d0f8f884
---
# Verdict helpers and the provides rule

Pure functions behind the reuse check's verdict. `decide`, the overlap rule, is described on [[reuse-search-tools]]; nothing here touches a file, the network or a model.

## Overlap answers
- `malformed_reason( probabilities )` returns None for a valid answer. A valid one has the keys `reuse`, `extend` and `unrelated` and no others. Each is a finite real number from 0 to 1 (a bool is not a number), and they sum to 1 within 0.02. Otherwise it returns the first of `not_a_mapping`, `missing_or_extra_keys`, `not_a_number`, `not_finite`, `out_of_range` or `sum_not_one`.
- `call_facts( probabilities )` returns `( p_overlap, confidence, choice )`: reuse plus extend, the largest probability, and the key holding it. A tie goes to reuse, then extend. It expects a valid answer.

## The provides rule
- `malformed_reason_provides( provides, coverage )` checks a Noul number in [0, 1] and four Score probabilities keyed `0` to `3`. Each is in [0, 1], and they sum to 1 within 0.02. It reports the number's fault first.
- `decide_provides( answers, expected_ids, failed_ids, flags )` returns the same keys as `decide`. Defaults: threshold 0.5, reuse 0.7, floor 0.3, coverage 0.5, shortlist 10.
- `REUSE` when an entry has provides at or above 0.7 and no gap cause holds. `EXTEND` when no entry reaches 0.7 and one has provides from 0.3 up to 0.7 and coverage (levels 2 and 3) at or above 0.5. `LOW_CONFIDENCE` holds when neither applies and an entry sits in the provides band or has coverage at or above 0.5. That answers `UNCERTAIN_READ_SOURCE`. A complete sweep with no entry at the floor holds `NO_MATCH` alone, and answers the same verdict.
- Malformed, duplicate or unknown-id answers are reported as `MALFORMED_ANSWER` and never half used. Failed or unaccounted calls, and a sweep with no answers, give `CALL_FAILED`, so an empty sweep is never `NO_MATCH`.
- Any flag outside the four pipeline flags raises `ValueError`.

## The uncertain band
- `check_band( band )` returns the band when it is at least 0.05 and under 0.5, and raises `ValueError` otherwise. A bool, NaN or infinity is refused.
