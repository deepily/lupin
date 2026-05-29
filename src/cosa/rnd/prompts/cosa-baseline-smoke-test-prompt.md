# COSA Framework Baseline Smoke Test Prompt (Pre-Change Data Collection)

**PURPOSE**: Establish comprehensive COSA framework baseline before major refactoring or changes
**MODE**: Pure data collection - ZERO remediation attempts
**PRINCIPLE**: Observe First, Fix Later
**SCOPE**: COSA Framework Only

## Your Task

I'm about to make significant changes to the COSA framework and need you to establish a comprehensive baseline of the current framework health. This is a **data collection only** session - do NOT attempt to fix any issues you discover.

### 1. Initialize Todo List

Create a todo list to track the baseline data collection process:

```
[COSA] Establish pre-change COSA framework smoke test baseline - STARTED at [TIMESTAMP]
[COSA] Create logs directory and generate timestamp
[COSA] Set up COSA environment (PYTHONPATH)
[COSA] Execute comprehensive COSA framework smoke tests
[COSA] Generate comprehensive baseline report
[COSA] Send baseline completion notification (if available)
[COSA] Document baseline in session history
```

### 2. Notification: Start of Baseline (Optional)

**If notification system is available**, send notification that baseline collection is starting:
```bash
# Check if notification script exists
if [ -f "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh" ]; then
    /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[COSA] 🔍 COSA framework baseline smoke test collection STARTED - Establishing pre-change framework health metrics" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ Notification system not available - proceeding with COSA baseline collection"
fi
```

### 3. Setup COSA Testing Environment

Execute the following commands to prepare for COSA framework testing:

```bash
# Navigate to COSA root directory
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa

# Create results directory structure
mkdir -p tests/results/logs
mkdir -p tests/results/reports

# Set up COSA framework environment
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
echo "✓ COSA PYTHONPATH configured"

# Verify COSA framework can be imported
python -c "import cosa; print('✓ COSA framework import successful')" || echo "❌ COSA framework import failed"
```

### 4. Execute COSA Framework Smoke Tests

Run comprehensive COSA framework tests with full logging:

```bash
# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "COSA baseline collection timestamp: ${TIMESTAMP}"

LOG_FILE="tests/results/logs/baseline_cosa_smoke_${TIMESTAMP}.log"
echo "Starting COSA framework baseline smoke test collection at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full COSA test suite
./tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "COSA framework smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Analyze and Report Results

Create a comprehensive baseline report with the following structure:

**Report File**: `tests/results/reports/YYYY.MM.DD-cosa-baseline-smoke-test-report.md`

```markdown
# COSA Framework Baseline Smoke Test Report

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Pre-change COSA framework baseline establishment
**Scope**: COSA Framework Only
**COSA Log**: tests/results/logs/baseline_cosa_smoke_[TIMESTAMP].log

## Executive Summary

**Framework Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Total Tests Executed**: [NUMBER] (COSA framework only)
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
**Critical Issues Identified**: [NUMBER]

## COSA Framework Results

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

### Failed Tests (by Priority)
#### CRITICAL Failures
[List any tests with 0% pass rate or core functionality broken]

#### HIGH Priority Failures
[List tests affecting major functionality]

#### MEDIUM Priority Failures
[List tests with edge case or performance issues]

## Performance Metrics

### COSA Framework Performance
- **Test Execution Time**: [XX.X seconds]
- **Module Loading Time**: [X.X ms]
- **Memory Usage**: [As available]
- **Import Performance**: [X.X ms average]

## Known Issues Pattern Analysis

### Common Failure Patterns
[Identify any recurring failure types without attempting fixes]

### Framework Dependencies
[Note any external dependency issues]

### Module Issues
[Document any specific module problems]

## Baseline Established

This baseline establishes the current COSA framework state as of [DATE] [TIME].
Any regressions introduced by upcoming changes can be measured against these metrics.

**Next Steps**: Proceed with planned COSA framework changes. Use COSA post-change smoke test prompt after modifications to validate and remediate any introduced issues.
```

### 6. Update History Document

Add the baseline collection to your session history:

```markdown
#### [DATE] - Pre-Change COSA Framework Baseline Collection

**Summary**: Established comprehensive COSA framework baseline before [DESCRIBE PLANNED CHANGES].

**Baseline Results**:
- **COSA Framework Tests**: [XX.X%] pass rate ([PASSED]/[TOTAL] tests)
- **Framework Health**: [STATUS]
- **Critical Issues**: [NUMBER] identified
- **Report**: [LINK TO REPORT FILE]

**Purpose**: Data collection only - no remediation attempted. COSA framework baseline ready for post-change comparison.
```

### 7. Notification: Baseline Complete (Optional)

**If notification system is available**, send notification that baseline is complete:
```bash
# Check if notification script exists
if [ -f "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh" ]; then
    /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[COSA] ✅ COSA framework baseline collection COMPLETE - [XX.X%] overall pass rate established, ready for changes" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ COSA framework baseline collection complete - notification system not available"
fi
```

### 8. Final Todo List Update

Mark all baseline collection tasks as completed and provide summary.

## CRITICAL REMINDERS

### ❌ DO NOT DO These Things:
- **No Remediation**: Do not fix any failing tests or issues discovered
- **No Environment Changes**: Do not modify COSA configuration files
- **No Code Changes**: Do not modify any COSA source code based on test failures
- **No Deep Investigation**: Do not spend time debugging root causes
- **No Assumptions**: Do not make assumptions about failure causes

### ✅ DO These Things:
- **Comprehensive Logging**: Capture every detail of COSA test execution
- **Complete Documentation**: Record all failures and patterns observed
- **Accurate Metrics**: Provide precise pass/fail counts and percentages
- **Timing Data**: Document COSA performance and execution times
- **Pattern Recognition**: Note recurring themes without taking action

## Success Criteria

✅ **Complete COSA Test Execution**: All COSA framework test categories executed to completion
✅ **Comprehensive Logging**: All output captured to timestamped log files
✅ **Detailed Report**: COSA baseline report generated with metrics and analysis
✅ **History Documentation**: Session documented in history.md
✅ **Optional Notification**: Progress notifications sent if system available
✅ **No Remediation**: Zero fixes attempted - pure data collection achieved

**COSA framework baseline established successfully. Framework is ready for planned changes.**

## Notes for COSA-Only Context

### Working Directory
- All commands assume you're working from the COSA root directory
- Log files stored in `tests/results/logs/` within COSA
- Reports stored in `tests/results/reports/` within COSA

### Dependencies
- **Required**: COSA framework properly accessible via PYTHONPATH
- **Optional**: Parent Lupin notification system (if available)
- **Required**: COSA smoke test infrastructure operational

### Scope Limitations
- **COSA Framework Only**: No Lupin-specific tests (FastAPI, WebSocket, etc.)
- **Framework Focus**: Core, Agents, REST, Memory, Training modules
- **Standalone Operation**: Can be run independently of Lupin project