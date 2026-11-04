---
capability: repo-tools-symindex-core-dart
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.dart_extractor.check_dependencies@363b1eacef
  - cosa.repo.symindex.dart_extractor.extract_dart@e4c13c94e9
  - cosa.repo.symindex.dart_extractor.find_dart@67910d19c6
  - cosa.repo.symindex.dart_extractor.prepare_scratch@44cd31475c
  - cosa.repo.symindex.dart_extractor.sibling_dart@d33d967fa7
---
# Symbol index: the Dart extractor

Indexes a Flutter tree such as `lupin-mobile`. It parses syntax only, through `dart_extract.dart` and the analyzer package, and writes nothing into the tree being indexed. The record contract is on [[repo-tools-symindex-core-extractors]].

## Finding the tools
- `find_dart( root )` returns the first dart executable it can use, in this order: the `LUPIN_DART` variable, `<root>/flutter/bin/dart`, `dart` on `PATH`, then `sibling_dart()`. It returns `None` when there is none.
- `sibling_dart()` walks up from the project root and returns the first `lupin-mobile/flutter/bin/dart` found beside an ancestor. That covers the main checkout and any worktree under `.claude/worktrees`.
- `check_dependencies( root=None )` returns `None` when dart is found and analyzer 7.7.1 is in the pub cache (`PUB_CACHE`, else `~/.pub-cache`). Otherwise it raises `DependencyMissing` with what `dart` or `analyzer`.

## Running it
- `prepare_scratch( dart, data_root )` makes the scratch pub project `dart-scratch` under the repo's data folder, with a pubspec and a copy of the script. It runs `pub get` offline first and online only if that fails, and skips it when nothing changed and packages are resolved. It raises `DependencyMissing` when the analyzer cannot be resolved.
- `extract_dart( root, files, data_root, ... )` returns one record per declaration, with `lang` set to `dart`, each passing `validate_record`. An empty file list returns `[]` without looking for dart.
- A file with parse errors yields no records. It is named in a warning (stderr unless a `warnings` list is passed) and appended to `unparsed`, so the index header lists it.
- Typedefs, top-level variables and constants are not indexed. A failing script raises `RuntimeError` carrying its stderr.
