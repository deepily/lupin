# Lupin Test Harness Update Prompt

**Purpose**: Systematic prompt for updating test harnesses after major code changes
**Scope**: Lupin Repository + CoSA Framework (dual-repo)
**Usage**: Execute this prompt after any significant code changes to ensure comprehensive test coverage
**Target**: Claude Code or AI assistant for automated test analysis and planning

## Executive Summary

This prompt provides a systematic approach for analyzing recent code changes across both Lupin and CoSA repositories and generating comprehensive test update plans. It reconciles existing test coverage with new requirements, identifies gaps, and provides implementation guidance for both smoke tests and unit tests.

**Key Capabilities**:
- Automated discovery of changed components via git analysis
- Cross-repository impact assessment
- Test type determination (smoke vs unit)
- Priority-based implementation planning
- Template-driven test creation

## Phase 1: Automated Discovery and Analysis

### 1.1 Repository Context Discovery

**Primary Task**: Analyze recent changes to identify all affected components

```bash
# Execute these commands to gather change data:

# 1. Get recent commits (adjust date range as needed)
git log --since="YYYY-MM-DD 00:00:00" --until="YYYY-MM-DD 23:59:59" --name-only --pretty=format:"=== Commit: %h - %s ===" | grep -E "\.py$|\.md$" | sort -u

# 2. Check CoSA submodule changes
cd src/cosa && git log --since="YYYY-MM-DD 00:00:00" --until="YYYY-MM-DD 23:59:59" --name-only --pretty=format:"=== Commit: %h - %s ===" | grep -E "\.py$" | sort -u

# 3. Categorize files by directory structure
find . -name "*.py" -newer reference_file -type f | sort

# 4. Identify new files vs modified files
git diff --name-status HEAD~N HEAD | grep -E "\.py$"
```

**Expected Output**: Comprehensive list of changed files categorized by:
- **New Components** (A - Added files)
- **Modified Components** (M - Modified files)
- **Deleted Components** (D - Deleted files)
- **Repository Location** (Lupin vs CoSA)
- **Component Type** (memory, rest, agents, utils, etc.)

### 1.2 Component Type Classification

**Primary Task**: Classify each changed component by its testing requirements

**Classification Logic**:

```python
# Component Classification Framework
component_types = {
    "memory/": {
        "type": "core_infrastructure",
        "requires_unit_tests": True,
        "requires_smoke_tests": True,
        "critical_for_system": True,
        "test_location": "src/cosa/tests/unit/memory/",
        "smoke_location": "inline quick_smoke_test()"
    },
    "rest/": {
        "type": "api_integration",
        "requires_unit_tests": True,
        "requires_smoke_tests": True,
        "critical_for_system": True,
        "test_location": "src/cosa/tests/unit/rest/",
        "smoke_location": "inline quick_smoke_test()"
    },
    "agents/": {
        "type": "business_logic",
        "requires_unit_tests": True,
        "requires_smoke_tests": True,
        "critical_for_system": False,
        "test_location": "src/cosa/tests/unit/agents/",
        "smoke_location": "inline quick_smoke_test()"
    },
    "lupin_app/": {
        "type": "lupin_integration",
        "requires_unit_tests": False,
        "requires_smoke_tests": True,
        "critical_for_system": True,
        "test_location": "src/tests/unit/",
        "smoke_location": "src/tests/lupin_smoke/"
    }
}
```

**Expected Output**: Each changed file classified with testing requirements

### 1.3 Current Test Coverage Inventory

**Primary Task**: Document existing test coverage status

```bash
# Inventory existing tests:

# 1. Count CoSA unit tests by category
find src/cosa/tests/unit -name "*.py" -type f | grep -v __pycache__ | sort

# 2. Count Lupin unit tests
find src/tests/unit -name "*.py" -type f | grep -v __pycache__ | sort

# 3. Find quick_smoke_test functions in CoSA
cd src/cosa && grep -l "quick_smoke_test" **/*.py | sort

# 4. Find Lupin smoke tests
find src/tests -name "*smoke*" -type f | sort

# 5. Check for integration tests
find src/tests -name "*integration*" -type f | sort
```

**Current State Documentation** (as of 2025.09.28):
- **CoSA Unit Tests**: 52 files across categories (agents, core, rest, memory, training)
- **CoSA Smoke Tests**: 14+ components with `quick_smoke_test()` functions
- **Lupin Unit Tests**: 9 files for critical components
- **Lupin Smoke Tests**: Category-based system with orchestration scripts
- **Integration Tests**: Limited - primarily WebSocket focused

## Phase 2: My Thought Process for Test Reconciliation

### 2.1 Historical Analysis

**How I Reconciled the Gap Between Old and New Test Harnesses**:

1. **Identified the Distinction**:
   - **Quick Smoke Tests**: End-to-end "does it work in reality?" validation with real dependencies
   - **Unit Tests**: Comprehensive isolated testing with ALL dependencies mocked
   - **Integration Tests**: Cross-component validation for critical workflows

2. **Discovered Coverage Patterns**:
   - **CoSA**: Strong smoke test coverage (14+ components) but gaps in unit tests for new memory components
   - **Lupin**: Orchestrated smoke test framework but limited unit test coverage
   - **Critical Gap**: Yesterday's three-level architecture changes lack corresponding test updates

3. **Recognized Infrastructure Strengths**:
   - **MockManager**: Sophisticated mocking infrastructure in CoSA
   - **Smoke Test Runners**: Automated discovery and execution
   - **Baseline Testing**: Comprehensive comparison capabilities

4. **Identified Integration Points**:
   - **Cross-Repo Dependencies**: Changes in CoSA memory layer affect Lupin queue system
   - **API Integration**: REST endpoints bridge both repositories
   - **Configuration**: Shared configuration affects both test suites

### 2.2 Reconciliation Strategy

**My Approach to Bringing Tests Up-to-Date**:

1. **Prioritize by Impact**:
   - 🚨 **CRITICAL**: Components affecting core functionality (normalizer, search)
   - 🔥 **HIGH**: New components requiring comprehensive coverage
   - ⚠️ **MEDIUM**: Integration points between repositories
   - 📝 **LOW**: Documentation and configuration changes

2. **Apply Test Type Logic**:
   - **New Components** → Full unit test suite + smoke test
   - **Modified Components** → Update existing tests + validate changes
   - **Integration Points** → Cross-repository integration tests
   - **Critical Path** → End-to-end validation tests

3. **Leverage Existing Infrastructure**:
   - **CoSA MockManager** for comprehensive mocking
   - **Smoke Test Patterns** for quick validation
   - **Baseline Comparison** for regression detection

## Phase 3: Systematic Update Framework

### 3.1 Change Impact Analysis

**Primary Task**: Map changes to test requirements

**Analysis Framework**:

```python
def analyze_change_impact(changed_files):
    """
    Analyze the testing impact of changed files.

    For each changed file, determine:
    1. What type of testing is required
    2. What existing tests need updates
    3. What new tests need creation
    4. Priority level based on criticality
    """

    impact_analysis = {}

    for file_path in changed_files:
        impact = {
            "file": file_path,
            "repository": "lupin" if "src/cosa" not in file_path else "cosa",
            "component_type": classify_component(file_path),
            "change_type": determine_change_type(file_path),  # new/modified/deleted
            "existing_tests": find_existing_tests(file_path),
            "required_tests": determine_test_requirements(file_path),
            "priority": calculate_priority(file_path),
            "integration_points": find_integration_points(file_path)
        }

        impact_analysis[file_path] = impact

    return impact_analysis
```

**Expected Output**: Complete mapping of changes to test requirements

### 3.2 Gap Identification

**Primary Task**: Identify missing or outdated test coverage

**Gap Analysis Logic**:

```python
def identify_test_gaps(impact_analysis):
    """
    Compare required tests with existing tests to find gaps.
    """

    gaps = {
        "missing_unit_tests": [],      # Components needing new unit tests
        "missing_smoke_tests": [],     # Components needing smoke tests
        "outdated_tests": [],          # Existing tests needing updates
        "missing_integration": [],     # Integration tests needed
        "cross_repo_impacts": []       # Cross-repository test updates
    }

    for file_path, analysis in impact_analysis.items():
        # Check for missing unit tests
        if analysis["required_tests"]["unit"] and not analysis["existing_tests"]["unit"]:
            gaps["missing_unit_tests"].append({
                "component": file_path,
                "priority": analysis["priority"],
                "template": determine_unit_test_template(file_path)
            })

        # Check for missing smoke tests
        if analysis["required_tests"]["smoke"] and not analysis["existing_tests"]["smoke"]:
            gaps["missing_smoke_tests"].append({
                "component": file_path,
                "priority": analysis["priority"],
                "pattern": "inline quick_smoke_test()"
            })

        # Check for outdated tests
        if analysis["existing_tests"]["unit"] and analysis["change_type"] == "modified":
            gaps["outdated_tests"].append({
                "test_file": analysis["existing_tests"]["unit"],
                "changes_needed": analyze_required_updates(file_path)
            })

        # Check for integration test needs
        if analysis["integration_points"]:
            gaps["missing_integration"].append({
                "components": analysis["integration_points"],
                "test_type": "integration",
                "scope": determine_integration_scope(analysis["integration_points"])
            })

    return gaps
```

