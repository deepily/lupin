---
description: Run Lupin post-change verification and remediation
allowed-tools: Bash(.*), TodoWrite, Read, Write, Edit, MultiEdit, Grep, Glob
arguments:
  - name: baseline_report
    description: Path to baseline report (optional, auto-detects latest)
    required: false
  - name: scope
    description: Remediation scope (FULL|CRITICAL_ONLY|SELECTIVE|ANALYSIS_ONLY)
    required: false
    default: FULL
---

# Lupin Post-Change Smoke Test (Verification & Remediation)

**PURPOSE**: Verify system health after major changes and remediate any introduced regressions
**MODE**: Comparison analysis with targeted remediation
**PRINCIPLE**: Compare, Analyze, Fix, Validate
**ARGUMENTS**: baseline_report=${1:-auto}, scope=${2:-FULL}

## Your Task

I have completed significant changes to the system and need you to verify the system health compared to the pre-change baseline, identify any regressions introduced, and systematically remediate any breaking changes.

### 1. Pre-Flight Validation & Setup

First, validate prerequisites and setup the remediation environment:

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box

# Auto-detect baseline report if not provided
if [ "${1}" = "auto" ] || [ -z "${1}" ]; then
    BASELINE_REPORT=$(ls -t src/rnd/*baseline-smoke-test-report.md 2>/dev/null | head -1)
    if [ -z "$BASELINE_REPORT" ]; then
        echo "❌ No baseline report found. Please run /smoke-test-baseline first or provide path"
        echo "Available reports:"
        ls -la src/rnd/*baseline*.md 2>/dev/null || echo "No baseline reports found"
        exit 1
    fi
    echo "✅ Auto-detected baseline: $BASELINE_REPORT"
else
    BASELINE_REPORT="${1}"
    if [ ! -f "$BASELINE_REPORT" ]; then
        echo "❌ Baseline report not found: $BASELINE_REPORT"
        exit 1
    fi
    echo "✅ Using specified baseline: $BASELINE_REPORT"
fi

# Set remediation scope
SCOPE="${2:-FULL}"
echo "✅ Remediation scope: $SCOPE"

# Create logs directory structure
mkdir -p src/tests/logs

# Create backup point
echo "Creating remediation backup point..."
git stash push -m "Pre-remediation backup $(date +%Y%m%d_%H%M%S)" --include-untracked 2>/dev/null || echo "✓ Working tree clean - no backup needed"
echo "✅ Git state captured for potential rollback"

# Generate timestamp for session
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "Session timestamp: ${TIMESTAMP}"

# Check if FastAPI server is running after changes
echo "=== Post-Change FastAPI Server Health Check ==="
curl -s http://localhost:7999/health || echo "❌ FastAPI server unreachable on port 7999"
```

### 2. Initialize Comprehensive Todo List

Create a todo list to track the post-change verification and remediation process:

```
[LUPIN] Post-change smoke test verification & remediation (${2:-FULL}) - STARTED at [TIMESTAMP]
[LUPIN] Pre-flight validation and baseline detection
[LUPIN] Execute post-change Lupin smoke test suite
[LUPIN] Execute post-change CoSA smoke tests (if baseline had full scope)
[LUPIN] Generate comparison analysis against baseline
[LUPIN] Identify and prioritize regressions (Critical → High → Medium)
[LUPIN] Phase 1: Fix Critical regressions (immediate)
[LUPIN] Phase 2: Fix High priority issues (same session)
[LUPIN] Phase 3: Fix Medium priority issues (scope permitting)
[LUPIN] Validate all fixes with targeted re-testing
[LUPIN] Generate final remediation report with metrics
[LUPIN] Send completion notification
[LUPIN] Document remediation session in history
```

### 3. Notification: Start of Remediation

Send notification that post-change verification is starting:

```bash
SCOPE_TEXT="${2:-FULL}"
notify-claude "[LUPIN] 🔍 Post-change smoke test verification STARTED (${SCOPE_TEXT}) - Comparing against baseline and preparing remediation" --type=progress --priority=medium
```

### 4. Execute Post-Change Lupin Smoke Tests

Run comprehensive Lupin smoke tests with full logging:

```bash
LOG_FILE="src/tests/logs/postchange_lupin_smoke_${TIMESTAMP}.log"
echo "Starting post-change Lupin smoke test verification at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full test suite
./src/tests/run-lupin-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "Post-change Lupin smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Execute Post-Change CoSA Framework Smoke Tests (Conditional)

**Determine scope from baseline report**:
First, check if baseline included CoSA tests by examining the baseline report.

```bash
# Check if baseline included CoSA tests
if grep -q "CoSA Framework Results: SKIPPED" "$BASELINE_REPORT" 2>/dev/null; then
    echo "CoSA framework smoke tests SKIPPED - baseline was Lupin-only"
    COSA_SCOPE="lupin"
else
    echo "Running CoSA tests to match baseline scope"
    COSA_SCOPE="full"

    LOG_FILE="src/tests/logs/postchange_cosa_smoke_${TIMESTAMP}.log"
    echo "Starting post-change CoSA smoke test verification at $(date)" | tee "${LOG_FILE}"
    echo "===========================================" | tee -a "${LOG_FILE}"

    # Set up CoSA environment
    export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src:$PYTHONPATH"

    # Execute full CoSA test suite
    ./src/cosa/tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

    echo "===========================================" | tee -a "${LOG_FILE}"
    echo "Post-change CoSA smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
    echo "Log file: ${LOG_FILE}"
fi
```

### 6. Baseline Comparison Analysis

Compare current results against the baseline report. Create an analysis document:

**Analysis File**: `src/rnd/$(date +%Y.%m.%d)-postchange-comparison-analysis.md`

```markdown
# Post-Change Comparison Analysis

**Date**: $(date +%Y.%m.%d)
**Timestamp**: ${TIMESTAMP}
**Purpose**: Post-change verification and regression identification
**Baseline Report**: $BASELINE_REPORT
**Post-Change Lupin Log**: src/tests/logs/postchange_lupin_smoke_${TIMESTAMP}.log
**Post-Change CoSA Log**: [Based on COSA_SCOPE determination]
**Remediation Scope**: ${2:-FULL}

## Executive Summary

**Changes Made**: [BRIEF DESCRIPTION OF CHANGES]
**Overall Health**: [EXCELLENT/GOOD/FAIR/POOR] (Baseline: [BASELINE STATUS])
**Total Tests Executed**: [NUMBER] (Baseline: [NUMBER])
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests) (Baseline: [XX.X%])
**Regressions Introduced**: [NUMBER]
**New Failures**: [NUMBER]
**Fixed Issues**: [NUMBER]

## Regression Analysis

### Critical Regressions (Immediate Fix Required)
[List any tests that went from PASS → FAIL and affect core functionality]

### Performance Regressions
[List any significant performance degradations]

### New Test Failures
[List any new test categories or tests that now fail]

## Improvement Analysis

### Fixed Issues
[List any tests that went from FAIL → PASS]

### Performance Improvements
[List any significant performance improvements]

### New Functionality
[List any new tests that now pass due to added features]

## Remediation Plan

### Phase 1: Critical Regressions (Fix Immediately)
[Ordered list of critical issues with specific remediation steps]

### Phase 2: High Priority Issues (Fix Today)
[Ordered list of high priority issues with specific remediation steps]

### Phase 3: Medium Priority Issues (Fix This Week)
[Ordered list of medium priority issues with specific remediation steps]
```

### 7. Systematic Remediation Process

**Based on scope parameter, execute remediation phases:**

```bash
SCOPE="${2:-FULL}"
case "$SCOPE" in
    "ANALYSIS_ONLY")
        echo "✓ Analysis complete - no remediation requested (ANALYSIS_ONLY scope)"
        ;;
    "CRITICAL_ONLY")
        echo "🔧 Starting Critical-only remediation..."
        # Implement only critical fixes
        ;;
    "SELECTIVE")
        echo "🔧 Starting selective remediation (user-guided)..."
        # Allow user to select which issues to fix
        ;;
    "FULL"|*)
        echo "🔧 Starting full remediation process..."
        # Fix all identified issues in priority order
        ;;
esac
```

**For each identified regression, follow this process:**

1. **Issue Identification**
   - Specific test(s) that regressed
   - Error messages and failure modes
   - Impact assessment (Critical/High/Medium/Low)

2. **Root Cause Analysis**
   - Relate failure to specific changes made
   - Identify likely root cause
   - Check for related failures

3. **Fix Implementation**
   - Make targeted fix for the specific issue
   - Ensure fix doesn't introduce new problems
   - Document the change made

4. **Verification**
   - Re-run the specific failing test(s)
   - Run related tests to ensure no new issues
   - Update todo list with fix status

5. **Time Boxing**
   - Critical issues: 10 minutes maximum per fix
   - High priority: 5 minutes maximum per fix
   - Medium priority: 2 minutes maximum per fix

### 8. Targeted Re-Testing After Fixes

After implementing fixes, run focused tests to validate:

```bash
# Test specific categories that had fixes
echo "Running validation tests for fixed categories..."
./src/tests/run-lupin-smoke-tests.sh 2>&1 | tee "src/tests/logs/remediation_validation_${TIMESTAMP}.log"

# Update comparison analysis with final results
echo "Updating final comparison analysis..."
```

### 9. Final Results Documentation

Create final comparison report showing before/after remediation:

**Final Report**: `src/rnd/$(date +%Y.%m.%d)-postchange-final-report.md`

```markdown
# Post-Change Final Results Report

**Date**: $(date +%Y.%m.%d)
**Remediation Scope**: ${2:-FULL}
**Session Duration**: [Calculate from start timestamp]

## Summary of Changes Made
[Description of the original changes]

## Summary of Issues Found and Fixed
- **Total Regressions Identified**: [NUMBER]
- **Critical Issues Fixed**: [NUMBER]
- **High Priority Issues Fixed**: [NUMBER]
- **Remaining Issues**: [NUMBER] (with justification)

## Final Health Comparison

| Metric | Baseline | Post-Change | After Remediation | Net Change |
|--------|----------|-------------|-------------------|------------|
| Overall Pass Rate | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Lupin Pass Rate | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| CoSA Pass Rate | [XX.X% or SKIPPED] | [XX.X% or SKIPPED] | [XX.X% or SKIPPED] | [±X.X% or N/A] |
| Critical Failures | [#] | [#] | [#] | [±#] |

## System Status

**Current Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Comparison to Baseline**: [IMPROVED/STABLE/SLIGHTLY DEGRADED]
**Ready for Production**: [YES/NO with reasoning]
```

### 10. Update History Document

Add the verification and remediation session to your history:

```markdown
#### $(date +%Y.%m.%d) - Post-Change Smoke Test Verification & Remediation

**Summary**: Verified system health after [DESCRIBE CHANGES] and remediated [NUMBER] regressions.

**Changes Validated**:
- [Brief description of original changes made]

**Results Comparison**:
- **Baseline**: [XX.X%] overall pass rate
- **Post-Change**: [XX.X%] overall pass rate
- **After Remediation**: [XX.X%] overall pass rate
- **Net Change**: [±X.X%]

**Issues Found & Fixed**:
- **Critical**: [NUMBER] identified, [NUMBER] fixed
- **High Priority**: [NUMBER] identified, [NUMBER] fixed
- **Total Changes Made**: [NUMBER] fixes implemented

**Final Status**: [EXCELLENT/GOOD/FAIR/POOR] - System [ready/not ready] for production use

**Documentation**: [Links to analysis and final report files]
```

### 11. Notification: Verification Complete

Send notification with final results:

```bash
SCOPE_TEXT="${2:-FULL}"
notify-claude "[LUPIN] ✅ Post-change verification COMPLETE (${SCOPE_TEXT}) - [XX.X%] final pass rate, [NUMBER] issues fixed, system [STATUS]" --type=progress --priority=medium
```

### 12. Final Todo List Update

Mark all verification and remediation tasks as completed and provide final summary.

## Remediation Guidelines

### ✅ DO These Things:
- **Systematic Approach**: Fix issues in priority order (Critical → High → Medium)
- **Targeted Fixes**: Make specific fixes for identified issues
- **Validation Testing**: Re-test after each fix to ensure it works
- **Documentation**: Document every change made and why
- **Root Cause Focus**: Fix underlying causes, not just symptoms
- **Regression Testing**: Ensure fixes don't break other functionality

### ⚠️ Remediation Priorities:
1. **Critical**: Tests that went from PASS → FAIL affecting core functionality
2. **High**: Significant performance regressions or major feature failures
3. **Medium**: Edge cases, minor features, or cosmetic issues
4. **Low**: Pre-existing issues not introduced by changes

### 🚫 Don't Fix These:
- **Pre-existing Issues**: Problems that existed in the baseline
- **Environmental Issues**: Problems caused by external dependencies
- **Out-of-Scope Changes**: Issues unrelated to the changes made
- **Low Impact Issues**: Minor problems that don't affect functionality

## Emergency Escalation

If critical issues cannot be resolved:

1. **Send urgent notification**:
```bash
notify-claude "[LUPIN] 🚨 URGENT: Critical post-change issues require immediate attention - [BRIEF DESCRIPTION]" --type=alert --priority=urgent
```

2. **Document the problem clearly**
3. **Suggest rollback procedures if needed**
4. **Wait for user guidance before proceeding**

## Success Criteria

✅ **Complete Test Execution**: All test categories re-executed after changes
✅ **Baseline Comparison**: Detailed comparison against pre-change baseline
✅ **Regression Identification**: All introduced issues identified and categorized
✅ **Critical Fixes**: All critical regressions successfully remediated
✅ **Validation Testing**: Fixes verified through targeted re-testing
✅ **Documentation**: Complete analysis and final report generated
✅ **History Update**: Session documented in history.md
✅ **Notification Sent**: Progress notifications sent with final results

**System verified and stabilized after changes. Ready for continued development.**