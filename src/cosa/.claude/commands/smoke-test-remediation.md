---
description: Run COSA framework post-change verification and remediation
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

# COSA Framework Post-Change Smoke Test Prompt (Verification & Remediation)

**PURPOSE**: Verify COSA framework health after major changes and remediate any introduced regressions
**MODE**: Comparison analysis with targeted remediation
**PRINCIPLE**: Compare, Analyze, Fix, Validate
**SCOPE**: COSA Framework Only
**ARGUMENTS**: baseline_report=${1:-auto}, scope=${2:-FULL}

## Your Task

I have completed significant changes to the COSA framework and need you to verify the framework health compared to the pre-change baseline, identify any regressions introduced, and systematically remediate any breaking changes.

### 1. Pre-Flight Validation & Setup

First, validate prerequisites and setup the remediation environment:

```bash
# Navigate to COSA root directory
cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa

# Auto-detect baseline report if not provided
if [ "${1}" = "auto" ] || [ -z "${1}" ]; then
    BASELINE_REPORT=$(ls -t tests/results/*cosa-baseline-smoke-test-report.md 2>/dev/null | head -1)
    if [ -z "$BASELINE_REPORT" ]; then
        echo "❌ No baseline report found. Please run /smoke-test-baseline first or provide path"
        echo "Available reports:"
        ls -la tests/results/*baseline*.md 2>/dev/null || echo "No baseline reports found"
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

# Create results directory structure
mkdir -p tests/results/logs
mkdir -p tests/results/analysis
mkdir -p tests/results/reports

# Create backup point
echo "Creating remediation backup point..."
git diff > "tests/results/cosa_pre_remediation_$(date +%Y%m%d_%H%M%S).patch"
echo "✅ Git state captured for potential rollback"

# Verify COSA framework operational
export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
python -c "import cosa; print('✅ COSA framework import successful')" || {
    echo "❌ COSA framework import failed - critical blocker"
    exit 1
}

# Generate timestamp for session
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
echo "Session timestamp: ${TIMESTAMP}"
```

### 2. Initialize Comprehensive Todo List

Create a todo list to track the post-change verification and remediation process:

```
[COSA] Post-change COSA framework verification & remediation - STARTED at [TIMESTAMP]
[COSA] Pre-flight validation and baseline detection
[COSA] Execute post-change COSA framework smoke tests
[COSA] Generate comparison analysis against baseline
[COSA] Identify and prioritize regressions (Critical → High → Medium)
[COSA] Phase 1: Fix Critical regressions (immediate)
[COSA] Phase 2: Fix High priority issues (same session)
[COSA] Phase 3: Fix Medium priority issues (scope permitting)
[COSA] Validate all fixes with targeted re-testing
[COSA] Generate final remediation report with metrics
[COSA] Send completion notification (if available)
[COSA] Document remediation session in history
```

### 3. Notification: Start of Remediation (Optional)

```bash
# Send notification (using global notify-claude command)
notify-claude "[COSA] 🔧 COSA framework post-change remediation STARTED - Scope: $SCOPE, Baseline: $(basename $BASELINE_REPORT)" --type=progress --priority=medium
```

### 4. Execute Post-Change COSA Framework Tests

Run comprehensive tests with enhanced logging:

```bash
LOG_FILE="tests/results/logs/postchange_cosa_remediation_${TIMESTAMP}.log"
echo "Starting COSA framework post-change remediation at $(date)" | tee "${LOG_FILE}"
echo "Baseline Report: $BASELINE_REPORT" | tee -a "${LOG_FILE}"
echo "Remediation Scope: $SCOPE" | tee -a "${LOG_FILE}"
echo "===========================================" | tee -a "${LOG_FILE}"

# Execute full COSA test suite
./tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee -a "${LOG_FILE}"

echo "===========================================" | tee -a "${LOG_FILE}"
echo "Post-change COSA framework tests completed at $(date)" | tee -a "${LOG_FILE}"
echo "Log file: ${LOG_FILE}"

# Extract basic metrics for immediate comparison
CURRENT_TESTS=$(grep -o "Tests run: [0-9]*" "${LOG_FILE}" | tail -1 | grep -o "[0-9]*" || echo "0")
CURRENT_FAILURES=$(grep -o "Failures: [0-9]*" "${LOG_FILE}" | tail -1 | grep -o "[0-9]*" || echo "0")
CURRENT_PASS_RATE=$(echo "scale=1; (($CURRENT_TESTS - $CURRENT_FAILURES) * 100) / $CURRENT_TESTS" | bc -l 2>/dev/null || echo "0.0")

echo "Current Test Results: $CURRENT_TESTS tests, $CURRENT_FAILURES failures, ${CURRENT_PASS_RATE}% pass rate"
```

