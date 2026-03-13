# {{PROJECT_NAME}} Baseline Smoke Test Prompt (Pre-Change Data Collection)

**PURPOSE**: Establish comprehensive {{PROJECT_NAME}} baseline before major refactoring or changes
**MODE**: Pure data collection - ZERO remediation attempts
**PRINCIPLE**: Observe First, Fix Later

## Your Task

I'm about to make significant changes to {{PROJECT_NAME}} and need you to establish a comprehensive baseline of the current system health. This is a **data collection only** session - do NOT attempt to fix any issues you discover.

### 1. Initialize Todo List

Create a todo list to track the baseline data collection process:

```
{{PROJECT_PREFIX}} Establish pre-change {{PROJECT_NAME}} baseline - STARTED at [TIMESTAMP]
{{PROJECT_PREFIX}} Create logs directory and generate timestamp
{{PROJECT_PREFIX}} Check system status and dependencies
{{PROJECT_PREFIX}} Execute full {{PROJECT_NAME}} test suite
{{PROJECT_PREFIX}} Generate comprehensive baseline report
{{PROJECT_PREFIX}} Send baseline completion notification
{{PROJECT_PREFIX}} Document baseline in session history
```

### 2. Notification: Start of Baseline

**If notification system is available**, send notification that baseline collection is starting:
```bash
# Check if notification script exists
if [ -f "{{NOTIFICATION_SCRIPT}}" ]; then
    {{NOTIFICATION_SCRIPT}} "{{PROJECT_PREFIX}} 🔍 {{PROJECT_NAME}} baseline collection STARTED - Establishing pre-change system health metrics" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ Notification system not available - proceeding with {{PROJECT_NAME}} baseline collection"
fi
```

### 3. Setup Data Collection Environment

Execute the following commands to prepare for data collection:

```bash
# Navigate to project root
cd {{PROJECT_ROOT}}

# Create logs directory structure
mkdir -p tests/logs

# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "{{PROJECT_NAME}} baseline collection timestamp: ${TIMESTAMP}"

# Check system dependencies and health
echo "=== {{PROJECT_NAME}} System Health Check ==="
# Add project-specific health checks here
# Example: curl -s {{SERVER_HEALTH_URL}} || echo "❌ Server unreachable"
# Example: python -c "import {{PROJECT_NAME}}; print('✓ Import successful')"
```

### 4. Execute {{PROJECT_NAME}} Test Suite

Run comprehensive {{PROJECT_NAME}} tests with full logging:

```bash
LOG_FILE="tests/logs/baseline_{{PROJECT_NAME}}_smoke_${TIMESTAMP}.log"
echo "Starting {{PROJECT_NAME}} baseline smoke test collection at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute test suite
{{TEST_SCRIPT}} 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "{{PROJECT_NAME}} smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Analyze and Report Results

Create a comprehensive baseline report with the following structure:

**Report File**: `rnd/YYYY.MM.DD-{{PROJECT_NAME}}-baseline-smoke-test-report.md`

```markdown
# {{PROJECT_NAME}} Baseline Smoke Test Report

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Pre-change {{PROJECT_NAME}} baseline establishment
**Test Log**: tests/logs/baseline_{{PROJECT_NAME}}_smoke_[TIMESTAMP].log

## Executive Summary

**System Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Total Tests Executed**: [NUMBER]
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
**Critical Issues Identified**: [NUMBER]

## {{PROJECT_NAME}} Test Results

### Summary
- **Total Categories**: [NUMBER]
- **Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests)
- **Categories Failing**: [NUMBER]/[TOTAL]

