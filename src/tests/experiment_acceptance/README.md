# Experiment acceptance tests (DRAFT, not frozen)

Black-box Playwright tests for the reuse experiment's build task (plan §7.2 step 3). They act through the UI and check results through the API. Elements are found by visible text and ARIA role only: no test ids, no CSS classes, no XPath. `src/tests/unit/test_experiment_acceptance_feature_map.py` enforces both rules and checks that every feature in the feature list is cited.

Not part of any Lupin tier: the directory is outside `src/tests/e2e_ui/partition/`. The harness (Phase 5) runs it against a run's own server.

| Variable | Meaning |
|---|---|
| `EXPERIMENT_SERVER_URL` | the run's server, e.g. `http://localhost:8123` |
| `EXPERIMENT_NOTIFY_API_KEY` | API key the sender side uses for `POST /api/notify` |

Each test registers its own throwaway account through the API, so tests do not depend on each other or on order.

Status 2026-10-25: collects and compiles; not run against any client, because no client exists in the frozen tree.