### 5. Intelligent Comparison Analysis

Create detailed comparison analysis with automatic regression detection:

**Analysis File**: `tests/results/analysis/$(date +%Y.%m.%d)-cosa-remediation-analysis-${TIMESTAMP}.md`

```markdown
# COSA Framework Remediation Analysis

**Date**: $(date +%Y-%m-%d)
**Timestamp**: ${TIMESTAMP}
**Purpose**: Post-change COSA framework verification and remediation
**Scope**: COSA Framework Only
**Remediation Mode**: $SCOPE
**Baseline Report**: $BASELINE_REPORT
**Post-Change Log**: tests/results/logs/postchange_cosa_remediation_${TIMESTAMP}.log

## Executive Summary

**Pre-Remediation Framework Health**: [Calculated from current test run]
**Baseline Pass Rate**: [Extract from baseline report]
**Current Pass Rate**: ${CURRENT_PASS_RATE}%
**Regression Detected**: [YES/NO based on comparison]
**Total Regressions Identified**: [Count from comparison]
**Remediation Scope**: $SCOPE

## Regression Analysis Matrix

### Critical Regressions (Fix Immediately) 🚨
[Auto-populate based on test comparison]
- Tests that went from PASS → FAIL affecting core framework
- Import failures or module loading issues
- API breaking changes
- Framework initialization failures

### High Priority Issues (Fix This Session) ⚠️
[Auto-populate based on test comparison]
- Significant performance degradations (>20% slower)
- Major feature functionality broken
- Multiple related test failures
- Memory leaks or resource issues

### Medium Priority Issues (Fix if Time Permits) 📝
[Auto-populate based on test comparison]
- Edge case failures
- Minor performance regressions (<20%)
- Cosmetic or logging issues
- Documentation test failures

## COSA Framework Results Comparison

| Category | Baseline | Current | Change | Status | Remediation Priority |
|----------|----------|---------|---------|---------|---------------------|
| Core | [Auto-extract] | [Auto-calc] | [Auto-calc] | [Auto-determine] | [Auto-assign] |
| Agents | [Auto-extract] | [Auto-calc] | [Auto-calc] | [Auto-determine] | [Auto-assign] |
| REST | [Auto-extract] | [Auto-calc] | [Auto-calc] | [Auto-determine] | [Auto-assign] |
| Memory | [Auto-extract] | [Auto-calc] | [Auto-calc] | [Auto-determine] | [Auto-assign] |
| Training | [Auto-extract] | [Auto-calc] | [Auto-calc] | [Auto-determine] | [Auto-assign] |

## Remediation Plan by Scope

### If SCOPE=FULL
1. **Phase 1**: All Critical issues (stop if >30 minutes)
2. **Phase 2**: All High priority issues (stop if >45 minutes total)
3. **Phase 3**: Medium priority issues (remaining time)

### If SCOPE=CRITICAL_ONLY
1. **Phase 1**: Critical issues only
2. **Document**: All other issues for future remediation

### If SCOPE=SELECTIVE
1. **Interactive**: Present issue list for user selection
2. **Fix**: Only user-selected issues

### If SCOPE=ANALYSIS_ONLY
1. **Report**: Generate analysis without remediation
2. **Document**: All issues with recommended fix approaches
```

### 6. Systematic Remediation Process

**For each identified regression, execute this workflow:**

#### Phase 1: Critical Issues (Time Limit: 10 min per issue)

```bash
echo "=== CRITICAL REMEDIATION PHASE ==="
CRITICAL_START_TIME=$(date +%s)

# Process each critical issue
for ISSUE in $CRITICAL_ISSUES; do
    ISSUE_START_TIME=$(date +%s)
    echo "Fixing Critical Issue: $ISSUE"

    # 1. Analyze the specific failure
    # 2. Identify root cause in COSA changes
    # 3. Implement targeted fix
    # 4. Test the specific fix
    # 5. Update progress tracker

    ISSUE_END_TIME=$(date +%s)
    ISSUE_DURATION=$((ISSUE_END_TIME - ISSUE_START_TIME))

    if [ $ISSUE_DURATION -gt 600 ]; then  # 10 minutes
        echo "⏰ Time limit exceeded for $ISSUE - documenting for manual review"
        # Document for manual intervention
    fi
done

CRITICAL_END_TIME=$(date +%s)
CRITICAL_DURATION=$((CRITICAL_END_TIME - CRITICAL_START_TIME))
echo "Critical phase completed in ${CRITICAL_DURATION}s"
```

