# Capability index (draft for Rick's slug approval)

One line per capability: `[[slug]]`, what it covers, the packages it spans. A rewritten `Design:` line points at `wiki/capabilities/<slug>.md`. The pages do not exist yet; they are written after the package sweep.

Drafted from the symbol index built at lupin `a7f2af593` (7,240 public symbols, 227 routes) and `python -m cosa.repo.symindex dups`. Package names are dotted import paths under `src/`.

## Job queue and agents

- [[cj-flow-queue]] — the todo, running, done and dead queues, the agentic pool, the ghost-job sweeper and job persistence. `cosa.rest` (fifo_queue, todo_fifo_queue, running_fifo_queue, queue_consumer, queue_protocol, job_persistence, dead_queue_watchdog), `cosa.agents.agentic_job_base`
- [[agent-llm-clients]] — the shared LLM client layer: model registry, client factory, completion and chat clients, token counting, prompt formatting, LLM exceptions. `cosa.agents` (llm_client, llm_client_factory, model_registry, base_llm_client, completion_client, token_counter, prompt_formatter, llm_exceptions)
- [[bounded-claude-code-jobs]] — running a Claude Code task as a bounded or interactive CJ Flow job, and dispatching it. `cosa.agents.claude_code`, `cosa.orchestration.claude_code`
- [[long-running-generator-agents]] — deep research, podcast and presentation generation, and the two chained jobs; this is where the duplicate `api_client` and `cosa_interface` clusters live. `cosa.agents` (deep_research, podcast_generator, presentation_generator, deep_research_to_podcast, deep_research_to_presentation)
- [[fix-expediter-agents]] — the bug-fix and test-fix expediters, the shared fix primitives, the test suite runner and its scheduling. `cosa.agents` (bug_fix_expediter, test_fix_expediter, shared, test_suite, tfe_to_cc, bug_injector)
- [[swe-crew-roles]] — the standing build crew: implementer, reviewer and tester seats and their charters. `cosa.agents.swe_team`
- [[xml-io-models]] — the XML request and response models agents parse and emit. `cosa.agents.io_models`, `cosa.agents.dm_compression`, `cosa.agents.dm_tutor`, `cosa.crud_for_dataframes` (xml_models)
- [[simple-task-agents]] — the small synchronous agents: math, calculator, calendar, date and time, weather, to-do list, receptionist, iterative debugging, runtime argument expeditor, prediction engine. `cosa.agents` (math_agent, calculator, calendaring_agent, date_and_time_agent, weather_agent, todo_list_agent, receptionist_agent, iterative_debugging_agent, runtime_argument_expeditor, prediction_engine)
- [[dataframe-crud]] — CRUD over DataFrames, storage, schemas and the intent dispatcher. `cosa.crud_for_dataframes`

## Notifications, decisions and voice

- [[notification-delivery]] — creating, routing and expiring notifications and their types, rate limits and push. `lupin_cli.notifications`, `cosa.rest` (notification_fifo_queue, notify_rate_limiter, notification_expiry_sweeper, fcm_push_pause, fcm_wake_service), `cosa.rest.routers`
- [[websocket-events]] — session-keyed WebSocket connections, subscriptions and event fan-out. `cosa.rest` (websocket_manager, routers), `lupin_app.main`
- [[decision-proxy]] — trust-scored auto-answering of questions, ratification, and the notification proxy. `cosa.agents` (decision_proxy, notification_proxy, dm_quality_judge)
- [[voice-persona-allocation]] — per-session voice personas, the persona matcher and name normalization. `cosa.rest.voice_persona_helpers`, `lupin_mcp` (commons_persona_matcher, persona_normalization, commons_llm_disambiguator)
- [[cosa-voice-mcp]] — the voice and commons MCP server: notify, ask and converse tools, commons, DMs, session info. `lupin_mcp` (cosa_voice_mcp, commons_*, notify_outbox, broadcast_handler, bridge_liveness_middleware)
- [[code-reuse-tools]] — check_exists, fetch_similar, replay and read_capability, and the Jev client. `lupin_mcp` (reuse_tools, reuse_call_log_middleware), `cosa.repo.symindex`

