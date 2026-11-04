> Part 17 of 17 of the [Lupin Notification API Reference](../notification-api.md): testing guide.

## 13. Testing Guide

### 13.1 Test File Inventory

| File | Location | Lines | Tests | Purpose |
|------|----------|------:|------:|---------|
| `test_notification_proxy.py` | `src/tests/unit/` | 1554 | 120 | Proxy strategies, responder routing, config, XML models |
| `test_notification_models.py` | `src/tests/unit/` | 736 | 41 | Pydantic notification request/response validation |
| `test_notifications_api.py` | `src/tests/unit/` | 567 | 11 | REST API endpoint unit tests (fire-and-forget, response-required, submit) |
| `test_notifications_sse_smoke.py` | `src/tests/smoke/` | 356 | 5 | SSE notification flow live smoke test |
| `test_notification_proxy_script_matching.py` | `src/tests/smoke/` | 851 | 1 | LLM script matcher end-to-end smoke test |
| `test_expeditor_mock_job_smoke.py` | `src/tests/smoke/` | 703 | 1 | Expeditor mock job live pipeline smoke test |
| `test_notifications_integration.py` | `src/tests/integration/` | 249 | 8 | End-to-end notification API integration tests |
| `test_notification_auth.py` | `src/tests/integration/` | 337 | 11 | Notification authentication integration tests |

**Total**: 5353 lines, 198 tests across 8 files.

---

### 13.2 Running Tests by Tier

**Unit tests** (fast, no server required):

```bash
# All notification unit tests
pytest src/tests/unit/test_notification_proxy.py -v
pytest src/tests/unit/test_notification_models.py -v
pytest src/tests/unit/test_notifications_api.py -v

# All unit tests at once
pytest src/tests/unit/test_notification*.py -v
```

**Smoke tests** (require running Lupin server on port 7999):

```bash
# SSE notification flow
pytest src/tests/smoke/test_notifications_sse_smoke.py -v -s

# LLM script matching ( requires vLLM with Phi-4 )
pytest src/tests/smoke/test_notification_proxy_script_matching.py -v -s

# Expeditor mock job pipeline
pytest src/tests/smoke/test_expeditor_mock_job_smoke.py -v -s
```

**Integration tests** (require running Lupin server):

```bash
# Notification API integration
pytest src/tests/integration/test_notifications_integration.py -v

# Notification auth integration
pytest src/tests/integration/test_notification_auth.py -v

# All integration tests via automated runner
./src/tests/run-integration-tests.sh -v
```

---

### 13.3 Test Credentials Setup

All notification tests that hit authenticated endpoints require credentials:

```bash
# For notification proxy and smoke tests
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="your@email.com"
export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD="yourpassword"

# All test types use the unified prefix (Session 267 unification)
```

**Critical**: Never hardcode credentials. Tests that find empty env vars
should raise `ValueError` with setup instructions.

---

### 13.4 What Each Test Suite Covers

**`test_notification_proxy.py`** (120 tests):
- `TestConfig` -- Profile loading, defaults, strategy choices
- `TestGetCredentials` -- 2-tier credential resolution
- `TestExpediterRulesConstruction` -- Rule strategy initialization
- `TestExpediterRulesCanHandle` -- Sender filtering, response_requested checks
- `TestExpediterRulesRespond` -- Keyword matching, YES_NO auto-confirm, batch handling
- `TestLLMFallback` -- Cloud strategy construction, availability checks
- `TestWebSocketListener` -- Construction, event callback wiring
- `TestNotificationResponder` -- Strategy routing, stats tracking
- `TestKeywordMapping` -- Keyword-to-argument mapping correctness
- `TestProfileCoverage` -- All profiles have required keys
- `TestKeywordOrderingRegression`. Order-sensitive matching regression tests
- `TestScriptMatcherResponseModel` -- Pydantic XML response parsing
- `TestVerificationResponseModel` -- Verification response parsing
- `TestLlmScriptMatcherConstruction` -- Script loader, vLLM availability
- `TestLlmScriptMatcherCanHandle` -- Sender filtering for script matcher
- `TestLlmScriptMatcherRespond`. Phi-4 fuzzy matching end-to-end
- `TestLlmAnswerVerifier` -- Semantic answer verification
- `TestQAScriptFormat` -- Script JSON structure validation
- `TestSenderIdFiltering`. Cross-strategy sender filtering
- `TestConfigAdditions` -- Config constant additions
- `TestResponderStrategyMode` -- `llm_script` / `rules` / `auto` mode routing

**`test_notification_models.py`** (41 tests):
- `TestNotificationRequestValidation` -- Request model field validation
- `TestSSEEventModels` -- SSE event serialization
- `TestNotificationResponse`. Response model construction
- `TestAsyncNotificationRequestValidation` -- Async request validation
- `TestAsyncNotificationResponse` -- Async response model

**`test_notifications_api.py`** (11 tests):
- `TestNotifyFireAndForget` -- Fire-and-forget endpoint
- `TestNotifyResponseRequired` -- Response-required endpoint
- `TestSubmitNotificationResponse` -- Response submission endpoint

**`test_notifications_integration.py`** (8 tests):
- End-to-end notification lifecycle against a live server

**`test_notification_auth.py`** (11 tests):
- Authentication flows for notification endpoints

---

### 13.5 Inline Smoke Tests

