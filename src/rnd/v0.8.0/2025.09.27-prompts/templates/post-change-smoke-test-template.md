# {{PROJECT_NAME}} Post-Change Smoke Test Prompt (Verification & Remediation)

**PURPOSE**: Verify {{PROJECT_NAME}} health after major changes and remediate any introduced regressions
**MODE**: Comparison analysis with targeted remediation
**PRINCIPLE**: Compare, Analyze, Fix, Validate

## Your Task

I have completed significant changes to {{PROJECT_NAME}} and need you to verify the system health compared to the pre-change baseline, identify any regressions introduced, and systematically remediate any breaking changes.

**Baseline Report Required**: You should have access to a {{PROJECT_NAME}} baseline report from before the changes. If not, ask me to provide the baseline report file path before proceeding.

### 1. Initialize Todo List

Create a todo list to track the post-change verification and remediation process:

```
{{PROJECT_PREFIX}} Post-change {{PROJECT_NAME}} verification - STARTED at [TIMESTAMP]
{{PROJECT_PREFIX}} Create logs directory and generate timestamp
{{PROJECT_PREFIX}} Check {{PROJECT_NAME}} system status after changes
{{PROJECT_PREFIX}} Execute full post-change {{PROJECT_NAME}} test suite
{{PROJECT_PREFIX}} Compare results against {{PROJECT_NAME}} baseline report
{{PROJECT_PREFIX}} Identify introduced regressions and breaking changes
{{PROJECT_PREFIX}} Prioritize remediation efforts by impact
{{PROJECT_PREFIX}} Systematically fix identified issues
{{PROJECT_PREFIX}} Validate fixes with targeted re-testing
{{PROJECT_PREFIX}} Generate final comparison report
{{PROJECT_PREFIX}} Send completion notification with summary
{{PROJECT_PREFIX}} Document remediation in session history
```

### 2. Notification: Start of Verification

**If notification system is available**, send notification that post-change verification is starting:
```bash
# Check if notification script exists
if [ -f "{{NOTIFICATION_SCRIPT}}" ]; then
    {{NOTIFICATION_SCRIPT}} "{{PROJECT_PREFIX}} 🔍 {{PROJECT_NAME}} post-change verification STARTED - Comparing against baseline and preparing remediation" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ Starting {{PROJECT_NAME}} post-change verification - notification system not available"
fi
```

### 3. Setup Post-Change Testing Environment

Execute the following commands to prepare for testing:

```bash
# Navigate to project root
cd {{PROJECT_ROOT}}

# Create logs directory structure
mkdir -p tests/logs

# Generate timestamp for unique log files
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "{{PROJECT_NAME}} post-change verification timestamp: ${TIMESTAMP}"

# Check system dependencies and health after changes
echo "=== Post-Change {{PROJECT_NAME}} System Health Check ==="
# Add project-specific health checks here
# Example: curl -s {{SERVER_HEALTH_URL}} || echo "❌ Server unreachable after changes"
# Example: python -c "import {{PROJECT_NAME}}; print('✓ Import successful after changes')"
```

### 4. Execute Post-Change {{PROJECT_NAME}} Test Suite

Run comprehensive {{PROJECT_NAME}} tests with full logging:

```bash
LOG_FILE="tests/logs/postchange_{{PROJECT_NAME}}_smoke_${TIMESTAMP}.log"
echo "Starting post-change {{PROJECT_NAME}} smoke test verification at $(date)" | tee "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute test suite
{{TEST_SCRIPT}} 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "Post-change {{PROJECT_NAME}} smoke tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"
```

### 5. Baseline Comparison Analysis

Compare current results against the baseline report. Create an analysis document:

**Analysis File**: `rnd/YYYY.MM.DD-{{PROJECT_NAME}}-postchange-comparison-analysis.md`