### 3.3 Priority-Based Task Generation

**Primary Task**: Generate ordered implementation tasks

**Priority Framework**:

1. **🚨 CRITICAL** (Immediate - Same Day):
   - Core functionality fixes (search, normalization)
   - Security-related changes
   - Data integrity components

2. **🔥 HIGH** (This Week):
   - New component validation
   - API endpoint changes
   - Configuration modifications

3. **⚠️ MEDIUM** (Next Sprint):
   - Integration point updates
   - Performance optimizations
   - Documentation components

4. **📝 LOW** (Future):
   - Refactoring improvements
   - Code cleanup
   - Minor enhancements

## Phase 4: Implementation Guidance

### 4.1 Test Creation Templates

#### Unit Test Template (CoSA Components)

```python
"""
Unit tests for [ComponentName] with comprehensive mocking.

Tests the [ComponentName] class including:
- [Core functionality 1]
- [Core functionality 2]
- [Integration points]

Zero external dependencies - all operations mocked for isolated testing.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any, Optional

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.[category].[component_name] import [ComponentName]


class Test[ComponentName]( unittest.TestCase ):
    """
    Comprehensive unit tests for [ComponentName] class.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All [ComponentName] functionality tested in isolation
        - External dependencies properly mocked
        - Edge cases and error conditions validated
    """

    def setUp( self ):
        """Setup for each test method."""
        self.mock_manager = MockManager()
        self.test_utilities = UnitTestUtilities()

    def tearDown( self ):
        """Cleanup after each test method."""
        self.mock_manager.reset_mocks()

    # TEST METHODS FOR RECENT CHANGES
    def test_[critical_change_functionality]( self ):
        """
        Test [critical functionality description].

        This test validates the recent changes made to [ComponentName]
        specifically addressing [change description].
        """
        # Mock setup
        with self.mock_manager.[relevant_mock]() as mock_[dependency]:
            # Test implementation
            pass

    def test_[integration_point]( self ):
        """
        Test integration with [IntegratedComponent].

        Validates that changes to [ComponentName] properly integrate
        with [IntegratedComponent] without breaking existing functionality.
        """
        pass

    # REGRESSION TESTS
    def test_backward_compatibility( self ):
        """
        Test that recent changes maintain backward compatibility.
        """
        pass


if __name__ == "__main__":
    unittest.main()
```

#### Smoke Test Enhancement Template

```python
def quick_smoke_test():
    """
    Quick smoke test for [ComponentName] - validates core workflow including recent changes.

    Tests:
        - [Core functionality]
        - [Recent change validation]
        - [Integration with dependencies]
        - [Critical path functionality]

    Uses real dependencies for end-to-end validation.
    """
    du.print_banner( "[ComponentName] Smoke Test - Post-Change Validation", prepend_nl=True )

    try:
        # Test 1: Core functionality (pre-existing)
        print( "\nTest 1: Core functionality validation..." )
        # Implementation
        print( f"✓ Core functionality working" )

        # Test 2: Recent change validation (NEW)
        print( "\nTest 2: Recent change validation..." )
        # Specific test for recent changes
        print( f"✓ Recent changes validated" )

        # Test 3: Integration validation (UPDATED)
        print( "\nTest 3: Integration validation..." )
        # Test integration points affected by changes
        print( f"✓ Integration points working" )

        # Test 4: Critical path end-to-end (NEW)
        print( "\nTest 4: Critical path end-to-end..." )
        # End-to-end workflow validation
        print( f"✓ Critical path operational" )

        print( "\n✓ All [ComponentName] smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Error during smoke test: {e}" )
        du.print_stack_trace( e, explanation="Smoke test failed", caller="[ComponentName].quick_smoke_test()" )

    print( "\n✓ [ComponentName] smoke test completed" )
```

#### Integration Test Template

```python
"""
Integration tests for [ComponentName] cross-repository functionality.

Tests end-to-end workflows that span multiple components and repositories,
validating that recent changes don't break critical system functionality.
"""

import unittest
import time
from typing import Dict, Any, List

# Import test infrastructure
from test_utilities import IntegrationTestUtilities


class Test[ComponentName]Integration( unittest.TestCase ):
    """
    Integration tests for [ComponentName] with real dependencies.

    Tests critical workflows that cross component boundaries,
    particularly focusing on recent changes and their impacts.
    """

    def setUp( self ):
        """Setup for integration tests."""
        self.test_utils = IntegrationTestUtilities()
        self.test_data = self.test_utils.generate_test_data()

    def test_end_to_end_[critical_workflow]( self ):
        """
        Test complete [critical workflow] end-to-end.

        Validates that recent changes to [ComponentName] work correctly
        in the full system context with real dependencies.
        """
        # Setup test scenario
        # Execute workflow
        # Validate results
        # Performance checks
        pass

    def test_cross_repo_integration( self ):
        """
        Test integration between Lupin and CoSA repositories.

        Ensures that changes in one repository don't break
        functionality in the other repository.
        """
        pass


if __name__ == "__main__":
    unittest.main()
```