#### Progress Tracking Table

Maintain real-time progress tracking:

```markdown
## Remediation Progress Tracker

| Issue ID | Category | Priority | Description | Status | Fix Applied | Time Spent | Validated |
|----------|----------|----------|-------------|---------|-------------|------------|-----------|
| CR-001 | Core | CRITICAL | Module import failure | ✅ Fixed | Import path correction | 3m | ✅ |
| CR-002 | Agents | CRITICAL | AgentBase instantiation | 🔄 In Progress | Constructor update | 8m | ⏳ |
| HP-001 | Memory | HIGH | Gister performance | ⏳ Pending | - | 0m | ❌ |
| MP-001 | Training | MEDIUM | Config loading | 📋 Deferred | - | 0m | ❌ |

**Legend**: ✅ Complete | 🔄 In Progress | ⏳ Pending | 📋 Deferred | ❌ Failed
```

### 7. Validation & Re-Testing

After each fix, validate immediately:

```bash
# Function to validate specific category
validate_fix() {
    local CATEGORY=$1
    echo "Validating fixes for category: $CATEGORY"

    # Run targeted tests for the category
    ./tests/smoke/scripts/run-cosa-smoke-tests.sh --category "$CATEGORY" 2>&1 | tee "tests/results/logs/validation_${CATEGORY}_${TIMESTAMP}.log"

    # Extract results
    local VALIDATION_RESULT=$?
    if [ $VALIDATION_RESULT -eq 0 ]; then
        echo "✅ $CATEGORY validation successful"
        return 0
    else
        echo "❌ $CATEGORY validation failed - fix may have introduced new issues"
        return 1
    fi
}

# Validate each fixed category
for CATEGORY in $FIXED_CATEGORIES; do
    validate_fix "$CATEGORY"
done
```

### 8. Final Comprehensive Testing

Run complete test suite after all fixes:

```bash
echo "=== FINAL VALIDATION SUITE ==="
FINAL_LOG="tests/results/logs/final_validation_cosa_${TIMESTAMP}.log"

# Execute complete test suite
./tests/smoke/scripts/run-cosa-smoke-tests.sh 2>&1 | tee "$FINAL_LOG"

# Extract final metrics
FINAL_TESTS=$(grep -o "Tests run: [0-9]*" "$FINAL_LOG" | tail -1 | grep -o "[0-9]*" || echo "0")
FINAL_FAILURES=$(grep -o "Failures: [0-9]*" "$FINAL_LOG" | tail -1 | grep -o "[0-9]*" || echo "0")
FINAL_PASS_RATE=$(echo "scale=1; (($FINAL_TESTS - $FINAL_FAILURES) * 100) / $FINAL_TESTS" | bc -l 2>/dev/null || echo "0.0")

echo "Final Results: $FINAL_TESTS tests, $FINAL_FAILURES failures, ${FINAL_PASS_RATE}% pass rate"
```

### 9. Generate Final Remediation Report

**Report File**: `tests/results/reports/$(date +%Y.%m.%d)-cosa-remediation-final-report-${TIMESTAMP}.md`

```markdown
# COSA Framework Remediation Final Report

## Session Metrics
- **Session Duration**: [Calculate total time]
- **Issues Identified**: [Count total]
- **Critical Issues Fixed**: [Count]
- **High Priority Issues Fixed**: [Count]
- **Medium Priority Issues Fixed**: [Count]
- **Issues Deferred**: [Count with reasons]
- **Success Rate**: [Percentage of issues resolved]

## Performance Impact Analysis

| Metric | Baseline | Pre-Remediation | Post-Remediation | Net Change |
|--------|----------|-----------------|------------------|------------|
| Overall Pass Rate | [%] | [%] | [%] | [±%] |
| Test Duration | [s] | [s] | [s] | [±%] |
| Critical Failures | [#] | [#] | [#] | [±#] |
| Memory Usage | [MB] | [MB] | [MB] | [±%] |

## Remediation Summary

### Successfully Fixed Issues
[List all issues that were successfully remediated with brief description of fix]

### Changes Made to COSA Framework
[List all code/configuration changes made during remediation]

### Remaining Issues (If Any)
[List any issues not fixed with justification and recommended next steps]

## Emergency Procedures (If Needed)

### Rollback Instructions
If critical issues remain:
```bash
# Restore pre-remediation state
git apply -R tests/results/cosa_pre_remediation_$(date +%Y%m%d)*.patch

