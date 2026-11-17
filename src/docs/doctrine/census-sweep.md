# Census sweep: unit tests that count across the whole tree

First sweep measured 14 November 2026 on the tree of `b84acd18b`. Second sweep (the three named gaps) measured the same day on the tree of `f20d11273`. The population is every tracked `src/tests/unit/**/*.py`.

## What selects a test

`src/tests/run-census-guards.sh` runs a test in the census if any one of these holds:

| Rule | Selects |
|---|---|
| File named `test_every_*`, `*census*`, `*_pin*`, `*pins*` or `*pinned*` | the whole file |
| Function named `test_every_*`, in any other file | that function |
| `@pytest.mark.census` on a function or class, in any other file | that function, or the whole class |

Add the mark when a test counts across the whole tree and its file name cannot change.

## Method

An AST scan of the files the name rule does not already pick. A function is a candidate when its body walks the tree (`git ls-files`, `git grep`, `os.walk`, `rglob`, `glob.glob`, `scan_tree`, `census(`). It is strong when it also asserts a count or an empty list and names the project root. The first sweep read the 16 strong ones by name and body.

## First sweep: result

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
| The other 9 strong candidates (`test_pyc_purge_on_checkout`, `test_stale_mcp_check`, `test_check_bundle_freshness` x2, `test_contended_coverage_guard` planted-child test, `test_doc_lint_ts_doc_exists` planted-export, `test_heartbeat_work_owed`, `test_reuse_outcome`, `test_reuse_search`) | not marked: each walks a copy or fixture, or checks one tool against the tree, and cannot go red from an unrelated new file |

## Second sweep: the three gaps

Rerunning the scan on `f20d11273` finds 209 test functions whose own body walks the tree; 44 were already selected and 165 were not. That 165 equals the first sweep's weak count by arithmetic only (181 - 16). The members were not compared against the first list.

| Gap | Measured | Ruling |
|---|---|---|
| 1. The unselected walkers read one by one | 165 read, each by walk line and assertions | 11 marked. The other 154 are not tree-wide counts: they walk a temporary tree or a copy, run a function named `census` over synthetic input (the fake `/proc` of `test_stale_mcp_check`, the parse of a pytest summary line), or are positive controls for a guard (`population > 1000`, "the census finds the known sites") that go red when a site is removed, never when one is added |
| 2. Walkers reached through a helper | 878 unit tests call a helper that walks, to three calls deep through names resolved in the same file or an imported repo module | 312 reach it through a helper under `src/tests/`; 566 through product code (`reconcile_worktrees`, `find_duplicates`, `tree_state_line` and the like). Of the 312, 33 are marked. Of the 566, 489 pass a temporary tree as a fixture and 77 take none; the 77 were read by name and 3 are marked, 74 are not (mocked arbiter factories, spawn gate, wake check) |
| 3. `src/cosa/tests/` | 7 tests walk, directly or through a helper | measured, not marked: the runner reads `git ls-files 'src/tests/unit/*'` only, so a mark there selects nothing. Two are whole-tree counts (`test_drop_hnsw_migration.py::test_no_two_migrations_share_a_down_revision`, `test_pgvector_migration.py::test_known_successors_only`). A follow-up row in the task store, titled "Census runner: also select marked guards under src/cosa/tests", extends the runner |

Marked in this sweep, direct walkers:

| File | Test |
|---|---|
| `deploy/test_no_password_literal_in_tracked_python.py` | `test_no_password_literal_in_tracked_python` |
| `lupin_mcp/test_the_promotion_opt_in_is_the_default_at_the_door.py` | `test_the_transition_surface_is_still_SEVEN_FILES` |
| `test_broadcast_ack_type_spellings_agree.py` | `test_the_multiplexer_does_not_inline_the_literal_anywhere_else` |
| `test_contended_coverage_guard.py` | `test_a_test_that_spawns_a_coverage_child_engages_the_escape_hatch` (it walks the real `src/tests`; the first sweep's ruling was for the planted-child test in the same file) |
| `test_notifications_js_one_play_audio_blob_and_no_fixed_email.py` | `test_nothing_else_in_the_static_tree_calls_a_legacy_get_current_user_email` |
| `test_reuse_phase5_run.py` | `test_only_this_driver_names_the_reserved_file_and_only_the_reader_and_this_test_hold_its_hash` |
| `test_scripts_name_collision_guard.py` | `test_the_declared_conf_collision_is_still_unreachable` |
| `test_sdk_error_result_login_hint.py` | `test_only_the_dispatcher_and_the_in_process_writer_call_error_result_text_directly` |
| `test_step12_internal_callers_use_flow_submit.py` | `test_no_internal_caller_still_reaches_the_queue_directly` |
| `test_task_approval_gate.py` | `test_the_holding_default_can_only_reach_a_create_never_an_existing_row` |
| `test_vector_refresh.py` | `test_no_script_calls_the_retired_install_verb_and_lupin_vm_sh_runs_cron_generate_for_this_job_instead` |

Marked in this sweep, helper-reached. Each is the guard of its file. The helper scan found them. Each was read by name, helper and assertion count. The files are:

- `test_git_pathspecs_are_anchored`
- `test_6c_push_job_has_no_production_caller`
- `test_admin_time_module`
- `test_connection_skips_route_through_the_helper` (two)
- `test_coverage_frame_excludes_non_src`
- `test_coverage_frame_completeness` (two)
- `test_database_creation_goes_through_the_helper`
- `test_e2e_first_click_names_its_own_row`
- `test_evidence_fidelity_guard`
- `test_job_state_transition_call_sites`
- `test_model_migration_drift`
- `test_no_env_beats_self_derived_root`
- `test_no_hardcoded_gcp_identifiers` (three)
- `test_no_off_origin_refs_in_served_html`
- `test_no_shadowing_bytecode`
- `test_no_static_client_calls_a_retired_door`
- `test_no_stylesheet_gives_the_error_stripe_row_a_display`
- `test_no_stylesheet_sizes_the_detail_field`
- `test_no_test_writes_the_live_artifact_root`
- `test_poked_rename_consistency`
- `test_pragma_reason_policy`
- `test_rnd_ledger_coverage_and_read_rule`
- `test_scripts_name_collision_guard` (three)
- `test_task_body_overlay_cache_bust` (three)
- `test_the_file_based_snapshot_backend_is_gone`
- `test_the_test_venue_never_drops_tables`
- `test_unit_suite_is_not_offered_in_the_container`
- `test_unpark_on_a_server_made_card`

## Census selection count

`run-census-guards.sh --list` printed 454 ids on `f20d11273` before the marks, and 501 after: 55 files by name and 446 test ids. The first sweep recorded 443 before and 450 after its seven marks, on an older tree. A marked parametrized test counts once per case.

## Named gaps still open

- The scan reads the text of each body, not what it asserts about a population. Every ruling is a judgement from names, helper chains and bodies, made once on this date.
- A helper reached by a name the scan cannot resolve is invisible to it. That means a method, an attribute of a fixture, or a call deeper than three. The count is unmeasured.
- The 566 product-code helper reaches were ruled by fixture signature, not each by body. 489 take a temporary tree. The 77 that take none were read by name.
