# symindex: symbol index for code-reuse review

Builds a per-repository index of public symbols and routes, finds duplicate functions, diffs two
snapshots and lints the code wiki against the index.

```bash
cd <repo> && PYTHONPATH=src python -m cosa.repo.symindex build     # publish the index
python -m cosa.repo.symindex fresh | dups | diff OLD NEW [--all] | lint
```

Exit codes: `build` 3 when a tool was missing (the index is still written), `fresh` 1 when stale,
`dups` and `lint` 1 when they report anything.

## Layout of one published index

`<out>/current` is a symlink to `gen-<manifest>/`, replaced atomically. A generation holds
`symbols.md`, `routes.md`, `symbols.jsonl` (public), `symbols-all.jsonl` (every definition) and
`header.json` (index root, manifest, `symbols_sha`, `pin_algorithm`, counts, missing tools).
Default `<out>`: `src/docs/index` for the lupin tree (gitignored); otherwise
`fleet_data_root( root )/reuse-review/index/<repo>`, so a read-only tree is never written to.

## What is a public symbol

Python: a class or function whose name does not start with `_`, at module level or under module-level
`if`/`try`/`with`/`for`/`while`/`match` blocks, plus the public methods of public classes and
`__init__`. `__all__` is ignored. Overloads and property setters repeat a name, so ids get `#2`, `#3`.
`diff --all` adds private names, dunders and helpers nested in functions (`f.<locals>.g`).
TS/JS: every top-level function, class, public method and function-valued `const`; `private`,
`protected` and `#private` members are left out. Ids are `<module path>.<qualified name>`, prefixed
`<repo>:` for any tree that is not lupin.

## Pins

A pin is the first 10 hex of a sha1 of the definition with docstrings and comments removed: the
Python AST dump, or the TypeScript leaf tokens joined by one space. A docs-only or whitespace edit
never changes it; a code edit does. `header.json` records `pin_algorithm` (for example
`py3.13/ts5.9.3`); a wiki page carries the same string, and `wiki_lint` reports a mismatch as one
finding instead of one stale finding per page.

## E3: JS/TS parser comparison (measured 2026-09-30, lupin `d40ed5cf4`)

| | TypeScript compiler under node (chosen) | tree-sitter (`tree_sitter` + JS + TS grammars) |
| --- | --- | --- |
| Class methods, typed arrow functions, generics | pass | pass |
| Comment and whitespace stable pin | pass (leaf tokens) | not built; comments are nodes, doable |
| New packages | none: `typescript` 5.9.3 is already in `node_modules` (23 MB) | 2 native wheels, 5.7 MB installed |
| Host requirement | `node`, found by absolute path ($LUPIN_NODE, PATH, `~/.nvm`) | none beyond the venv |
| Import cost | one node start per build | 8.8 ms |
| Time, 194 web-client files | 0.87 s | 0.4 s (walks nested functions too, so its symbol count is not comparable) |

Both pass the three fixture cases, so the ruling's default stands: the TypeScript compiler. The
cost is a runtime dependency on `node` inside the cosa-voice subprocess; a missing node is reported
as DEPENDENCY_MISSING, never as an empty index.

## Coverage of the node extractor

`ts_extract.js` runs as a subprocess, so pytest coverage cannot see it. Measure it with c8 while the
Python tests that call it run (100% statements, branches, functions, lines at `82cd1d2aa` + fixtures):

```bash
NODE_V8_COVERAGE=/tmp/v8cov PYTHONPATH=src python -m pytest src/tests/unit/test_symindex_js.py src/tests/unit/test_symindex_build.py -q
node_modules/.bin/c8 report --temp-directory /tmp/v8cov --include src/cosa/repo/symindex/ts_extract.js --reporter=text
```

## Known limits

- `#2`, `#3` id suffixes follow source order, so inserting an earlier duplicate renumbers the later ones.
- Routes: `APIRouter` and `FastAPI()` receivers with a literal path. A non-literal path, a route added with
  `add_api_route`, and a decorator on an attribute receiver (`self.router`) are not indexed.
- The Firefox plugin's JS (a separate repository) is not indexed.
