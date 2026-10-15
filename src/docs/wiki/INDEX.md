# Capability index

One line per capability: `[[slug]]`, what it covers, the packages it spans. A rewritten `Design:` line points at `wiki/capabilities/<slug>.md`. Every slug below has a page. The slugs were approved provisionally; the JavaScript and TypeScript revisit is still owed.

Drafted from the symbol index built at lupin `a7f2af593` (7,240 public symbols, 227 routes) and `python -m cosa.repo.symindex dups`. Package names are dotted import paths under `src/`.

## Job queue and agents

- [[cj-flow-queue]] — the todo, running, done and dead queues, the agentic pool, the ghost-job sweeper and job persistence. `cosa.rest` (fifo_queue, todo_fifo_queue, running_fifo_queue, queue_consumer, queue_protocol, job_persistence, dead_queue_watchdog), `cosa.agents.agentic_job_base`
- [[agent-llm-clients]] — the shared LLM client layer: model registry, client factory, completion and chat clients, token counting, prompt formatting, LLM exceptions. `cosa.agents` (llm_client, llm_client_factory, model_registry, base_llm_client, completion_client, token_counter, prompt_formatter, llm_exceptions)
- [[bounded-claude-code-jobs]] — running a Claude Code task as a bounded or interactive CJ Flow job, and dispatching it. `cosa.agents.claude_code`, `cosa.orchestration.claude_code`
- [[xml-io-models]] — the XML request and response models agents parse and emit. `cosa.agents.io_models`, `cosa.agents.dm_compression`, `cosa.agents.dm_tutor`, `cosa.crud_for_dataframes` (xml_models)
- [[dataframe-crud]] — CRUD over DataFrames, storage, schemas and the intent dispatcher. `cosa.crud_for_dataframes`
- [[dataframe-crud-operations]] — list, update, mark-done and query functions, the spoken answer for each result and the calendar agent. `cosa.crud_for_dataframes` (crud_operations, dispatcher, calendar_crud_agent)
- [[dataframe-crud-schemas-and-intent]] — the todo, calendar and generic column definitions, the parsed `CRUDIntent` and the intent prompt. `cosa.crud_for_dataframes` (schemas, xml_models, intent_extractor)

## Notifications, decisions and voice

- [[notification-delivery]] — creating, routing and expiring notifications and their types, rate limits and push. `lupin_cli.notifications`, `cosa.rest` (notification_fifo_queue, notify_rate_limiter, notification_expiry_sweeper, fcm_push_pause, fcm_wake_service), `cosa.rest.routers`
- [[websocket-events]] — session-keyed WebSocket connections, subscriptions and event fan-out. `cosa.rest` (websocket_manager, routers), `lupin_app.main`
- [[decision-proxy]] — trust-scored auto-answering of questions, ratification, and the notification proxy. `cosa.agents` (decision_proxy, notification_proxy, dm_quality_judge)

## Fleet, heartbeat and the task store

- [[heartbeat-arbiter]] — fleet liveness: the arbiter loop, watchdogs, escalation, context-pressure, health watcher and the poker job. `cosa.agents` (heartbeat_arbiter, heartbeat_poker_job, heartbeat_poker_commons_gateway), `lupin_arbiter_app`, `cosa.rest` (follow_through_escalation_watcher, commons_*_watcher)
- [[claude-code-hooks]] — the session-start, stop, pre/post tool and prompt hooks, heartbeat events and the session bridge. `lupin_cli.claude_code.hooks`
- [[seat-lifecycle]] — spawning seats, the fleet size cap, mementos, self re-spin, reaping and worktree hygiene. `lupin_mcp` (session_spawner, fleet_size_cap, fleet_cap_*, memento_*, reap_*, self_respin_core)

## Auth, data and platform

- [[auth-and-accounts]] — JWT, refresh tokens, API keys, users, passwords, email tokens, rate limits and audit. `cosa.rest` (auth, auth_middleware, auth_models, jwt_service, user_service, admin_service, refresh_token_service, password_service, email_*), `cosa.rest.db.repositories` (token and api-key repositories)
- [[solution-memory]] — solution snapshots, embeddings, canonical synonyms and snapshot managers. `cosa.memory`, `cosa.rest.db.repositories` (solution_snapshot, embedding_cache, question_embedding, canonical_synonym), `lupin_model_server`
- [[rest-routers]] — the FastAPI routers and the v2 submit surface. `cosa.rest.routers`, `cosa.rest.v2`, `lupin_app` (main, bootstrap_helpers, asset_tokens, versioned_static)
- [[configuration]] — INI configuration, the config cache registry and the doc-viewer manifest. `cosa.config`
- [[shared-utilities]] — path and project-root helpers, memory watch, Vertex logging, checked-hash bytecode. `cosa.utils`, `cosa.tools`

## Quality tooling

- [[test-and-eval-scripts]] — test harnesses, falsify, coverage and scan scripts, evaluation and probe scripts, migrations. `scripts`, `cosa.agents.test_harness`
- [[model-training]] — PEFT training, XML prompt generation and validation, quantization. `cosa.training`, `cosa.research`

## Web client


## Written pages (added at assembly)

Pages with two passes at one sha, one line each: `[[slug]]`, what it covers, the packages it pins. `[[agent-llm-clients]]` is written too; its line is above.

