---
capability: dead-rnd-citations
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dead_rnd_citations.tracked_files@9304f9f537
  - scripts.dead_rnd_citations.is_archive@9746e7b076
  - scripts.dead_rnd_citations.in_corpus@42f1a902c1
  - scripts.dead_rnd_citations.cross_repo_names@252354e8c6
  - scripts.dead_rnd_citations.cross_repo_pattern@0795199205
  - scripts.dead_rnd_citations.is_cross_repo@b83582177e
  - scripts.dead_rnd_citations.is_annotated@e8a155e617
  - scripts.dead_rnd_citations.wrap_head@d28ecd6dfc
  - scripts.dead_rnd_citations.wrap_tail@307eaffbdc
  - scripts.dead_rnd_citations.citation_instructs@5e10599ad6
  - scripts.dead_rnd_citations.scan@7164c4d1f4
  - scripts.dead_rnd_citations.scan_index_links@26341c1ca3
---
# Dead research citations scanner

Scans the repo for `src/rnd/…` citations that no longer resolve, and reports its own corpus. The population exclusion is recorded as code, because a defect recorded only in a document is not a control. The scanner asserts no count: a guard written against the live dead total would ship red, and a red guard gets deleted.

## Corpus
- `tracked_files` lists every file git tracks, relative to the repo root. It raises if git cannot answer, so an empty list never hides a failed call.
- `is_archive` is true for a frozen historical record, such as the history folders and the nested R&D tree.
- `in_corpus` returns true for every tracked file. The earlier file-level exclusion of research documents hid dead links in an index, so `citation_instructs` now decides per citation. The index file list survives only as a positive control.

## Citations that do not count
- `cross_repo_names` reads the sibling repo names from the `external repos` key of the config file. It puts the longest first, leaves out this repo and adds the unregistered sibling. A missing key raises `ValueError`.
- `cross_repo_pattern` builds the pattern for a sibling name before a match, and refuses a name that is merely the tail of a longer word.
- `is_cross_repo` is true when the text before a match names a sibling repo, so a bare local citation is still resolved here.
- `is_annotated` is true when the match sits inside a recovery command or its line carries the removed marker.
- `wrap_head` and `wrap_tail` strip the wrap furniture of a continued line, so a path split across two lines is joined. A comment marker is removed, because it is not part of the path.
- `citation_instructs` decides by property rather than file. Outside `src/rnd/` every citation instructs. Inside it, only a call argument in Python or a markdown link target does.

## Scanning
- `scan` returns the scanned count, skipped, live and dead citations, and which index files were reached. The scanned count lets a caller tell an empty result from an empty search.
- `scan_index_links` resolves the markdown links in the index relative to `src/rnd/`. It is kept apart from `scan` because the fix is a different shape.
