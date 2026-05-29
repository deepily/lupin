# Test Harness for Agentic Jobs

Zero-cost testing infrastructure for the Lupin queue system.

## Overview

The test harness provides mock implementations of long-running agentic jobs that simulate
the full queue lifecycle (todo → run → done/dead) without incurring inference costs.

## MockAgenticJob

Simulates long-running agentic jobs (like Deep Research) without making any API calls.

### Features

- **Configurable iteration count**: Random (within range) or fixed
- **Configurable sleep duration**: Random (within range) or fixed between phases
- **Configurable failure probability**: Simulate failures for testing dead queue
- **Real notifications**: Emits progress notifications via cosa-voice MCP
- **Mock artifacts**: Creates fake report_path, abstract, and cost_summary for UI testing
- **Full queue integration**: Works with existing queue consumer/producer

### Use Cases

1. **UI Development**: Test queue visualization without waiting for real jobs
2. **Queue Flood Testing**: Submit multiple jobs to test queue stacking
3. **Failure Path Testing**: Verify dead queue and error display
4. **Phase 6 Validation**: Test job_id notification routing
5. **Phase 7 Validation**: Test enhanced job cards (status, duration, artifacts)

## API Endpoint

### POST /api/mock-job/submit

Submit a mock job to the todo queue.

**Authentication**: Required (Bearer token)

**Request Body** (all fields optional with defaults):

```json
{
    "iterations_min": 3,
    "iterations_max": 8,
    "sleep_min": 1.0,
    "sleep_max": 5.0,
    "failure_probability": 0.0,
    "fixed_iterations": null,
    "fixed_sleep": null,
    "description": "Custom description",
    "websocket_id": "session-id"
}
```

**Response**:

```json
{
    "status": "queued",
    "job_id": "mock-a1b2c3d4",
    "queue_position": 1,
    "config": {
        "iterations": 5,
        "sleep_seconds": 2.34,
        "will_fail": false,
        "fail_at_iteration": null,
        "estimated_duration": "11.7s"
    },
    "message": "Mock job queued: [Mock] Test job with 5 phases"
}
```

### GET /api/mock-job/health

Health check endpoint.

## Quick Start

### 1. Get Authentication Token

```bash
TOKEN=$(curl -s -X POST "http://localhost:7999/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com", "password": "PASSWORD"}' \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['tokens']['access_token'])")
```

### 2. Submit Quick Mock Job (2 iterations, 1 second each)

```bash
curl -X POST "http://localhost:7999/api/mock-job/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fixed_iterations": 2, "fixed_sleep": 1.0}'
```

### 3. Submit Mock Job with Defaults (random 3-8 iterations, 1-5s sleep)

```bash
curl -X POST "http://localhost:7999/api/mock-job/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 4. Submit Failing Mock Job

```bash
curl -X POST "http://localhost:7999/api/mock-job/submit" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"failure_probability": 1.0, "fixed_iterations": 3}'
```

### 5. Queue Flood Test (5 jobs)

```bash
for i in {1..5}; do
  curl -X POST "http://localhost:7999/api/mock-job/submit" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"fixed_iterations": 2, "fixed_sleep": 1.5}'
  echo ""
done
```

### 6. Check Queue Status

```bash
# Check todo queue
curl -s "http://localhost:7999/api/get-queue/todo" -H "Authorization: Bearer $TOKEN"

# Check running queue
curl -s "http://localhost:7999/api/get-queue/run" -H "Authorization: Bearer $TOKEN"

# Check done queue
curl -s "http://localhost:7999/api/get-queue/done" -H "Authorization: Bearer $TOKEN"

# Check dead queue
curl -s "http://localhost:7999/api/get-queue/dead" -H "Authorization: Bearer $TOKEN"
```

## Configuration Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `iterations_min` | int | 3 | Minimum iterations (1-20) |
| `iterations_max` | int | 8 | Maximum iterations (1-20) |
| `sleep_min` | float | 1.0 | Minimum sleep seconds (0.1-30.0) |
| `sleep_max` | float | 5.0 | Maximum sleep seconds (0.1-30.0) |
| `failure_probability` | float | 0.0 | Probability of failure (0.0-1.0) |
| `fixed_iterations` | int | null | Override random iterations |
| `fixed_sleep` | float | null | Override random sleep |
| `description` | string | null | Custom description for queue display |
| `websocket_id` | string | null | WebSocket session ID for notifications |

## Running the Smoke Test

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin
export PYTHONPATH="src:$PYTHONPATH"
python -m cosa.agents.test_harness.mock_job
```

Expected output:

```
==================================================
  MockAgenticJob Smoke Test
==================================================
Testing module import...
✓ Module imported successfully
Testing job instantiation with defaults...
✓ Job created with id: mock-a1b2c3d4
  - iterations: 5
  - sleep_seconds: 2.34
  - will_fail: False
...
✓ Smoke test completed successfully
```

## Mock Artifacts (for Done Queue Display)

When a mock job completes successfully, it creates mock artifacts:

```python
{
    "report_path": "/io/mock-reports/mock-a1b2c3d4/report.md",
    "abstract": "Mock research completed successfully. Simulated 5 phases over 11.7 seconds. This is a test job for UI development."
}
```

And a cost summary:

```python
{
    "total_cost_usd": 0.0,
    "total_input_tokens": 3542,
    "total_output_tokens": 1287,
    "duration_seconds": 11.7
}
```

These artifacts are designed to exercise the Phase 7 enhanced done job card UI without
requiring any actual inference calls.

## Implementation Files

| File | Description |
|------|-------------|
| `__init__.py` | Package exports |
| `mock_job.py` | MockAgenticJob class (~300 lines) |
| `README.md` | This documentation |
| `../../../rest/routers/mock_job.py` | API router (~120 lines) |

## Related Documentation

- **AgenticJobBase**: `src/cosa/agents/agentic_job_base.py`
- **DeepResearchJob**: `src/cosa/agents/deep_research/job.py`
- **Queue System**: `src/cosa/rest/running_fifo_queue.py`
- **Phase 7 Plan**: `/home/rruiz/.claude/plans/tidy-doodling-pizza.md`