- [[agent-voice-io]] — how a job tells the user something or asks a question, and what it does when nobody can answer. `cosa.agents.utils` (voice_io, sender_id, sync_notify), `cosa.agents.deep_research` (cosa_interface, voice_io)
- [[agentic-job-contract]] — `AgenticJobBase`: the fields and lifecycle every long-running queue job provides. `cosa.agents` (agentic_job_base), `cosa.agents.claude_code`, `cosa.agents.deep_research`
- [[deep-research]] — answering a question from the web and saving a markdown report. `cosa.agents.deep_research` (cli, search_cache, seed_context)
- [[generator-sdk-clients]] — the Claude Agent SDK client classes of the podcast, presentation and deep-research agents. `cosa.agents.podcast_generator`, `cosa.agents.presentation_generator`, `cosa.agents.deep_research` (api_client)
- [[presentation-generation]] — turning a source document into a YAML deck, Marp Markdown and a pptx, with its review gates. `cosa.agents.presentation_generator` (job, deck_verdict)
- [[presentation-visual-renderers]] — the seventh pipeline phase, which replaces each `VISUAL` marker in the Marp file with renderer output. `cosa.agents.presentation_generator.renderers`
- [[podcast-generation]] — turning a research document into a two-host script and one MP3 per language. `cosa.agents.podcast_generator` (orchestrator)
- [[fix-expediter-bfe]] — the bug-fix expediter: takes one dead queue job and tries to fix the code that killed it. `cosa.agents.bug_fix_expediter`
- [[fix-expediter-tfe]] — the test-fix expediter: clusters one finished suite's failures, fixes them and queues a rerun. `cosa.agents.test_fix_expediter` (cluster, resume_resolver)
- [[fix-shared-primitives]] — the coder and tester retry loop, the git step and the plan and report writers both expediters use. `cosa.agents.shared` (fix_executor)
- [[swe-team-orchestrator]] — the SWE team job: a Lead splits a task, a Coder builds each piece, a Tester checks it. `cosa.agents.swe_team` (agent_definitions)
- [[scheduled-test-suite]] — the test suite runner as a queue job, its scheduling and attestation. `cosa.agents.test_suite` (job, attestation, v2_client)
- [[notification-proxy]] — a separate process that answers response-required notifications by following a script for a test profile. `cosa.agents.notification_proxy` (option_sentinels, scalar_answers, strategies)
- [[proxy-agent-base]] — the shared layer under the proxy agents: WebSocket listener, responder base, strategy protocol, REST submitter, settings and flags. `cosa.agents.utils.proxy_agents` (base_cli, base_config, rest_submitter)
- [[dev-server-lifecycle]] — small modules that say whether a server is free, announce its restarts and name the code it runs. `cosa.rest` (venue_idle, managed_bounce_broadcast, code_identity, error_envelope, pytest_args_policy)
- [[embedding-pipeline]] — turning text into vectors, caching them and searching them in Postgres. `cosa.memory`, `cosa.rest.db` (embedding_regeneration, repositories.vector_search)
- [[question-gist-and-synonyms]] — reducing a spoken question to verbatim, normalized and gist forms so a repeat skips the similarity search. `cosa.memory`, `cosa.rest.db.repositories`
- [[web-search-tools]] — the Kagi search client and the vendor-neutral wrapper the weather agent and router fallback use. `cosa.tools` (search_kagi)
- [[commons-and-dm]] — the server half of cross-session messaging: operator broadcasts and AI-to-AI direct messages. `cosa.rest` (dm_experiment), `cosa.rest.routers` (commons, dm)
- [[retired-queue-doors]] — the old queue routes that now answer 410 Gone and name the door that replaced them. `cosa.rest.routers` (_retired_doors)
- [[cc-session-bridge]] — the per-process `cc-<pid>.json` file that carries a Claude Code seat's session ids and voice persona. `lupin_cli.claude_code.hooks.lib` (session_bridge, sessions_dir)
- [[cc-hooks-git-guards]] — the five text-matching guards that refuse or flag a risky `git` or `kill` command before it runs. `lupin_cli.claude_code.hooks` (pre_tool_use), `lupin_cli.claude_code.hooks.lib` (branch_lock_guard, commit_scope_guard, kill_guard, merge_head_guard, stash_guard)
- [[cc-hooks-heartbeat]] — the stop hook's check of whether a seat still owes work, and the poke that blocks the stop. `lupin_cli.claude_code.hooks.lib` (heartbeat_decision, heartbeat_hold, heartbeat_poke_cap, heartbeat_poke_mute, heartbeat_user_gates, heartbeat_work_owed)
- [[research-chained-pipelines]] — the two jobs that run deep research and hand its report to podcast or presentation generation. `cosa.agents` (deep_research_to_podcast, deep_research_to_presentation)
- [[doc-lint-gate]] — the pre-commit gate that lints docstrings, comments and markdown on staged files. `cosa.repo.doc_lint` (gate, cli, changed_ranges, text_rules)
- [[cosa-voice-mcp-server]] — the FastMCP server a seat uses to speak, ask blocking questions and read or change its session state. `lupin_mcp` (cosa_voice_mcp)
- [[db-session-and-schema]] — the Postgres engine, session manager, ORM base, boot-time Alembic upgrade and schema drift check. `cosa.rest.db` (database, auto_migrate, schema_drift)
- [[branch-and-directory-loc-analysis]] — counting lines of code by branch change, by directory and by day. `cosa.repo` (branch_analyzer, directory_analyzer, git_loc_delta)
- [[claude-code-dispatch]] — `ClaudeCodeDispatcher`: runs one bounded or interactive Claude Code task and returns its result. `cosa.orchestration.claude_code`
- [[agy-runtime]] — one prompt through Google's `agy` command-line agent and one raw answer back, with a pinned binary fingerprint. `cosa.orchestration.agy`
- [[embedding-caches-and-pool]] — the question and text embedding caches, the OpenAI embedding manager, engine accessors and the bounded embedding pool. `cosa.memory`
- [[solution-manager-backend]] — the Postgres snapshot manager, its factory and converters, the two-tier search helpers and the input-output and query-log tables. `cosa.memory`
- [[training-corpus-and-trainer-tools]] — the training corpus fingerprint and the privilege, environment and GPU helpers `peft_trainer` runs. `cosa.training`
- [[worktree-lifecycle]] — how git worktrees are made for each spawned seat and each BFE or TFE job. Teardown, the reaper and the janitor remove them. `cosa.agents.shared` (seat_teardown, worktree_reaper, worktree_refusal_ledger, worktree_straggler_tickets), `cosa.utils` (seat_worktree, worktree_artifacts)
- [[small-agents-core]] — seven small agents that answer one voice or text request each, inline on the queue's consumer thread. `cosa.agents` (calculator), `cosa.rest.v2`, `cosa.utils.util_code_runner`
- [[mcp-session-spawn-and-reap]] — the four MCP tools a manager seat uses to start, list and end Claude Code seats. `lupin_mcp` (session_spawner, reap_memento, self_respin_core)
- [[session-transcript-console]] — showing another seat's transcript as display blocks: a REST backlog plus a live WebSocket tail, admin accounts only. `cosa.rest` (cc_transcript_mapper, cc_transcript_tailer), `cosa.rest.routers` (cc_transcript, websocket)
- [[doc-viewer]] — serving repo files and the `io/` folder to the browser by `path=<project>/<rel>`, and admin upload into them. `cosa.rest.routers` (docs_files, io_files, _scope_registry), `cosa.rest` (upload_size_guard), `cosa.config` (docview_manifest)
- [[system-admin-and-stats]] — the small routers that report on the server, steer it, and map clean URLs to pages. `cosa.rest.routers` (system, mode, stats, multiplexer_config, pages, websocket_admin)
- [[symbol-index]] — the list of every Python, JavaScript, TypeScript and Dart definition in a tree, each with a content pin that wiki pages quote. `cosa.repo.symindex` (build, py_index, spec, paths, wiki_lint)
- [[reuse-search-tools]] — the four MCP tools that ask whether a new definition already exists, reading the symbol index and the wiki. `lupin_mcp` (cosa_voice_mcp, reuse_tools, reuse_call_log_middleware), `cosa.repo.symindex` (verdict)
- [[mcp-task-store-tools]] — the ten MCP tools a session uses to read and write the task store over HTTP. `lupin_mcp` (task_store_tools, cosa_voice_mcp)
- [[mcp-commons-and-dm]] — the two ways a session talks to peers: the file blackboard (`commons_*`) and inline direct messages (`dm_*`). `lupin_mcp` (commons_store, commons_ask, cosa_voice_mcp)
- [[lupin-cli-notifications]] — the command-line clients that send a notification to the Lupin server, and the sync one that waits for the user's answer. `lupin_cli.notifications` (notify_user_sync, notify_user_async, notify_user, human_ask_containment)
- [[task-promotion-gate]] — the rules for moving a row out of the holding area onto a board, and for who may set a priority. `cosa.rest` (task_promotion_gate, task_promotion_resolver, task_request_lifecycle, task_request_pledge, task_priority_firewall, task_approval_settings)
- [[web-client-audio-and-tts]] — how the browser records speech for transcription and plays server-made speech through a queue. `src/lupin_app/static/js/multiplexer` (audio, render, shared, stores, wireTtsIntent)
- [[web-client-jobs-and-session-panes]] — the seven renderers that draw the jobs, submit, Q&A, session strip, persona modal, nav bar and reading panes. `src/lupin_app/static/js/multiplexer/render`
- [[web-client-transport-and-auth]] — the multiplexer page's two WebSockets, refreshable login token and in-page event bus, wired by `bootMultiplexer`. `src/lupin_app/static/js/multiplexer` (auth, transport, boot, shared)
- [[web-client-stores]] — the multiplexer page's state stores, each built by a `createXStore` function from the event bus and announcing change as a `store_*_changed` event. `src/lupin_app/static/js/multiplexer/stores`
- [[db-repositories]] — the Postgres repository classes built on one generic base, mapped to the capability that uses each, and the vector search they share. `cosa.rest.db` (repositories, database)
- [[web-client-task-board-panes]] — the four panes that show the task store: task list, epic board, holding area and finished tasks. `src/lupin_app/static/js/multiplexer/render`
- [[web-client-notification-panes]] — the pane renderers that draw notifications, action-required cards, broadcasts, commons activity and fleet status. `src/lupin_app/static/js/multiplexer` (render, stores)
- [[deep-research-door]] — the deep-research router: it serves finished reports and a health check, and no longer accepts jobs. `cosa.rest.routers` (deep_research, _retired_doors)
- [[app-bootstrap-and-static]] — how `lupin_app` builds the FastAPI app: startup root check, `/static` serving and cache-busting asset tokens. `lupin_app` (main, bootstrap_helpers, versioned_static, asset_tokens)
- [[dm-rewrite-model-study]] — the one-off package that compares Phi-4 14B on a local vLLM host with `gemini-3.1-flash-lite` on Vertex for the DM Tutor rewrite task. It replays frozen DM bodies. `cosa.research.phi4_flash_lite_study` (freeze_corpus, replay_harness)
- [[dm-rewrite-study-freeze]] — the helpers that checksum, filter, sample and verify the frozen DM replay set. `cosa.research.phi4_flash_lite_study` (freeze_corpus)
- [[dm-rewrite-study-replay]] — loading the snapshot, the per-arm guards, the outcome counts and latency, and the replay command line. `cosa.research.phi4_flash_lite_study` (replay_harness)
- [[dm-rewrite-study-checks]] — the arm-marker proof that each arm reached its model, and the McNemar and Wilson tests with their floor guards. `cosa.research.phi4_flash_lite_study` (arm_markers, statistics)
- [[dm-rewrite-study-report]] — the results report and the blind hand-labelling sheet with its answer key. `cosa.research.phi4_flash_lite_study` (report, label_sheet)
- [[voice-persona-allocation]] — how each Claude Code session gets a named voice, the speakerphone switch beside it, and the name normalization every persona lookup shares. `cosa.rest` (voice_persona_helpers), `cosa.rest.routers` (voice_persona, speakerphone), `lupin_mcp` (persona_normalization, commons_persona_matcher, commons_llm_disambiguator)
- [[task-store]] — the store of owed work: one row per task, decision, review request, bug or gate, with an append-only event trail, served through `/api/tasks`. `cosa.rest` (task_store_rules, task_store_owed, task_store_rejoin, task_chase_consumer, task_store_change_notifier, task_store_epic_keys, task_store_prose_refs)
- [[v2-ask-flow]] — the v2 door onto CJ Flow. `AskFlow` takes a question or a decided command and returns one result, over `/api/v2/ask`, `ask-audio`, `transcribe`, `submit`, `resume`, `resume-job` and `agents`. `cosa.rest.v2` (flow, registry), `cosa.rest.routers` (v2_ask)
- [[model-server]] — the standalone FastAPI app that holds Whisper and two text encoders on one GPU, which compute containers call over HTTP. `lupin_model_server` (main)
- [[speech-to-text-routing]] — how `SpeechToTextProvider` sends audio to in-process Whisper or to the model server, and the four routes that call it. `cosa.memory` (speech_to_text_provider), `cosa.rest.routers` (speech)
- [[utils-config-secrets-and-vertex]] — three `cosa.utils` helpers: the API config loader, secret redaction for reports and logs, and the Vertex daily spend ceiling. No caller outside its tests uses the ceiling. `cosa.utils` (config_loader, secret_redaction, vertex_spend_ceiling)
- [[vertex-env-guards]] — the launch-time guards and composer for a Vertex-billed Claude Code session, plus the tmux and pane environment checks. `cosa.utils` (vertex_env)
- [[vertex-logging-probe]] — Vertex logging probe: sentinel, BigQuery location checks, readout and canary-gated verdicts. `cosa.utils` (vertex_logging)
- [[vertex-monitoring-oracle]] — Cloud Monitoring oracle that shows a call ran on Vertex, canary-gated. `cosa.utils` (vertex_monitoring_oracle)
- [[spend-ceiling-prices-and-report-redaction]] — ModelPrice, UnpricedModelError, max_daily_usd_at_tpm and pytest longrepr redaction. `cosa.utils` (vertex_spend_ceiling, secret_redaction)
- [[gcs-and-api-rate-limit-helpers]] — GCS text read/write helpers, the API resource manager singleton, and GCP project/location lookup. `cosa.utils` (util_gcs, api_resource_manager, gcp_project)
- [[claude-process-memory-watch]] — samples live Claude Code process memory and writes one alert line per runaway, naming the session. `cosa.utils` (cc_memory_watch)
- [[model-server-liveness-and-transcript-tail]] — refusing a run when a vLLM endpoint is dead, and byte-offset JSONL transcript reads for the console. `cosa.utils` (model_server_liveness, transcript_tail)
- [[tree-state-and-import-origin]] — the tree-state line, start sha and bundle hash, and the imports= origin token. `cosa.utils` (tree_state, import_origin)
- [[checked-hash-bytecode]] — checked-hash pyc write control, pyc census and mode ledger. `cosa.utils` (checked_hash_pyc)
- [[unit-network-guard-and-collection-diagnosis]] — outbound-dial guard for unit tests and the pytest collection-failure diagnosis. `cosa.utils` (unit_network_guard, pytest_collection_diagnosis)
- [[coverage-frame-and-visual-failures]] — coverage config against disk check, and the per-run folder for visual snapshot failures. `cosa.utils` (coverage_frame, visual_failures)
- [[coverage-contention-guard]] — detects another running suite before a coverage run. `cosa.utils` (coverage_contention)
- [[worktree-venv-and-drift-disclosure]] — worktree venv provisioning verdicts, the drift sentence, and artifact-outcome parsing. `cosa.utils` (worktree_venv, seat_worktree, worktree_artifacts)
- [[db-grants-matrix-and-startup-check]] — the role and privilege matrix for the dev and test databases, the read-only grants check and the boot-time alarm. `cosa.utils` (db_grants)
- [[db-provisioning-secret-files-and-dotenv-login]] — the `db_roles` provisioning command, the compose secret files, and how host processes get a database login from `.env` or a password file. `cosa.utils` (db_roles, db_secret_files, dotenv_password)
- [[credential-drift-and-scrubbing]] — API key file against Secret Manager drift check, in-place scrubbing of credential values from files, and the container OAuth token restart decision. `cosa.utils` (secret_drift, credential_file_scrubber, credential_watch)
- [[util-file-readers-and-writers]] — whole-file, line, json and dictionary readers, writers, source listings and key file lookup. `cosa.utils` (util)
- [[util-console-args-and-xml-helpers]] — banner and list printing, name=value arguments, small string helpers and the deprecated xml tag readers. `cosa.utils` (util, util_xml)
- [[bounded-retry-policy]] — RetryPolicy rules, backoff step and the async retry call. `cosa.utils` (bounded_retry)
- [[timestamps-clock-and-dm-word-count]] — bracketed eastern stamps, clock helpers and direct message word counts. `cosa.utils` (edt_timestamp, dm_text, util)
- [[hook-link-tick-reporting]] — git hook link findings, fingerprint, resend decision and delivery. `cosa.utils` (hook_link_tick)
- [[notification-text-helpers]] — question and answer text shaping for voice and the api. `cosa.utils` (notification_utils)
- [[util-voice-config-stopwatch-and-torch]] — spoken char cap, tts mode, Stopwatch and torch device helpers. `cosa.utils` (util, util_stopwatch, util_pytorch)
- [[util-code-runner-and-dataframe]] — subprocess code runner and the path-keeping DeepilyDataFrame. `cosa.utils` (util_code_runner, util_pandas)
- [[gate-reachability]] — the census of test files that no gate runner can reach, and of reachable files that collect no test. `cosa.repo` (gate_reachability)
- [[iterative-debugging-agent]] — the agent that asks an LLM to fix code that failed, runs the fix, and reports whether it worked. `cosa.agents` (iterative_debugging_agent), `cosa.agents.agent_base`
- [[runtime-argument-expeditor]] — finding the arguments a voice command left out, asking the user for them, and returning a complete args dict. `cosa.agents.runtime_argument_expeditor` (expeditor, agent_registry, cli_help)
- [[prediction-engine]] — guessing how the user will answer a notification, showing the guess as a hint, and logging the real answer to measure accuracy. `cosa.agents.prediction_engine`
- [[tfe-to-cc-prompt-bundles]] — the prompt builders and reply parsers for running the test-fix expediter's diagnose and fix steps on Claude Code. `cosa.agents.tfe_to_cc` (prompts)
- [[bug-injector]] — a test aid: an LLM breaks working generated code with one fatal edit, so the auto-debug path has work. `cosa.agents` (bug_injector), `cosa.utils` (util_code_runner)
- [[candidate-stage]] — planned, not built: the ranked first stage that picks which index entries Jev judges, with its redactor and stored vectors. `cosa.repo.symindex.candidates` (planned), `lupin_mcp` (reuse_redact, reuse_tools)
- [[doc-lint-support-modules]] — caps fixer, diff ranges, links, waivers, swept scope, word list. `cosa.repo.doc_lint` (caps_fix, changed_ranges, links, waivers, swept_scope, word_list)
- [[doc-lint-text-rules]] — writing rules and docstring linter. `cosa.repo.doc_lint` (text_rules, docstring_lint)
- [[doc-lint-markdown-comments-and-tools]] — md and comment linters, ruff/markdownlint/dart runners. `cosa.repo.doc_lint` (md_lint, comment_lint, tool_runners)
- [[doc-lint-package-sweep]] — scope gate, package lister, package lock. `cosa.repo.doc_lint` (scope_gate, sweep_packages, sweep_lock)
- [[doc-lint-package-check]] — per-package rewrite check. `cosa.repo.doc_lint` (package_check)
- [[doc-lint-ts-dart-linters]] — TypeScript, JavaScript and Dart comment linters. `cosa.repo.doc_lint` (tsdoc_lint, dartdoc_lint)
- [[doc-lint-ts-count-tables]] — TypeScript comment and export-doc count tables. `cosa.repo.doc_lint` (ts_counts, ts_doc_exists)
- [[doc-lint-count-table]] — Python finding count table. `cosa.repo.doc_lint` (counts)
- [[doc-lint-gate-staged-input]] — what the gate reads from the index and merges. `cosa.repo.doc_lint` (gate)
- [[doc-lint-gate-refusals]] — what refuses a commit and its wording. `cosa.repo.doc_lint` (gate)
- [[doc-lint-range-gate-epoch]] — blocking epoch rules. `cosa.repo.doc_lint` (range_gate)
- [[doc-lint-range-gate-replay]] — commit-by-commit replay. `cosa.repo.doc_lint` (range_gate)
- [[doc-lint-metrics-measure]] — token and marker rates per package. `cosa.repo.doc_lint` (doc_metrics)
- [[doc-lint-metrics-dashboard]] — dashboard page and rise check. `cosa.repo.doc_lint` (doc_metrics)
- [[doc-lint-marker-counts]] — marker counting. `cosa.repo.doc_lint` (marker_counts)
- [[doc-lint-split-check]] — page-split line check. `cosa.repo.doc_lint` (split_check)
- [[doc-lint-claim-history]] — history tag and destination check. `cosa.repo.doc_lint` (history_class, history_destination)
- [[doc-lint-claim-extractor]] — claims and verified quotes. `cosa.repo.doc_lint` (claim_extractor)
- [[doc-lint-claim-judge]] — claim verdicts and history labels. `cosa.repo.doc_lint` (claim_judge)
- [[doc-lint-judges]] — prose judge, Jev back end, reader test. `cosa.repo.doc_lint` (prose_judge, jev_judge, reader_rig)
- [[doc-lint-jev-transport]] — Jev HTTP door and budget. `cosa.repo.doc_lint` (jev_transport)
- [[doc-lint-model-transport]] — model call door, agy, budget. `cosa.repo.doc_lint` (model_transport)
- [[doc-lint-harness-runner]] — runner, ledger, schedule, cli. `cosa.repo.doc_lint` (harness_runner, harness_schedule, harness_cli)
- [[doc-lint-harness-report]] — exit-gate figures. `cosa.repo.doc_lint` (harness_report)
- [[doc-lint-judge-comparison-ledger]] — rebuild from a ledger. `cosa.repo.doc_lint` (judge_comparison)
- [[doc-lint-judge-comparison-report]] — per-judge tables. `cosa.repo.doc_lint` (judge_comparison)
- [[doc-lint-docs-only-diff]] — proves a rewrite left code unchanged. `cosa.repo.doc_lint` (docs_only_diff, ts_docs_only_diff)
- [[doc-lint-contract-diff]] — Requires/Ensures/Raises diff. `cosa.repo.doc_lint` (contract_diff)
- [[doc-lint-cli-and-rnd-gate]] — shared cli helpers and R&D gate 0. `cosa.repo.doc_lint` (cli, rnd_gate0)
- [[doc-lint-pool-builder]] — Python docstring pool. `cosa.repo.doc_lint` (pool_builder)
- [[doc-lint-dart-pairs]] — Dart before/after pairs. `cosa.repo.doc_lint` (dart_pairs)
- [[doc-lint-dart-pool-builder]] — Dart doc-block pool. `cosa.repo.doc_lint` (dart_pool_builder)
- [[doc-lint-page-pairs-and-loader]] — page chunks and pair loader. `cosa.repo.doc_lint` (page_pairs, labelled_pairs)
- [[doc-lint-labelled-set-text-helpers]] — text predicates. `cosa.repo.doc_lint` (labelled_set_rules)
- [[doc-lint-labelled-set-rejections]] — seeded-removal rejection rules. `cosa.repo.doc_lint` (labelled_set_rules)
- [[doc-lint-seeder-units-and-io]] — files, strata, split partition. `cosa.repo.doc_lint` (labelled_set_seeder)
- [[doc-lint-seeder-candidates]] — delete/weaken/relocate candidates. `cosa.repo.doc_lint` (labelled_set_seeder)
- [[doc-lint-seeder-plan]] — split draw and writer tasks. `cosa.repo.doc_lint` (labelled_set_seeder)
- [[doc-lint-seeder-writer-and-checks]] — blind writer and rule 1. `cosa.repo.doc_lint` (labelled_set_seeder)
- [[doc-lint-seeder-verify-and-assemble]] — redraw, second seat, assemble. `cosa.repo.doc_lint` (labelled_set_seeder)
- [[doc-lint-reader-run-text]] — reader-test questions and text. `cosa.repo.doc_lint` (reader_rig_run)
- [[doc-lint-reader-run-scoring]] — reader-test scoring and caps. `cosa.repo.doc_lint` (reader_rig_run)
- [[doc-lint-train-builder]] — approved packages for the merge train. `cosa.repo.doc_lint` (train_builder)
- [[rest-data-db-startup]] — the database URL, connection-pool size, boot-time wait and migration config helpers. `cosa.rest.db` (auto_migrate, database)
- [[rest-data-schema-drift]] — the boot-time check that compares ORM models with the live database and raises a drift alarm. `cosa.rest.db` (schema_drift)
- [[rest-data-embedding-regeneration]] — the plan, fill and swap steps that re-embed stored text: scope, exclusions, norm band and verification. `cosa.rest.db` (embedding_regeneration)
- [[rest-data-embedding-regen-run-control]] — the busy and off-peak gate and the checkpoint file that lets a regeneration run resume. `cosa.rest.db` (embedding_regeneration)
- [[rest-data-embedding-regen-batching]] — the character budget, batch splitting and bulk shadow-column write of a regeneration run. `cosa.rest.db` (embedding_regeneration)
- [[rest-data-vector-store-models]] — the eight pgvector table models: tables, keys and index rules. `cosa.rest.db` (vector_store_models)
- [[rest-data-repos-auth]] — the user, API key, token, failed-login and audit-log repositories. `cosa.rest.db` (repositories)
- [[rest-data-repos-tasks]] — TaskRepository and ApprovalSettingRepository: task rows, the event trail and promotion-gate settings. `cosa.rest.db` (repositories)
- [[rest-data-repos-notifications]] — the notification, push-token and podcast-proxy-spent repositories. `cosa.rest.db` (repositories)
- [[rest-data-repos-proxy-predictions]] — the proxy-decision, trust-state, prediction-decision and prediction-log repositories. `cosa.rest.db` (repositories)
- [[rest-data-repos-memory]] — the embedding-cache, question-embedding, input/output, query-log and solution-snapshot repositories. `cosa.rest.db` (repositories)
- [[rest-data-v2-execution]] — the inline and queued executors, AskFlow hand-off, pending entries and submit refusals. `cosa.rest.v2` (executor, flow, pending, refusal)
- [[rest-data-v2-routing]] — the command registry, router client and prompt generator, and the request bearer token. `cosa.rest.v2` (registry, router_client, router_prompt_generator, request_context)
- [[rest-data-v2-cache-and-sources]] — V2Cache, StageTrace, the near-match guard and source-document validation. `cosa.rest.v2` (cache, trace, near_match_guard, source_document)
- [[agent-feedback-and-project-utils]] — Approval and rejection reading, project detection, Claude Code job notifications. `cosa.agents` (claude_code, utils)
- [[agent-small-agents-and-helpers]] — Calendar, date-time and todo agents, runnable code, confirmation dialog, id generator. `cosa.agents` (agent_base, calendaring_agent, confirmation_dialog, date_and_time_agent, receptionist_agent, runnable_code, todo_list_agent, two_word_id_generator)
- [[agent-voice-io-functions]] — Voice-first questions with terminal fallback, mode and job id switches. `cosa.agents` (utils)
- [[bfe-data-model]] — Bug fix expediter state records, dead-job packaging and config. `cosa.agents` (bug_fix_expediter)
- [[bfe-prompts-and-voice]] — Bug fix expediter agent prompts and voice and notify wrappers. `cosa.agents` (bug_fix_expediter)
- [[calculator-operations]] — Voice calculator: intent extraction, arithmetic, conversion, price comparison, mortgage. `cosa.agents` (calculator)
- [[decision-proxy-learning-models]] — Bayesian regression, conformal check, case-based vote, decision embeddings and the ICRL prompt. `cosa.agents` (decision_proxy)
- [[decision-proxy-presence]] — Human-presence feed the decision proxy checks before answering. `cosa.agents` (decision_proxy)
- [[decision-proxy-startup]] — Decision proxy command line, listener, status notices and generic trust config reader. `cosa.agents` (decision_proxy)
- [[decision-strategy-contract]] — Abstract decision strategy, result record, category classifier and the four proxy record models. `cosa.agents` (decision_proxy)
- [[deep-research-cli]] — Terminal entry point for deep research: args, email and storage resolution, prerequisites. `cosa.agents` (deep_research)
- [[deep-research-cost-and-rate-limits]] — Usage records, model tiers, API response record and the web-search rate limiter. `cosa.agents` (deep_research)
- [[deep-research-narrowing-harness]] — Stand-alone harness and mock client for the theme-narrowing step. `cosa.agents` (deep_research)
- [[deep-research-prompts]] — Prompt builders and JSON parsers for clarify, plan, research, synthesize, revise. `cosa.agents` (deep_research)
- [[deep-research-search-cache]] — Per-user daily search cache and seed-document readers. `cosa.agents` (deep_research)
- [[deep-research-state]] — Run-state enums, Pydantic models and the typed dict for the research run. `cosa.agents` (deep_research)
- [[deep-research-voice-interface]] — Async notify/ask wrappers and per-task dispatch context. `cosa.agents` (deep_research)
- [[dm-compression-freeze]] — Freeze, validate and restore protocol that protects literals in a rewritten DM. `cosa.agents` (dm_compression)
- [[dm-compression-pipeline]] — Compress a DM or deliver the original; the rewriter agent and its response model. `cosa.agents` (dm_compression)
- [[dm-judge-directness-extraction]] — Version 2 directness extraction: sentence split, validation and position weights. `cosa.agents` (dm_quality_judge)
- [[dm-judge-grade-scale]] — Five-label grade scale, label normalizer and the judge response shapes. `cosa.agents` (dm_quality_judge)
- [[dm-quality-judge]] — DM quality judge factory, length bands, overall grade and the two judge versions. `cosa.agents` (dm_quality_judge)
- [[dm-tutor-rewrite]] — Rewrite a long DM into headline, two sentences and P.S., with its gate. `cosa.agents` (dm_tutor)
- [[dm-tutor-sentences]] — Sentence counting and pointer-token helpers behind the tutor trigger. `cosa.agents` (dm_tutor)
- [[expeditor-cli-and-mock-submit]] — Expeditor response models, CLI help builder and the mock job submit command. `cosa.agents` (runtime_argument_expeditor, test_harness)
- [[fix-git-operations]] — GitOps command wrapper and the GitStrategist trust-to-git strategy. `cosa.agents` (bug_fix_expediter, shared)
- [[fix-run-outputs-and-guards]] — Plan and report writers, resume guard, SDK error shaping, timeout brake. `cosa.agents` (shared)
- [[generator-voice-bridges]] — Podcast and presentation cosa_interface and voice_io wrappers over the shared voice layer. `cosa.agents` (podcast_generator, presentation_generator)
- [[heartbeat-arbiter-plumbing]] — Arbiter commons gateway, journal logger, per-edge ledger, event tail offsets, lineage carry file. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-context-pressure]] — Transcript-based context pressure, liveness and fleet table. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-fleet-view]] — Per-session fleet view, liveness verdicts, snapshot and table rendering. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-idle-roster-and-managers]] — Idle classification and roster, manager lineage and active-manager resolution. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-outreach-throttles]] — Ping backoff and rate caps, operator-gate urgency routing, pending-outreach ledger. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-poker]] — Heartbeat poker job, its clock and commons seams, production gateway. `cosa.agents` (heartbeat_poker_commons_gateway, heartbeat_poker_job)
- [[heartbeat-respin-boot-receipts]] — Boot receipts a re-spun seat writes, and the finders for them. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-respin-wake-verdict]] — Wake verdict for a re-spun successor, alert text and watch arming. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-self-respin-loop]] — Self-respin observer loop, marker sweep, sample recorder, stale-MCP tell. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-self-respin-markers]] — Self-respin marker contract, wake proof and the verdict classifier. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-turn-age-watchdog]] — Held-turn detector daemon: a dangling tool call in a quiet pane. `cosa.agents` (heartbeat_arbiter)
- [[heartbeat-wait-graph]] — Who-waits-on-whom graph, deadlock rings, store-backed corroboration. `cosa.agents` (heartbeat_arbiter)
- [[llm-completion-clients]] — Completion and chat clients, agent wrapper, prompt and output formatters. `cosa.agents` (llm_client, llm_client_factory, llm_completion, prompt_formatter, raw_output_formatter)
- [[llm-data-types]] — Request, response, message and stream-chunk dataclasses for LLM calls. `cosa.agents` (llm_data_types)
- [[llm-exceptions]] — The LLM client exception family. `cosa.agents` (llm_exceptions)
- [[llm-model-config-and-window]] — Provider and model config, context-window lookup and clamping, token counter. `cosa.agents` (model_registry, model_window, token_counter)
- [[notification-proxy-model-answers]] — Matcher and verifier response models, cloud fallback, answer verifier and script path helpers. `cosa.agents` (notification_proxy)
- [[notification-proxy-option-sentinels]] — Positional answer sentinels and checks of an answer against the card. `cosa.agents` (notification_proxy)
- [[notification-proxy-startup]] — Notification proxy command line, websocket listener and status notices. `cosa.agents` (notification_proxy)
- [[orphan-bridge-reaper]] — Sweep that reaps dead session bridges with no manager. `cosa.agents` (shared)
- [[podcast-audio-and-host-config]] — Podcast API, TTS and stitch result types, voice and host profile config. `cosa.agents` (podcast_generator)
- [[podcast-cli]] — Podcast generator command-line modes and flags. `cosa.agents` (podcast_generator)
- [[podcast-mock-clients]] — Canned script and silent audio stand-ins for the podcast clients. `cosa.agents` (podcast_generator)
- [[podcast-prompts]] — Podcast analysis, script and revision prompt builders, response parsers, host personality text. `cosa.agents` (podcast_generator)
- [[podcast-script-state]] — Podcast state enums, typed dict, segment and prosody helpers, review-gate wording. `cosa.agents` (podcast_generator)
- [[prediction-accuracy-comparators]] — Per-question-type comparators that score a prediction against the actual answer. `cosa.agents` (prediction_engine)
- [[presentation-cli]] — Presentation generator command line and its content-phase API response type. `cosa.agents` (presentation_generator)
- [[presentation-deck-model]] — Slide and arc models, Marp text renderer, deck verdict. `cosa.agents` (presentation_generator)
- [[presentation-prompts]] — Narrative, outline, elaboration and visual prompt builders, parsers, timing clamp summary. `cosa.agents` (presentation_generator)
- [[research-chained-cli]] — Terminal entry points and presentation pipeline state for the chained research pipelines. `cosa.agents` (deep_research_to_podcast, deep_research_to_presentation)
- [[seat-teardown-and-liveness]] — Seat self-teardown door, liveness test and worktree collision error. `cosa.agents` (shared)
- [[swe-engineering-proxy-rules]] — Engineering categories, cap levels, classifier and proxy config reader. `cosa.agents` (swe_team)
- [[swe-team-cli-and-config]] — SWE team command line and the SweTeamConfig dataclass. `cosa.agents` (swe_team)
- [[swe-team-notifications]] — Role-aware notification interface, voice rebinding and user-message client. `cosa.agents` (swe_team)
- [[swe-team-roles]] — Agent role definitions, model tier choice and role sender ids. `cosa.agents` (swe_team)
- [[swe-team-state-and-task-files]] — Typed task, result and finding records, initial state and the feature list file. `cosa.agents` (swe_team)
- [[swe-team-test-run-and-dry-run]] — Independent pytest runner and the mock SDK session for dry runs. `cosa.agents` (swe_team)
- [[swe-team-tool-hooks]] — SDK tool hooks, dangerous command guard and streaming prompt wrapper. `cosa.agents` (swe_team)
- [[test-suite-attestation]] — Hash-chained ledger that a test tier ran. `cosa.agents` (test_suite)
- [[test-suite-container-gates-and-voice]] — Container refusal of host-only suites, foreign-key truncate check, voice wrappers. `cosa.agents` (test_suite)
- [[tfe-intake-and-resume]] — Snapshot loading, seed clustering, resume resolution and config. `cosa.agents` (test_fix_expediter)
- [[tfe-prompts-and-voice]] — Test fix expediter per-cluster prompts and voice delegates. `cosa.agents` (test_fix_expediter)
- [[tfe-state-and-checkpoint]] — Test fix expediter state, checkpoint and voice-gate signals. `cosa.agents` (test_fix_expediter)
- [[worktree-reaper-branch-queries]] — Janitor read-only worktree and branch queries and the safe merged-branch delete. `cosa.agents` (shared)
- [[worktree-reaper-retire-and-sweep]] — Ignored-file evacuation, branch archive and retire, and the retention sweep. `cosa.agents` (shared)
- [[worktree-refusal-ledger]] — Refused-tree ledger with one notice per change. `cosa.agents` (shared)
- [[worktree-straggler-tickets]] — Task-store rows for long-refused trees and unlanded archived branches. `cosa.agents` (shared)
- [[xml-agent-response-models]] — XML models for receptionist, calendar and brainstorm code, plus the parser factory. `cosa.agents` (io_models)
- [[xml-routing-and-answer-models]] — XML models for routing, yes or no, gist and file or job matching. `cosa.agents` (io_models)

