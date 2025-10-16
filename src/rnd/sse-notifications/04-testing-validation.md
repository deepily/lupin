# SSE Notification System - Testing & Validation

**Last Updated**: 2025.10.15

## Related Documentation

- **[Index](00-index.md)**: Master navigation
- **[Current Implementation](01-implementation-current.md)**: Active phases
- **[Architecture](02-architecture.md)**: System design
- **[Decisions](03-decisions.md)**: Decision log

---

## Test Strategy

### Testing Approach

**Phase 1 (PoC)**: Manual testing + validation scripts
- Goal: Validate SSE pattern works end-to-end
- Scope: Standalone components on port 8000
- Method: Manual execution, observation, test scenarios

**Phase 2 (Production)**: Manual testing + integration tests
- Goal: Validate production integration
- Scope: Port 7999 endpoint + script migration
- Method: Integration tests with production environment

### Test Pyramid

```
                    ▲
                   / \
                  /   \
                 /  E2E \ (Phase 1 & 2)
                /_______\
               /         \
              / Integration\ (Phase 2 only)
             /____________\
            /              \
           /  Unit (optional)\
          /___________________\
```

**Focus**: E2E testing for PoC validation, integration testing for production

---

## Phase 1: PoC Test Plan

### Test Scenarios

#### Scenario 1: Happy Path - Successful Notification

**Setup**:
- Terminal 1: `python src/server.py` (running on port 8000)
- Terminal 2: `./src/send-notification-from-claude-sync "Test message" 5 120`

**Expected Behavior**:
1. Client connects to server successfully
2. Server sends ack event: `[ACK] Request received`
3. Server sends heartbeat events every 5s: `[HEARTBEAT] Elapsed: 5.01s`
4. Server completes processing (random 2-120s)
5. Server sends result event: `SUCCESS: Processed: Test message (took Xs)`
6. Client exits with code 0
7. Bash wrapper captures result in stdout

**Validation**:
- ✓ All events received in correct order
- ✓ Heartbeats maintain connection
- ✓ Result delivered to bash wrapper
- ✓ Exit code = 0
- ✓ stdout contains result, stderr contains diagnostics

---

#### Scenario 2: Timeout - Processing Exceeds Limit

**Setup**:
- Modify server to simulate long processing (>120 seconds)
- Terminal 1: `python src/server.py`
- Terminal 2: `./src/send-notification-from-claude-sync "Test message" 5 10`
  (Note: 10 second timeout for faster testing)

**Expected Behavior**:
1. Client connects successfully
2. Ack received
3. Heartbeats received every 5s
4. After 10 seconds, client times out
5. Client prints: `ERROR: Timeout after 10s`
6. Client exits with code 1
7. Server continues processing (connection dropped)

**Validation**:
- ✓ Timeout triggers after specified duration
- ✓ Client exits cleanly with error code
- ✓ Error message visible in stderr
- ✓ No zombie processes
- ✓ Server handles dropped connection gracefully

---

#### Scenario 3: Connection Failure - Server Not Running

**Setup**:
- Ensure server is NOT running on port 8000
- Terminal 1: `./src/send-notification-from-claude-sync "Test message" 5 120`

**Expected Behavior**:
1. Client attempts connection
2. Connection refused immediately
3. Error printed: `ERROR: Request failed: Connection refused`
4. Client exits with code 1

**Validation**:
- ✓ Clean error message
- ✓ Exit code = 1
- ✓ No hanging processes

---

#### Scenario 4: Malformed Response - Invalid JSON

**Setup**:
- Modify server to send invalid JSON (manual test)
- Terminal 1: `python src/server.py` (with injected bad JSON)
- Terminal 2: `./src/send-notification-from-claude-sync "Test message" 5 120`