### 4.2 Test Naming Conventions

**File Naming Standards**:

```
# Unit Tests
src/cosa/tests/unit/[category]/unit_test_[component_name].py
src/tests/unit/unit_test_[component_name].py

# Smoke Tests
# Inline in component files as quick_smoke_test() function

# Integration Tests
src/tests/integration/test_[workflow_name]_integration.py

# Cross-Repository Tests
src/tests/cross_repo/test_[lupin_cosa]_[functionality].py
```

**Test Method Naming**:

```python
# Unit test methods
def test_[functionality]_[scenario]( self ):
def test_[functionality]_with_[condition]( self ):
def test_[functionality]_error_handling( self ):

# Focus on recent changes
def test_[recent_change]_functionality( self ):
def test_[recent_change]_integration( self ):
def test_[recent_change]_regression( self ):
```

## Phase 5: Validation and Quality Assurance

### 5.1 Coverage Requirements

**Minimum Coverage Standards**:

```python
coverage_requirements = {
    "critical_components": {
        "unit_test_coverage": 95,    # Lines of code covered
        "method_coverage": 100,      # All public methods tested
        "branch_coverage": 90,       # Decision branches covered
        "integration_coverage": 100  # All integration points tested
    },
    "standard_components": {
        "unit_test_coverage": 85,
        "method_coverage": 95,
        "branch_coverage": 80,
        "integration_coverage": 90
    },
    "support_components": {
        "unit_test_coverage": 75,
        "method_coverage": 90,
        "branch_coverage": 70,
        "integration_coverage": 80
    }
}
```

### 5.2 Success Metrics

**Validation Checklist**:

- [ ] **All modified components have corresponding test updates**
- [ ] **All new components have complete test suites**
- [ ] **All integration points are tested**
- [ ] **Critical path functionality validated end-to-end**
- [ ] **No regression in existing functionality**
- [ ] **Performance metrics within acceptable ranges**
- [ ] **Cross-repository compatibility confirmed**

**Quality Gates**:

1. **Phase 1 Gate**: All critical component tests pass
2. **Phase 2 Gate**: All new component tests achieve coverage requirements
3. **Phase 3 Gate**: All integration tests pass
4. **Phase 4 Gate**: Complete test suite passes with baseline comparison

### 5.3 Continuous Validation

**Ongoing Monitoring**:

```bash
# Run after each phase completion
./src/tests/run-lupin-smoke-tests.sh --category all
cd src/cosa && python3 tests/smoke/infrastructure/cosa_smoke_runner.py

# Performance baseline comparison
python3 src/scripts/benchmark_snapshot_managers.py

# Coverage analysis
coverage run -m pytest src/tests/unit/
coverage report --show-missing
```

## Usage Instructions

### Quick Start

1. **Execute Discovery Phase**:
   ```bash
   # Replace date with your change window
   git log --since="2025-09-27 00:00:00" --until="2025-09-28 00:00:00" --name-only --pretty=format:"=== Commit: %h - %s ===" | grep -E "\.py$"
   ```

2. **Run This Prompt**: Provide the discovered files to Claude Code with this prompt

3. **Follow Generated Plan**: Implement tests in priority order

4. **Validate Results**: Run comprehensive test suites and validate coverage

### Full Implementation

1. **Phase 1**: Execute automated discovery
2. **Phase 2**: Analyze impact and identify gaps
3. **Phase 3**: Generate priority-based implementation plan
4. **Phase 4**: Create tests using provided templates
5. **Phase 5**: Validate coverage and performance

## Example Execution Context

**Sample Prompt for Claude Code**:

```
I've made significant changes to the Lupin/CoSA codebase in the following files:
[LIST OF CHANGED FILES]

Please execute the Lupin Test Harness Update process:

1. Analyze the impact of these changes on our test coverage
2. Identify gaps between existing tests and new requirements
3. Generate a priority-based implementation plan for updating our test harnesses
4. Provide specific test creation guidance using our established patterns

Focus on maintaining the distinction between smoke tests (quick_smoke_test() functions) and unit tests (comprehensive MockManager-based testing). Ensure coverage across both Lupin and CoSA repositories.
```

---

**Document Version**: 1.0
**Last Updated**: 2025.09.28
**Maintainer**: Development Team
**Usage**: Execute after any significant code changes to ensure comprehensive test coverage