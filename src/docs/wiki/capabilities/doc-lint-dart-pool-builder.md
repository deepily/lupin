---
capability: doc-lint-dart-pool-builder
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.dart_pool_builder.read_file_list@8922bce0d8
  - cosa.repo.doc_lint.dart_pool_builder.refusal_reason@40e1595bd7
  - cosa.repo.doc_lint.dart_pool_builder.list_blobs@bdcd6d06d4
  - cosa.repo.doc_lint.dart_pool_builder.dart_rows@e5a3c6ac4e
  - cosa.repo.doc_lint.dart_pool_builder.build_dart_pool@c9c002ebca
  - cosa.repo.doc_lint.dart_pool_builder.builder_sha256@4b6a27c6b0
  - cosa.repo.doc_lint.dart_pool_builder.write_pool@2d26f3d527
  - cosa.repo.doc_lint.dart_pool_builder.build_parser@c0f3cac4fb
  - cosa.repo.doc_lint.dart_pool_builder.main@09f8c0eb64
---
# Doc-lint Dart pool builder

Builds the pool of Dart doc blocks that the labelled-set seeder's plan step draws from. It reuses the block reader of [[doc-lint-dart-pairs]]; the Python pool is [[doc-lint-pool-builder]].

## Population
- `read_file_list` reads one repo-relative path per line, ignoring blank lines. The listed files are the whole population, and no disk walk finds more.
- `refusal_reason` names a file that may not enter: `test file` for a `test` or `integration_test` directory, `generated file` for `.g.dart`, `.freezed.dart` and `.mocks.dart`.
- `list_blobs` finds each file's blob at one commit. It raises `ValueError` for an empty list or a path not ending in `.dart`. It also raises for a test or generated file, or a path that is no blob there.

## Rows and output
- `dart_rows` returns one file's rows and its unattached count. A row is `{ id, file, symbol, old }` with ids `<file>::<symbol>`. A block that names no declaration is left out and counted.
- `build_dart_pool` keeps one row per distinct doc text and returns the facts the manifest records.
- `write_pool` writes the rows, sorted keys one per line, and a `.manifest.json` with the facts and the builder and pool hashes. `builder_sha256` hashes this module's own file.
- `build_parser` and `main` build one pool. `main` returns 0, or 2 after printing why it refused.
