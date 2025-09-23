# Post-Change Smoke Test Prompt (Verification & Remediation)

**PURPOSE**: Verify system health after major changes and remediate any introduced regressions
**MODE**: Comparison analysis with targeted remediation
**PRINCIPLE**: Compare, Analyze, Fix, Validate

## Test Scope Configuration

**IMPORTANT**: Before starting, specify which test scope to use by setting TEST_SCOPE:

### Option 1: FULL SUITE (Lupin + COSA) - DEFAULT
- Set `TEST_SCOPE="full"` to run both Lupin and COSA smoke tests
- Comprehensive verification across entire project ecosystem
- Use when baseline was established with "full" scope

### Option 2: LUPIN ONLY
- Set `TEST_SCOPE="lupin"` to run only Lupin smoke tests (skip COSA framework tests)
- Faster execution when changes are Lupin-specific
- Use when baseline was established with "lupin" scope

**Your Choice**: TEST_SCOPE="full"  *(Change this to "lupin" if desired)*

**CRITICAL**: The TEST_SCOPE must match the scope used for your baseline establishment!

---

## Your Task

I have completed significant system changes and need you to verify the system health compared to the pre-change baseline, identify any regressions introduced, and systematically remediate any breaking changes.

**Baseline Report Required**: You should have access to a baseline report from before the changes. If not, ask me to provide the baseline report file path before proceeding.

### 1. Initialize Todo List

Create a todo list to track the post-change verification and remediation process:

**If TEST_SCOPE="full":**
```
[LUPIN] Post-change smoke test verification (FULL) - STARTED at [TIMESTAMP]
[LUPIN] Create logs directory and generate timestamp
[LUPIN] Check FastAPI server status after changes
[LUPIN] Execute full post-change Lupin smoke test suite
[LUPIN] Execute full post-change CoSA smoke test suite
[LUPIN] Compare results against baseline report (Lupin + COSA)
[LUPIN] Identify introduced regressions and breaking changes
[LUPIN] Prioritize remediation efforts by impact
[LUPIN] Systematically fix identified issues
[LUPIN] Validate fixes with targeted re-testing
[LUPIN] Generate final comparison report
[LUPIN] Send completion notification with summary
[LUPIN] Document remediation in session history
```

**If TEST_SCOPE="lupin":**
```
[LUPIN] Post-change smoke test verification (LUPIN-ONLY) - STARTED at [TIMESTAMP]
[LUPIN] Create logs directory and generate timestamp
[LUPIN] Check FastAPI server status after changes
[LUPIN] Execute full post-change Lupin smoke test suite
[LUPIN] Compare results against baseline report (Lupin-only)
[LUPIN] Identify introduced regressions and breaking changes
[LUPIN] Prioritize remediation efforts by impact
[LUPIN] Systematically fix identified issues
[LUPIN] Validate fixes with targeted re-testing
[LUPIN] Generate final comparison report
[LUPIN] Send completion notification with summary
[LUPIN] Document remediation in session history
```

### 2. Notification: Start of Verification

Send notification that post-change verification is starting:

**If TEST_SCOPE="full":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src/scripts/notify.sh "[LUPIN] 🔍 Post-change smoke test verification STARTED (FULL SUITE) - Comparing Lupin + COSA against baseline and preparing remediation" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

**If TEST_SCOPE="lupin":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src/scripts/notify.sh "[LUPIN] 🔍 Post-change smoke test verification STARTED (LUPIN-ONLY) - Comparing Lupin against baseline and preparing remediation" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

### 3. Setup Post-Change Testing Environment

Execute the following commands to prepare for testing:

```bash
cd /mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box

# Create logs directory structure
mkdir -p src/tests/logs

# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "Post-change verification timestamp: ${TIMESTAMP}"

# Check if FastAPI server is running after changes
echo "=== Post-Change FastAPI Server Health Check ==="
curl -s http://localhost:7999/health || echo "❌ FastAPI server unreachable on port 7999"
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

**Check TEST_SCOPE**:
- If TEST_SCOPE="lupin", **SKIP this section** and go directly to step 6.
- If TEST_SCOPE="full", execute the following:

Run comprehensive CoSA framework tests with full logging:

```bash
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
```

**If skipped (TEST_SCOPE="lupin")**: Add this note to your documentation:
```
CoSA framework smoke tests SKIPPED - TEST_SCOPE set to "lupin" only
```

### 6. Baseline Comparison Analysis

Compare current results against the baseline report. Create an analysis document:

**Analysis File**: `src/rnd/YYYY.MM.DD-postchange-comparison-analysis.md`

```markdown
# Post-Change Comparison Analysis

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Post-change verification and regression identification
**Baseline Report**: [PATH TO BASELINE REPORT]
**Post-Change Lupin Log**: src/tests/logs/postchange_lupin_smoke_[TIMESTAMP].log
**Post-Change CoSA Log**: src/tests/logs/postchange_cosa_smoke_[TIMESTAMP].log

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

## Comparison Tables

### Lupin Results Comparison
| Category | Baseline Pass Rate | Current Pass Rate | Change | Status |
|----------|-------------------|------------------|--------|---------|
| WebSocket Tests | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Basic FastAPI Tests | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Notification System | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Audio/TTS System | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Queue Workflow | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |

### CoSA Results Comparison
| Category | Baseline Pass Rate | Current Pass Rate | Change | Status |
|----------|-------------------|------------------|--------|---------|
| Core | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Agents | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| REST | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Memory | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Training | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |

## Remediation Plan

### Phase 1: Critical Regressions (Fix Immediately)
[Ordered list of critical issues with specific remediation steps]

### Phase 2: High Priority Issues (Fix Today)
[Ordered list of high priority issues with specific remediation steps]

### Phase 3: Medium Priority Issues (Fix This Week)
[Ordered list of medium priority issues with specific remediation steps]
```

### 7. Systematic Remediation Process

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

5. **Documentation**
   - Document what was broken
   - Document how it was fixed
   - Update comparison analysis

### 8. Targeted Re-Testing After Fixes

After implementing fixes, run focused tests to validate:

```bash
# Test specific categories that had fixes
./src/tests/run-lupin-smoke-tests.sh --category [CATEGORY] 2>&1 | tee "src/tests/logs/remediation_validation_${TIMESTAMP}.log"

# Run quick validation of all categories
./src/tests/run-lupin-smoke-tests.sh --quick 2>&1 | tee "src/tests/logs/final_validation_${TIMESTAMP}.log"
```

### 9. Final Results Documentation

Create final comparison report showing before/after remediation:

**Final Report**: `src/rnd/YYYY.MM.DD-postchange-final-report.md`

```markdown
# Post-Change Final Results Report

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

## Remediation Summary

### Issues Fixed
[List of all issues that were successfully remediated]

### Changes Made
[List of all code/configuration changes made during remediation]

### Remaining Issues
[List any issues not fixed with justification (e.g., pre-existing, out of scope, etc.)]

## System Status

**Current Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Comparison to Baseline**: [IMPROVED/STABLE/SLIGHTLY DEGRADED]
**Ready for Production**: [YES/NO with reasoning]
```

### 10. Update History Document

Add the verification and remediation session to your history:

```markdown
#### [DATE] - Post-Change Smoke Test Verification & Remediation

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

**If TEST_SCOPE="full":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src/scripts/notify.sh "[LUPIN] ✅ Post-change verification COMPLETE (FULL SUITE) - [XX.X%] final pass rate, [NUMBER] issues fixed, Lupin + COSA system [STATUS]" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
```

**If TEST_SCOPE="lupin":**
```bash
/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src/scripts/notify.sh "[LUPIN] ✅ Post-change verification COMPLETE (LUPIN-ONLY) - [XX.X%] final pass rate, [NUMBER] issues fixed, Lupin system [STATUS]" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
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

## Emergency Escalation

If critical issues cannot be resolved:

1. **Send urgent notification**:
```bash
/mnt/DATA01/include/www.deepily.ai/projects/genie-in-the-box/src/scripts/notify.sh "[LUPIN] 🚨 URGENT: Critical post-change issues require immediate attention - [BRIEF DESCRIPTION]" --type=alert --priority=urgent --target-user=ricardo.felipe.ruiz@gmail.com
```

2. **Document the problem clearly**
3. **Suggest rollback procedures if needed**
4. **Wait for user guidance before proceeding**