**Expected Behavior**:
1. Client connects successfully
2. Client receives malformed event
3. JSON parse error logged: `ERROR: Failed to parse event: ...`
4. Client continues processing (doesn't crash)
5. Final result still delivered if possible

**Validation**:
- ✓ Client handles JSON errors gracefully
- ✓ Logging shows parse errors
- ✓ Client doesn't crash on bad events
- ✓ Connection remains open

---

### Test Execution Checklist

#### Pre-Testing Setup
- [ ] Python dependencies installed: `fastapi`, `uvicorn`, `requests`
- [ ] Server script exists: `src/server.py`
- [ ] Client script exists: `src/client.py`
- [ ] Bash wrapper exists and is executable: `src/send-notification-from-claude-sync`
- [ ] Port 8000 is available (not in use)

#### Test Execution
- [ ] Scenario 1: Happy path completed successfully
- [ ] Scenario 2: Timeout behavior validated
- [ ] Scenario 3: Connection failure handled correctly
- [ ] Scenario 4: Malformed JSON handled gracefully

#### Post-Testing Validation
- [ ] No zombie processes remaining
- [ ] Server shuts down cleanly
- [ ] Exit codes correct (0 for success, 1 for errors)
- [ ] stdout/stderr separation working correctly

---

## Phase 2: Production Integration Test Plan

### Integration Test Scenarios

#### Scenario 5: Production SSE Endpoint

**Setup**:
- Production FastAPI running on port 7999
- SSE endpoint registered: `/api/notifications/sse`

**Test**:
```bash
./send-notification-from-claude-sync "Production test" 5 120
```

**Expected Behavior**:
1. Connect to port 7999 (not 8000)
2. Route to `/api/notifications/sse` endpoint
3. Same event flow as PoC
4. Result delivered successfully

**Validation**:
- ✓ Endpoint accessible on port 7999
- ✓ Routing works correctly
- ✓ SSE events flow as expected
- ✓ Result captured successfully

---

#### Scenario 6: Async Endpoint Still Works

**Setup**:
- Production FastAPI running on port 7999
- Both async and sync scripts available

**Test**:
```bash
# Test async (fire-and-forget)
send-notification-from-claude-async "Async test" --type=task --priority=low

# Test sync (wait for response)
send-notification-from-claude-sync "Sync test" 5 120
```

**Expected Behavior**:
- Async script returns immediately (no wait)
- Sync script waits for response
- Both work correctly without conflicts

**Validation**:
- ✓ Async endpoint still functional
- ✓ Sync endpoint works independently
- ✓ No interference between endpoints
- ✓ Correct routing for each script

---

#### Scenario 7: Script Migration Verification

**Setup**:
- Scripts deployed to `/home/rruiz/.local/bin/`
- Old script renamed: `notify-claude` → `send-notification-from-claude-async`
- New script added: `send-notification-from-claude-sync`

**Test**:
```bash
# Verify scripts are accessible
which send-notification-from-claude-async
which send-notification-from-claude-sync

# Test both scripts
send-notification-from-claude-async "Async test"
send-notification-from-claude-sync "Sync test" 5 120
```

**Expected Behavior**:
- Both scripts found in PATH
- Both scripts execute successfully
- Correct behavior for each (async vs sync)

**Validation**:
- ✓ Scripts deployed to correct location
- ✓ Scripts are executable
- ✓ Scripts accessible from any directory
- ✓ Correct behavior for each type

---

### Integration Test Execution Checklist

#### Pre-Integration Setup
- [ ] Phase 1 PoC completed and validated
- [ ] Production FastAPI server accessible (port 7999)
- [ ] SSE endpoint implemented and registered
- [ ] Scripts ready for deployment

#### Integration Testing
- [ ] Scenario 5: Production SSE endpoint tested
- [ ] Scenario 6: Async/sync coexistence verified
- [ ] Scenario 7: Script migration validated

#### Post-Integration Validation
- [ ] Both endpoints operational
- [ ] No performance degradation
- [ ] Team documentation updated
- [ ] Migration guide provided

---

## Performance Validation

### Metrics to Monitor

**Connection Metrics**:
- Time to establish connection (should be < 100ms)
- Heartbeat consistency (every ~5s, ±0.5s)
- Timeout accuracy (within ±1s of specified timeout)

**Processing Metrics**:
- Server processing time (2-120s for PoC, depends on actual work in production)
- Client event parsing latency (< 10ms per event)
- Total round-trip time (connection + processing + result delivery)

**Resource Metrics**:
- Memory usage (should be stable, no leaks)
- CPU usage (minimal during idle, spike during processing)
- Open connections (cleaned up after completion)

### Performance Test Commands

```bash
# Measure connection time
time ./src/send-notification-from-claude-sync "test" 5 120

# Monitor server resources
top -p $(pgrep -f "python src/server.py")

# Check open connections
netstat -an | grep 8000  # PoC
netstat -an | grep 7999  # Production
```

---

## Test Results Log

### Phase 1 Results

**Date**: TBD
**Test**: PoC Validation
**Results**: (To be filled during testing)

| Scenario | Status | Notes |
|----------|--------|-------|
| Happy path | ⧖ Pending | |
| Timeout | ⧖ Pending | |
| Connection failure | ⧖ Pending | |
| Malformed JSON | ⧖ Pending | |

---

### Phase 2 Results

**Date**: TBD
**Test**: Production Integration
**Results**: (To be filled during testing)

| Scenario | Status | Notes |
|----------|--------|-------|
| Production endpoint | ⧖ Pending | |
| Async/sync coexistence | ⧖ Pending | |
| Script migration | ⧖ Pending | |

---

## Known Issues & Limitations

### Phase 1 (PoC)

**None identified yet** - will update during testing

### Phase 2 (Production)

**Anticipated Issues**:
- Port 7999 routing conflicts (mitigation: careful endpoint naming)
- Script migration disruption (mitigation: phased rollout with team communication)

---

*Token count target: 3,000-6,000*
*Update with test results as validation progresses*
