# COSA Framework Post-Change Smoke Test Prompt (Verification & Remediation)

**PURPOSE**: Verify COSA framework health after major changes and remediate any introduced regressions
**MODE**: Comparison analysis with targeted remediation
**PRINCIPLE**: Compare, Analyze, Fix, Validate
**SCOPE**: COSA Framework Only

## Your Task

I have completed significant changes to the COSA framework and need you to verify the framework health compared to the pre-change baseline, identify any regressions introduced, and systematically remediate any breaking changes.

**Baseline Report Required**: You should have access to a COSA baseline report from before the changes. If not, ask me to provide the baseline report file path before proceeding.

### 1. Initialize Todo List

Create a todo list to track the post-change verification and remediation process:

```
[COSA] Post-change COSA framework smoke test verification - STARTED at [TIMESTAMP]
[COSA] Create logs directory and generate timestamp
[COSA] Set up COSA environment after changes
[COSA] Execute full post-change COSA framework smoke tests
[COSA] Compare results against COSA baseline report
[COSA] Identify introduced regressions and breaking changes
[COSA] Prioritize remediation efforts by impact
[COSA] Systematically fix identified issues
[COSA] Validate fixes with targeted re-testing
[COSA] Generate final comparison report
[COSA] Send completion notification (if available)
[COSA] Document remediation in session history
```

### 2. Notification: Start of Verification (Optional)

**If notification system is available**, send notification that post-change verification is starting:
```bash
# Check if notification script exists
if [ -f "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh" ]; then
    /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[COSA] 🔍 COSA framework post-change verification STARTED - Comparing against baseline and preparing remediation" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ Starting COSA framework post-change verification - notification system not available"
fi
```

### 3. Setup Post-Change COSA Testing Environment

Execute the following commands to prepare for testing:

```bash
# Navigate to COSA root directory
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa

# Create results directory structure
mkdir -p tests/results/logs
mkdir -p tests/results/analysis
mkdir -p tests/results/reports

# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "COSA post-change verification timestamp: ${TIMESTAMP}"

# Set up COSA framework environment
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
echo "✓ COSA PYTHONPATH configured"

# Verify COSA framework can be imported after changes
python -c "import cosa; print('✓ COSA framework import successful after changes')" || echo "❌ COSA framework import failed - critical issue"
```

### 4. Execute Post-Change COSA Framework Smoke Tests

Run comprehensive COSA framework tests with full logging:

```bash
LOG_FILE="tests/results/logs/postchange_cosa_smoke_${TIMESTAMP}.log"
echo "Starting post-change COSA framework smoke test verification at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full COSA test suite
./tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "Post-change COSA framework smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Baseline Comparison Analysis

Compare current results against the baseline report. Create an analysis document:

**Analysis File**: `tests/results/analysis/YYYY.MM.DD-cosa-postchange-comparison-analysis.md`

```markdown
# COSA Framework Post-Change Comparison Analysis

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Post-change COSA framework verification and regression identification
**Scope**: COSA Framework Only
**Baseline Report**: [PATH TO COSA BASELINE REPORT]
**Post-Change Log**: tests/results/logs/postchange_cosa_smoke_[TIMESTAMP].log

## Executive Summary

**Changes Made**: [BRIEF DESCRIPTION OF COSA CHANGES]
**Framework Health**: [EXCELLENT/GOOD/FAIR/POOR] (Baseline: [BASELINE STATUS])
**Total Tests Executed**: [NUMBER] (Baseline: [NUMBER])
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests) (Baseline: [XX.X%])
**Regressions Introduced**: [NUMBER]
**New Failures**: [NUMBER]
**Fixed Issues**: [NUMBER]

## COSA Framework Regression Analysis

### Critical Regressions (Immediate Fix Required)
[List any tests that went from PASS → FAIL and affect core framework functionality]

### Performance Regressions
[List any significant performance degradations in COSA modules]

### New Test Failures
[List any new COSA test categories or tests that now fail]

## COSA Framework Improvement Analysis

### Fixed Issues
[List any COSA tests that went from FAIL → PASS]