## Draft slugs folded into written pages

These names were in the first draft of this index. Each now has no page of its own, because written pages cover it. No line here is a page id.

- `code-reuse-tools` is `reuse-search-tools`, and `cosa-voice-mcp` is `cosa-voice-mcp-server`.
- `database-repositories` is `db-repositories`, with `db-session-and-schema` for the engine and migrations.
- `swe-crew-roles` is `swe-team-orchestrator`.
- `fix-expediter-agents` is split into `fix-expediter-bfe`, `fix-expediter-tfe`, `fix-shared-primitives` and `scheduled-test-suite`.
- `tfe_to_cc` is `tfe-to-cc-prompt-bundles`, and `bug_injector` is `bug-injector`.
- `long-running-generator-agents` is split into `deep-research`, `podcast-generation`, `presentation-generation`, `research-chained-pipelines` and `generator-sdk-clients`.
- `web-client` is the six `web-client-*` pages. JavaScript and TypeScript docs are out of scope for plan 1 per Rick's ruling.
- `docs-and-code-analysis-tools` is `doc-lint-gate`, `symbol-index` and `branch-and-directory-loc-analysis`. `cosa.repo.gate_reachability` is `gate-reachability`.
- `simple-task-agents` is `small-agents-core` for seven agents. `iterative_debugging_agent` is `iterative-debugging-agent`. `runtime_argument_expeditor` is `runtime-argument-expeditor`. `prediction_engine` is `prediction-engine`.