Every module in the notification proxy package includes a `quick_smoke_test()`
function runnable via `python -m`:

```bash
# Config module ( profiles, credentials, API key resolution )
python -m cosa.agents.notification_proxy.config

# WebSocket listener ( construction, event dispatch )
python -m cosa.agents.notification_proxy.listener

# Notification responder ( strategy routing, stats )
python -m cosa.agents.notification_proxy.responder

# XML response models ( ScriptMatcherResponse, BatchScriptMatcherResponse, VerificationResponse )
python -m cosa.agents.notification_proxy.xml_models

# Expediter rules strategy ( keyword matching )
python -m cosa.agents.notification_proxy.strategies.expediter_rules

# LLM script matcher strategy ( Phi-4 fuzzy matching )
python -m cosa.agents.notification_proxy.strategies.llm_script_matcher

# LLM fallback strategy ( Claude Sonnet )
python -m cosa.agents.notification_proxy.strategies.llm_fallback

# Answer verifier ( semantic equivalence checking )
python -m cosa.agents.notification_proxy.verification
```

Each smoke test prints pass/fail status with `du.print_banner()` formatting.

---

### 13.6 Pre-Merge Notification Test Checklist

All notification tests **must pass** before merging to main:

```bash
# Step 1: Unit tests ( no server required )
pytest src/tests/unit/test_notification_proxy.py \
       src/tests/unit/test_notification_models.py \
       src/tests/unit/test_notifications_api.py -v

# Step 2: Integration tests ( requires running server )
./src/tests/run-integration-tests.sh -v

# Step 3: Smoke tests ( requires running server + optional vLLM )
pytest src/tests/smoke/test_notifications_sse_smoke.py -v -s
pytest src/tests/smoke/test_expeditor_mock_job_smoke.py -v -s
```

**Do not merge with failing tests**. If a test is legitimately flaky, document
the flakiness and create a separate fix.

---

### 13.7 Writing New Notification Tests

**Unit test template** (add to `src/tests/unit/test_notification_proxy.py`):

```python
class TestYourNewFeature:
    """Tests for [describe what you're testing]."""

    def test_basic_behavior( self ):
        """Verify the happy path."""
        strategy = ExpediterRuleStrategy(
            profile_name     = "deep_research",
            accepted_senders = DEFAULT_ACCEPTED_SENDERS,
            debug            = True
        )

        notification = {
            "sender_id"          : EXPEDITER_SENDER_ID,
            "response_requested" : True,
            "message"            : "What topic would you like to research?",
            "response_type"      : "open_ended",
        }

        assert strategy.can_handle( notification )
        answer = strategy.respond( notification )
        assert answer is not None

    def test_edge_case( self ):
        """Verify graceful handling of [edge case]."""
        # ...
```

**Smoke test template** (add to `src/tests/smoke/`):

```python
#!/usr/bin/env python3
"""
Smoke test: [describe what this validates end-to-end].

Requires:
    - Lupin server running on port 7999
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD set
"""

import os
import sys
import requests

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT" )
if LUPIN_ROOT is None:
    raise RuntimeError( "LUPIN_ROOT environment variable not set." )

src_path = os.path.join( LUPIN_ROOT, "src" )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )


def test_your_feature():
    """End-to-end validation of [feature]."""
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    assert email and password, "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and _PASSWORD"

    base_url = "http://localhost:7999"

    # Step 1: Authenticate
    resp = requests.post(
        f"{base_url}/auth/login",
        json = { "email" : email, "password" : password }
    )
    assert resp.status_code == 200, f"Login failed: {resp.text[ :200 ]}"
    token = resp.json()[ "tokens" ][ "access_token" ]

    # Step 2: Send notification
    # ...

    # Step 3: Verify response
    # ...


if __name__ == "__main__":
    test_your_feature()
    print( "\nAll smoke tests passed." )
```

**Key conventions**:
- Unit tests use `pytest` fixtures and mocks -- no server required
- Smoke tests use real HTTP calls. Server must be running
- Both use spaces inside parentheses: `len( items )`, `range( 10 )`
- Align colons in dicts: `"key"  : "value"`
- Use Design by Contract docstrings for test helper functions

---

### 13.8 Related Testing Documentation

| Document | Description |
|----------|-------------|
| [`src/docs/automated-interactive-testing.md`](../automated-interactive-testing.md) | Comprehensive guide to the notification proxy testing system — profiles, Q&A scripts, strategy chain, scenario authoring, CLI reference |
| [`src/tests/smoke/README.md`](../../tests/smoke/README.md) | Quick-start guide for all smoke tests |
| [`src/tests/README.md`](../../tests/README.md) | Lupin 5-tier testing strategy overview |
| [`src/tests/AUTH-TESTING-GUIDE.md`](../../tests/AUTH-TESTING-GUIDE.md) | Test credential management patterns |
| [`src/docs/proxy-admin-guide.md`](../proxy-admin-guide.md) | Decision Proxy admin how-to — Trust Dashboard, Ratification page, trust feedback loop |
| [`src/rnd/v0.1.5/2026.02.23-trust-proxy-preference-learning/2026.02.27-end-to-end-trust-proxy-overview.md`](../../rnd/v0.1.5/2026.02.23-trust-proxy-preference-learning/2026.02.27-end-to-end-trust-proxy-overview.md) | End-to-end conceptual overview — 5 stages from cold start to autonomous proxy, CBR engine, trust models, component map |
