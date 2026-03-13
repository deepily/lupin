# {PROJECT_NAME} - Architecture Reference

**Created**: {DATE}
**Status**: REFERENCE DOCUMENTATION
**Project**: {PROJECT_FULL_NAME}
**Last Updated**: {LAST_UPDATED}

**Purpose**: This document contains the timeless architectural design and decisions. For current implementation status, see [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md). For completed phase details, see [phases/](phases/).

---

## Table of Contents

1. [Research Foundation](#research-foundation)
2. [Executive Summary](#executive-summary)
3. [Current System Analysis](#current-system-analysis)
4. [Architecture Design](#architecture-design)
5. [Database Schema Design](#database-schema-design)
6. [Security Architecture](#security-architecture)
7. [Configuration Management](#configuration-management)
8. [Testing Strategy](#testing-strategy)
9. [Decision Log](#decision-log)

---

## Research Foundation

### Research Summary

**Research Phase**: {RESEARCH_PHASE_DATES}
**Research Documents**: [research/README.md](research/README.md)
**Synthesis Document**: [research/synthesis.md](research/synthesis.md)

**Key Research Findings**:
- {RESEARCH_FINDING_1}
- {RESEARCH_FINDING_2}
- {RESEARCH_FINDING_3}

**Technology Selection Rationale**:
- **{TECH_1}**: Selected because {TECH_1_RATIONALE}
- **{TECH_2}**: Selected because {TECH_2_RATIONALE}
- **{TECH_3}**: Selected because {TECH_3_RATIONALE}

**Alternatives Considered**: See [research/synthesis.md](research/synthesis.md) for detailed technology comparison.

**Research Impact on Design**:
- {RESEARCH_IMPACT_1}
- {RESEARCH_IMPACT_2}

---

## Executive Summary

### Current State

{CURRENT_STATE_DESCRIPTION}

**Key Components**:
- {COMPONENT_1}: {COMPONENT_1_DESCRIPTION}
- {COMPONENT_2}: {COMPONENT_2_DESCRIPTION}
- {COMPONENT_3}: {COMPONENT_3_DESCRIPTION}

**System Capabilities**:
- {CAPABILITY_1}
- {CAPABILITY_2}
- {CAPABILITY_3}

### Goal

{PROJECT_GOAL_DESCRIPTION}

**Target Architecture**:
- {TARGET_1}
- {TARGET_2}
- {TARGET_3}

**Key Features**:
- {FEATURE_1}
- {FEATURE_2}
- {FEATURE_3}

### Strategy

{IMPLEMENTATION_STRATEGY}

**Approach**:
- {APPROACH_1}
- {APPROACH_2}
- {APPROACH_3}

**Guiding Principles**:
- {PRINCIPLE_1}
- {PRINCIPLE_2}
- {PRINCIPLE_3}

### Timeline Estimate

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| {PHASE_1} | {DURATION_1} | {DELIVERABLES_1} |
| {PHASE_2} | {DURATION_2} | {DELIVERABLES_2} |
| {PHASE_3} | {DURATION_3} | {DELIVERABLES_3} |

**Total**: {TOTAL_DURATION} for complete implementation

### Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| {RISK_1} | {SEVERITY_1} | {MITIGATION_1} |
| {RISK_2} | {SEVERITY_2} | {MITIGATION_2} |
| {RISK_3} | {SEVERITY_3} | {MITIGATION_3} |

---

## Current System Analysis

### Component Inventory

#### Component 1: {COMPONENT_1_NAME}

**Location**: `{COMPONENT_1_PATH}`

**Purpose**: {COMPONENT_1_PURPOSE}

**Key Features**:
- {FEATURE_1_1}
- {FEATURE_1_2}
- {FEATURE_1_3}

**Dependencies**:
- {DEPENDENCY_1_1}
- {DEPENDENCY_1_2}

**Integration Points**:
```python
# Example usage pattern
{CODE_EXAMPLE_1}
```

**Known Issues**:
- {ISSUE_1_1}
- {ISSUE_1_2}

---

#### Component 2: {COMPONENT_2_NAME}

**Location**: `{COMPONENT_2_PATH}`

**Purpose**: {COMPONENT_2_PURPOSE}

**Key Features**:
- {FEATURE_2_1}
- {FEATURE_2_2}

**Configuration**:
```ini
[{CONFIG_SECTION}]
{CONFIG_KEY_1} = {CONFIG_VALUE_1}
{CONFIG_KEY_2} = {CONFIG_VALUE_2}
```

---

### System Flow Analysis

**Primary Flow**:
```
{FLOW_STEP_1}
  ↓
{FLOW_STEP_2}
  ↓
{FLOW_STEP_3}
  ↓
{FLOW_STEP_4}
```

**Error Handling**:
- {ERROR_CASE_1}: {ERROR_HANDLING_1}
- {ERROR_CASE_2}: {ERROR_HANDLING_2}

### Existing Infrastructure to Preserve

#### Infrastructure Element 1: {INFRA_1_NAME}

**Location**: `{INFRA_1_PATH}`

**Purpose**: {INFRA_1_PURPOSE}

**Must Maintain**: {INFRA_1_CONSTRAINT}

**Rationale**: {INFRA_1_RATIONALE}

**Usage Example**:
```python
{INFRA_1_EXAMPLE}
```

---

## Architecture Design

### High-Level Architecture

```
┌─────────────────────────────────────────────┐
│          {COMPONENT_LAYER_1}                │
├─────────────────────────────────────────────┤
│          {COMPONENT_LAYER_2}                │
├─────────────────────────────────────────────┤
│          {COMPONENT_LAYER_3}                │
├─────────────────────────────────────────────┤
│          {COMPONENT_LAYER_4}                │
└─────────────────────────────────────────────┘
```

**Layer Responsibilities**:
- **{LAYER_1}**: {LAYER_1_RESPONSIBILITY}
- **{LAYER_2}**: {LAYER_2_RESPONSIBILITY}
- **{LAYER_3}**: {LAYER_3_RESPONSIBILITY}
- **{LAYER_4}**: {LAYER_4_RESPONSIBILITY}

### Component Architecture

#### Component A: {COMPONENT_A_NAME}

**Responsibility**: {COMPONENT_A_RESPONSIBILITY}

**Interface**:
```python
class {COMPONENT_A_CLASS}:
    def {METHOD_A_1}( self, {PARAMS_A_1} ) -> {RETURN_A_1}:
        """
        {METHOD_A_1_DESCRIPTION}

        Requires:
            - {REQUIRES_A_1}

        Ensures:
            - {ENSURES_A_1}

        Raises:
            - {RAISES_A_1}
        """
        pass
```

**Implementation Details**:
- {DETAIL_A_1}
- {DETAIL_A_2}

**Design Decisions**:

**Decision A1**: {DECISION_A_1}

**Options Considered**:
- **Option 1**: {OPTION_A_1_1}
  - ✅ Pros: {PROS_A_1_1}
  - ❌ Cons: {CONS_A_1_1}

- **Option 2**: {OPTION_A_1_2}
  - ✅ Pros: {PROS_A_1_2}
  - ❌ Cons: {CONS_A_1_2}

**Decision**: {DECISION_A_1_CHOICE}

**Rationale**: {DECISION_A_1_RATIONALE}

---

### Integration Points

#### Integration Point 1: {INTEGRATION_1_NAME}

**Components**: {INTEGRATION_1_COMPONENTS}

**Protocol**: {INTEGRATION_1_PROTOCOL}

**Data Flow**:
```
{INTEGRATION_1_SENDER} → {INTEGRATION_1_MESSAGE} → {INTEGRATION_1_RECEIVER}
```

**Error Handling**: {INTEGRATION_1_ERROR_HANDLING}

**Backward Compatibility**: {INTEGRATION_1_COMPAT}

---

### Performance Considerations

**Scalability**:
- {SCALABILITY_1}
- {SCALABILITY_2}

**Bottlenecks**:
- {BOTTLENECK_1}: {BOTTLENECK_1_MITIGATION}
- {BOTTLENECK_2}: {BOTTLENECK_2_MITIGATION}

**Optimization Strategy**:
- {OPTIMIZATION_1}
- {OPTIMIZATION_2}

---

## Database Schema Design

### Database Technology Selection

**Options Considered**:

**Option 1: {DB_OPTION_1}**
- ✅ Pros: {DB_1_PROS}
- ❌ Cons: {DB_1_CONS}

**Option 2: {DB_OPTION_2}**
- ✅ Pros: {DB_2_PROS}
- ❌ Cons: {DB_2_CONS}

**Decision**: {DB_CHOICE}

**Rationale**: {DB_RATIONALE}

### Schema Design

#### Table 1: {TABLE_1_NAME}

**Purpose**: {TABLE_1_PURPOSE}

**Schema**:
```sql
CREATE TABLE {TABLE_1_NAME} (
    {COLUMN_1_1}    {TYPE_1_1} {CONSTRAINTS_1_1},
    {COLUMN_1_2}    {TYPE_1_2} {CONSTRAINTS_1_2},
    {COLUMN_1_3}    {TYPE_1_3} {CONSTRAINTS_1_3},

    -- Constraints
    {TABLE_1_CONSTRAINTS}
);

-- Indexes
{TABLE_1_INDEXES}
```

**Field Decisions**:

1. **{FIELD_1_1}**: {FIELD_1_1_RATIONALE}
2. **{FIELD_1_2}**: {FIELD_1_2_RATIONALE}
3. **{FIELD_1_3}**: {FIELD_1_3_RATIONALE}

**Access Patterns**:
- {ACCESS_PATTERN_1_1}
- {ACCESS_PATTERN_1_2}

---

#### Table 2: {TABLE_2_NAME}

**Purpose**: {TABLE_2_PURPOSE}

**Schema**:
```sql
CREATE TABLE {TABLE_2_NAME} (
    {COLUMN_2_1}    {TYPE_2_1} {CONSTRAINTS_2_1},
    {COLUMN_2_2}    {TYPE_2_2} {CONSTRAINTS_2_2},

    -- Foreign Keys
    {TABLE_2_FK}
);
```

---

### Data Migration Strategy

**Migration Approach**: {MIGRATION_APPROACH}

**Migration Steps**:
1. {MIGRATION_STEP_1}
2. {MIGRATION_STEP_2}
3. {MIGRATION_STEP_3}

**Rollback Procedure**: {ROLLBACK_PROCEDURE}

---

## Security Architecture

### Threat Model

**Primary Threats**:
1. **{THREAT_1}**: {THREAT_1_DESCRIPTION}
2. **{THREAT_2}**: {THREAT_2_DESCRIPTION}
3. **{THREAT_3}**: {THREAT_3_DESCRIPTION}

### Security Principles

**Defense in Depth**:
- {DEFENSE_1}
- {DEFENSE_2}

**Principle of Least Privilege**:
- {PRIVILEGE_1}
- {PRIVILEGE_2}

**Secure by Default**:
- {SECURE_1}
- {SECURE_2}

### Mitigation Strategies

#### Strategy 1: {MITIGATION_1_NAME}

**Implementation**: {MITIGATION_1_IMPL}

**Protects Against**: {MITIGATION_1_PROTECTS}

**Configuration**:
```ini
[{MITIGATION_1_SECTION}]
{MITIGATION_1_CONFIG}
```

---

#### Strategy 2: {MITIGATION_2_NAME}

**Implementation**: {MITIGATION_2_IMPL}

**Protects Against**: {MITIGATION_2_PROTECTS}

---

### Known Security Limitations

**Accepted Risks**:
1. {ACCEPTED_RISK_1}: {ACCEPTED_RISK_1_JUSTIFICATION}
2. {ACCEPTED_RISK_2}: {ACCEPTED_RISK_2_JUSTIFICATION}

**Future Enhancements**:
- {SECURITY_ENHANCEMENT_1}
- {SECURITY_ENHANCEMENT_2}

---

## Configuration Management

### Configuration Structure

**Primary Configuration**: `{CONFIG_FILE_PATH}`
**Documentation**: `{CONFIG_EXPLAINER_PATH}`

### Configuration Keys

```ini
[{CONFIG_SECTION_1}]
# ================================
# {CONFIG_GROUP_1_NAME}
# ================================
{CONFIG_KEY_1} = {CONFIG_VALUE_1}
{CONFIG_KEY_2} = {CONFIG_VALUE_2}

# ================================
# {CONFIG_GROUP_2_NAME}
# ================================
{CONFIG_KEY_3} = {CONFIG_VALUE_3}
{CONFIG_KEY_4} = {CONFIG_VALUE_4}
```

### Environment Variables

**Required**:
- `{ENV_VAR_1}`: {ENV_VAR_1_DESCRIPTION}
- `{ENV_VAR_2}`: {ENV_VAR_2_DESCRIPTION}

**Optional**:
- `{ENV_VAR_3}`: {ENV_VAR_3_DESCRIPTION}

### Configuration Validation

**Startup Validation**:
```python
def validate_configuration():
    """
    Validate configuration at startup.

    Ensures:
        - {VALIDATION_1}
        - {VALIDATION_2}
    """
    # Implementation
```

---

## Testing Strategy

### Testing Framework Overview

**Multi-Level Testing Approach**:

1. **Quick Smoke Tests**: {SMOKE_TEST_DESCRIPTION}
2. **Unit Tests**: {UNIT_TEST_DESCRIPTION}
3. **Integration Tests**: {INTEGRATION_TEST_DESCRIPTION}
4. **System Tests**: {SYSTEM_TEST_DESCRIPTION}

### Testing Requirements by Phase

**Phase 1**: {PHASE_1_TESTING}
**Phase 2**: {PHASE_2_TESTING}
**Phase 3**: {PHASE_3_TESTING}

### Test Execution Guidelines

**Pre-Implementation**:
1. {PRE_IMPL_1}
2. {PRE_IMPL_2}

**During Implementation**:
1. {DURING_IMPL_1}
2. {DURING_IMPL_2}

**Post-Implementation**:
1. {POST_IMPL_1}
2. {POST_IMPL_2}

---

## Decision Log

| Date | Decision | Rationale | Alternatives Considered |
|------|----------|-----------|-------------------------|
| {DECISION_1_DATE} | {DECISION_1} | {RATIONALE_1} | {ALTERNATIVES_1} |
| {DECISION_2_DATE} | {DECISION_2} | {RATIONALE_2} | {ALTERNATIVES_2} |
| {DECISION_3_DATE} | {DECISION_3} | {RATIONALE_3} | {ALTERNATIVES_3} |

---

## Cross-References

### Related Documents

- **Active Work**: [{PROJECT_NAME}-active-work.md]({PROJECT_NAME}-active-work.md)
- **Navigation**: [README.md](README.md)
- **Decision Details**: [{PROJECT_NAME}-decision-log.md]({PROJECT_NAME}-decision-log.md)
- **Testing**: [{PROJECT_NAME}-testing-tracking.md]({PROJECT_NAME}-testing-tracking.md)
- **Research**: [research/synthesis.md](research/synthesis.md)

### Code Locations

- **Implementation**: `{CODE_PATH}`
- **Configuration**: `{CONFIG_PATH}`
- **Tests**: `{TEST_PATH}`

---

**Token Budget**: 6,000-12,000 tokens | Current: ~{CURRENT_TOKEN_COUNT}

**Document Version**: {VERSION}
**Template Version**: 1.0
**Last Updated**: {LAST_UPDATED}
**Maintained By**: {MAINTAINER}
