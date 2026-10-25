---
capability: repo-tools-candidate-storage-paths
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.storage_paths.build_config@2edbd2a3b5
  - cosa.repo.symindex.candidates.storage_paths.data_subdir@7c43fa990b
  - cosa.repo.symindex.candidates.storage_paths.candidate_dir@7099737910
  - cosa.repo.symindex.candidates.storage_paths.search_interpreter@728770d5c6
  - cosa.repo.symindex.candidates.storage_paths.main_checkout@5967b0a20d
  - cosa.repo.symindex.candidates.storage_paths.handoff_dir@0c6e18e1da
  - cosa.repo.symindex.candidates.storage_paths.container_path@d87be61ec8
  - cosa.repo.symindex.candidates.storage_paths.shortlist_arm@70d5d06fa0
---
# Candidate storage paths

Every location of the candidate stage comes from an INI key, and an environment variable overrides it. No path is written in code, and a missing key is a named error, never a default.

## Keys
- `KEYS` maps seven names to an INI key and an environment variable. They are: data subdir (`LUPIN_REUSE_REVIEW_DATA_SUBDIR`), vectors, query cache, purpose lines, search interpreter, handoff and container root. The six candidate keys use `LUPIN_REUSE_CANDIDATE_*` names.
- `build_config()` builds the `ConfigurationManager` from `LUPIN_CONFIG_MGR_CLI_ARGS`, or raises `DEPENDENCY_MISSING`.
- `data_subdir( config=None, environ=None )` returns the reuse-review folder name. It raises `STORAGE_KEY_MISSING` when neither source is set.

## Directories
- `candidate_dir( name, data_directory )` takes `vectors`, `query_cache` or `purpose`. An INI value is relative to `data_directory`; an override must be absolute.
- `search_interpreter()` returns the path that runs the search process and raises `DEPENDENCY_MISSING` when the key is absent or the file is not there.

## Handoff to a container
- `main_checkout( root )` resolves a worktree to its parent checkout, which the containers mount.
- `handoff_dir( root )` is where the purpose-line job's request and response files are exchanged. An INI value is relative to the main checkout; an override must be absolute.
- `container_path( host_path, root )` translates a host path under the main checkout to the container's path, or raises `HANDOFF_NOT_IN_CONTAINER`.

## Shortlist arm
- `shortlist_arm( default, config=None, environ=None )` returns the search arm the shipped stage runs. `LUPIN_REUSE_CANDIDATE_ARM` wins when set and not blank. Otherwise the INI key `reuse candidate shortlist arm` is used, and otherwise `default`.
- The name is stripped and not checked here, because the stage refuses an unknown arm. It raises `DEPENDENCY_MISSING` when the INI must be read and no manager can be built.
