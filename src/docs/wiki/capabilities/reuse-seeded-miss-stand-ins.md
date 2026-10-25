---
capability: reuse-seeded-miss-stand-ins
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_seeded_miss_e2e.SavedAnswerMissing@6ca81a58b2
  - lupin_mcp.reuse_seeded_miss_e2e.words@e562e86bde
  - lupin_mcp.reuse_seeded_miss_e2e.candidate_of@38c41213fa
  - lupin_mcp.reuse_seeded_miss_e2e.answer_for@7f85a44b2c
  - lupin_mcp.reuse_seeded_miss_e2e.StandInJev@60645115eb
  - lupin_mcp.reuse_seeded_miss_e2e.NoCallTransport@52f2623a86
  - lupin_mcp.reuse_seeded_miss_e2e.FakeStore@ceb00fabd8
  - lupin_mcp.reuse_seeded_miss_e2e.build_sandbox@225e655136
  - lupin_mcp.reuse_seeded_miss_e2e.write_index@024eeb26fd
  - lupin_mcp.reuse_seeded_miss_e2e.write_docstring@7714c8020c
  - lupin_mcp.reuse_seeded_miss_e2e.StandInStage@1f2c9cb776
  - lupin_mcp.reuse_seeded_miss_e2e.make_context@24a0dfd766
  - lupin_mcp.reuse_seeded_miss_e2e.seed_cache@51dcd629e6
---
# Reuse seeded-miss run: stand-ins and sandbox

The parts of the seeded-miss end-to-end run that stand in for the real services. It seeds a miss in a throwaway repository, repairs a docstring and proves the repair by replay. The scenario is on [[reuse-seeded-miss-scenario]].

## Throwaway repository
- `build_sandbox` writes five public functions and two capability pages under the work folder. The wrong page's index line matches the need and the right page's line does not.
- `write_index` writes the wiki index with the right page's line as given. `write_docstring` rewrites the missed symbol's first docstring line to hold the need's words.

## Stand-in Jev
- `words` returns the lower-case words of three or more characters, without stop words. `answer_for` gives the relevant answer when the candidate shares half the need's words, else the unrelated one.
- `candidate_of` reads the candidate text back out of a packed question's instructions, or `None` when there is none.
- `StandInJev` answers a packed body from the words the need and a candidate share. A changed docstring line therefore changes the answer. It keeps every body it was sent and counts the calls.
- `NoCallTransport` is the transport of a run on saved answers. Every post raises `SavedAnswerMissing` and keeps the need, because the sweep treats a raised error as a failed call.

## Stand-in services
- `StandInStage` answers every entry but the excluded one, sorted by id. The real stage does the same when the index is smaller than K.
- `make_context` returns a packed context with the stand-in stage and the given transport.
- `FakeStore` is an in-memory store with the three calls the librarian makes. A query returns every row, so a held or parked state never hides one.
- `seed_cache` copies a saved `jev-cache` folder into the run's data folder after summing its size. A missing folder, or one over the size limit, raises `RunRefused`.
