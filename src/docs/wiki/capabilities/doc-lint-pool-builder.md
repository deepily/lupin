---
capability: doc-lint-pool-builder
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.pool_builder.run_git@9183aac4ce
  - cosa.repo.doc_lint.pool_builder.resolve_commit@73b839f6ae
  - cosa.repo.doc_lint.pool_builder.prefix_of@6f9b8cfb4a
  - cosa.repo.doc_lint.pool_builder.list_sources@cb4d4e067e
  - cosa.repo.doc_lint.pool_builder.read_blobs@359a587045
  - cosa.repo.doc_lint.pool_builder.docstrings_of@5087a8049a
  - cosa.repo.doc_lint.pool_builder.pool_rows@d46e2890ba
  - cosa.repo.doc_lint.pool_builder.normalised@0ce2aafda2
  - cosa.repo.doc_lint.pool_builder.drop_duplicates@ec4ce4c596
  - cosa.repo.doc_lint.pool_builder.build_pool@3bc0dfb113
  - cosa.repo.doc_lint.pool_builder.builder_sha256@4b6a27c6b0
  - cosa.repo.doc_lint.pool_builder.write_pool@6d3a8141b7
  - cosa.repo.doc_lint.pool_builder.build_parser@637276283a
  - cosa.repo.doc_lint.pool_builder.main@ffb483566e
---
# Doc-lint docstring pool builder

Builds the pool of Python docstrings that the labelled-set seeder's plan step draws from. The Dart equivalent is [[doc-lint-dart-pool-builder]].

## Reading the commit
- `run_git` returns a command's stdout bytes, and `resolve_commit` returns the full sha. Both raise `RuntimeError` naming the command or the ref on failure.
- `prefix_of` gives a directory prefix with one trailing slash, so `src/cosa` misses `src/cosa_x`. `list_sources` lists tracked `.py` blobs under the include and outside the exclude prefixes, minus `SKIP_PARTS` directories and submodules.
- `read_blobs` reads blobs by oid with one git process and raises when git reports an oid missing.

## Rows
- `docstrings_of` returns the symbol and docstring of the module and each class or function that has one. The whole tree is walked, so a definition under an `if` or `try` is found.
- `pool_rows` returns `{ id, file, symbol, old }` per docstring, with ids `<file>::<symbol>` and `#2`, `#3` for a repeat. Text that is not UTF-8 or does not parse is skipped with its reason.
- `normalised` collapses white space. `drop_duplicates` keeps one row per distinct normalised text, the one with the smallest id, and lists what it dropped.

## Pool and manifest
- `build_pool` sorts rows by file and source order, so one commit always gives the same rows, and returns the facts the manifest records. An empty include or an empty pool raises `ValueError`.
- `write_pool` writes sorted-key rows, one per line, and a `.manifest.json` with the facts, `builder_sha256` and `pool_sha256`. `builder_sha256` hashes this module's own file.
- `write_pool` takes an optional `builder_sha`. The manifest records it, or this module's hash when it is `None`. [[doc-lint-dart-pool-builder]] passes its own.
- `build_parser` and `main` build one pool and return 0, or 2 after printing why it refused.
