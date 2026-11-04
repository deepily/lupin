---
capability: repo-tools-candidate-arms-metrics
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.arm_metrics.recall_at_k@14ab826db5
  - cosa.repo.symindex.candidates.arm_metrics.t1_table@59e96e3f66
  - cosa.repo.symindex.candidates.arm_metrics.reference_ids@13fde88429
  - cosa.repo.symindex.candidates.arm_metrics.twin_rank@384ba333d2
  - cosa.repo.symindex.candidates.arm_metrics.t3_summary@b7cfd6795d
  - cosa.repo.symindex.candidates.arm_metrics.decide_with_ids@7ccc74ab87
  - cosa.repo.symindex.candidates.arm_metrics.t2_replay@b7c9e9bdf2
  - cosa.repo.symindex.candidates.arm_metrics.choose_vectors@540a3b9921
---
# Candidate arms: the measures

The offline comparison scores each arm (a choice of ranked lists to fuse) with the pure functions in `arm_metrics.py`. They read no files; the caller brings shortlists, rankings and cached answers. The wiring is on [[repo-tools-candidate-arms-wiring]].

## Recall
- `recall_at_k( shortlist, reference )` returns the share of the reference ids that the shortlist holds, 0.0 to 1.0. An empty reference raises `ValueError`, because recall is undefined there.
- `reference_ids( decision )` reads the full sweep's shortlist out of a `verdict.decide` result: the ids of its shortlist rows, sorted.
- `t1_table( shortlists, references )` takes arm, then K, then need id. It returns mean recall, mean shortlist size and per-need recall for each arm and K.
- A need with an empty reference is left out of the mean and the per-need map. `mean_size` still counts it.

## Twin rank
- `twin_rank( ranking, twin_id )` returns the 1-based position of a known twin, or `None` when it is not in the ranking.
- `t3_summary( ranks_by_language )` gives, per language, the member count, the unranked count and the median of ranked twins.
- It also gives `median_all`, which counts an unranked twin as worse than any rank, and the twins inside the top 10, 50 and 128 (`TOP_CUTS`).

## Verdict replay
- `decide_with_ids( rows, ids )` runs the verdict table on cached answers and returns the verdict string. If any row carries `provides`, all rows go through `decide_provides`; otherwise they go through `decide`. No flag is set and no call counts as failed.
- `t2_replay( shortlists, answers )` replays every repeat of a need twice. One replay uses the shortlisted entries that have a cached answer. The other uses every answered entry as the reference. It returns `flip_rate` (needs whose repeats disagree), `agreement`, `uncached`, `needs` and the verdicts.
- Pass `decide_fn` to `t2_replay` to swap the decider.

## Choosing vectors
- `choose_vectors( one, two )` takes the one-vector and two-vector figures, each with `recall_128` and `median_rank`.
- It returns the two-vector arm name only when that arm has a higher recall at 128 or a lower median rank. A tie or a missing figure keeps the one-vector arm.
- Feed it `median_all`, not the ranked-only median.