## Fleet, heartbeat and the task store

- [[task-store]] — owed work rows, transitions, receipts, promotion gates, priority firewall, epic keys and rejoin. `cosa.rest` (task_store_*, task_promotion_*, task_request_*, task_priority_firewall, task_approval_settings, task_chase_consumer), `lupin_mcp.task_store_tools`
- [[heartbeat-arbiter]] — fleet liveness: the arbiter loop, watchdogs, escalation, context-pressure, health watcher and the poker job. `cosa.agents` (heartbeat_arbiter, heartbeat_poker_job, heartbeat_poker_commons_gateway), `lupin_arbiter_app`, `cosa.rest` (follow_through_escalation_watcher, commons_*_watcher)
- [[claude-code-hooks]] — the session-start, stop, pre/post tool and prompt hooks, heartbeat events and the session bridge. `lupin_cli.claude_code.hooks`
- [[seat-lifecycle]] — spawning seats, the fleet size cap, mementos, self re-spin, reaping and worktree hygiene. `lupin_mcp` (session_spawner, fleet_size_cap, fleet_cap_*, memento_*, reap_*, self_respin_core)

## Auth, data and platform

- [[auth-and-accounts]] — JWT, refresh tokens, API keys, users, passwords, email tokens, rate limits and audit. `cosa.rest` (auth, auth_middleware, auth_models, jwt_service, user_service, admin_service, refresh_token_service, password_service, email_*), `cosa.rest.db.repositories` (token and api-key repositories)
- [[database-repositories]] — Postgres models and repository classes; this is where the `is_valid`, `cleanup_expired` and `mark_used` clusters live. `cosa.rest.db`, `cosa.rest.postgres_models`, `cosa.rest.sqlite_database`
- [[solution-memory]] — solution snapshots, embeddings, canonical synonyms and snapshot managers. `cosa.memory`, `cosa.rest.db.repositories` (solution_snapshot, embedding_cache, question_embedding, canonical_synonym), `lupin_model_server`
- [[rest-routers]] — the FastAPI routers and the v2 submit surface. `cosa.rest.routers`, `cosa.rest.v2`, `lupin_app` (main, bootstrap_helpers, asset_tokens, versioned_static)
- [[configuration]] — INI configuration, the config cache registry and the doc-viewer manifest. `cosa.config`
- [[shared-utilities]] — path and project-root helpers, memory watch, Vertex logging, checked-hash bytecode. `cosa.utils`, `cosa.tools`

## Quality tooling

- [[docs-and-code-analysis-tools]] — the doc linters, the symbol index and wiki lint, LoC and branch analyzers. `cosa.repo` (doc_lint, symindex, branch_analyzer, directory_analyzer, git_loc_delta, gate_reachability)
- [[test-and-eval-scripts]] — test harnesses, falsify, coverage and scan scripts, evaluation and probe scripts, migrations. `scripts`, `cosa.agents.test_harness`
- [[model-training]] — PEFT training, XML prompt generation and validation, quantization. `cosa.training`, `cosa.research`

## Web client

