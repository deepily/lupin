# Baseline Smoke Test Prompt (Pre-Change Data Collection)

**PURPOSE**: Establish comprehensive baseline before major refactoring or changes
**MODE**: Pure data collection - ZERO remediation attempts
**PRINCIPLE**: Observe First, Fix Later

## Test Scope Configuration

**IMPORTANT**: Before starting, specify which test scope to use by setting TEST_SCOPE:

### Option 1: FULL SUITE (Lupin + COSA) - DEFAULT
- Set `TEST_SCOPE="full"` to run both Lupin and COSA smoke tests
- Comprehensive baseline across entire project ecosystem
- Recommended for major refactoring or full system changes

### Option 2: LUPIN ONLY
- Set `TEST_SCOPE="lupin"` to run only Lupin smoke tests (skip COSA framework tests)
- Faster execution when changes are Lupin-specific
- Use when COSA framework is not being modified

**Your Choice**: TEST_SCOPE="full"  *(Change this to "lupin" if desired)*

---

## Your Task

I'm about to make significant changes to the system and need you to establish a comprehensive baseline of the current system health. This is a **data collection only** session - do NOT attempt to fix any issues you discover.

### 1. Initialize Todo List

Create a todo list to track the baseline data collection process:

**If TEST_SCOPE="full":**
```
[LUPIN] Establish pre-change smoke test baseline (FULL) - STARTED at [TIMESTAMP]
[LUPIN] Create logs directory and generate timestamp
[LUPIN] Check FastAPI server status (port 7999)
[LUPIN] Execute full Lupin smoke test suite
[LUPIN] Execute CoSA framework smoke tests
[LUPIN] Generate comprehensive baseline report (Lupin + COSA)
[LUPIN] Send baseline completion notification
[LUPIN] Document baseline in session history
```

**If TEST_SCOPE="lupin":**
```
[LUPIN] Establish pre-change smoke test baseline (LUPIN-ONLY) - STARTED at [TIMESTAMP]
[LUPIN] Create logs directory and generate timestamp
[LUPIN] Check FastAPI server status (port 7999)
[LUPIN] Execute full Lupin smoke test suite
[LUPIN] Generate baseline report (Lupin-only)
[LUPIN] Send baseline completion notification
[LUPIN] Document baseline in session history
```

### 2. Notification: Start of Baseline

Send notification that baseline collection is starting:

**If TEST_SCOPE="full":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[LUPIN] 🔍 Baseline smoke test collection STARTED (FULL SUITE) - Establishing pre-change Lupin + COSA system health metrics" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

**If TEST_SCOPE="lupin":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[LUPIN] 🔍 Baseline smoke test collection STARTED (LUPIN-ONLY) - Establishing pre-change Lupin system health metrics" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

### 3. Setup Data Collection Environment

Execute the following commands to prepare for data collection:

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin

# Create logs directory structure
mkdir -p src/tests/logs

# Check if FastAPI server is running
echo "=== FastAPI Server Health Check ==="
curl -s http://localhost:7999/health || echo "❌ FastAPI server unreachable on port 7999"
```

### 4. Execute Lupin Smoke Tests (Full Suite)

Run comprehensive Lupin smoke tests with full logging:

```bash
# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "Baseline collection timestamp: ${TIMESTAMP}"

LOG_FILE="src/tests/logs/baseline_lupin_smoke_${TIMESTAMP}.log"
echo "Starting Lupin baseline smoke test collection at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full test suite
./src/tests/run-lupin-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "Lupin smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Execute CoSA Framework Smoke Tests (Conditional)

**Check TEST_SCOPE**:
- If TEST_SCOPE="lupin", **SKIP this section** and go directly to step 6.
- If TEST_SCOPE="full", execute the following:

Run comprehensive CoSA framework tests with full logging:

```bash
# Generate timestamp for CoSA logs
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# Set up CoSA environment
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"

# Create CoSA log file
LOG_FILE="src/tests/logs/baseline_cosa_smoke_${TIMESTAMP}.log"
echo "Starting CoSA baseline smoke test collection at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full CoSA test suite
./src/cosa/tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "CoSA smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

**If skipped (TEST_SCOPE="lupin")**: Add this note to your documentation:
```
CoSA framework smoke tests SKIPPED - TEST_SCOPE set to "lupin" only
```

### 6. Analyze and Report Results

Create a comprehensive baseline report with the following structure:

**Report File**: `src/rnd/YYYY.MM.DD-baseline-smoke-test-report.md`

```markdown
# Baseline Smoke Test Report

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Pre-change baseline establishment
**Test Scope**: [TEST_SCOPE value - "full" or "lupin"]
**Lupin Log**: src/tests/logs/baseline_lupin_smoke_[TIMESTAMP].log
**CoSA Log**: [If TEST_SCOPE="full": src/tests/logs/baseline_cosa_smoke_[TIMESTAMP].log | If TEST_SCOPE="lupin": N/A - COSA tests skipped]

## Executive Summary

**Test Scope**: [TEST_SCOPE="full": Lupin + COSA comprehensive testing | TEST_SCOPE="lupin": Lupin-only testing]
**Overall System Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Total Tests Executed**: [NUMBER] [If TEST_SCOPE="lupin": (Lupin only)]
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
**Critical Issues Identified**: [NUMBER]

