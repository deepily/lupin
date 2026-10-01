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
