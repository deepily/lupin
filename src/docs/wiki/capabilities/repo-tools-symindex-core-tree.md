---
capability: repo-tools-symindex-core-tree
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.spec.IndexSpec@f7b067cb99
  - cosa.repo.symindex.spec.NotARepo@51835f1312
  - cosa.repo.symindex.spec.all_files@9b1b676e82
  - cosa.repo.symindex.spec.git_toplevel@2b61563bc7
  - cosa.repo.symindex.spec.is_lupin_tree@2e91e30932
  - cosa.repo.symindex.spec.iter_files@fd6f9ece34
  - cosa.repo.symindex.spec.manifest@f74658b557
  - cosa.repo.symindex.spec.skipped@b19801eed4
  - cosa.repo.symindex.spec.is_test_path@d43ece9f59
  - cosa.repo.symindex.paths.data_dir@c20448be9c
  - cosa.repo.symindex.paths.index_readable@7cb2af5d9a
  - cosa.repo.symindex.paths.registered_repo_names@9ff11b29de
  - cosa.repo.symindex.errors.DependencyMissing@0301641e93
---
# Symbol index: which files, where output goes

`spec_for` and `default_out_dir` are on [[symbol-index]]. This page holds the pieces they are built from.

## Choosing the tree
- `git_toplevel( start=None )` returns the git working-tree root holding `start` (default: the current directory). It raises `NotARepo` outside a work tree.
- `is_lupin_tree( root )` is true when `src/cosa` and `src/lupin_mcp` both exist under `root`.
- `IndexSpec` holds one answer: `root`, `name`, the Python, JavaScript and Dart roots, the `module_base` that module names are taken from, and the skipped directory names. Its constructor checks no directory.

## Which files count
- `skipped( rel_path, skip_parts )` is true when a directory part of the path is in `skip_parts`. It is also true when the name ends in `.d.ts`, `.min.js`, `.g.dart` or `.freezed.dart`. The file's own name is never matched against the directory names.
- `iter_files( spec, roots, suffixes )` returns the sorted, de-duplicated absolute paths under `roots` with one of the suffixes that are not skipped relative to `spec.root`.
- `all_files( spec )` is the union of the Python, script (`.js`, `.mjs`, `.cjs`, `.ts`, `.tsx`) and Dart lists. `manifest` reads it. The build makes its own three `iter_files` calls, so the two populations are not tied by one shared function.
- `manifest( spec )` is a sha1 over each indexed file's relative path, mtime in nanoseconds and size. An added, deleted, resized or touched file changes it.

## Output and failures
- `data_dir( index_root )` returns the reuse-review data folder of the repository: the fleet data root of that repo plus the `reuse review data subdir` setting. A worktree resolves to its parent checkout. The folder is not created. It raises `CandidateError` `STORAGE_KEY_MISSING` when neither the INI key nor its override is set.
- `DependencyMissing( what, detail="" )` is raised for an absent node, typescript, dart or analyzer. Its `what` attribute names the tool, and the build records it in `missing_dependencies`.
- `index_readable( root )` is the test every `NOT_LUPIN_TREE` site shares. It is true for a lupin tree, or a registered repo with a built, published index. `registered_repo_names` reads the `external repos` list. `is_test_path` is true for a path with a `tests` folder.
