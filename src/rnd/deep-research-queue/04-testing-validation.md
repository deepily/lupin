# Testing & Validation - Deep Research Queue Integration

> **Test Strategy Document** | Created: 2026-01-18

## Testing Philosophy

Following LUPIN's three-tier testing strategy:
1. **Smoke Tests**: Quick sanity checks for new modules
2. **Unit Tests**: Isolated function tests for complex logic
3. **Integration Tests**: End-to-end workflow validation

## Phase 1-4 Testing (Session 69)

### Smoke Tests

**AgenticJobBase Smoke Test** (`src/cosa/agents/agentic_job_base.py`):
```python
def quick_smoke_test():
    """Quick smoke test for AgenticJobBase."""
    import cosa.utils.util as cu
    cu.print_banner( "AgenticJobBase Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.agentic_job_base import AgenticJobBase
        print( "✓ Module imported successfully" )

        # Test 2: Can't instantiate abstract class
        print( "Testing abstract class protection..." )
        try:
            AgenticJobBase( "user1", "test@test.com", "session1" )
            print( "✗ Should not instantiate abstract class!" )
        except TypeError:
            print( "✓ Abstract class correctly prevents instantiation" )

        print( "\n✓ Smoke test completed successfully" )
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
```

**DeepResearchJob Smoke Test** (`src/cosa/agents/deep_research/job.py`):
```python
def quick_smoke_test():
    """Quick smoke test for DeepResearchJob."""
    import cosa.utils.util as cu
    cu.print_banner( "DeepResearchJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research.job import DeepResearchJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = DeepResearchJob(
            query="test query",
            user_id="user123",
            user_email="test@test.com",
            session_id="session456",
            budget=1.00,
            debug=True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "dr-" ), "ID should start with dr-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Deep Research]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        print( "\n✓ Smoke test completed successfully" )
    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()
```

### Manual API Testing (curl)

**Submit Job Test**:
```bash
# Test 1: Submit research job
curl -X POST http://localhost:7999/api/deep-research/submit \
  -H "Authorization: Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "test topic for smoke testing",
    "user_email": "ricardo.felipe.ruiz@gmail.com",
    "budget": 0.10,
    "websocket_id": "test-session"
  }'

# Expected: {"status": "queued", "job_id": "dr-...", ...}
```

**Check Queue Status**:
```bash
# Test 2: Check todo queue
curl http://localhost:7999/api/get-queue/todo \
  -H "Authorization: Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com"

# Test 3: Check running queue
curl http://localhost:7999/api/get-queue/running \
  -H "Authorization: Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com"

# Test 4: Check done queue (after job completes)
curl http://localhost:7999/api/get-queue/done \
  -H "Authorization: Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com"
```

**Error Cases**:
```bash
# Test 5: Missing auth
curl -X POST http://localhost:7999/api/deep-research/submit \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
# Expected: 401 Unauthorized

# Test 6: Invalid request
curl -X POST http://localhost:7999/api/deep-research/submit \
  -H "Authorization: Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com" \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: 422 Validation Error
```

### Verification Checklist

**Phase 1 - AgenticJobBase**:
- [ ] Module imports without error
- [ ] Abstract class prevents direct instantiation
- [ ] Subclass can be created
- [ ] `id_hash` generates unique IDs with prefix
- [ ] `is_cacheable` returns False

**Phase 2 - DeepResearchJob**:
- [ ] Module imports without error
- [ ] Job instantiates with all parameters
- [ ] `id_hash` starts with "dr-"
- [ ] `last_question_asked` returns formatted string
- [ ] `is_cacheable` returns False (inherited)

**Phase 3 - FastAPI Endpoint**:
- [ ] Endpoint accessible at `/api/deep-research/submit`
- [ ] Returns 401 without auth
- [ ] Returns 422 for invalid body
- [ ] Creates job and pushes to queue
- [ ] Returns job_id in response

**Phase 4 - Queue Integration**:
- [ ] Job picked up by consumer thread
- [ ] Job moves todo → running → done
- [ ] WebSocket events broadcast
- [ ] No snapshot storage attempted

---

## Future Phase Testing

### Phase 5 - cosa-voice Enhancement
- [ ] `job_id` parameter accepted by all tools
- [ ] Notifications with job_id include it in payload
- [ ] Backward compatible (job_id=None works)

### Phase 6-7 - Frontend
- [ ] Job cards render in Queue View
- [ ] Activity log updates in real-time
- [ ] Completed jobs show abstract and report link
- [ ] Interactive prompts appear in Response Required

### Phase 8 - COSA Router
- [ ] Natural language triggers deep research
- [ ] Budget extracted from constraints
- [ ] User email resolved from auth context

---

## Test Data

### Sample Queries

| Query | Budget | Expected Duration |
|-------|--------|-------------------|
| "test topic" | $0.10 | ~30 seconds |
| "cats vs dogs" | $0.50 | ~2 minutes |
| "quantum computing approaches" | $2.00 | ~5 minutes |

### Test Users

| Email | Token Format |
|-------|--------------|
| ricardo.felipe.ruiz@gmail.com | `Bearer mock_token_email_ricardo.felipe.ruiz@gmail.com` |
| test@test.com | `Bearer mock_token_email_test@test.com` |

---

## Known Limitations

1. **No live research in tests**: Smoke tests verify structure only, not actual research execution
2. **Budget enforcement**: Budget is passed but enforcement depends on Anthropic API
3. **WebSocket testing**: Manual observation required for WebSocket events
