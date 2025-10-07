# Phase {PHASE_NUMBER}: {PHASE_NAME}

**Status**: {PHASE_STATUS}
**Project**: {PROJECT_NAME}
**Started**: {START_DATE}
**Completed**: {COMPLETION_DATE}
**Duration**: {ACTUAL_DURATION} (Estimated: {ESTIMATED_DURATION})

**Purpose**: Archive of completed Phase {PHASE_NUMBER} implementation details and outcomes.

---

## Table of Contents

1. [Phase Overview](#phase-overview)
2. [Objectives](#objectives)
3. [Implementation Details](#implementation-details)
4. [Testing Results](#testing-results)
5. [Decisions Made](#decisions-made)
6. [Issues Encountered](#issues-encountered)
7. [Lessons Learned](#lessons-learned)

---

## Phase Overview

### Summary

{PHASE_SUMMARY}

### Scope

**In Scope**:
- {IN_SCOPE_1}
- {IN_SCOPE_2}
- {IN_SCOPE_3}

**Out of Scope** (Moved to later phases):
- {OUT_SCOPE_1}
- {OUT_SCOPE_2}

### Dependencies

**Required**:
- {DEPENDENCY_1}: {DEPENDENCY_1_STATUS}
- {DEPENDENCY_2}: {DEPENDENCY_2_STATUS}

**Enabled**:
- Phase {NEXT_PHASE}: {ENABLED_DESCRIPTION}

---

## Objectives

### Primary Objectives

#### Objective 1: {OBJECTIVE_1}

**Target**: {OBJECTIVE_1_TARGET}
**Achieved**: {OBJECTIVE_1_ACHIEVED}
**Success Metric**: {OBJECTIVE_1_METRIC}
**Result**: {OBJECTIVE_1_RESULT}

**Implementation**:
- {OBJECTIVE_1_IMPL_1}
- {OBJECTIVE_1_IMPL_2}

---

#### Objective 2: {OBJECTIVE_2}

**Target**: {OBJECTIVE_2_TARGET}
**Achieved**: {OBJECTIVE_2_ACHIEVED}
**Success Metric**: {OBJECTIVE_2_METRIC}
**Result**: {OBJECTIVE_2_RESULT}

**Implementation**:
- {OBJECTIVE_2_IMPL_1}
- {OBJECTIVE_2_IMPL_2}

---

#### Objective 3: {OBJECTIVE_3}

**Target**: {OBJECTIVE_3_TARGET}
**Achieved**: {OBJECTIVE_3_ACHIEVED}
**Success Metric**: {OBJECTIVE_3_METRIC}
**Result**: {OBJECTIVE_3_RESULT}

**Implementation**:
- {OBJECTIVE_3_IMPL_1}
- {OBJECTIVE_3_IMPL_2}

---

### Secondary Objectives

- {SECONDARY_1}: {SECONDARY_1_STATUS}
- {SECONDARY_2}: {SECONDARY_2_STATUS}
- {SECONDARY_3}: {SECONDARY_3_STATUS}

---

## Implementation Details

### Files Created

| File Path | Purpose | Lines of Code |
|-----------|---------|---------------|
| `{FILE_1}` | {FILE_1_PURPOSE} | {FILE_1_LOC} |
| `{FILE_2}` | {FILE_2_PURPOSE} | {FILE_2_LOC} |
| `{FILE_3}` | {FILE_3_PURPOSE} | {FILE_3_LOC} |

**Total**: {TOTAL_FILES} files, {TOTAL_LOC} lines of code

### Files Modified

| File Path | Changes | Impact |
|-----------|---------|--------|
| `{MOD_FILE_1}` | {MOD_1_CHANGES} | {MOD_1_IMPACT} |
| `{MOD_FILE_2}` | {MOD_2_CHANGES} | {MOD_2_IMPACT} |

### Key Components Implemented

#### Component 1: {COMPONENT_1_NAME}

**Location**: `{COMPONENT_1_PATH}`

**Purpose**: {COMPONENT_1_PURPOSE}

**Key Features**:
- {COMPONENT_1_FEATURE_1}
- {COMPONENT_1_FEATURE_2}
- {COMPONENT_1_FEATURE_3}

**Interface**:
```python
class {COMPONENT_1_CLASS}:
    def {COMPONENT_1_METHOD_1}( self, {PARAMS_1} ) -> {RETURN_1}:
        """
        {METHOD_1_DESCRIPTION}

        Requires:
            - {REQUIRES_1}

        Ensures:
            - {ENSURES_1}
        """
        pass

    def {COMPONENT_1_METHOD_2}( self, {PARAMS_2} ) -> {RETURN_2}:
        """
        {METHOD_2_DESCRIPTION}
        """
        pass
```

**Usage Example**:
```python
{COMPONENT_1_USAGE_EXAMPLE}
```

**Design Decisions**:
- {COMPONENT_1_DECISION_1}
- {COMPONENT_1_DECISION_2}

**Testing**: {COMPONENT_1_TESTING_STATUS}

---

#### Component 2: {COMPONENT_2_NAME}

**Location**: `{COMPONENT_2_PATH}`

**Purpose**: {COMPONENT_2_PURPOSE}

**Key Features**:
- {COMPONENT_2_FEATURE_1}
- {COMPONENT_2_FEATURE_2}

**Interface**:
```python
{COMPONENT_2_INTERFACE}
```

**Testing**: {COMPONENT_2_TESTING_STATUS}

---

### Configuration Changes

**New Configuration Keys**:
```ini
[{CONFIG_SECTION}]
{NEW_CONFIG_KEY_1} = {NEW_CONFIG_VALUE_1}
{NEW_CONFIG_KEY_2} = {NEW_CONFIG_VALUE_2}
```

**Modified Configuration**:
- {CONFIG_CHANGE_1}
- {CONFIG_CHANGE_2}

**Configuration Documentation**: Updated in `{CONFIG_EXPLAINER_PATH}`

### Dependencies Added

| Dependency | Version | Purpose | License |
|------------|---------|---------|---------|
| {DEP_1} | {DEP_1_VERSION} | {DEP_1_PURPOSE} | {DEP_1_LICENSE} |
| {DEP_2} | {DEP_2_VERSION} | {DEP_2_PURPOSE} | {DEP_2_LICENSE} |

**Installation**:
```bash
pip install {DEP_1}=={DEP_1_VERSION} {DEP_2}=={DEP_2_VERSION}
```

---

## Testing Results

### Test Suite Summary

| Suite | Implemented | Passing | Total Planned | Pass Rate | Status |
|-------|-------------|---------|---------------|-----------|--------|
| {SUITE_1} | {SUITE_1_IMPL} | {SUITE_1_PASS} | {SUITE_1_TOTAL} | {SUITE_1_RATE}% | ✅ |
| {SUITE_2} | {SUITE_2_IMPL} | {SUITE_2_PASS} | {SUITE_2_TOTAL} | {SUITE_2_RATE}% | ✅ |
| {SUITE_3} | {SUITE_3_IMPL} | {SUITE_3_PASS} | {SUITE_3_TOTAL} | {SUITE_3_RATE}% | ✅ |

**Overall**: {TOTAL_PASSING}/{TOTAL_TESTS} tests passing ({OVERALL_PASS_RATE}%)

### Smoke Test Results

**Command**: `python {SMOKE_TEST_FILE}`

**Output Summary**:
```
{SMOKE_TEST_OUTPUT}
```

**Result**: ✅ All smoke tests passing

### Unit Test Results

**Command**: `pytest {UNIT_TEST_PATH}`

**Coverage**: {TEST_COVERAGE}%

**Key Tests**:
- `test_{TEST_1}`: {TEST_1_DESCRIPTION} - ✅ PASS
- `test_{TEST_2}`: {TEST_2_DESCRIPTION} - ✅ PASS
- `test_{TEST_3}`: {TEST_3_DESCRIPTION} - ✅ PASS

**Result**: ✅ All unit tests passing

### Integration Test Results

**Tests Executed**:
- {INTEGRATION_TEST_1}: ✅ PASS
- {INTEGRATION_TEST_2}: ✅ PASS

**Result**: ✅ All integration tests passing

### Performance Benchmarks

| Benchmark | Target | Actual | Status |
|-----------|--------|--------|--------|
| {BENCHMARK_1} | {BENCHMARK_1_TARGET} | {BENCHMARK_1_ACTUAL} | {BENCHMARK_1_STATUS} |
| {BENCHMARK_2} | {BENCHMARK_2_TARGET} | {BENCHMARK_2_ACTUAL} | {BENCHMARK_2_STATUS} |

---

## Decisions Made

### Decision 1: {DECISION_1}

**Date**: {DECISION_1_DATE}
**Context**: {DECISION_1_CONTEXT}

**Options Considered**:

**Option A**: {OPTION_1_A}
- ✅ Pros: {PROS_1_A}
- ❌ Cons: {CONS_1_A}

**Option B**: {OPTION_1_B}
- ✅ Pros: {PROS_1_B}
- ❌ Cons: {CONS_1_B}

**Option C**: {OPTION_1_C}
- ✅ Pros: {PROS_1_C}
- ❌ Cons: {CONS_1_C}

**Decision**: {DECISION_1_CHOICE}

**Rationale**: {DECISION_1_RATIONALE}

**Impact**: {DECISION_1_IMPACT}

**Documented In**: [{PROJECT_NAME}-decision-log.md]({PROJECT_NAME}-decision-log.md#{DECISION_1_ANCHOR})

---

### Decision 2: {DECISION_2}

**Date**: {DECISION_2_DATE}
**Context**: {DECISION_2_CONTEXT}

**Decision**: {DECISION_2_CHOICE}

**Rationale**: {DECISION_2_RATIONALE}

**Documented In**: [{PROJECT_NAME}-decision-log.md]({PROJECT_NAME}-decision-log.md#{DECISION_2_ANCHOR})

---

## Issues Encountered

### Issue 1: {ISSUE_1}

**Severity**: {ISSUE_1_SEVERITY}
**Discovered**: {ISSUE_1_DATE}

**Description**: {ISSUE_1_DESCRIPTION}

**Impact**: {ISSUE_1_IMPACT}

**Resolution**: {ISSUE_1_RESOLUTION}

**Resolution Date**: {ISSUE_1_RESOLUTION_DATE}

**Preventive Measures**: {ISSUE_1_PREVENTION}

---

### Issue 2: {ISSUE_2}

**Severity**: {ISSUE_2_SEVERITY}
**Discovered**: {ISSUE_2_DATE}

**Description**: {ISSUE_2_DESCRIPTION}

**Resolution**: {ISSUE_2_RESOLUTION}

---

### Unresolved Issues (Deferred)

| Issue | Severity | Deferred To | Rationale |
|-------|----------|-------------|-----------|
| {DEFERRED_1} | {DEFERRED_1_SEV} | {DEFERRED_1_PHASE} | {DEFERRED_1_RATIONALE} |

---

## Lessons Learned

### What Went Well

1. **{SUCCESS_1}**
   - {SUCCESS_1_DESCRIPTION}
   - Why it worked: {SUCCESS_1_REASON}
   - Repeat in future: {SUCCESS_1_REPEAT}

2. **{SUCCESS_2}**
   - {SUCCESS_2_DESCRIPTION}
   - Why it worked: {SUCCESS_2_REASON}

3. **{SUCCESS_3}**
   - {SUCCESS_3_DESCRIPTION}

### What Could Be Improved

1. **{IMPROVEMENT_1}**
   - Issue: {IMPROVEMENT_1_ISSUE}
   - Impact: {IMPROVEMENT_1_IMPACT}
   - Recommendation: {IMPROVEMENT_1_RECOMMENDATION}

2. **{IMPROVEMENT_2}**
   - Issue: {IMPROVEMENT_2_ISSUE}
   - Recommendation: {IMPROVEMENT_2_RECOMMENDATION}

### Technical Insights

1. **{INSIGHT_1}**
   - Discovery: {INSIGHT_1_DISCOVERY}
   - Application: {INSIGHT_1_APPLICATION}

2. **{INSIGHT_2}**
   - Discovery: {INSIGHT_2_DISCOVERY}

### Process Improvements

1. **{PROCESS_1}**
   - Old approach: {PROCESS_1_OLD}
   - New approach: {PROCESS_1_NEW}
   - Benefit: {PROCESS_1_BENEFIT}

2. **{PROCESS_2}**
   - Recommendation: {PROCESS_2_RECOMMENDATION}

---

## Phase Completion Checklist

**Technical Requirements**:
- [x] All primary objectives achieved
- [x] All secondary objectives achieved or deferred
- [x] All smoke tests passing
- [x] All unit tests passing
- [x] Integration tests passing
- [x] Performance benchmarks met
- [x] No critical bugs

**Documentation Requirements**:
- [x] Phase documentation complete
- [x] Architecture reference updated
- [x] Decision log updated
- [x] API documentation updated
- [x] Configuration documentation updated
- [x] Code comments complete

**Quality Gates**:
- [x] Code review completed
- [x] Security review completed
- [x] Performance review completed
- [x] Test coverage > {TARGET_COVERAGE}%

**Handoff**:
- [x] Next phase planning complete
- [x] Dependencies for next phase documented
- [x] Known issues documented
- [x] Phase archived

---

## Next Phase Preview

**Phase {NEXT_PHASE_NUMBER}**: {NEXT_PHASE_NAME}

**Dependencies Met**:
- {NEXT_DEP_1}: ✅
- {NEXT_DEP_2}: ✅

**Blockers Removed**:
- {BLOCKER_REMOVED_1}
- {BLOCKER_REMOVED_2}

**Estimated Start**: {NEXT_PHASE_START}
**Estimated Duration**: {NEXT_PHASE_DURATION}

---

## Cross-References

### Related Documents

- **Project Navigation**: [README.md](../README.md)
- **Architecture**: [{PROJECT_NAME}-architecture-reference.md](../{PROJECT_NAME}-architecture-reference.md)
- **Active Work** (moved to next phase): [{PROJECT_NAME}-active-work.md](../{PROJECT_NAME}-active-work.md)
- **Decision Log**: [{PROJECT_NAME}-decision-log.md](../{PROJECT_NAME}-decision-log.md)

### Related Phases

- **Previous Phase**: [phase-{PREV_PHASE}-{PREV_PHASE_NAME}.md](phase-{PREV_PHASE}-{PREV_PHASE_NAME}.md)
- **Next Phase**: [phase-{NEXT_PHASE}-{NEXT_PHASE_NAME}.md](phase-{NEXT_PHASE}-{NEXT_PHASE_NAME}.md)

### Code References

- **Implementation**: `{IMPLEMENTATION_PATH}`
- **Tests**: `{TEST_PATH}`
- **Configuration**: `{CONFIG_PATH}`

---

**Token Budget**: 3,000-6,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Archived**: {ARCHIVE_DATE}
**Phase Completion**: {COMPLETION_DATE}
