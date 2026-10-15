---
capability: candidate-stage
status: planned, not built
plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.14-reuse-lookup-candidate-stage-plan.md
---
# Candidate stage (planned, not built)

Nothing on this page exists in code yet. It records what the approved plan will build, so a reader does not look for it.

## What it will do
- Rank the symbol index before Jev sees it. The ranking is rank fusion over BM25, a prose vector list, a code vector list and the wiki page list.
- Pass the top 128 entries to Jev, widened to 512 when the top Jev score sits inside the uncertain band. Packs hold 50 entries, sorted by id.
- Redact the need string first. Emails, URLs, IP addresses, credentials and absolute paths are blanked, and known lupin routes are kept.
- Keep one vector set, the current state of the repo. A receipt records its manifest hash, and a replay after a rebuild refuses.

## Where it will live
- The ranking code goes in `cosa.repo.symindex.candidates`, run as a child process in the Lupin environment.
- The redactor goes in `lupin_mcp.reuse_redact`. The wiring goes in `lupin_mcp.reuse_tools`.
- Vectors come from the existing `/api/embeddings` endpoints, which gain a `role` field and an `engines` block.

## Don't
- Don't treat a name here as importable. No module named above exists yet.
- Don't use a page-first route. The plan removes it in its wiring phase.

## Invariants the plan sets
- The same need and the same vector set give the same shortlist, byte for byte.
- A "write new" verdict carries a measured miss-rate bound from a shadow audit of 1% of lookups.
- No storage path is hard-coded. Every location is an INI key with an environment override.
