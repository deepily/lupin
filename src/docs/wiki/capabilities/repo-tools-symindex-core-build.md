---
capability: repo-tools-symindex-core-build
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.build.collect@5204c9d557
  - cosa.repo.symindex.build.current_generation@c4c2cc7c10
  - cosa.repo.symindex.build.logic_version@f2bdda5b60
  - cosa.repo.symindex.build.read_header@cc7751000e
  - cosa.repo.symindex.build.read_symbols@cd44dfad87
  - cosa.repo.symindex.build.symbol_line@543437c610
---
# Symbol index: collecting and reading a generation

Companion to [[symbol-index]], which covers the CLI, `build`, `ensure` and `is_fresh`. This page is the lower layer those call and the readers that open a published folder.

## Collecting
- `collect( spec )` extracts every Python, script and Dart symbol of one tree and returns a dict: `symbols` (public), `all_symbols`, `routes`, `missing`, `unparsed`, `pin_algorithm`. It publishes nothing; on a Dart tree it refreshes the scratch project under the data folder.
- A tool that is not installed goes into `missing` and its symbols are left out; the rest is still built. A Python file that fails to parse, or a Dart file the analyzer reports errors in, goes into `unparsed`.
- Each record gets a unique id. It is `<module>.<name>` for Python and the dotted file path plus name otherwise. A tree other than lupin adds a `<repo>:` prefix, and a repeat gets `#2`, `#3`.
- The pin is the first 10 hex of a sha1 over `pin_text`, unless the extractor already supplied `pin`.

## The pin algorithm string
- `logic_version( py_source, js_source, dart_source )` returns 6 hex characters over the extractor code with docstrings and comments removed. It is the `x<hex>` part of `pin_algorithm`.
- Editing a comment in `py_index.py`, `ts_extract.js`, `ts_kind_names.cjs` or `dart_extract.dart` leaves it alone. Editing code changes it, so every page then reads as algorithm-changed instead of stale.

## Reading a generation
- `current_generation( out_dir )` follows the `current` link and returns the folder, or `None` when nothing is published or the link is broken.
- `read_header( gen )` returns the parsed `header.json`: root, repo, manifest, pin algorithm, counts, missing tools, unparsed files.
- `read_symbols( gen, all_symbols=False )` returns the records of `symbols.jsonl`, or of `symbols-all.jsonl` when `all_symbols` is true. The lint, the diff and the reuse tools all read through these two.
- `symbol_line( r )` renders one record as the `symbols.md` line: `<file>::<name><sig> — <doc> [<id>@<pin>]`.

## Not here
- Output location (`default_out_dir`, `data_dir`) and the file-skipping rules are on [[repo-tools-symindex-core-tree]].
