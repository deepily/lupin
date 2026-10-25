---
capability: repo-tools-symindex-core-build
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.build.collect@7d5c95020c
  - cosa.repo.symindex.build.current_generation@c4c2cc7c10
  - cosa.repo.symindex.build.logic_version@f2bdda5b60
  - cosa.repo.symindex.build.read_header@cc7751000e
  - cosa.repo.symindex.build.read_symbols@cd44dfad87
  - cosa.repo.symindex.build.symbol_line@543437c610
  - cosa.repo.symindex.build.judge_doc@adcf1ef70e
  - cosa.repo.symindex.build.read_searchable@9be16212a9
  - cosa.repo.symindex.build.scope_of@7347e022ec
  - cosa.repo.symindex.build.search_sha@cbfef10af6
  - cosa.repo.symindex.build.searchable_jsonl@606872a022
---
# Symbol index: collecting and reading a generation

Companion to [[symbol-index]], which covers the CLI, `build`, `ensure` and `is_fresh`. This page is the lower layer those call and the readers that open a published folder.

## Collecting
- `collect( spec )` extracts every Python, JavaScript, TypeScript and Dart symbol of one tree. It returns a dict: `symbols` (public), `all_symbols`, `routes`, `missing`, `unparsed`, `skipped_files` and `pin_algorithm`. It publishes nothing. On a Dart tree it refreshes the scratch project under the data folder.
- A tool that is not installed goes into `missing` and its symbols are left out; the rest is still built. A Python file that fails to parse or decode, or a Dart file the analyzer reports errors in, goes into `unparsed`. `skipped_files` counts the indexed-suffix files each skip rule left out.
- Each record gets a unique id. It is `<module>.<name>` for Python and the dotted file path plus name otherwise. A tree other than lupin adds a `<repo>:` prefix, and a repeat gets `#2`, `#3`.
- Each record also gets a `scope` from `scope_of`: `test` under a tests folder, else `public`, `nested` or `private`.
- The pin is the first 10 hex of a sha1 over `pin_text`, unless the extractor already supplied `pin`.

## The pin algorithm string
- `logic_version( py_source, js_source, dart_source )` returns 6 hex characters over the extractor code with docstrings and comments removed. It is the `x<hex>` part of `pin_algorithm`.
- Editing a comment or docstring in `py_index.py`, `ts_extract.js`, `ts_kind_names.cjs` or `dart_extract.dart` leaves it alone. Only whole-line comments count for Dart. Editing code changes it, so every page then reads as algorithm-changed instead of stale.

## Reading a generation
- `current_generation( out_dir )` follows the `current` link and returns the folder, or `None` when nothing is published or the link is broken.
- `read_header( gen )` returns the parsed `header.json`: root, repo, manifest, pin algorithm, counts, missing tools, unparsed files and the skipped-file counts.
- `read_symbols( gen, all_symbols=False )` returns the records of `symbols.jsonl`, or of `symbols-all.jsonl` when `all_symbols` is true. The lint and the diff read through it.
- `read_searchable( gen, tests=False )` returns the records whose `scope` is `public` or `private`, plus `test` when asked, never `nested`. The judge, the vectors and the purpose lines read through it. `searchable_jsonl` renders that listing as jsonl, with a stored purpose line attached to each record whose pin has one when `purposes` is given. `search_sha` hashes it, and `judge_doc` is the docstring text the judge reads.
- `symbol_line( r )` renders one record as the `symbols.md` line: `<file>::<name><sig> — <doc> [<id>@<pin>]`.

## Not here
- Output location (`default_out_dir`, `data_dir`) and the file-skipping rules are on [[repo-tools-symindex-core-tree]].
