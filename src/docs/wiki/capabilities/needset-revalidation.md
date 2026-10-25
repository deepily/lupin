---
capability: needset-revalidation
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.revalidate.read_index@d820b1b9db
  - lupin_mcp.reuse_needset.revalidate.load_frozen@e830e3d10d
  - lupin_mcp.reuse_needset.revalidate.broken_keys@d8a16f06e5
  - lupin_mcp.reuse_needset.revalidate.near_new_definitions@d17b58ce90
  - lupin_mcp.reuse_needset.revalidate.gone_line@6438dd3b7e
  - lupin_mcp.reuse_needset.revalidate.revalidate@cd9ddee1d9
  - lupin_mcp.reuse_needset.revalidate.refreeze@7f5dac32b2
  - lupin_mcp.reuse_needset.revalidate.source_reader@7ad5153262
  - lupin_mcp.reuse_needset.revalidate.real_evidence@b80da31fe7
  - lupin_mcp.reuse_needset.revalidate.parse_args@dcb12fbff7
  - lupin_mcp.reuse_needset.revalidate.load_parts@6f70af295a
  - lupin_mcp.reuse_needset.revalidate.main@dc5eb99497
---
# Need set: re-validation

The day before the first scored run, this command re-checks the frozen set against a newer index. It flags a key symbol that was renamed or deleted. It flags a definition added since the freeze that the search ranks near a matched need, which may be a new twin. It also flags one near a nothing-exists need. The freeze is on [[needset-freeze]].

## Checks
- `read_index` returns the searchable definitions of an index generation by id. `load_frozen` verifies the manifest, then checks that the frozen copy's hashes equal the manifest's, and returns the manifest, needs and old index.
- `broken_keys` lists key symbols the new index lacks. One is `renamed` when exactly one new id has the same file, kind, signature and docstring, else `deleted`. A symbol still present is never listed.
- `near_new_definitions` lists, per need, the added definitions that rank in the top of the word or vector search.
- `gone_line` describes a missing key symbol for the reviewer: its id, and its old kind, name, signature and first docstring line.

## Result and refreeze
- `revalidate` returns a report, the flags and one reviewer item per flagged need, and writes nothing. A flag carries the reasons `broken_key`, `new_twin_candidate` or `near_nothing_need`. No reason is shown to the reviewer.
- `refreeze` writes a new frozen copy and manifest in a new folder. The manifest keeps the old hashes under `refrozen_from`. It raises `REVALIDATION_OPEN` while any key is broken.

## Command
- `parse_args` needs `--frozen-dir`, `--new-index`, `--new-vectors`, `--root`, `--query-cache-dir`, `--out` and `--top`. `--refreeze` is optional.
- `load_parts` loads the real vectors and the live embeddings endpoint. `real_evidence` and `source_reader` build the search and the source text from them.
- `main` writes `needset-revalidation.json` and the items file into `--out` and returns the report.
