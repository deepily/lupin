# Smoke Tests

Quick-start guide for Lupin's smoke test suite. For comprehensive documentation on the
automated interactive testing system, see [`src/docs/automated-interactive-testing.md`](../../docs/automated-interactive-testing.md).

---

## Smoke Test Files

| File | Description | Requires Server | Requires Proxy |
|------|-------------|:---------------:|:--------------:|
| `test_calculator_live_pipeline.py` | 6-query Calculator agent live pipeline test | Yes | No |
| `test_crud_for_dataframes_smoke.py` | DataFrame CRUD storage layer validation | No | No |
| `test_crud_live_pipeline.py` | 8-scenario CRUD live pipeline test (todo + calendar) | Yes | Optional |
| `test_deep_research_dry_run_smoke.py` | Deep research agent dry-run validation | Yes | No |
| `test_deep_research_submit_smoke.py` | Deep research submission + polling | Yes | No |
| `test_embedding_benchmark.py` | Local GPU vs OpenAI embedding comparison | No | No |
| `test_expeditor_mock_job_smoke.py` | 13-scenario expeditor mock job matrix | Yes | Yes |
| `test_local_embedding_smoke.py` | Local embedding model validation | No | No |
| `test_mcp_smoke.py` | cosa-voice MCP server validation | Yes | No |
| `test_notification_proxy_script_matching.py` | Proxy script matcher strategy validation | No | No |
| `test_notifications_sse_smoke.py` | SSE notification delivery validation | Yes | No |
| `test_podcast_generator_dry_run_smoke.py` | Podcast generator dry-run validation | Yes | No |
| `test_proxy_integration.py` | **12-scenario integration test** (Calculator + CRUD + Expediter) | Yes | Yes |
| `test_research_to_podcast_dry_run_smoke.py` | Research-to-podcast chained workflow dry-run | Yes | No |
| `test_token_proactive_refresh_smoke.py` | JWT token proactive refresh validation | Yes | No |
| `test_vllm_dynamic_client_smoke.py` | vLLM dynamic client initialization | No | No |

### Utility Modules (`utilities/`)

| File | Description |
|------|-------------|
| `utilities/live_pipeline_base.py` | Base class: auth, session, submit/poll, validation framework |
| `utilities/embedded_proxy.py` | Mixin: auto-launch notification proxy as subprocess |
| `utilities/interactive_smoke_test.py` | Combined base class (pipeline + proxy) |

---

## Quick-Start Commands

```bash
# Calculator (no proxy needed)
python src/tests/smoke/test_calculator_live_pipeline.py --no-confirm

# CRUD with auto-proxy
python src/tests/smoke/test_crud_live_pipeline.py --auto-proxy --no-confirm

# Full integration test (all 3 groups)
LUPIN_INTERACTIVE_TESTS=true \
python src/tests/smoke/test_proxy_integration.py --group all --auto-proxy --no-confirm

# Integration test - calculator group only
python src/tests/smoke/test_proxy_integration.py --group calculator --no-confirm

# Integration test - via pytest
pytest src/tests/smoke/test_proxy_integration.py -v

# Expeditor mock job smoke test
LUPIN_INTERACTIVE_TESTS=true \
python src/tests/smoke/test_expeditor_mock_job_smoke.py --auto-proxy --no-confirm

# Deep research dry-run
python src/tests/smoke/test_deep_research_dry_run_smoke.py

# Standalone notification proxy (separate terminal)
python -m cosa.agents.notification_proxy --profile all_agents --strategy llm_script
```

> **Important**: Always use these automated scripts for pipeline testing. Manual curl-based
> job submission is prohibited — see project `CLAUDE.md` Testing Anti-Patterns.

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `LUPIN_ROOT` | Project root (required for PYTHONPATH) |
| `LUPIN_TEST_EMAIL` | Standard test account email |
| `LUPIN_TEST_PASSWORD` | Standard test account password |
| `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL` | Interactive test account email |
| `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD` | Interactive test account password |
| `LUPIN_INTERACTIVE_TESTS` | Set to `"true"` to enable expediter scenarios |

See [`src/tests/AUTH-TESTING-GUIDE.md`](../AUTH-TESTING-GUIDE.md) for credential setup patterns.

---

## Related Documentation

- **Comprehensive guide**: [`src/docs/automated-interactive-testing.md`](../../docs/automated-interactive-testing.md) — Full reference for the proxy testing system
- **Testing strategy**: [`src/tests/README.md`](../README.md) — 5-tier testing overview
- **Notification API**: [`src/docs/notification-api.md`](../../docs/notification-api.md) — Notification system reference
- **Agentic voice workflow**: [`src/workflow/agentic-voice-workflow.md`](../../workflow/agentic-voice-workflow.md) — Building new agents that need testing