- [[web-client]] — the browser pages, queue UI, notifications UI and their JavaScript and TypeScript modules (2,052 indexed symbols). `src.lupin_app.static` (JS and TypeScript docs are out of scope for plan 1, per Rick's JS and TypeScript ruling; the slug exists so the symbols have a home)

## Written pages (added at assembly)

Pages with two passes at one sha, one line each: `[[slug]]`, what it covers, the packages it pins. `[[agent-llm-clients]]` is written too; its line is above.

- [[agent-voice-io]] — how a job tells the user something or asks a question, and what it does when nobody can answer. `cosa.agents.utils` (voice_io, sender_id, sync_notify), `cosa.agents.deep_research` (cosa_interface, voice_io)
- [[agentic-job-contract]] — `AgenticJobBase`: the fields and lifecycle every long-running queue job provides. `cosa.agents` (agentic_job_base), `cosa.agents.claude_code`, `cosa.agents.deep_research`
- [[deep-research]] — answering a question from the web and saving a markdown report. `cosa.agents.deep_research` (cli, search_cache, seed_context)
- [[generator-sdk-clients]] — the Claude Agent SDK client classes of the podcast, presentation and deep-research agents. `cosa.agents.podcast_generator`, `cosa.agents.presentation_generator`, `cosa.agents.deep_research` (api_client)
- [[presentation-generation]] — turning a source document into a YAML deck, Marp Markdown and a pptx, with its review gates. `cosa.agents.presentation_generator` (job, deck_verdict)
- [[presentation-visual-renderers]] — phase 7: replacing each VISUAL marker in the Marp file with renderer output. `cosa.agents.presentation_generator.renderers`
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
- [[worktree-lifecycle]] — how git worktrees are made for each spawned seat and each BFE or TFE job, and removed by teardown, the reaper and the janitor. `cosa.agents.shared` (seat_teardown, worktree_reaper, worktree_refusal_ledger, worktree_straggler_tickets), `cosa.utils` (seat_worktree, worktree_artifacts)
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
- [[task-promotion-gate]] — the rules for moving a row out of the holding area onto a board, and for who may set a priority. `cosa.rest` (task_promotion_gate, task_promotion_resolver, task_request_lifecycle, task_request_pledge, task_priority_firewall)
- [[web-client-audio-and-tts]] — how the browser records speech for transcription and plays server-made speech through a queue. `src/lupin_app/static/js/multiplexer` (audio, render, shared, stores, wireTtsIntent)
- [[web-client-jobs-and-session-panes]] — the seven renderers that draw the jobs, submit, Q&A, session strip, persona modal, nav bar and reading panes. `src/lupin_app/static/js/multiplexer/render`
- [[web-client-transport-and-auth]] — the multiplexer page's two WebSockets, refreshable login token and in-page event bus, wired by `bootMultiplexer`. `src/lupin_app/static/js/multiplexer` (auth, transport, boot, shared)
- [[web-client-stores]] — the multiplexer page's state stores, each built by a `createXStore` function from the event bus and announcing change as a `store_*_changed` event. `src/lupin_app/static/js/multiplexer/stores`
- [[db-repositories]] — the Postgres repository classes built on one generic base, mapped to the capability that uses each, and the vector search they share. `cosa.rest.db` (repositories, database)
- [[web-client-task-board-panes]] — the four panes that show the task store: task list, epic board, holding area and finished tasks. `src/lupin_app/static/js/multiplexer/render`
- [[web-client-notification-panes]] — the pane renderers that draw notifications, action-required cards, broadcasts, commons activity and fleet status. `src/lupin_app/static/js/multiplexer` (render, stores)
- [[deep-research-door]] — the deep-research router: it serves finished reports and a health check, and no longer accepts jobs. `cosa.rest.routers` (deep_research, _retired_doors)
- [[app-bootstrap-and-static]] — how `lupin_app` builds the FastAPI app: startup root check, `/static` serving and cache-busting asset tokens. `lupin_app` (main, bootstrap_helpers, versioned_static, asset_tokens)
- [[dm-rewrite-model-study]] — the one-off package that compares Phi-4 14B on a local vLLM host with `gemini-3.1-flash-lite` on Vertex for the DM Tutor rewrite task, replaying frozen DM bodies. `cosa.research.phi4_flash_lite_study` (freeze_corpus, replay_harness)
- [[voice-persona-allocation]] — how each Claude Code session gets a named voice, the speakerphone switch beside it, and the name normalization every persona lookup shares. `cosa.rest` (voice_persona_helpers), `cosa.rest.routers` (voice_persona)
- [[task-store]] — the store of owed work: one row per task, decision, review request, bug or gate, with an append-only event trail, served through `/api/tasks`. `cosa.rest` (task_store_rules, task_store_owed, task_store_rejoin, task_chase_consumer, task_store_change_notifier)
