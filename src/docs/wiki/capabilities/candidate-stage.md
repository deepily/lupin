---
capability: candidate-stage
status: built; wired into check_exists through an optional candidate stage
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
- `lupin_mcp.reuse_tools` builds a `CandidateStage` client (`lupin_mcp.reuse_candidates`) from the INI storage keys. It asks the Lupin server's resident search for the shortlist, because the cosa-voice process cannot import numpy.
- `check_exists` sweeps only that shortlist when the context carries a stage. `fetch_similar` always sweeps every entry.
- A failed stage answers `UNCERTAIN_READ_SOURCE` with cause `CALL_FAILED`, and nothing is swept. The receipt's `candidate_stage` block names the error.
- `lupin_mcp.reuse_redact` blanks emails, URLs, IP addresses, absolute paths and credential-shaped tokens in the need before it leaves the machine. Known lupin routes are kept.

## Don't
- Don't expect the vector set to follow the repo on its own. It is rebuilt by a job, and a replay after a rebuild is refused.
- Don't catch a message. Catch the `CandidateError` code.
- The older page-first route still exists in `reuse_tools` (`page_candidates`). See [[reuse-search-tools]] for what a lookup sends.
