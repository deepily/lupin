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
- [[rest-services-account-tables]] — the ORM tables for users, refresh tokens, API keys, email and password tokens, failed logins, the audit log and FCM device tokens. `cosa.rest` (postgres_models)
- [[rest-services-fleet-tables]] — the ORM tables for notifications, proxy decisions, trust, predictions, job history, server lifecycle, approval settings and the task store. `cosa.rest` (postgres_models)
- [[rest-services-test-run-guards]] — the pytest-args allowlist, the per-run suite token and the venue idle verdict. `cosa.rest` (pytest_args_policy, suite_run_token, venue_idle)
- [[rest-services-queue-helpers]] — queue filter authorization, the user job tracker, job state transition events, the todo queue, salutations and the in-memory LLM query. `cosa.rest` (queue_auth, queue_extensions, queue_protocol, queue_util, running_fifo_queue, salutations, todo_fifo_queue, util_llm_client)
- [[rest-services-repair-and-chase-loops]] — repair-attempt limits, the test-suite completion watchdog, watchdog startup and the task chase daemon. `cosa.rest` (repair_attempt_tracker, test_suite_completion_watchdog, watchdogs, task_chase_consumer)
- [[rest-services-login-tokens-and-lockout]] — failed-login records, refresh-token storage and revocation, and the SQLite auth database. `cosa.rest` (rate_limiter, refresh_token_service, sqlite_database)
- [[rest-services-user-accounts-and-ids]] — user create, authenticate and password functions, and the system-id and user-UUID helpers. `cosa.rest` (user_service, user_id_generator)
- [[rest-services-approval-settings-readers]] — approver lists, enforcement and holding-area switches, the legacy file import and actor identity recording. `cosa.rest` (task_approval_settings, task_actor_identity)
- [[rest-services-approval-gate-decisions]] — the pure refusal rules for admit, pull, mint and batch, and the validated settings writes. `cosa.rest` (task_approval_settings)
- [[rest-services-promotion-gate-ask]] — the promotion precheck, the owner ask, the approval record and the operator-answer check. `cosa.rest` (task_promotion_gate)
- [[rest-services-promotion-cards-and-deadlines]] — the ask and un-park cards, ticket deadlines and the stalled-ticket sweep. `cosa.rest` (task_promotion_gate, task_promotion_resolver)
- [[rest-services-task-requests-and-pledges]] — admit and demote requests, verdict rules, badge counts and deletion pledges. `cosa.rest` (task_request_lifecycle, task_request_pledge)
- [[rest-services-task-owed-predicates]] — the owed, parked, holding and stale-reason predicates and their SQL twins. `cosa.rest` (task_store_owed)
- [[rest-services-task-board-audits]] — the prose-reference scan, the rejoin dormancy stamp and the epic-key audit. `cosa.rest` (task_store_prose_refs, task_store_rejoin, task_store_epic_keys)
- [[rest-services-task-feed-and-priority-firewall]] — the task_store_changed push sink and the priority, operator and manager checks. `cosa.rest` (task_store_change_notifier, task_priority_firewall)
- [[rest-services-task-write-validators]] — the create, patch, title, terminal-edit and envelope-tail checks on task writes. `cosa.rest` (task_store_rules)
- [[rest-services-task-transition-rules]] — the receipt, blocker and park rules for a task status change. `cosa.rest` (task_store_rules)
- [[rest-services-task-refs-personas-and-ratio-gate]] — task reference classification, persona fields, the epic-key advisory and the ratio gate. `cosa.rest` (task_store_rules)
- [[rest-services-voice-persona-chains]] — persona chain and manager roster parsing, the overflow persona and session allocation. `cosa.rest` (voice_persona_helpers)
- [[repo-tools-branch-diff-and-config]] — branch analyzer input side: the YAML settings loader, file-type classifier, git diff reader and its error types. `cosa.repo.branch_analyzer` (config_loader, file_classifier, git_diff_parser, exceptions)
- [[repo-tools-branch-stats-and-reports]] — branch analyzer totals and console, JSON and Markdown reports, plus the older standalone diff script. `cosa.repo.branch_analyzer` (statistics_collector, report_formatter), `cosa.repo.branch_change_analysis`
- [[repo-tools-directory-scan-stats-and-reports]] — directory analyzer file records, per-type totals, reports and error types. `cosa.repo.directory_analyzer` (directory_scanner, statistics_collector, report_formatter, exceptions)
- [[repo-tools-git-loc-delta-read-and-bucket]] — the daily LoC delta's git log reader, per-day bucketing, date bounds and errors. `cosa.repo.git_loc_delta` (git_log_parser, daily_aggregator, date_bounds, exceptions)
- [[repo-tools-git-loc-delta-outputs]] — the daily LoC delta's console, JSON and CSV output, sidecar file and plot. `cosa.repo.git_loc_delta` (report_formatter, csv_writer, plotter)
- [[repo-tools-loc-cli-entrypoints]] — the four line-count command lines, their flags, default output paths and exit codes. `cosa.repo` (run_branch_analyzer, run_directory_analyzer, run_git_loc_delta, run_git_loc_delta_global)
- [[repo-tools-docker-smoke-report]] — reading the docker smoke junit report so that a skip counts as a failure. `cosa.repo.docker_smoke_report`
- [[repo-tools-symindex-core-build]] — the lower layer of the symbol index build and the readers of a published generation. `cosa.repo.symindex` (build)
- [[repo-tools-symindex-core-tree]] — which files the symbol index reads, the repo manifest, the data folder and its errors. `cosa.repo.symindex` (spec, paths, errors)
- [[repo-tools-symindex-core-extractors]] — the symbol record contract and the Python and TypeScript extractors. `cosa.repo.symindex` (extractor_contract, py_index, js_index)
- [[repo-tools-symindex-core-dart]] — indexing a Flutter tree: tool lookup, the scratch project and Dart extraction. `cosa.repo.symindex` (dart_extractor)
- [[repo-tools-symindex-core-routes-diff-dups]] — route resolution, generation diff and the exact and near duplicate finder. `cosa.repo.symindex` (routes, diff, dups)
- [[repo-tools-symindex-librarian-queue]] — turning wiki lint findings into one task-store row per package. `cosa.repo.symindex` (librarian_queue)
- [[repo-tools-symindex-librarian-tick-run]] — the daily librarian job: lint, queue the findings, export reuse misses. `cosa.repo.symindex` (librarian_tick)
- [[repo-tools-symindex-librarian-tick-config]] — the librarian tick's settings, caps, cron lines and locked crontab edit. `cosa.repo.symindex` (librarian_tick)
- [[repo-tools-symindex-misses]] — the reuse-miss block format in store rows and its atomic export. `cosa.repo.symindex` (miss_record)
- [[repo-tools-symindex-need-input]] — the stripped input a need writer reads and the checks on the sentence it writes. `cosa.repo.symindex` (need_input, need_writer)
- [[repo-tools-symindex-need-writing]] — writing one need sentence per sampled member, resume and redo, and the needs document. `cosa.repo.symindex` (need_writer)
- [[repo-tools-symindex-verdict-policy]] — the pure checks and rules behind the reuse verdict, and the band check. `cosa.repo.symindex` (verdict, labelled_set)
- [[repo-tools-symindex-labelled-run]] — the twin-group split and the join of answered pairs to the negatives record. `cosa.repo.symindex` (stage2_split, labelled_set)
- [[repo-tools-symindex-repair-check]] — replaying a missed reuse receipt before and after a summary rewrite. `cosa.repo.symindex` (repair_check)
- [[repo-tools-symindex-vectors-refresh]] — the daily vector refresh job and the purpose-line and vector build it runs. `cosa.repo.symindex` (vector_refresh, candidate_build)
- [[repo-tools-symindex-vectors-status]] — the stale-vector-set check and its status file and store row. `cosa.repo.symindex` (vector_status)
- [[repo-tools-candidate-ranking]] — candidate shortlist ranking: identifier splitting, BM25, rank fusion, the wiki page list and error codes. `cosa.repo.symindex.candidates` (bm25, rank_fusion, identifier_split, wiki_list, errors)
- [[repo-tools-candidate-vector-store]] — the sealed on-disk vector set, its hashes, swap-in and load checks. `cosa.repo.symindex.candidates` (vector_store)
- [[repo-tools-candidate-vector-build]] — embedding every index entry through the embeddings endpoints, with the engine check and query-vector cache. `cosa.repo.symindex.candidates` (vector_build, vector_store)
- [[repo-tools-candidate-vector-freshness]] — the vector set's build-info file, manifest reader and build lock. `cosa.repo.symindex.candidates` (freshness)
- [[repo-tools-candidate-search]] — the stdin and stdout search process: request checks and cosine ranking. `cosa.repo.symindex.candidates` (search)
- [[repo-tools-candidate-stage-and-resident]] — the per-lookup stage, its shortlist and replay, and the resident search that keeps stages loaded. `cosa.repo.symindex.candidates` (candidate_stage, resident)
- [[repo-tools-candidate-shadow-audit]] — sampling lookups, comparing the shortlist with a full sweep and the miss-rate bound. `cosa.repo.symindex.candidates` (shadow_audit)
- [[repo-tools-candidate-shadow-audit-queue]] — queuing, draining and storing shadow audit receipts. `cosa.repo.symindex.candidates` (shadow_audit)
- [[repo-tools-candidate-purpose-lines]] — the purpose-line store, its judging rule and writer. `cosa.repo.symindex.candidates` (purpose_lines)
- [[repo-tools-candidate-storage-paths]] — INI keys and environment overrides for every candidate stage path. `cosa.repo.symindex.candidates` (storage_paths)
- [[repo-tools-candidate-arms-wiring]] — the five comparison arms put onto the candidate stage. `cosa.repo.symindex.candidates` (arms)
- [[repo-tools-candidate-arms-metrics]] — recall, twin rank and verdict replay scores for each arm. `cosa.repo.symindex.candidates` (arm_metrics)
- [[repo-tools-candidate-arms-run-inputs]] — reading needs, the stored snapshot and cached judge answers for a measurement. `cosa.repo.symindex.candidates` (arm_run)
- [[repo-tools-candidate-arms-measure]] — measuring one arm and writing its partial results page. `cosa.repo.symindex.candidates` (arm_run)
- [[repo-tools-candidate-arms-report]] — building the final arm comparison page. `cosa.repo.symindex.candidates` (arm_report)
- [[rest-routers-admin-users]] — the admin-only `/admin/users` routes: list, details, roles, status, password reset, create, delete and batch delete. `cosa.rest.routers` (admin)
- [[rest-routers-admin-user-models]] — the request and reply models behind the admin user routes. `cosa.rest.routers` (admin)
- [[rest-routers-admin-snapshots]] — the admin-only solution snapshot routes: search, detail, delete, preview, similar, and the test-only source refresh. `cosa.rest.routers` (admin)
- [[rest-routers-arbiter-switches]] — the `/api/arbiter` routes for the cached fleet snapshot, the fleet-size dial and the skeleton crew switch. `cosa.rest.routers` (arbiter)
- [[rest-routers-auth-account]] — the `/auth` routes: register, refresh, logout, current user, password change and reset, email verification. `cosa.rest.routers` (auth)
- [[rest-routers-commons-broadcast]] — sending one message to every live seat the caller owns, with its fan-out, rate limit and reply body. `cosa.rest.routers` (commons)
- [[rest-routers-commons-sessions-and-history]] — the read routes that list the seats a broadcast would reach and the recent broadcast history. `cosa.rest.routers` (commons)
- [[rest-routers-decision-proxy]] — the `/api/proxy` routes that list, ratify and delete proxy decisions, show trust, and switch the trust mode. `cosa.rest.routers` (decision_proxy)
- [[rest-routers-dm-audit-counters]] — the in-memory DM traffic counters and their reset, snapshot and log-line helpers. `cosa.rest.routers` (dm)
- [[rest-routers-dm-grading-and-experiment]] — how a DM is graded, the experiment window and how the grade is pushed back to the sender. `cosa.rest.routers` (dm)
- [[rest-routers-dm-send-get-and-list]] — the `/api/dm` doors that send, respond to, fetch and list peer direct messages. `cosa.rest.routers` (dm)
- [[rest-routers-embeddings-and-test-stubs]] — the `/api/embeddings` door to the embedding provider, plus the job and mock-job stub routes. `cosa.rest.routers` (embeddings, jobs, mock_job)
- [[rest-routers-file-door-guards]] — the pinned-open errors, scope config, credential sniff and root checks the doc viewer and `io/` file doors share. `cosa.rest.routers` (_pinned_open, _scope_registry, docs_files, io_files)
- [[rest-routers-job-control-and-history]] — the per-job doors on the queue router: cancel, message, interactions, job history, and five retired 410 doors. `cosa.rest.routers` (queues)
- [[rest-routers-mode-and-client-config]] — the user agent mode routes, the multiplexer tuning values and the admin transcript roster. `cosa.rest.routers` (mode, multiplexer_config, cc_transcript)
- [[rest-routers-notification-helpers-and-catch-up]] — the notification timezone and sender helpers and the undelivered, awaiting-response and answers-owed catch-up routes. `cosa.rest.routers` (notifications)
- [[rest-routers-notification-sender-conversations]] — the per-sender conversation routes: sender lists, conversations by date, soft delete, active conversation and gist. `cosa.rest.routers` (notifications)
- [[rest-routers-notification-user-inbox]] — the per-user inbox routes: list, next, played, delete, bulk delete, prediction vote and broadcast acks. `cosa.rest.routers` (notifications)
- [[rest-routers-page-shells-and-stats]] — the `/app/*` page shell routes and the global time-saved leaderboard. `cosa.rest.routers` (pages, stats)
- [[rest-routers-peer-queue-watch]] — the admin routes that read and watch the queues of a peer Lupin server. `cosa.rest.routers` (peer)
- [[rest-routers-podcast-proxy]] — the `/api/podcast-proxy` ask, start and card-status routes and the viewer doors. `cosa.rest.routers` (podcast_proxy)
- [[rest-routers-poke-mute-and-fcm-pause]] — the heartbeat poke mute switch and the mobile token registry and push pause. `cosa.rest.routers` (heartbeat, fcm)
- [[rest-routers-queue-views-and-removal]] — the queue reading, pool status, reset, delete, pause and resume routes. `cosa.rest.routers` (queues)
- [[rest-routers-request-auth-guards]] — the API-key-or-JWT guard, the path and query identity owner guards and the shared id generator. `cosa.rest.middleware` (api_key_auth, path_identity), `cosa.rest.dependencies` (config)
- [[rest-routers-retired-submit-doors]] — ten tombstone submit routes that answer 410 Gone and name the replacement door. `cosa.rest.routers` (bug_fix_expediter, claude_code_queue, deep_research_to_podcast, deep_research_to_presentation, mock_job, podcast_generator, presentation_generator, swe_team, test_suite)
- [[rest-routers-reuse-candidates-search]] — the `/api/reuse-candidates` stage upload and search routes over the resident candidate index. `cosa.rest.routers` (reuse_candidates)
- [[rest-routers-speech-tts-streaming]] — the OpenAI and ElevenLabs text-to-speech doors and the PCM test socket, with audio returned over the audio WebSocket. `cosa.rest.routers` (speech)
- [[rest-routers-speech-upload-helpers]] — the upload directory, suffix, cleanup, io-row and utterance-id helpers the speech and v2 audio doors share. `cosa.rest.routers` (speech)
- [[rest-routers-system-and-session]] — the health, server info, WebSocket session views, client config and runtime switch routes. `cosa.rest.routers` (system)
- [[rest-routers-tasks-approval-and-requests]] — the approval settings, manager-pull switch and manager promote and demote request routes. `cosa.rest.routers` (tasks)
- [[rest-routers-tasks-reads]] — the task query, event stream, flow-ratio report, promotion ticket and epic story read routes. `cosa.rest.routers` (tasks)
- [[rest-routers-tasks-writes]] — the task create, transition, correlate, unpark-ask, amend and patch routes and their body models. `cosa.rest.routers` (tasks)
- [[rest-routers-v2-ask-bodies]] — the typed request and reply bodies of the `/api/v2` doors. `cosa.rest.routers` (v2_ask)
- [[rest-routers-v2-ask-doors]] — the `/api/v2` agents, ask, ask-audio, transcribe, resume and resume-job handlers. `cosa.rest.routers` (v2_ask)
- [[rest-routers-voice-and-speakerphone]] — the voice persona pool, allocate, read, release and sample routes and the speakerphone flag. `cosa.rest.routers` (voice_persona, speakerphone)
- [[rest-routers-websocket-endpoints]] — the `/ws/audio` socket and the routes that inspect and manage live WebSocket sessions. `cosa.rest.routers` (websocket, websocket_admin)
- [[rest-core-admin-accounts]] — administrator actions on user accounts (list, roles, status, reset, create) and the password helpers. `cosa.rest` (admin_service, password_service, jwt_service)
- [[rest-core-email-tokens]] — one-use email verification and password-reset tokens, and the SMTP mail that carries them. `cosa.rest` (email_token_service, email_service)
- [[rest-core-auth-bearer]] — bearer-scheme auth dependencies and the JWT and mock verifiers. `cosa.rest` (auth)
- [[rest-core-auth-roles]] — header-based auth dependencies, role-requiring builders and role checks. `cosa.rest` (auth_middleware)
- [[rest-core-auth-audit-and-models]] — the authentication audit log and the /auth request and response models. `cosa.rest` (auth_audit, auth_models)
- [[rest-core-fifo-queue]] — the FifoQueue container and the job state transition matrix. `cosa.rest` (fifo_queue, job_state)
- [[rest-core-notification-queue]] — the notification queue, the per-sender notify limit and the expiry dry run. `cosa.rest` (notification_fifo_queue, notify_rate_limiter, notification_expiry_sweeper)
- [[rest-core-job-persistence-lifecycle]] — writing a job's life to job_history and restoring jobs after a restart. `cosa.rest` (job_persistence)
- [[rest-core-job-history-queries]] — job history reads and deletes, the agentic job factory and the test-database cleanup. `cosa.rest` (job_persistence, agentic_job_factory, job_history_cleanup)
- [[rest-core-dead-queue-and-escalation]] — failed-job triage for the Bug Fix Expediter and the aged awaiting-manager escalation. `cosa.rest` (dead_queue_watchdog, follow_through_escalation_watcher)
- [[rest-core-commons-watchers]] — the commons ack and activity watchers and the broadcast rate limit. `cosa.rest` (commons_ack_watcher, commons_activity_watcher, commons_rate_limiter)
- [[rest-core-dm-experiment]] — the runtime policy for the DM verbosity two-arm pilot. `cosa.rest` (dm_experiment)
- [[rest-core-arbiter-bootstrap]] — the standing arbiter startup job, the fleet snapshot cache and the code identity record. `cosa.rest` (arbiter_bootstrap, arbiter_snapshot_store, code_identity)
- [[rest-core-managed-bounce]] — the bounce warning and all-clear broadcasts and their ack and roster logic. `cosa.rest` (managed_bounce_broadcast)
- [[rest-core-mobile-push]] — the content-free FCM wake push and its in-memory pause. `cosa.rest` (fcm_wake_service, fcm_push_pause)
- [[rest-core-flow-ratio-settings]] — the closed-to-new task ratio gate's window, threshold and enforcement settings. `cosa.rest` (flow_ratio_settings)
- [[rest-core-transcript-tee]] — mapping Claude Code transcript lines to console blocks and the tailer settings. `cosa.rest` (cc_transcript_mapper, cc_transcript_tailer)
- [[rest-core-error-envelope]] — the self-explaining 500 body for unhandled server exceptions. `cosa.rest` (error_envelope)
- [[rest-core-persona-key-backfill]] — the sweep that canonicalizes persona keys on task-store rows. `cosa.rest` (persona_key_backfill)
- [[rest-core-podcast-door]] — the podcast proxy's document check, refusals and judged copy. `cosa.rest` (podcast_proxy)
- [[rest-core-podcast-cards]] — the podcast approval card, the start checks and the dry-run switch. `cosa.rest` (podcast_proxy)

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