## Lupin Test Results

### Summary
- **Total Categories**: [NUMBER]
- **Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
- **Categories Failing**: [NUMBER]/[TOTAL]

### Category Breakdown
| Category | Tests | Passed | Failed | Pass Rate | Status |
|----------|-------|--------|--------|-----------|---------|
| WebSocket Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Basic FastAPI Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Notification System | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Audio/TTS System | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Queue Workflow | [#] | [#] | [#] | [XX.X%] | [STATUS] |

### Failed Tests (by Priority)
#### CRITICAL Failures
[List any tests with 0% pass rate or core functionality broken]

#### HIGH Priority Failures
[List tests affecting major functionality]

#### MEDIUM Priority Failures
[List tests with edge case or performance issues]

## CoSA Framework Results (Conditional)

**If TEST_SCOPE="lupin"**:
```
CoSA Framework Results: SKIPPED - TEST_SCOPE set to "lupin" only
```

**If TEST_SCOPE="full"**:

### Summary
- **Total Categories**: [NUMBER]
- **Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
- **Categories Failing**: [NUMBER]/[TOTAL]

### Category Breakdown
| Category | Tests | Passed | Failed | Pass Rate | Status |
|----------|-------|--------|--------|-----------|---------|
| Core | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Agents | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| REST | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Memory | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Training | [#] | [#] | [#] | [XX.X%] | [STATUS] |

## Performance Metrics

### Lupin Performance
- **Test Execution Time**: [XX.X seconds]
- **Average Connection Time**: [X.X ms]
- **Server Response Time**: [X.X ms]

### CoSA Performance (Conditional)

**If TEST_SCOPE="lupin"**:
```
CoSA Performance Metrics: SKIPPED - TEST_SCOPE set to "lupin" only
```

**If TEST_SCOPE="full"**:
- **Test Execution Time**: [XX.X seconds]
- **Module Loading Time**: [X.X ms]
- **Memory Usage**: [As available]

## Known Issues Pattern Analysis

### Common Failure Patterns
[Identify any recurring failure types without attempting fixes]

### Infrastructure Issues
[Note any systemic problems affecting multiple categories]

### Environment Dependencies
[Document any external dependency issues]

## Baseline Established

This baseline establishes the current system state as of [DATE] [TIME].
Any regressions introduced by upcoming changes can be measured against these metrics.

**Next Steps**: Proceed with planned changes. Use post-change smoke test prompt after modifications to validate and remediate any introduced issues.
```

### 7. Update History Document

Add the baseline collection to your session history:

```markdown
#### [DATE] - Pre-Change Baseline Smoke Test Collection

**Summary**: Established comprehensive baseline before [DESCRIBE PLANNED CHANGES].

**Baseline Results**:
- **Test Scope**: [TEST_SCOPE value]
- **Lupin Tests**: [XX.X%] pass rate ([PASSED]/[TOTAL] tests)
- **CoSA Tests**: [If TEST_SCOPE="full": [XX.X%] pass rate ([PASSED]/[TOTAL] tests) | If TEST_SCOPE="lupin": SKIPPED]
- **Overall Health**: [STATUS]
- **Critical Issues**: [NUMBER] identified
- **Report**: [LINK TO REPORT FILE]

**Purpose**: Data collection only - no remediation attempted. Baseline ready for post-change comparison.
```

### 8. Notification: Baseline Complete

Send notification that baseline is complete:

**If TEST_SCOPE="full":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[LUPIN] ✅ Baseline smoke test collection COMPLETE (FULL SUITE) - [XX.X%] overall pass rate established, Lupin + COSA ready for changes" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

**If TEST_SCOPE="lupin":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[LUPIN] ✅ Baseline smoke test collection COMPLETE (LUPIN-ONLY) - [XX.X%] Lupin pass rate established, ready for changes" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

### 9. Final Todo List Update

Mark all baseline collection tasks as completed and provide summary.

## CRITICAL REMINDERS

### ❌ DO NOT DO These Things:
- **No Remediation**: Do not fix any failing tests or issues discovered
- **No Environment Changes**: Do not restart services or modify configurations
- **No Code Changes**: Do not modify any source code based on test failures
- **No Deep Investigation**: Do not spend time debugging root causes
- **No Assumptions**: Do not make assumptions about failure causes

### ✅ DO These Things:
- **Comprehensive Logging**: Capture every detail of test execution
- **Complete Documentation**: Record all failures and patterns observed
- **Accurate Metrics**: Provide precise pass/fail counts and percentages
- **Timing Data**: Document performance and execution times
- **Pattern Recognition**: Note recurring themes without taking action

## Success Criteria

✅ **Complete Test Execution**: All test categories executed to completion
✅ **Comprehensive Logging**: All output captured to timestamped log files
✅ **Detailed Report**: Baseline report generated with metrics and analysis
✅ **History Documentation**: Session documented in history.md
✅ **Notification Sent**: Progress notifications sent at start and completion
✅ **No Remediation**: Zero fixes attempted - pure data collection achieved

**Baseline established successfully. System is ready for planned changes.**