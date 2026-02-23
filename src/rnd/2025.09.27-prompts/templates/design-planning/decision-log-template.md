# {PROJECT_NAME} - Decision Log

**Created**: {DATE}
**Status**: LIVING DOCUMENT
**Project**: {PROJECT_FULL_NAME}
**Last Updated**: {LAST_UPDATED}

**Purpose**: Comprehensive record of architectural decisions, trade-offs, and rationale. This document explains WHY choices were made, not just WHAT was chosen.

---

## Table of Contents

1. [Decision Summary Table](#decision-summary-table)
2. [Decision Details](#decision-details)
3. [Decision Categories](#decision-categories)
4. [Superseded Decisions](#superseded-decisions)

---

## Decision Summary Table

| ID | Date | Decision | Category | Status | Impact |
|----|------|----------|----------|--------|--------|
| {DEC_ID_1} | {DATE_1} | {DECISION_1_SHORT} | {CATEGORY_1} | {STATUS_1} | {IMPACT_1} |
| {DEC_ID_2} | {DATE_2} | {DECISION_2_SHORT} | {CATEGORY_2} | {STATUS_2} | {IMPACT_2} |
| {DEC_ID_3} | {DATE_3} | {DECISION_3_SHORT} | {CATEGORY_3} | {STATUS_3} | {IMPACT_3} |
| {DEC_ID_4} | {DATE_4} | {DECISION_4_SHORT} | {CATEGORY_4} | {STATUS_4} | {IMPACT_4} |
| {DEC_ID_5} | {DATE_5} | {DECISION_5_SHORT} | {CATEGORY_5} | {STATUS_5} | {IMPACT_5} |

**Legend**:
- **Status**: ACTIVE | SUPERSEDED | UNDER_REVIEW | DEFERRED
- **Impact**: HIGH | MEDIUM | LOW
- **Category**: Architecture | Database | Security | Performance | Integration | Testing | Configuration

---

## Decision Details

### Decision {DEC_ID_1}: {DECISION_1_TITLE} {#decision-{DEC_ID_1}}

**Date**: {DECISION_1_DATE}
**Status**: {DECISION_1_STATUS}
**Category**: {DECISION_1_CATEGORY}
**Impact**: {DECISION_1_IMPACT}
**Decided By**: {DECISION_1_DECIDER}
**Phase**: {DECISION_1_PHASE}

#### Context

{DECISION_1_CONTEXT}

**Problem Statement**: {DECISION_1_PROBLEM}

**Constraints**:
- {CONSTRAINT_1_1}
- {CONSTRAINT_1_2}
- {CONSTRAINT_1_3}

**Requirements**:
- {REQUIREMENT_1_1}
- {REQUIREMENT_1_2}

#### Options Considered

##### Option A: {OPTION_1_A}

**Description**: {OPTION_1_A_DESC}

**Pros**:
- ✅ {PRO_1_A_1}
- ✅ {PRO_1_A_2}
- ✅ {PRO_1_A_3}

**Cons**:
- ❌ {CON_1_A_1}
- ❌ {CON_1_A_2}
- ❌ {CON_1_A_3}

**Estimated Effort**: {EFFORT_1_A}

**Risk Level**: {RISK_1_A}

**Example Implementation**:
```python
{CODE_EXAMPLE_1_A}
```

---

##### Option B: {OPTION_1_B}

**Description**: {OPTION_1_B_DESC}

**Pros**:
- ✅ {PRO_1_B_1}
- ✅ {PRO_1_B_2}

**Cons**:
- ❌ {CON_1_B_1}
- ❌ {CON_1_B_2}

**Estimated Effort**: {EFFORT_1_B}

**Risk Level**: {RISK_1_B}

**Example Implementation**:
```python
{CODE_EXAMPLE_1_B}
```

---

##### Option C: {OPTION_1_C}

**Description**: {OPTION_1_C_DESC}

**Pros**:
- ✅ {PRO_1_C_1}
- ✅ {PRO_1_C_2}

**Cons**:
- ❌ {CON_1_C_1}
- ❌ {CON_1_C_2}

**Estimated Effort**: {EFFORT_1_C}

**Risk Level**: {RISK_1_C}

---

#### Decision

**Selected**: {DECISION_1_CHOICE}

**Rationale**: {DECISION_1_RATIONALE}

**Key Factors**:
1. {KEY_FACTOR_1_1}
2. {KEY_FACTOR_1_2}
3. {KEY_FACTOR_1_3}

**Trade-offs Accepted**:
- {TRADEOFF_1_1}
- {TRADEOFF_1_2}

#### Implementation

**Location**: `{DECISION_1_IMPL_LOCATION}`

**Implementation Notes**: {DECISION_1_IMPL_NOTES}

**Configuration**:
```ini
[{DECISION_1_CONFIG_SECTION}]
{DECISION_1_CONFIG_KEY} = {DECISION_1_CONFIG_VALUE}
```

**Testing**: {DECISION_1_TESTING}

#### Impact Analysis

**Positive Impacts**:
- {POSITIVE_IMPACT_1_1}
- {POSITIVE_IMPACT_1_2}

**Negative Impacts**:
- {NEGATIVE_IMPACT_1_1} (Mitigation: {MITIGATION_1_1})
- {NEGATIVE_IMPACT_1_2} (Mitigation: {MITIGATION_1_2})

**Affected Components**:
- {AFFECTED_1_1}
- {AFFECTED_1_2}

#### Review & Validation

**Validation Criteria**:
- [ ] {VALIDATION_1_1}
- [ ] {VALIDATION_1_2}
- [ ] {VALIDATION_1_3}

**Review Date**: {DECISION_1_REVIEW_DATE}

**Outcome**: {DECISION_1_OUTCOME}

**Lessons Learned**: {DECISION_1_LESSONS}

---

### Decision {DEC_ID_2}: {DECISION_2_TITLE} {#decision-{DEC_ID_2}}

**Date**: {DECISION_2_DATE}
**Status**: {DECISION_2_STATUS}
**Category**: {DECISION_2_CATEGORY}
**Impact**: {DECISION_2_IMPACT}
**Phase**: {DECISION_2_PHASE}

#### Context

{DECISION_2_CONTEXT}

#### Options Considered

##### Option A: {OPTION_2_A}

**Pros**:
- ✅ {PRO_2_A_1}
- ✅ {PRO_2_A_2}

**Cons**:
- ❌ {CON_2_A_1}

---

##### Option B: {OPTION_2_B}

**Pros**:
- ✅ {PRO_2_B_1}

**Cons**:
- ❌ {CON_2_B_1}
- ❌ {CON_2_B_2}

---

#### Decision

**Selected**: {DECISION_2_CHOICE}

**Rationale**: {DECISION_2_RATIONALE}

**Implementation**: {DECISION_2_IMPL}

---

### Decision {DEC_ID_3}: {DECISION_3_TITLE} {#decision-{DEC_ID_3}}

**Date**: {DECISION_3_DATE}
**Status**: {DECISION_3_STATUS}
**Category**: {DECISION_3_CATEGORY}
**Impact**: {DECISION_3_IMPACT}

#### Context

{DECISION_3_CONTEXT}

#### Decision

**Selected**: {DECISION_3_CHOICE}

**Rationale**: {DECISION_3_RATIONALE}

**Trade-offs**: {DECISION_3_TRADEOFFS}

---

## Decision Categories

### Architecture Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {ARCH_DEC_1_ID} | {ARCH_DEC_1} | {ARCH_RAT_1} | {ARCH_STATUS_1} |
| {ARCH_DEC_2_ID} | {ARCH_DEC_2} | {ARCH_RAT_2} | {ARCH_STATUS_2} |

### Database Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {DB_DEC_1_ID} | {DB_DEC_1} | {DB_RAT_1} | {DB_STATUS_1} |
| {DB_DEC_2_ID} | {DB_DEC_2} | {DB_RAT_2} | {DB_STATUS_2} |

### Security Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {SEC_DEC_1_ID} | {SEC_DEC_1} | {SEC_RAT_1} | {SEC_STATUS_1} |
| {SEC_DEC_2_ID} | {SEC_DEC_2} | {SEC_RAT_2} | {SEC_STATUS_2} |

### Performance Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {PERF_DEC_1_ID} | {PERF_DEC_1} | {PERF_RAT_1} | {PERF_STATUS_1} |

### Integration Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {INT_DEC_1_ID} | {INT_DEC_1} | {INT_RAT_1} | {INT_STATUS_1} |

### Testing Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {TEST_DEC_1_ID} | {TEST_DEC_1} | {TEST_RAT_1} | {TEST_STATUS_1} |

### Configuration Decisions

| ID | Decision | Rationale | Status |
|----|----------|-----------|--------|
| {CONF_DEC_1_ID} | {CONF_DEC_1} | {CONF_RAT_1} | {CONF_STATUS_1} |

---

## Superseded Decisions

### Decision {SUPER_ID_1}: {SUPER_DECISION_1} (SUPERSEDED)

**Original Date**: {SUPER_DATE_1}
**Superseded Date**: {SUPER_SUPERSEDED_DATE_1}
**Superseded By**: [Decision {SUPER_BY_1}](#decision-{SUPER_BY_1})

**Original Decision**: {SUPER_ORIGINAL_1}

**Why Superseded**: {SUPER_REASON_1}

**Migration Path**: {SUPER_MIGRATION_1}

**Lessons Learned**: {SUPER_LESSONS_1}

---

### Decision {SUPER_ID_2}: {SUPER_DECISION_2} (SUPERSEDED)

**Original Date**: {SUPER_DATE_2}
**Superseded Date**: {SUPER_SUPERSEDED_DATE_2}
**Superseded By**: [Decision {SUPER_BY_2}](#decision-{SUPER_BY_2})

**Why Superseded**: {SUPER_REASON_2}

---

## Decision-Making Guidelines

### When to Log a Decision

Log decisions when:
- Architecture or design changes
- Technology selection or replacement
- Trade-offs between competing approaches
- Security or performance considerations
- Changes to existing decisions

Don't log:
- Minor implementation details
- Obvious choices with no alternatives
- Temporary workarounds
- Pure bug fixes

### Decision Template

```markdown
### Decision {ID}: {TITLE}

**Date**: YYYY.MM.DD
**Status**: ACTIVE | SUPERSEDED | UNDER_REVIEW | DEFERRED
**Category**: Architecture | Database | Security | Performance | Integration | Testing | Configuration
**Impact**: HIGH | MEDIUM | LOW

#### Context
[Why is this decision needed? What problem does it solve?]

#### Options Considered
##### Option A: [Name]
**Pros**: [Advantages]
**Cons**: [Disadvantages]

##### Option B: [Name]
**Pros**: [Advantages]
**Cons**: [Disadvantages]

#### Decision
**Selected**: [Chosen option]
**Rationale**: [Why this option was chosen]
**Trade-offs**: [What was sacrificed]

#### Implementation
**Location**: [Where implemented]
**Notes**: [Implementation details]
```

### Review Schedule

- **Monthly**: Review ACTIVE decisions for validation
- **Quarterly**: Review all decisions for relevance
- **Phase Completion**: Review phase-related decisions
- **Major Changes**: Review affected decisions

---

## Cross-References

### Related Documents

- **Architecture Reference**: [{PROJECT_NAME}-architecture-reference.md]({PROJECT_NAME}-architecture-reference.md)
- **Active Work**: [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md)
- **Navigation**: [README.md](README.md)
- **Testing**: [{PROJECT_NAME}-testing-tracking.md]({PROJECT_NAME}-testing-tracking.md)

### External References

- {EXTERNAL_REF_1}: {EXTERNAL_URL_1}
- {EXTERNAL_REF_2}: {EXTERNAL_URL_2}

---

## Maintenance Notes

**Update Frequency**: As decisions are made
**Owner**: {OWNER_NAME}
**Reviewers**: {REVIEWER_LIST}

**Review Checklist**:
- [ ] All new decisions logged
- [ ] Categories updated
- [ ] Superseded decisions marked
- [ ] Cross-references current
- [ ] Impact analysis complete

---

**Token Budget**: 6,000-12,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}
