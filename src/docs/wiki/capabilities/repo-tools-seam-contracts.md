---
capability: repo-tools-seam-contracts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.spec.IndexSpec@8cb186ff48
  - cosa.repo.symindex.spec.detected_spec@7a0be26984
  - lupin_cli.claude_code.hooks.lib.heartbeat_hold.fleet_data_root@f42b2cc795
  - cosa.memory.embedding_provider.EmbeddingProvider@37be6ca656
  - cosa.repo.duplicate_check.judge.judge_run@3ad6419146
  - cosa.repo.symindex.task_store_adapter.TaskStoreAdapter@a788853e36
  - cosa.utils.hook_link_tick.notify_route@42195f40bf
  - lupin_mcp.cron_generate.lines_for_job@ae3a14af36
---
# Code-health seam contracts

The code-health tools share eight seams. A seam is a name and a contract for something that already exists, never a new class; Lupin's code is the first implementation of each. Each default below is pinned by a test in `src/tests/unit/test_seam_contract_defaults.py` against a literal taken from the base sha, so a changed default fails that test. See [[repo-tools-code-health-settings]] for the INI keys that override these defaults, and [[job-cron-generate]] for the lines the `Scheduler` seam writes.

## IndexSpec
Answers which files, languages and branch an index covers. `IndexSpec` holds `py_roots`, `js_roots`, `dart_roots`, `module_base` and `skip_parts`. `detected_spec` fills them from the tree. A lupin layout indexes the lupin packages and script roots, with `module_base` set to `src`. A Flutter tree indexes `lib/` as Dart. Any other tree indexes every Python and script file under its root. The INI keys override detection field by field, and a blank key keeps the detected value. The default skip set is `tests`, `migrations`, `.venv`, `vendor`, `node_modules`, `rnd`, `__pycache__` and `.git`.
## DataRoot
Answers where one repo keeps its state. `fleet_data_root` returns `<DEEPILY_DATA_DIR>/<repo-name>`, named for the checkout, and a worktree resolves to its parent checkout. With the variable unset it derives the sibling `projects-data/<repo-name>` rather than falling back to the repo root. INI `... subdir` keys are relative to this folder.
## EmbeddingProvider
Answers text to vector. `EmbeddingProvider` owns the route and the key file. A process that does not own the engines reaches the server named by `LUPIN_APP_SERVER_URL`, read on every call. The default is `http://localhost:7999`, and a blank value counts as unset.

## Judge
Answers whether definition A is the same job as definition B, for the duplicate check only. `judge_run` takes a backend that carries `.name`, `.server_label` and `.complete( model, system, user )`. The model is the global INI key `duplicate check judge model`, not a per-repo value. It is part of the config sha, so a new model needs its own frozen config. The doc-lint judges are a separate seam with a different shape and are not covered here.

## TaskStoreAdapter
Answers how to file a finding as a row, idempotently. `TaskStoreAdapter` is the shared base of the live adapters. The stamped defaults are `PROJECT = "lupin"` in the filing module and `sender_project` `lupin` in the librarian's direct message (`notify_owner`). Owner and managers are not part of this seam; each has one home in the settings.

## Notifier
Answers how to tell a person that something failed or slipped. `notify_route` resolves the API base, key and recipient, and `send_notify` posts to `/api/notify`. The caller names the variable that holds the base: the duplicate check and librarian use `LUPIN_API_BASE`, the hook-link tick and the doc-lint gate use `HOOK_LINK_API_BASE`. The default is `http://localhost:7999`. The duplicate check posts under the sender id `claude.code@lupin.deepily.ai#duplicate-check-daily`.

## Scheduler
Answers how the registry becomes cron lines and how each run gets its full environment. A registry row's `repo` key names its repo, and `repo_of` returns `lupin` when the key is absent. `lines_for_job` gives a row of another repo its own `--root`, config assignment and data folder; a Lupin row's lines are unchanged. Schedules live in the registry and limits live in the INI.

## Gate
Answers whether a commit or merge is refused. The gate scripts are the doc-lint gates, the reuse gates and the git hook chain. `install-git-hooks.sh` fixes two hook names, `pre-commit` and `pre-push`, and their two chain scripts, and links to the scripts of the checkout it runs in. The INI has no gate key, so a gate is Lupin-only until a repo supplies its own chain scripts.