```markdown
# {{PROJECT_NAME}} Post-Change Comparison Analysis

**Date**: [DATE]
**Timestamp**: [TIMESTAMP]
**Purpose**: Post-change {{PROJECT_NAME}} verification and regression identification
**Baseline Report**: [PATH TO {{PROJECT_NAME}} BASELINE REPORT]
**Post-Change Log**: tests/logs/postchange_{{PROJECT_NAME}}_smoke_[TIMESTAMP].log

## Executive Summary

**Changes Made**: [BRIEF DESCRIPTION OF {{PROJECT_NAME}} CHANGES]
**System Health**: [EXCELLENT/GOOD/FAIR/POOR] (Baseline: [BASELINE STATUS])
**Total Tests Executed**: [NUMBER] (Baseline: [NUMBER])
**Overall Pass Rate**: [XX.X%] ([PASSED]/[TOTAL] tests) (Baseline: [XX.X%])
**Regressions Introduced**: [NUMBER]
**New Failures**: [NUMBER]
**Fixed Issues**: [NUMBER]

## {{PROJECT_NAME}} Regression Analysis

### Critical Regressions (Immediate Fix Required)
[List any tests that went from PASS → FAIL and affect core {{PROJECT_NAME}} functionality]

### Performance Regressions
[List any significant performance degradations in {{PROJECT_NAME}}]

### New Test Failures
[List any new {{PROJECT_NAME}} test categories or tests that now fail]

## {{PROJECT_NAME}} Improvement Analysis

### Fixed Issues
[List any {{PROJECT_NAME}} tests that went from FAIL → PASS]

### Performance Improvements
[List any significant performance improvements in {{PROJECT_NAME}}]

### New Functionality
[List any new {{PROJECT_NAME}} tests that now pass due to added features]

## {{PROJECT_NAME}} Results Comparison
| Category | Baseline Pass Rate | Current Pass Rate | Change | Status |
|----------|-------------------|------------------|--------|---------|
| [CATEGORY_1] | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| [CATEGORY_2] | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| [CATEGORY_3] | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| [CATEGORY_4] | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |
| [CATEGORY_5] | [XX.X%] | [XX.X%] | [±X.X%] | [IMPROVED/DEGRADED/STABLE] |

## Remediation Plan

### Phase 1: Critical {{PROJECT_NAME}} Regressions (Fix Immediately)
[Ordered list of critical {{PROJECT_NAME}} issues with specific remediation steps]

### Phase 2: High Priority {{PROJECT_NAME}} Issues (Fix Today)
[Ordered list of high priority {{PROJECT_NAME}} issues with specific remediation steps]

### Phase 3: Medium Priority {{PROJECT_NAME}} Issues (Fix This Week)
[Ordered list of medium priority {{PROJECT_NAME}} issues with specific remediation steps]
```

### 6. Systematic Remediation Process

**For each identified {{PROJECT_NAME}} regression, follow this process:**

1. **Issue Identification**
   - Specific {{PROJECT_NAME}} test(s) that regressed
   - Error messages and failure modes
   - Impact assessment on {{PROJECT_NAME}} (Critical/High/Medium/Low)

2. **Root Cause Analysis**
   - Relate failure to specific {{PROJECT_NAME}} changes made
   - Identify likely root cause
   - Check for related {{PROJECT_NAME}} failures

3. **Fix Implementation**
   - Make targeted fix for the specific {{PROJECT_NAME}} issue
   - Ensure fix doesn't introduce new {{PROJECT_NAME}} problems
   - Document the {{PROJECT_NAME}} change made

4. **Verification**
   - Re-run the specific failing {{PROJECT_NAME}} test(s)
   - Run related {{PROJECT_NAME}} tests to ensure no new issues
   - Update todo list with fix status

5. **Documentation**
   - Document what was broken in {{PROJECT_NAME}}
   - Document how it was fixed
   - Update comparison analysis

### 7. Targeted Re-Testing After Fixes

After implementing fixes, run focused {{PROJECT_NAME}} tests to validate:

```bash
# Test specific {{PROJECT_NAME}} categories that had fixes
{{TEST_SCRIPT}} --category [CATEGORY] 2>&1 | tee "tests/logs/{{PROJECT_NAME}}_remediation_validation_${TIMESTAMP}.log"

# Run quick validation of all {{PROJECT_NAME}} categories
{{TEST_SCRIPT}} --quick 2>&1 | tee "tests/logs/{{PROJECT_NAME}}_final_validation_${TIMESTAMP}.log"
```

### 8. Final Results Documentation

Create final comparison report showing before/after remediation:

**Final Report**: `rnd/YYYY.MM.DD-{{PROJECT_NAME}}-postchange-final-report.md`

```markdown
# {{PROJECT_NAME}} Post-Change Final Results Report

## Summary of {{PROJECT_NAME}} Changes Made
[Description of the original {{PROJECT_NAME}} changes]

## Summary of {{PROJECT_NAME}} Issues Found and Fixed
- **Total {{PROJECT_NAME}} Regressions Identified**: [NUMBER]
- **Critical {{PROJECT_NAME}} Issues Fixed**: [NUMBER]
- **High Priority {{PROJECT_NAME}} Issues Fixed**: [NUMBER]
- **Remaining {{PROJECT_NAME}} Issues**: [NUMBER] (with justification)

## Final {{PROJECT_NAME}} Health Comparison

| Metric | Baseline | Post-Change | After Remediation | Net Change |
|--------|----------|-------------|-------------------|------------|
| Overall Pass Rate | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| [CATEGORY_1] | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| [CATEGORY_2] | [XX.X%] | [XX.X%] | [XX.X%] | [±X.X%] |
| [CATEGORY_3] | [XX.X%] | [XX.X%] | [±X.X%] | [±X.X%] |
| Critical Failures | [#] | [#] | [#] | [±#] |

## {{PROJECT_NAME}} Remediation Summary

### {{PROJECT_NAME}} Issues Fixed
[List of all {{PROJECT_NAME}} issues that were successfully remediated]

### {{PROJECT_NAME}} Changes Made
[List of all {{PROJECT_NAME}} code/configuration changes made during remediation]

### Remaining {{PROJECT_NAME}} Issues
[List any {{PROJECT_NAME}} issues not fixed with justification]

## {{PROJECT_NAME}} System Status

**Current Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Comparison to Baseline**: [IMPROVED/STABLE/SLIGHTLY DEGRADED]
**Ready for Production**: [YES/NO with reasoning]
```

### 9. Update History Document

Add the verification and remediation session to your history:

```markdown
#### [DATE] - Post-Change {{PROJECT_NAME}} Verification & Remediation

**Summary**: Verified {{PROJECT_NAME}} health after [DESCRIBE CHANGES] and remediated [NUMBER] regressions.

**{{PROJECT_NAME}} Changes Validated**:
- [Brief description of original {{PROJECT_NAME}} changes made]

**Results Comparison**:
- **Baseline**: [XX.X%] overall pass rate
- **Post-Change**: [XX.X%] overall pass rate
- **After Remediation**: [XX.X%] overall pass rate
- **Net Change**: [±X.X%]

**{{PROJECT_NAME}} Issues Found & Fixed**:
- **Critical**: [NUMBER] identified, [NUMBER] fixed
- **High Priority**: [NUMBER] identified, [NUMBER] fixed
- **Total Changes Made**: [NUMBER] fixes implemented

**Final Status**: [EXCELLENT/GOOD/FAIR/POOR] - {{PROJECT_NAME}} [ready/not ready] for production use

**Documentation**: [Links to analysis and final report files]
```

### 10. Notification: Verification Complete

**If notification system is available**, send notification with final results:
```bash
# Check if notification script exists
if [ -f "{{NOTIFICATION_SCRIPT}}" ]; then
    {{NOTIFICATION_SCRIPT}} "{{PROJECT_PREFIX}} ✅ {{PROJECT_NAME}} post-change verification COMPLETE - [XX.X%] final pass rate, [NUMBER] issues fixed, system [STATUS]" --type=progress --priority=medium --target-user=ricardo.felipe.ruiz@gmail.com
else
    echo "✓ {{PROJECT_NAME}} verification complete - [XX.X%] final pass rate, [NUMBER] issues fixed"
fi
```

