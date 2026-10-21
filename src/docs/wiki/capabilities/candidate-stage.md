---
capability: candidate-stage
status: built; used by check_exists on the packed live path
plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.14-reuse-lookup-candidate-stage-plan.md
---
# Candidate stage

The candidate stage ranks the symbol index so that `check_exists` asks Jev about a shortlist, not every entry. The code exists. This page is the map; each part has its own page.

## Where each part lives
- Ranking (BM25, rank fusion, the wiki page list): [[repo-tools-candidate-ranking]] in `cosa.repo.symindex.candidates`.
- Vectors: [[repo-tools-candidate-vector-store]], [[repo-tools-candidate-vector-build]] and [[repo-tools-candidate-vector-freshness]]. Purpose lines: [[repo-tools-candidate-purpose-lines]].
- Search and the resident process: [[repo-tools-candidate-search]] and [[repo-tools-candidate-stage-and-resident]]. Paths and keys: [[repo-tools-candidate-storage-paths]].
- Shadow audit of "write new" verdicts: [[repo-tools-candidate-shadow-audit]] and [[repo-tools-candidate-shadow-audit-queue]].
- Offline comparison of the five arms: [[repo-tools-candidate-arms-wiring]], with its metrics, run-inputs, measure and report pages.

## How the lookup uses it
- `lupin_mcp.reuse_tools` builds a `CandidateStage` client (`lupin_mcp.reuse_candidates`) only on the packed path, when `LUPIN_REUSE_JEV_PACK_SIZE` is set. Without it every `check_exists` sweeps all entries.
- The client reads the live vector set from the INI storage folders. It asks the Lupin server's resident search for the shortlist, because the cosa-voice process cannot import numpy.
- It defaults to the concat-vector arm (Rick's ruling) and K 128. The INI key `reuse candidate shortlist arm`, or the variable `LUPIN_REUSE_CANDIDATE_ARM`, names another arm; `B2w` is the one that takes the wiki list. A policy with a band asks again at K 512 when the first sweep sits near a cut-off, and sweeps the extra entries. The shipped policy has no band, so it never does. Rick ruled the band off. The 0.076 fit stays in the policy header comment of `verdict.py`.
- `check_exists` sweeps only the shortlist, route `candidates`. `fetch_similar` always sweeps every entry, route `full`.
- A stage that fails on its first call answers `UNCERTAIN_READ_SOURCE` with `CALL_FAILED` in its causes, and nothing is swept. If only the widening call fails, the first sweep's decision stands with `CALL_FAILED` added. The receipt's `candidate_stage` block names the error.
- `lupin_mcp.reuse_redact` blanks emails, URLs, IP addresses, absolute paths and credential-shaped tokens in the need before anything is asked. Known lupin routes are kept.
- `page_candidates` in `reuse_tools` lists the wiki pages that feed the wiki list of arm `B2w`.

## Don't
- Don't expect a replay after a vector-set rebuild to work. It raises `VECTOR_SET_REPLACED` when the manifest hash on disk differs from the receipt's.
- Don't catch a message. Catch the `CandidateError` code.
- Don't expect the shadow audit to run by itself. Nothing in `lupin_mcp` or the server calls it yet.
- See [[reuse-search-tools]] for what a lookup sends to Jev.