# Verify rollback successful
./tests/smoke/scripts/run-cosa-smoke-tests.sh --quick
```

### Escalation Contacts
- Framework Owner: [Contact info]
- Emergency Support: [Contact info]

## Framework Status Assessment

**Current Health**: [EXCELLENT/GOOD/FAIR/POOR]
**Comparison to Baseline**: [IMPROVED/STABLE/SLIGHTLY DEGRADED/DEGRADED]
**Ready for Production**: [YES/NO with detailed reasoning]
**Recommended Next Steps**: [Specific actionable items]
```

### 10. Update History & Notifications

```bash
# Update session history
cat >> history.md << EOF
#### $(date +%Y.%m.%d) - COSA Framework Post-Change Remediation

**Summary**: Remediated COSA framework after [DESCRIBE CHANGES] with $SCOPE scope

**Results**:
- **Baseline**: [%] pass rate
- **Pre-Remediation**: [%] pass rate
- **Post-Remediation**: [%] pass rate
- **Net Improvement**: [±%]

**Issues Addressed**:
- **Critical**: [#] identified, [#] fixed
- **High Priority**: [#] identified, [#] fixed
- **Total Fixes Applied**: [#]

**Session Duration**: [X] minutes
**Framework Status**: [STATUS] - [ready/needs attention]

**Artifacts**:
- Log: tests/results/logs/postchange_cosa_remediation_${TIMESTAMP}.log
- Analysis: tests/results/analysis/$(date +%Y.%m.%d)-cosa-remediation-analysis-${TIMESTAMP}.md
- Report: tests/results/reports/$(date +%Y.%m.%d)-cosa-remediation-final-report-${TIMESTAMP}.md

EOF

# Send completion notification (using global notify-claude command)
notify-claude "[COSA] ✅ Framework remediation COMPLETE - ${FINAL_PASS_RATE}% final pass rate, [#] issues fixed, framework [STATUS]" --type=progress --priority=medium
```

### 11. Final Todo List Update

Mark all remediation tasks as completed with detailed summary.

## Results Directory Structure

All outputs organized in `tests/results/`:

```
tests/results/
├── logs/                                   # Test execution logs
│   ├── postchange_cosa_remediation_YYYYMMDD_HHMMSS.log
│   ├── validation_Core_YYYYMMDD_HHMMSS.log
│   └── final_validation_cosa_YYYYMMDD_HHMMSS.log
├── analysis/                               # Comparison analysis files
│   └── YYYY.MM.DD-cosa-remediation-analysis-YYYYMMDD_HHMMSS.md
├── reports/                                # Final remediation reports
│   └── YYYY.MM.DD-cosa-remediation-final-report-YYYYMMDD_HHMMSS.md
└── cosa_pre_remediation_YYYYMMDD_HHMMSS.patch  # Git backup for rollback
```

## Remediation Guidelines & Intelligence

### ⏰ Time Management
- **Critical Issues**: Max 10 minutes per issue
- **High Priority**: Max 5 minutes per issue
- **Medium Priority**: Max 2 minutes per issue
- **Total Session**: Max 60 minutes (adjust scope if needed)

### 🎯 Fix Prioritization Logic
```bash
# Auto-categorize issues by impact
categorize_issue() {
    local ISSUE=$1

    if [[ $ISSUE =~ "import|module|initialization|core" ]]; then
        echo "CRITICAL"
    elif [[ $ISSUE =~ "performance.*[0-9]{2,}%|major.*fail|API.*break" ]]; then
        echo "HIGH"
    else
        echo "MEDIUM"
    fi
}
```

### 🚨 Emergency Escalation Triggers
- Multiple critical fixes fail
- Pass rate decreases below baseline
- Session exceeds 90 minutes
- Framework becomes non-operational

### ✅ Success Criteria
✅ **Critical Issues Resolved**: All blocking issues fixed or documented
✅ **Pass Rate Improved**: Current ≥ Baseline pass rate
✅ **Framework Operational**: All modules import and function
✅ **Documentation Complete**: All changes and issues documented
✅ **Validation Successful**: Final test suite passes

**COSA framework verified, stabilized, and ready for continued development.**

### Notes for Advanced Usage

#### Selective Category Remediation
```bash
# Fix only specific categories
/smoke-test-remediation auto SELECTIVE
# Then choose: "Agents,Memory" when prompted
```

#### Analysis Without Fixes
```bash
# Generate comparison report only
/smoke-test-remediation auto ANALYSIS_ONLY
```

#### Custom Baseline
```bash
# Use specific baseline report
/smoke-test-remediation "tests/results/2025.09.20-cosa-baseline-report.md" FULL
```