### 11. Final Todo List Update

Mark all verification and remediation tasks as completed and provide final summary.

## Remediation Guidelines

### ✅ DO These Things:
- **Systematic Approach**: Fix {{PROJECT_NAME}} issues in priority order (Critical → High → Medium)
- **Targeted Fixes**: Make specific fixes for identified {{PROJECT_NAME}} issues
- **Validation Testing**: Re-test after each {{PROJECT_NAME}} fix to ensure it works
- **Documentation**: Document every {{PROJECT_NAME}} change made and why
- **Root Cause Focus**: Fix underlying {{PROJECT_NAME}} causes, not just symptoms
- **Regression Testing**: Ensure {{PROJECT_NAME}} fixes don't break other functionality

### ⚠️ Remediation Priorities:
1. **Critical**: {{PROJECT_NAME}} tests that went from PASS → FAIL affecting core functionality
2. **High**: Significant performance regressions or major {{PROJECT_NAME}} feature failures
3. **Medium**: {{PROJECT_NAME}} edge cases, minor features, or cosmetic issues
4. **Low**: Pre-existing {{PROJECT_NAME}} issues not introduced by changes

### 🚫 Don't Fix These:
- **Pre-existing {{PROJECT_NAME}} Issues**: Problems that existed in the baseline
- **Environmental Issues**: Problems caused by external dependencies
- **Out-of-Scope Changes**: Issues unrelated to the {{PROJECT_NAME}} changes made
- **Low Impact Issues**: Minor {{PROJECT_NAME}} problems that don't affect functionality

## Success Criteria

✅ **Complete {{PROJECT_NAME}} Test Execution**: All {{PROJECT_NAME}} test categories re-executed after changes
✅ **Baseline Comparison**: Detailed comparison against pre-change {{PROJECT_NAME}} baseline
✅ **Regression Identification**: All introduced {{PROJECT_NAME}} issues identified and categorized
✅ **Critical Fixes**: All critical {{PROJECT_NAME}} regressions successfully remediated
✅ **Validation Testing**: {{PROJECT_NAME}} fixes verified through targeted re-testing
✅ **Documentation**: Complete analysis and final {{PROJECT_NAME}} report generated
✅ **History Update**: Session documented in history.md
✅ **Optional Notification**: Progress notifications sent if system available

**{{PROJECT_NAME}} verified and stabilized after changes. Ready for continued development.**

## Emergency Escalation

If critical {{PROJECT_NAME}} issues cannot be resolved:

1. **Send urgent notification (if available)**:
```bash
if [ -f "{{NOTIFICATION_SCRIPT}}" ]; then
    {{NOTIFICATION_SCRIPT}} "{{PROJECT_PREFIX}} 🚨 URGENT: Critical {{PROJECT_NAME}} issues require immediate attention - [BRIEF DESCRIPTION]" --type=alert --priority=urgent --target-user=ricardo.felipe.ruiz@gmail.com
fi
```

2. **Document the {{PROJECT_NAME}} problem clearly**
3. **Suggest {{PROJECT_NAME}} rollback procedures if needed**
4. **Wait for user guidance before proceeding**

---

## Template Customization Notes

**Before using this template:**

1. **Replace all placeholders** with project-specific values:
   - `{{PROJECT_NAME}}` → Your project name
   - `{{PROJECT_PREFIX}}` → Your TodoWrite prefix (e.g., [MYPROJECT])
   - `{{PROJECT_ROOT}}` → Full path to your project root
   - `{{TEST_SCRIPT}}` → Path to your test execution script
   - `{{NOTIFICATION_SCRIPT}}` → Path to your notification script

2. **Customize test categories** in comparison tables to match your project structure

3. **Update performance metrics** and health checks to reflect your project's needs

4. **Modify remediation workflows** to match your project's debugging and fix processes

5. **Remove or modify** notification sections if not applicable

6. **Adjust file paths** to match your project's directory structure

7. **Customize emergency escalation** procedures to match your project's support workflow