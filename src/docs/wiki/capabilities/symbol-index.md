---
capability: symbol-index
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.repo.symindex.__main__.main@6681909677
  - cosa.repo.symindex.build.build@09e95fcde0
  - cosa.repo.symindex.build.is_fresh@000012c2c9
  - cosa.repo.symindex.build.ensure@2bd7e42472
  - cosa.repo.symindex.build.environment@b6257e0ad0
  - cosa.repo.symindex.py_index.pin@c0bd7387a7
  - cosa.repo.symindex.spec.spec_for@dcc9afbd88
  - cosa.repo.symindex.paths.default_out_dir@f298ce42ab
  - cosa.repo.symindex.wiki_lint.queue@e0e0d92208
  - lupin_mcp.reuse_tools.prepare@f9dcbbdae1
---
# Symbol index

`cosa.repo.symindex` lists every Python, JavaScript, TypeScript and Dart definition in a tree with a content pin. Wiki pages quote those pins, and the reuse tools search the list. See [[reuse-search-tools]].

## Building it
- `python -m cosa.repo.symindex` has the subcommands `build`, `fresh`, `dups`, `diff` and `lint`. `build` writes a `gen-<hash>` folder holding `symbols.jsonl` (public symbols), `symbols-all.jsonl`, `symbols.md`, `routes.md` and `header.json`.
- A `current` link names the live folder, and an exclusive lock serializes builds. Only the newest three folders are kept.
- Every build re-reads every file. There is no per-file cache. `is_fresh` compares a hash of each file's path, mtime and size, so a bare `touch` makes the index stale.
- In the Lupin tree the output goes to `src/docs/index`. Any other repo writes under the fleet data root.
- Lupin's Python roots are `cosa`, `lupin_cli`, `lupin_mcp`, `lupin_app`, `lupin_arbiter_app`, `lupin_model_server` and `scripts`. Its web root `lupin_app/static/js` holds both JavaScript and TypeScript. Tests, migrations and `rnd` are skipped.
- A Flutter tree (`pubspec.yaml` plus `lib/`, such as `lupin-mobile`) is indexed as Dart. Any other tree gets every `.py`, `.js`, `.ts` and `.tsx` file, minus the same skipped folders and `.d.ts` and `.min.js` files.

## Symbols and pins
- A symbol is a class, function or method. Python names starting with `_` and nested helpers are not public, but `__init__` is. `__all__` is ignored.
- TypeScript symbols are top-level functions and classes, their public methods, constructors, getters and setters. A top-level `const`, `let` or `var` set to an arrow or function expression is also listed. Interfaces and types are not listed.
- A Python pin is the first 10 hex of a hash of the syntax tree with docstrings removed. Comments and whitespace do not change it, and an edit that changes the tree does.
- The `pin_algorithm` string joins the Python version and a hash of the extractor code. It adds the TypeScript version for a tree with JavaScript or TypeScript, and the Dart parser's for Dart.
- `lint` has seven kinds: `stale`, `dangling`, `unindexed`, `orphan`, `orphan_package`, `pin_algorithm_changed` and `pin_algorithm_missing`. An `orphan` is a public symbol in a documented package that no page pins.
- `orphan_package` is one finding with a count for a package that has no page. A changed or missing `pin_algorithm` switches `stale` off for every page.

## Failures and callers
- `build` exits 3 when any tool is missing, such as node, TypeScript or the Dart analyzer, and the index is built without it. A Python or Dart file that will not parse is listed in `unparsed` and skipped.
- If node itself fails, `build` crashes with a traceback. `fresh` exits 1 when stale. `dups` and `lint` exit 1 when they find something.
- `reuse_tools.prepare` is the one runtime reader, through the MCP tools. It calls `ensure` and answers `INDEX_STALE` if that raises.
- No INI key and no hook uses the index. The environment variables `LUPIN_REUSE_DATA_DIR` and `LUPIN_REUSE_OUT_DIR` move its folders for the reuse tools only. The CLI uses `--out`.