### Performance Improvements
[List any significant performance improvements in COSA modules]

### New Functionality
[List any new COSA tests that now pass due to added features]

## COSA Framework Results Comparison
| Category | Baseline Pass Rate | Current Pass Rate | Change | Status |
|----------|-------------------|------------------|--------|---------|
| Core | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Agents | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| REST | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Memory | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| Training | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |

## Remediation Plan

### Phase 1: Critical COSA Regressions (Fix Immediately)
[Ordered list of critical COSA framework issues with specific remediation steps]

### Phase 2: High Priority COSA Issues (Fix Today)
[Ordered list of high priority COSA framework issues with specific remediation steps]

### Phase 3: Medium Priority COSA Issues (Fix This Week)
[Ordered list of medium priority COSA framework issues with specific remediation steps]
```

### 6. Systematic Remediation Process

**For each identified COSA framework regression, follow this process:**

1. **Issue Identification**
   - Specific COSA test(s) that regressed
   - Error messages and failure modes
   - Impact assessment on COSA framework (Critical/High/Medium/Low)

2. **Root Cause Analysis**
   - Relate failure to specific COSA changes made
   - Identify likely root cause in COSA modules
   - Check for related COSA failures

3. **Fix Implementation**
   - Make targeted fix for the specific COSA issue
   - Ensure fix doesn't introduce new COSA problems
   - Document the COSA change made

4. **Verification**
   - Re-run the specific failing COSA test(s)
   - Run related COSA tests to ensure no new issues
   - Update todo list with fix status

5. **Documentation**
   - Document what was broken in COSA
   - Document how it was fixed
   - Update comparison analysis

### 7. Targeted Re-Testing After Fixes

After implementing fixes, run focused COSA tests to validate:

```bash
# Test specific COSA categories that had fixes
./tests/smoke/scripts/run-cosa-smoke-tests.sh --category [CATEGORY] 2>&1 | tee "tests/results/logs/cosa_remediation_validation_${TIMESTAMP}.log"

# Run quick validation of all COSA categories
./tests/smoke/scripts/run-cosa-smoke-tests.sh --quick 2>&1 | tee "tests/results/logs/cosa_final_validation_${TIMESTAMP}.log"
```

### 8. Final Results Documentation

Create final comparison report showing before/after remediation:

**Final Report**: `tests/results/reports/YYYY.MM.DD-cosa-postchange-final-report.md`

```markdown
# COSA Framework Post-Change Final Results Report

## Summary of COSA Changes Made
[Description of the original COSA framework changes]

## Summary of COSA Issues Found and Fixed
- **Total COSA Regressions Identified**: [NUMBER]
- **Critical COSA Issues Fixed**: [NUMBER]
- **High Priority COSA Issues Fixed**: [NUMBER]
- **Remaining COSA Issues**: [NUMBER] (with justification)

## Final COSA Framework Health Comparison

