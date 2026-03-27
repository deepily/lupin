# {PROJECT_NAME} - Testing Tracking

**Created**: {DATE}
**Status**: LIVING DOCUMENT
**Project**: {PROJECT_FULL_NAME}
**Last Updated**: {LAST_UPDATED}

**Purpose**: Comprehensive tracking of all test suites, coverage, and quality metrics. This document provides a clear view of testing health and progress.

---

## Table of Contents

1. [Testing Overview](#testing-overview)
2. [Test Suite Status](#test-suite-status)
3. [Coverage Metrics](#coverage-metrics)
4. [Test Failures & Issues](#test-failures--issues)
5. [Testing Strategy](#testing-strategy)
6. [Quality Gates](#quality-gates)

---

## Testing Overview

### Overall Status

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| **Total Tests** | {TOTAL_TESTS} | {TARGET_TOTAL} | {TOTAL_STATUS} |
| **Passing Tests** | {PASSING_TESTS} | {TARGET_PASSING} | {PASSING_STATUS} |
| **Pass Rate** | {PASS_RATE}% | {TARGET_RATE}% | {RATE_STATUS} |
| **Code Coverage** | {COVERAGE}% | {TARGET_COVERAGE}% | {COVERAGE_STATUS} |
| **Critical Failures** | {CRITICAL_FAILURES} | 0 | {CRITICAL_STATUS} |
| **Test Execution Time** | {EXEC_TIME}s | <{TARGET_TIME}s | {TIME_STATUS} |

**Legend**:
- 🟢 **HEALTHY**: Meeting or exceeding targets
- 🟡 **WARNING**: Below target but acceptable
- 🔴 **CRITICAL**: Urgent attention needed

### Test Distribution

| Category | Count | Percentage | Status |
|----------|-------|------------|--------|
| Unit Tests | {UNIT_COUNT} | {UNIT_PERCENT}% | {UNIT_STATUS} |
| Integration Tests | {INT_COUNT} | {INT_PERCENT}% | {INT_STATUS} |
| Smoke Tests | {SMOKE_COUNT} | {SMOKE_PERCENT}% | {SMOKE_STATUS} |
| System Tests | {SYS_COUNT} | {SYS_PERCENT}% | {SYS_STATUS} |
| Performance Tests | {PERF_COUNT} | {PERF_PERCENT}% | {PERF_STATUS} |

**Total**: {TOTAL_TESTS} tests across {TEST_SUITE_COUNT} suites

---

## Test Suite Status

### Suite 1: {SUITE_1_NAME}

**Type**: {SUITE_1_TYPE}
**Location**: `{SUITE_1_PATH}`
**Framework**: {SUITE_1_FRAMEWORK}
**Owner**: {SUITE_1_OWNER}

**Status Summary**:

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Passing | {SUITE_1_PASS} | {SUITE_1_PASS_PERCENT}% |
| ❌ Failing | {SUITE_1_FAIL} | {SUITE_1_FAIL_PERCENT}% |
| ⏭️ Skipped | {SUITE_1_SKIP} | {SUITE_1_SKIP_PERCENT}% |
| **Total** | {SUITE_1_TOTAL} | 100% |

**Pass Rate**: {SUITE_1_PASS_RATE}% (Target: {SUITE_1_TARGET}%)

**Execution Time**: {SUITE_1_TIME}s (Average: {SUITE_1_AVG}s)

**Coverage**: {SUITE_1_COVERAGE}%

**Command**: `{SUITE_1_COMMAND}`

**Tests**:

| Test Name | Status | Duration | Last Run | Notes |
|-----------|--------|----------|----------|-------|
| `{TEST_1_1}` | ✅ PASS | {TEST_1_1_TIME}s | {TEST_1_1_DATE} | {TEST_1_1_NOTES} |
| `{TEST_1_2}` | ✅ PASS | {TEST_1_2_TIME}s | {TEST_1_2_DATE} | {TEST_1_2_NOTES} |
| `{TEST_1_3}` | ❌ FAIL | {TEST_1_3_TIME}s | {TEST_1_3_DATE} | {TEST_1_3_NOTES} |
| `{TEST_1_4}` | ✅ PASS | {TEST_1_4_TIME}s | {TEST_1_4_DATE} | {TEST_1_4_NOTES} |
| `{TEST_1_5}` | ⏭️ SKIP | - | {TEST_1_5_DATE} | {TEST_1_5_NOTES} |

**Recent Changes**:
- {SUITE_1_CHANGE_1}
- {SUITE_1_CHANGE_2}

**Known Issues**: {SUITE_1_ISSUES}

---

### Suite 2: {SUITE_2_NAME}

**Type**: {SUITE_2_TYPE}
**Location**: `{SUITE_2_PATH}`
**Framework**: {SUITE_2_FRAMEWORK}
**Owner**: {SUITE_2_OWNER}

**Status Summary**:

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Passing | {SUITE_2_PASS} | {SUITE_2_PASS_PERCENT}% |
| ❌ Failing | {SUITE_2_FAIL} | {SUITE_2_FAIL_PERCENT}% |
| ⏭️ Skipped | {SUITE_2_SKIP} | {SUITE_2_SKIP_PERCENT}% |
| **Total** | {SUITE_2_TOTAL} | 100% |

**Pass Rate**: {SUITE_2_PASS_RATE}% (Target: {SUITE_2_TARGET}%)

**Command**: `{SUITE_2_COMMAND}`

**Tests**:

| Test Name | Status | Duration | Last Run |
|-----------|--------|----------|----------|
| `{TEST_2_1}` | ✅ PASS | {TEST_2_1_TIME}s | {TEST_2_1_DATE} |
| `{TEST_2_2}` | ✅ PASS | {TEST_2_2_TIME}s | {TEST_2_2_DATE} |
| `{TEST_2_3}` | ✅ PASS | {TEST_2_3_TIME}s | {TEST_2_3_DATE} |

---

### Suite 3: {SUITE_3_NAME}

**Type**: {SUITE_3_TYPE}
**Location**: `{SUITE_3_PATH}`
**Status**: {SUITE_3_STATUS}

**Status Summary**:

| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Passing | {SUITE_3_PASS} | {SUITE_3_PASS_PERCENT}% |
| ❌ Failing | {SUITE_3_FAIL} | {SUITE_3_FAIL_PERCENT}% |
| **Total** | {SUITE_3_TOTAL} | 100% |

**Pass Rate**: {SUITE_3_PASS_RATE}%

**Command**: `{SUITE_3_COMMAND}`

---

## Coverage Metrics

### Overall Coverage

| Component | Lines | Covered | Coverage | Target | Status |
|-----------|-------|---------|----------|--------|--------|
| {COMPONENT_1} | {COMP_1_LINES} | {COMP_1_COVERED} | {COMP_1_COV}% | {COMP_1_TARGET}% | {COMP_1_STATUS} |
| {COMPONENT_2} | {COMP_2_LINES} | {COMP_2_COVERED} | {COMP_2_COV}% | {COMP_2_TARGET}% | {COMP_2_STATUS} |
| {COMPONENT_3} | {COMP_3_LINES} | {COMP_3_COVERED} | {COMP_3_COV}% | {COMP_3_TARGET}% | {COMP_3_STATUS} |
| **Total** | {TOTAL_LINES} | {TOTAL_COVERED} | {TOTAL_COV}% | {TOTAL_TARGET}% | {TOTAL_COV_STATUS} |

### Coverage by Test Type

| Test Type | Coverage Contribution | Lines Covered |
|-----------|----------------------|---------------|
| Unit Tests | {UNIT_COV_CONTRIB}% | {UNIT_LINES_COV} |
| Integration Tests | {INT_COV_CONTRIB}% | {INT_LINES_COV} |
| System Tests | {SYS_COV_CONTRIB}% | {SYS_LINES_COV} |

### Uncovered Critical Paths

| Path | Severity | Risk | Action Needed |
|------|----------|------|---------------|
| {UNCOV_PATH_1} | {UNCOV_SEV_1} | {UNCOV_RISK_1} | {UNCOV_ACTION_1} |
| {UNCOV_PATH_2} | {UNCOV_SEV_2} | {UNCOV_RISK_2} | {UNCOV_ACTION_2} |

### Coverage Trend

| Date | Coverage | Change | Notes |
|------|----------|--------|-------|
| {TREND_DATE_1} | {TREND_COV_1}% | +{TREND_CHANGE_1}% | {TREND_NOTES_1} |
| {TREND_DATE_2} | {TREND_COV_2}% | +{TREND_CHANGE_2}% | {TREND_NOTES_2} |
| {TREND_DATE_3} | {TREND_COV_3}% | -{TREND_CHANGE_3}% | {TREND_NOTES_3} |

**Coverage Goal**: Maintain >{COVERAGE_GOAL}% coverage with upward trend

---

## Test Failures & Issues

### Critical Failures (P0)

| Test | Suite | Failure Reason | First Failed | Last Run | Assignee | Status |
|------|-------|----------------|--------------|----------|----------|--------|
| {CRIT_TEST_1} | {CRIT_SUITE_1} | {CRIT_REASON_1} | {CRIT_FIRST_1} | {CRIT_LAST_1} | {CRIT_ASSIGN_1} | {CRIT_STATUS_1} |
| {CRIT_TEST_2} | {CRIT_SUITE_2} | {CRIT_REASON_2} | {CRIT_FIRST_2} | {CRIT_LAST_2} | {CRIT_ASSIGN_2} | {CRIT_STATUS_2} |

**Critical Failure Count**: {CRITICAL_FAIL_COUNT} (Target: 0)

**Blocking Release**: {BLOCKING_STATUS}

---

### High Priority Failures (P1)

| Test | Suite | Failure Reason | Status |
|------|-------|----------------|--------|
| {HIGH_TEST_1} | {HIGH_SUITE_1} | {HIGH_REASON_1} | {HIGH_STATUS_1} |
| {HIGH_TEST_2} | {HIGH_SUITE_2} | {HIGH_REASON_2} | {HIGH_STATUS_2} |

---

### Medium Priority Failures (P2)

| Test | Suite | Failure Reason | Status |
|------|-------|----------------|--------|
| {MED_TEST_1} | {MED_SUITE_1} | {MED_REASON_1} | {MED_STATUS_1} |

---

### Flaky Tests

| Test | Suite | Flake Rate | Last Flake | Action |
|------|-------|------------|------------|--------|
| {FLAKY_TEST_1} | {FLAKY_SUITE_1} | {FLAKY_RATE_1}% | {FLAKY_DATE_1} | {FLAKY_ACTION_1} |
| {FLAKY_TEST_2} | {FLAKY_SUITE_2} | {FLAKY_RATE_2}% | {FLAKY_DATE_2} | {FLAKY_ACTION_2} |

**Flaky Test Count**: {FLAKY_COUNT} (Target: <5)

**Stability**: {STABILITY_PERCENT}% (1 - flake rate)

---

### Skipped Tests

| Test | Suite | Skip Reason | When to Unskip |
|------|-------|-------------|----------------|
| {SKIP_TEST_1} | {SKIP_SUITE_1} | {SKIP_REASON_1} | {SKIP_UNSKIP_1} |
| {SKIP_TEST_2} | {SKIP_SUITE_2} | {SKIP_REASON_2} | {SKIP_UNSKIP_2} |

---

## Testing Strategy

### Test Pyramid

```
       ┌─────────────┐
       │   System    │  {SYS_COUNT} tests ({SYS_PERCENT}%)
       │    Tests    │
       └─────────────┘
      ┌───────────────┐
      │  Integration  │  {INT_COUNT} tests ({INT_PERCENT}%)
      │     Tests     │
      └───────────────┘
    ┌───────────────────┐
    │    Unit Tests     │  {UNIT_COUNT} tests ({UNIT_PERCENT}%)
    └───────────────────┘
```

**Target Distribution**:
- Unit Tests: {UNIT_TARGET}%
- Integration Tests: {INT_TARGET}%
- System Tests: {SYS_TARGET}%

**Current Distribution**:
- Unit Tests: {UNIT_ACTUAL}%
- Integration Tests: {INT_ACTUAL}%
- System Tests: {SYS_ACTUAL}%

**Status**: {PYRAMID_STATUS}

### Testing by Phase

| Phase | Tests Planned | Tests Implemented | Pass Rate | Status |
|-------|---------------|-------------------|-----------|--------|
| {PHASE_1} | {PHASE_1_PLAN} | {PHASE_1_IMPL} | {PHASE_1_RATE}% | {PHASE_1_STATUS} |
| {PHASE_2} | {PHASE_2_PLAN} | {PHASE_2_IMPL} | {PHASE_2_RATE}% | {PHASE_2_STATUS} |
| {PHASE_3} | {PHASE_3_PLAN} | {PHASE_3_IMPL} | {PHASE_3_RATE}% | {PHASE_3_STATUS} |

### Test Execution Workflow

**Development Cycle**:
1. {DEV_TEST_1}
2. {DEV_TEST_2}
3. {DEV_TEST_3}

**Pre-Commit**:
- Run fast unit tests
- Code style checks
- Static analysis

**Continuous Integration**:
- Full test suite execution
- Coverage report generation
- Performance benchmarks

**Pre-Release**:
- All tests must pass
- Coverage > {TARGET_COVERAGE}%
- No critical failures
- Performance benchmarks met

---

## Quality Gates

### Phase Completion Gates

**Required for Phase Sign-Off**:
- [ ] All critical tests passing (100%)
- [ ] All high-priority tests passing (100%)
- [ ] Medium-priority tests passing (>{MEDIUM_TARGET}%)
- [ ] Code coverage > {PHASE_COVERAGE_TARGET}%
- [ ] No P0 or P1 failures
- [ ] Performance benchmarks met
- [ ] Test documentation complete

### Release Gates

**Required for Release**:
- [ ] All test suites passing (100%)
- [ ] No critical or high-priority failures
- [ ] Code coverage > {RELEASE_COVERAGE_TARGET}%
- [ ] Performance regression tests passing
- [ ] Security tests passing
- [ ] Load tests passing (if applicable)
- [ ] Smoke tests in production environment passing

### Continuous Quality Monitoring

**Daily Checks**:
- [ ] Test pass rate > {DAILY_TARGET}%
- [ ] No new critical failures
- [ ] Coverage not decreased

**Weekly Checks**:
- [ ] Review flaky tests
- [ ] Update test documentation
- [ ] Address medium-priority failures

**Monthly Checks**:
- [ ] Test suite performance review
- [ ] Coverage gap analysis
- [ ] Testing strategy review

---

## Testing Priorities

### Critical Tests (Must Always Pass)

| Test | Suite | Reason |
|------|-------|--------|
| {CRIT_PRIO_1} | {CRIT_PRIO_SUITE_1} | {CRIT_PRIO_REASON_1} |
| {CRIT_PRIO_2} | {CRIT_PRIO_SUITE_2} | {CRIT_PRIO_REASON_2} |
| {CRIT_PRIO_3} | {CRIT_PRIO_SUITE_3} | {CRIT_PRIO_REASON_3} |

### High Priority Tests (Should Pass)

| Test | Suite | Impact if Failing |
|------|-------|-------------------|
| {HIGH_PRIO_1} | {HIGH_PRIO_SUITE_1} | {HIGH_PRIO_IMPACT_1} |
| {HIGH_PRIO_2} | {HIGH_PRIO_SUITE_2} | {HIGH_PRIO_IMPACT_2} |

### Tests Pending Implementation

| Test | Priority | Target Phase | Reason |
|------|----------|--------------|--------|
| {PENDING_1} | {PENDING_PRIO_1} | {PENDING_PHASE_1} | {PENDING_REASON_1} |
| {PENDING_2} | {PENDING_PRIO_2} | {PENDING_PHASE_2} | {PENDING_REASON_2} |

---

## Cross-References

### Related Documents

- **Active Work**: [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md)
- **Architecture**: [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md)
- **Navigation**: [README.md](README.md)
- **Risks**: [{PROJECT_NAME}-risk-issues.md]({PROJECT_NAME}-risk-issues.md)

### Test Locations

- **Unit Tests**: `{UNIT_TEST_PATH}`
- **Integration Tests**: `{INT_TEST_PATH}`
- **Smoke Tests**: `{SMOKE_TEST_PATH}`
- **Test Fixtures**: `{FIXTURE_PATH}`
- **Test Data**: `{TEST_DATA_PATH}`

---

## Maintenance Notes

**Update Frequency**: After each test run or significant test changes
**Owner**: {OWNER_NAME}
**Reviewers**: {REVIEWER_LIST}

**When to Update**:
- After test runs (update pass rates)
- New tests added
- Tests modified or removed
- Coverage changes
- Failures occur or are resolved

**Review Schedule**:
- Daily: Critical failure review
- Weekly: Full status review
- Monthly: Strategy and coverage review

---

**Token Budget**: 3,000-6,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}
