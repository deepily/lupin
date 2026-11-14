# Census sweep: unit tests that count across the whole tree

Measured 14 November 2026 on the tree of `b84acd18b`. The population is every tracked `src/tests/unit/**/*.py`: 181 test functions whose own body walks the tree.

## What selects a test

`src/tests/run-census-guards.sh` runs a test in the census if any one of these holds:

| Rule | Selects |
|---|---|
| File named `test_every_*`, `*census*`, `*_pin*`, `*pins*` or `*pinned*` | the whole file |
| Function named `test_every_*`, in any other file | that function |
| `@pytest.mark.census` on a function or class, in any other file | that function, or the whole class |

Add the mark when a test counts across the whole tree and its file name cannot change.

## Method

An AST scan of the files the name rule does not already pick. A function is a candidate when its body walks the tree (`git ls-files`, `git grep`, `os.walk`, `rglob`, `glob.glob`, `scan_tree`, `census(`). It is strong when it also asserts a count or an empty list and names the project root. 16 were strong (7 marked here, 9 not, plus `TestTheRatchet` which the scan skipped because bd90df1b5 had marked it). Each was read by name and body.

## Result

| Test | Ruling |
|---|---|
| `test_dom_assert_lint.py::TestTheRatchet` | marked (bd90df1b5) |
| `test_both_js_test_doors_reach_the_same_cap.py::test_the_corpus_is_exactly_the_two_known_doors` | marked |
| `test_doc_lint_counts.py::test_the_rule_files_of_the_real_tree_match_what_git_lists_for_that_set_and_are_not_empty` | marked |
| `test_doc_lint_ts_doc_exists.py::test_the_real_census_runs_over_this_repository_and_reads_every_file` | marked |
| `test_hook_spawn_stdout_discipline.py::test_hook_tree_has_no_unredirected_popen` | marked |
| `test_no_bare_pisp_invocation.py::test_no_instructing_file_hands_a_seat_an_unrunnable_pisp_command` | marked |
| `test_no_git_conflict_markers_in_src.py::test_no_tracked_file_under_src_carries_a_conflict_marker` | marked |
| `test_router_corpus_consistency.py::TestDuplicateGroupsDoNotGrow` | marked (class) |
| The other 9 strong candidates (`test_pyc_purge_on_checkout`, `test_stale_mcp_check`, `test_check_bundle_freshness` x2, `test_contended_coverage_guard`, `test_doc_lint_ts_doc_exists` planted-export, `test_heartbeat_work_owed`, `test_reuse_outcome`, `test_reuse_search`) | not marked: each walks a copy or fixture, or checks one tool against the tree, and cannot go red from an unrelated new file |

Before this row, 11 of the 181 walkers were already selected (by name or `test_every_`). The 165 weak candidates (a walk, but no count or no root) were not read one by one.

## Named gaps

- A test that reaches the tree through a helper in another module has no walk in its own body, so this scan cannot see it. The count of those is unmeasured.
- The scan reads the text of each body, not what it asserts about a population. The strong list is a judgement from names and bodies, made once on this date.
- The unit directory only. `src/cosa/tests/` has its own census guards and was not swept.