| Metric | Baseline | Post-Change | After Remediation | Net Change |
|--------|----------|-------------|-------------------|------------|
| Overall Pass Rate | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Core Module | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Agents Module | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| REST Module | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Memory Module | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Training Module | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| Critical Failures | [#] | [#] | [#] | [±#] |

## COSA Framework Remediation Summary

### COSA Issues Fixed
[List of all COSA framework issues that were successfully remediated]

### COSA Changes Made
[List of all COSA code/configuration changes made during remediation]

### Remaining COSA Issues
[List any COSA framework issues not fixed with justification]

## COSA Framework Status

**Current Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Comparison to Baseline**: [IMPROVED/STABLE/SLIGHTLY DEGRADED]
**Ready for Production**: [YES/NO with reasoning]
```

### 9. Update History Document

Add the verification and remediation session to your history:

```markdown
#### [DATE] - Post-Change COSA Framework Verification & Remediation

**Summary**: Verified COSA framework health after [DESCRIBE CHANGES] and remediated [NUMBER] regressions.

**COSA Changes Validated**:
- [Brief description of original COSA framework changes made]

**Results Comparison**:
- **Baseline**: [XX.X%] overall pass rate
- **Post-Change**: [XX.X%] overall pass rate
- **After Remediation**: [XX.X%] overall pass rate
- **Net Change**: [±X.X%]

**COSA Issues Found & Fixed**:
- **Critical**: [NUMBER] identified, [NUMBER] fixed
- **High Priority**: [NUMBER] identified, [NUMBER] fixed
- **Total Changes Made**: [NUMBER] fixes implemented

**Final Status**: [EXCELLENT/GOOD/FAIR/POOR] - COSA framework [ready/not ready] for production use

**Documentation**: [Links to analysis and final report files]
```

### 10. Notification: Verification Complete (Optional)

**If notification system is available**, send notification with final results:
```bash
# Check if notification script exists
if [ -f "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh" ]; then
    /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[COSA] ✅ COSA framework post-change verification COMPLETE - [XX.X%] final pass rate, [NUMBER] issues fixed, framework [STATUS]" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ COSA framework verification complete - [XX.X%] final pass rate, [NUMBER] issues fixed"
fi
```

### 11. Final Todo List Update

Mark all verification and remediation tasks as completed and provide final summary.

## Remediation Guidelines

### ✅ DO These Things:
- **Systematic Approach**: Fix COSA issues in priority order (Critical → High → Medium)
- **Targeted Fixes**: Make specific fixes for identified COSA framework issues
- **Validation Testing**: Re-test after each COSA fix to ensure it works
- **Documentation**: Document every COSA change made and why
- **Root Cause Focus**: Fix underlying COSA causes, not just symptoms
- **Regression Testing**: Ensure COSA fixes don't break other framework functionality

### ⚠️ Remediation Priorities:
1. **Critical**: COSA tests that went from PASS → FAIL affecting core framework functionality
2. **High**: Significant performance regressions or major COSA feature failures
3. **Medium**: COSA edge cases, minor features, or cosmetic issues
4. **Low**: Pre-existing COSA issues not introduced by changes

### 🚫 Don't Fix These:
- **Pre-existing COSA Issues**: Problems that existed in the baseline
- **Environmental Issues**: Problems caused by external dependencies
- **Out-of-Scope Changes**: Issues unrelated to the COSA changes made
- **Low Impact Issues**: Minor COSA problems that don't affect functionality

## Success Criteria

✅ **Complete COSA Test Execution**: All COSA framework test categories re-executed after changes
✅ **Baseline Comparison**: Detailed comparison against pre-change COSA baseline
✅ **Regression Identification**: All introduced COSA issues identified and categorized
✅ **Critical Fixes**: All critical COSA regressions successfully remediated
✅ **Validation Testing**: COSA fixes verified through targeted re-testing
✅ **Documentation**: Complete analysis and final COSA report generated
✅ **History Update**: Session documented in history.md
✅ **Optional Notification**: Progress notifications sent if system available

**COSA framework verified and stabilized after changes. Ready for continued development.**

## Emergency Escalation

If critical COSA framework issues cannot be resolved:

1. **Send urgent notification (if available)**:
```bash
if [ -f "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh" ]; then
    /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/scripts/notify.sh "[COSA] 🚨 URGENT: Critical COSA framework issues require immediate attention - [BRIEF DESCRIPTION]" --type=alert --priority=urgent --target-user=ricardo.felipe.ruiz@gmail.com
fi
```

2. **Document the COSA problem clearly**
3. **Suggest COSA rollback procedures if needed**
4. **Wait for user guidance before proceeding**

## Notes for COSA-Only Context

### Working Directory
- All commands assume you're working from the COSA root directory
- Log files stored in `tests/results/logs/` within COSA
- Analysis stored in `tests/results/analysis/` within COSA
- Reports stored in `tests/results/reports/` within COSA

### Dependencies
- **Required**: COSA framework properly accessible via PYTHONPATH
- **Optional**: Parent Lupin notification system (if available)
- **Required**: COSA smoke test infrastructure operational
- **Required**: COSA baseline report from pre-change testing

### Scope Limitations
- **COSA Framework Only**: No Lupin-specific remediation
- **Framework Focus**: Core, Agents, REST, Memory, Training modules
- **Standalone Operation**: Can be run independently of Lupin project