### Category Breakdown
| Category | Tests | Passed | Failed | Pass Rate | Status |
|----------|-------|--------|--------|-----------|---------|
| [CATEGORY_1] | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| [CATEGORY_2] | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| [CATEGORY_3] | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| [CATEGORY_4] | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| [CATEGORY_5] | [#] | [#] | [#] | [XX.X%] | [STATUS] |

### Failed Tests (by Priority)
#### CRITICAL Failures
[List any tests with 0% pass rate or core functionality broken]

#### HIGH Priority Failures
[List tests affecting major functionality]

#### MEDIUM Priority Failures
[List tests with edge case or performance issues]

## Performance Metrics

### {{PROJECT_NAME}} Performance
- **Test Execution Time**: [XX.X seconds]
- **[METRIC_1]**: [VALUE]
- **[METRIC_2]**: [VALUE]
- **[METRIC_3]**: [VALUE]

## Known Issues Pattern Analysis

### Common Failure Patterns
[Identify any recurring failure types without attempting fixes]

### Infrastructure Issues
[Note any systemic problems affecting multiple categories]

### Environment Dependencies
[Document any external dependency issues]

## Baseline Established

This baseline establishes the current {{PROJECT_NAME}} state as of [DATE] [TIME].
Any regressions introduced by upcoming changes can be measured against these metrics.

**Next Steps**: Proceed with planned {{PROJECT_NAME}} changes. Use {{PROJECT_NAME}} post-change smoke test prompt after modifications to validate and remediate any introduced issues.
```

### 6. Update History Document

Add the baseline collection to your session history:

```markdown
#### [DATE] - Pre-Change {{PROJECT_NAME}} Baseline Collection

**Summary**: Established comprehensive {{PROJECT_NAME}} baseline before [DESCRIBE PLANNED CHANGES].

**Baseline Results**:
- **{{PROJECT_NAME}} Tests**: [XX.X%] pass rate ([PASSED]/[TOTAL] tests)
- **System Health**: [STATUS]
- **Critical Issues**: [NUMBER] identified
- **Report**: [LINK TO REPORT FILE]

**Purpose**: Data collection only - no remediation attempted. {{PROJECT_NAME}} baseline ready for post-change comparison.
```

### 7. Notification: Baseline Complete

**If notification system is available**, send notification that baseline is complete:
```bash
# Check if notification script exists
if [ -f "{{NOTIFICATION_SCRIPT}}" ]; then
    {{NOTIFICATION_SCRIPT}} "{{PROJECT_PREFIX}} ✅ {{PROJECT_NAME}} baseline collection COMPLETE - [XX.X%] overall pass rate established, ready for changes" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ {{PROJECT_NAME}} baseline collection complete - notification system not available"
fi
```

### 8. Final Todo List Update

Mark all baseline collection tasks as completed and provide summary.

## CRITICAL REMINDERS

### ❌ DO NOT DO These Things:
- **No Remediation**: Do not fix any failing tests or issues discovered
- **No Environment Changes**: Do not restart services or modify configurations
- **No Code Changes**: Do not modify any {{PROJECT_NAME}} source code based on test failures
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
✅ **Detailed Report**: {{PROJECT_NAME}} baseline report generated with metrics and analysis
✅ **History Documentation**: Session documented in history.md
✅ **Optional Notification**: Progress notifications sent if system available
✅ **No Remediation**: Zero fixes attempted - pure data collection achieved

**{{PROJECT_NAME}} baseline established successfully. System is ready for planned changes.**

---

## Template Customization Notes

**Before using this template:**

1. **Replace all placeholders** with project-specific values:
   - `{{PROJECT_NAME}}` → Your project name
   - `{{PROJECT_PREFIX}}` → Your TodoWrite prefix (e.g., [MYPROJECT])
   - `{{PROJECT_ROOT}}` → Full path to your project root
   - `{{TEST_SCRIPT}}` → Path to your test execution script
   - `{{NOTIFICATION_SCRIPT}}` → Path to your notification script

2. **Customize test categories** in the report table to match your project structure

3. **Update performance metrics** to reflect what your project tracks

4. **Modify health checks** in step 3 to match your project's dependencies

5. **Remove or modify** notification sections if not applicable

6. **Adjust file paths** to match your project's directory structure