# WG-2 — Smoke-test prerequisite skip discipline (7 ERRORs + 9 FAILs)

## Root causes (three sub-bugs)

### WG-2a — `_docker_available()` doesn't catch `FileNotFoundError`

`src/tests/smoke/test_container_preflight.py:31-37` calls `subprocess.run(['docker', 'info'])` without guarding. When the docker binary isn't on PATH (test container reality), the exception escapes the autouse fixture → 7 setup ERRORs instead of 7 graceful SKIPs.

### WG-2b — `LivePipelineTestBase` returns silent `False` instead of `pytest.skip()`

`src/tests/smoke/utilities/live_pipeline_base.py:689-694` (credential check) and `:789-791` (ConnectionError handler) return `False`. The 9 inheriting test files wrap `run_scenarios` in `assert quick_smoke_test()` → infrastructure gaps surface as FAIL, not SKIP.

Inheriting test files (confirmed by exploration):
- `test_calculator_live_pipeline`
- `test_test_suite_live_pipeline`
- `test_proxy_integration`
- `test_swe_team_proxy`
- `test_presentation_live_smoke`
- `test_research_to_presentation_live_smoke`
- `test_podcast_generator_dry_run_smoke`
- `test_deep_research_submit_smoke`
- `test_deep_research_dry_run_smoke`

### WG-2c — bare `assert quick_smoke_test()` in pytest entry points

Most pytest entry points in `bfe_phase6_repair_loop_smoke`, `presentation_render_only_smoke`, etc. are bare `assert quick_smoke_test()`. They benefit automatically from WG-2b. Spot-check confirms no per-file work needed.

## Fixes

### WG-2a fix (`test_container_preflight.py`)

```python
def _docker_available():
    try:
        result = subprocess.run( [ "docker", "info" ], capture_output=True, timeout=5 )
        return result.returncode == 0
    except ( FileNotFoundError, OSError, subprocess.TimeoutExpired ):
        return False
```

### WG-2b fix (`live_pipeline_base.py`)

Conditional pytest import (keeps file runnable as standalone CLI script). At each of the two sites:

```python
try:
    import pytest as _pytest
except ImportError:
    _pytest = None

# ... in run_scenarios, at credential gate (line ~689):
if not email or not password:
    if _pytest is not None:
        _pytest.skip( f"{self.CREDENTIAL_ENV_PREFIX}_{{EMAIL,PASSWORD}} not set" )
    print( "Missing environment variables..." )
    return False

# ... in run_scenarios, at ConnectionError handler (line ~789):
except requests.exceptions.ConnectionError:
    if _pytest is not None:
        _pytest.skip( f"server unreachable at {self.BASE_URL}" )
    print( f"\nConnection failed - is the server running on {self.BASE_URL}?" )
    return False
```

The `print` + `return False` paths remain reachable when invoked outside pytest.

## Acceptance

- `pytest src/tests/smoke/test_container_preflight.py` reports **7 SKIPPED**, 0 ERROR (when no docker on PATH).
- `pytest src/tests/smoke/test_calculator_live_pipeline.py` reports **SKIPPED** when `LUPIN_TEST_INTERACTIVE_MOCK_JOBS_*` unset or `:7999` unreachable, **PASSED** when prereqs satisfied.
- All 9 inheriting tests benefit automatically.

## Files

- `src/tests/smoke/test_container_preflight.py` (~4 lines)
- `src/tests/smoke/utilities/live_pipeline_base.py` (~10 lines, two sites)

## Status

- [ ] WG-2a edit
- [ ] WG-2a py_compile
- [ ] WG-2b edit
- [ ] WG-2b py_compile
- [ ] Smoke run on `:7999` to confirm SKIPs
