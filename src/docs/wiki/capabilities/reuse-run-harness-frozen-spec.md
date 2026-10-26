---
capability: reuse-run-harness-frozen-spec
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.freeze.feature_ids@e85d28121f
  - lupin_mcp.reuse_harness.freeze.collect_tests@80b38659f6
  - lupin_mcp.reuse_harness.freeze.check_feature_map@95d745bad4
  - lupin_mcp.reuse_harness.freeze.build_spec@5354831e30
  - lupin_mcp.reuse_harness.gitrepo.GitRepo@9ea9104ce4
  - lupin_mcp.reuse_harness.gitrepo.GitRepo.resolve@9ebbe77b9f
  - lupin_mcp.reuse_harness.gitrepo.GitRepo.is_ancestor@ee333aff62
  - lupin_mcp.reuse_harness.gitrepo.GitRepo.list_at@1c1f7b14ab
  - lupin_mcp.reuse_harness.gitrepo.GitRepo.file_at@22af3d438a
---
# Reuse run harness: the frozen spec

This page covers how a run's spec comes from the commit Rick froze. See [[reuse-run-harness]] for the run.

## What it reads
- `build_spec` reads the test files and the feature list from the frozen commit. It never reads the tip of main.
- A sha that names no commit, or that main does not hold, is `NOT_FROZEN`.
- `GitRepo` answers four questions from the commit. They are its full sha, whether main holds it, the files directly in a folder, and one file's text.

## What it refuses
- `collect_tests` maps each module-level test function to its `feature` markers.
- `check_feature_map` refuses an unmarked test, a marker naming no listed feature, and a feature with no test.
- A `Test` class is refused, because its methods would go uncounted.
- `feature_ids` reads the ids from the table rows of the feature list.

## Don't
- Don't read the freeze from the working tree. A later commit can add a test or a feature row.
