---
capability: rest-routers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.v2_ask.build_ask_flow@b1951b74a7
  - cosa.rest.routers.v2_ask.install_ask_flow@b35d082dfd
  - cosa.rest.routers.v2_ask.get_ask_flow@d4e3989e83
  - cosa.rest.routers._retired_doors.refusal_detail@28e39ec43b
  - cosa.rest.routers._scope_registry.build_scope_registry@31e0911165
  - cosa.rest.routers._scope_registry.resolve_in_scope@b5d0cf1c5e
  - cosa.rest.routers._pinned_open.open_pinned@4865d9e913
  - cosa.rest.routers._dir_listing.list_directory@db3a6d0ceb
---
# REST routers

How the FastAPI app gets its routes: one module per router under `src/cosa/rest/routers/`, all registered in `src/lupin_app/main.py`.

## Registration
- Each router module defines `router = APIRouter( ... )`. `main.py` imports the modules in one `from cosa.rest.routers import ...` line and calls `app.include_router( <module>.router )` for each.
- A new router needs both edits: the name in that import line and an `include_router` call beside the others.

## Declaring a prefix
- A router may carry its own `prefix`: `auth` uses `/auth`, `admin` uses `/admin`, `commons` uses `/api/commons`, `dm` uses `/api/dm`.
- Some use the shared prefix `/api` and put the rest in each route: `queues`, `notifications`, `tasks`, `arbiter`.
- Others declare only `tags` and write the full path in each decorator, so a route's URL is read from the decorator: `v2_ask` (`/api/v2/ask`), `pages`, `system`.

## Groups
- Identity and admin: `auth`, `admin`; see [[auth-and-accounts]].
- Server and pages: `system`, `mode`, `stats`, `multiplexer_config`, `pages`, `websocket_admin`; see [[system-admin-and-stats]].
- Queues and jobs: `queues`, `jobs`, `peer`, `claude_code_queue`, `test_suite`, `mock_job`; see [[cj-flow-queue]]. `bug_fix_expediter` is a 410 tombstone; see [[fix-expediter-bfe]].
- Ask and speech: `v2_ask`, `speech`, `embeddings`; see [[v2-ask-flow]].
- Generators: `deep_research`, `podcast_generator`, `presentation_generator`, `podcast_proxy` (ask, then start) and the two `deep_research_to_*` chains; see [[deep-research-door]].
- Fleet and messaging: `commons`, `dm`, `tasks`, `arbiter`, `heartbeat`, `speakerphone`, `voice_persona`, `swe_team`, `decision_proxy`; see [[commons-and-dm]] and [[task-store]].
- Files: `docs_files` and `io_files` serve whitelisted files; see [[doc-viewer]].
- Events: `websocket`, `notifications`, `fcm` (mobile wake tokens); see [[websocket-events]] and [[notification-delivery]]. `cc_transcript` is the transcript backlog door; see [[session-transcript-console]].

## Shared helpers
- Modules starting with an underscore are helpers, not routers: `_scope_registry` (scope table, path resolution), `_pinned_open`, `_dir_listing`, `_retired_doors`.
- `_retired_doors` builds the 410 refusals; see [[retired-queue-doors]].
- The v2 ask engine lives in `src/cosa/rest/v2/`; `v2_ask` builds it with `build_ask_flow` and `install_ask_flow`, and `get_ask_flow` is the dependency tests override.
