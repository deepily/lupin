---
capability: repo-tools-candidate-shadow-audit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.shadow_audit.is_sampled@9cad6051f6
  - cosa.repo.symindex.candidates.shadow_audit.need_hash@b8cda2ce7e
  - cosa.repo.symindex.candidates.shadow_audit.compare@17df622003
  - cosa.repo.symindex.candidates.shadow_audit.audit_receipt@44c38ca621
  - cosa.repo.symindex.candidates.shadow_audit.tally@1871b16b05
  - cosa.repo.symindex.candidates.shadow_audit.audit_bound@944b3f8725
  - cosa.repo.symindex.candidates.shadow_audit.bound_for_verdict@1b3623f3cf
---
# Candidate shadow audit: sampling and bound

The shadow audit sweeps every symbol for a small share of lookups and compares the answer with the shortlist the stage kept. The receipts give an upper bound on how often the stage misses a true match. Nothing here makes a live call: the sweep transport is passed in. The queue half is in [[repo-tools-candidate-shadow-audit-queue]].

## Sampling and judging
- `is_sampled( need, generation, rate=0.01 )` hashes the generation and need into 10,000 buckets, so a lookup is always in or always out. A rate outside 0 to 1 raises `AUDIT_RATE_INVALID`.
- `need_hash( need )` is the sha256 of a need, so a receipt names a need without keeping its words.
- `compare( live_verdict, full_verdict, causal_ids, candidate_ids )` returns `miss` when the full sweep matched and none of its causal ids was kept. It returns `inconclusive` when the sweep could not decide or matched with no causal id, and `ok` otherwise.
- `audit_receipt( need, language, generation, index_sha, live, sweep, today )` builds the receipt dict. Its id is 16 hex characters of a hash of need hash, generation and index sha, so a repeat is one receipt.

## The bound
- `tally( receipts, language, generation )` returns `audits` (conclusive only), `misses`, `inconclusive` and `bound`. Receipts of another language or generation are not counted.
- `audit_bound( misses, n )` is the 95% one-sided upper bound on the miss share. It is 1.0 for no audits, `1 - 0.05 ** ( 1 / n )` for no misses, and the Wilson bound otherwise. Bad counts raise `AUDIT_COUNTS_INVALID`.
- `bound_for_verdict( data_dir, language, generation )` is `tally` over the receipts on disk.
