# CI/CD Testing Implementation Plan for CoSA Framework

> **Last Updated:** 2025-05-19

## Executive Summary

This document outlines an incremental approach for implementing automated testing within the CoSA framework to support CI/CD workflows. The strategy builds upon existing main-block tests while gradually introducing formal pytest-based testing that can be triggered automatically on remote branch pushes. The implementation prioritizes minimal disruption to the current development workflow while ensuring high-quality, reliable test coverage.

## Current State Analysis

### Testing Approaches Currently in Use

The CoSA codebase currently employs an informal testing strategy via main-block tests within most modules. These tests provide basic validation but have several limitations:

| Feature | Current State | Target State |
|---------|---------------|--------------|
| Test Triggers | Manual execution | Automated on push/PR |
| Test Structure | Main-block tests | Formal pytest framework |
| Test Coverage | Basic functionality | Comprehensive units and integration |
| Test Reporting | Console output | Formatted reports |
| Test Environment | Developer machine | CI/CD pipeline |
| Assertion Style | Print-based verification | Formal assertions |

### Example from RunnableCode

The recent enhancement to `runnable_code.py` provides an excellent example of a more structured testing approach that can serve as a model for other modules:

```python
if __name__ == "__main__":
    
    import time
    
    def run_test(title, code, example, should_succeed=True):
        """Run a test case with the given code and example."""
        du.print_banner(f"TEST: {title}", prepend_nl=True)
        
        # Create test instance with debug mode
        test_runner = RunnableCode(debug=True, verbose=True)
        
        # Set up prompt response dictionary
        test_runner.prompt_response_dict = {
            "code": code.strip().split("\n"),
            "example": example,
            "returns": "string"
        }
        
        # Print the test code
        test_runner.print_code("Test Code")
        
        # Check if code is runnable
        print(f"Is code runnable? {test_runner.is_code_runnable()}")
        
        # Execute the code
        start_time = time.time()
        result = test_runner.run_code()
        duration = time.time() - start_time
        
        # Verify results
        success = test_runner.code_ran_to_completion()
        print(f"Code ran successfully: {success}")
        print(f"Execution time: {duration:.4f} seconds")
        print(f"Return code: {result['return_code']}")
        print(f"Output: {result['output']}")
        
        # Check if result matches expectation
        if success == should_succeed:
            print("✅ Test PASSED")
        else:
            print("❌ Test FAILED")
        
        return success, result
    
    # Test cases
    hello_code = """
def say_hello():
    return "Hello, World!"
"""
    error_code = """
def divide(a, b):
    return a / b
"""
    # Run tests
    t1_success, t1_result = run_test("Simple Hello World", hello_code, hello_example)
    t2_success, t2_result = run_test("Division by Zero Error", error_code, error_example, should_succeed=False)
```

This structure can be adapted for formal pytest modules while preserving the ability to run tests directly.

## Implementation Strategy

The implementation strategy follows a phased approach to gradually introduce formal testing without disrupting existing development workflows.

### Phase 1: Foundational Setup

1. **Test Directory Structure**
   ```
   src/cosa/tests/
   ├── __init__.py
   ├── conftest.py
   ├── unit/
   │   ├── __init__.py
   │   ├── utils/
   │   │   ├── __init__.py
   │   │   └── test_util.py
   │   └── agents/
   │       ├── __init__.py
   │       └── v010/
   │           ├── __init__.py
   │           └── test_runnable_code.py
   └── integration/
       └── __init__.py
   ```

2. **Common Test Fixtures (conftest.py)**
   - Environment configuration
   - Temporary file creation/cleanup
   - Mock LLM clients
   - Test data fixtures

3. **GitHub Actions Workflow**
   - `.github/workflows/test.yml` file that runs on push
   - Initial configuration focusing only on util module tests

### Phase 2: Core Utility Testing

Using `cosa.utils.util` as a starting point:

1. **Extract tests from existing main block**
   - Preserve the original main block for development testing
   - Create parallel pytest-compatible tests from same logic

2. **Add proper assertions and mocks**
   - Replace print-based verification with assertions
   - Add mocks for environment variables and file systems

3. **Example test_util.py Implementation**
   ```python
   import os
   import pytest
   import tempfile
   from datetime import datetime
   
   import cosa.utils.util as du
   
   @pytest.fixture
   def setup_debug():
       """Enable debug mode for tests."""
       prev_debug = du.debug
       du.init(True)
       yield
       du.init(prev_debug)
   
   def test_get_current_datetime():
       """Test that get_current_datetime returns formatted string."""
       dt_str = du.get_current_datetime()
       assert isinstance(dt_str, str)
       assert "@" in dt_str
       assert len(dt_str) > 10
   
   def test_get_current_date():
       """Test get_current_date with different formats."""
       # Test standard format
       date_str = du.get_current_date()
       assert isinstance(date_str, str)
       assert len(date_str.split("-")) == 3
       
       # Test prose format
       prose_date = du.get_current_date(return_prose=True)
       assert isinstance(prose_date, str)
       assert "," in prose_date
       
       # Test with offset
       tomorrow = du.get_current_date(offset=1)
       today = du.get_current_date()
       assert tomorrow != today
   
   def test_write_and_read_file():
       """Test file writing and reading."""
       with tempfile.NamedTemporaryFile(delete=False) as temp:
           temp_path = temp.name
       
       try:
           # Test write lines
           test_lines = ["line1", "line2", "line3"]
           du.write_lines_to_file(temp_path, test_lines)
           
           # Test read as list
           read_lines = du.get_file_as_list(temp_path)
           assert read_lines == test_lines
           
           # Test read as string
           read_str = du.get_file_as_string(temp_path)
           assert read_str == "line1\nline2\nline3"
       finally:
           if os.path.exists(temp_path):
               os.remove(temp_path)
   ```

### Phase 3: Agent Testing (RunnableCode)

The `runnable_code.py` module with its enhanced test structure is an ideal candidate for the next phase:

1. **Test isolation for RunnableCode**
   - Create mocks for dependencies
   - Isolate from file system where possible

2. **Example test_runnable_code.py Implementation**
   ```python
   import pytest
   from unittest.mock import patch, MagicMock
   
   from cosa.agents.v010.runnable_code import RunnableCode
   
   @pytest.fixture
   def mock_code_runner():
       """Mock for util_code_runner.assemble_and_run_solution."""
       with patch('cosa.utils.util_code_runner.assemble_and_run_solution') as mock:
           # Configure the mock to return a success response
           mock.return_value = {
               "return_code": 0,
               "output": "Hello, World!"
           }
           yield mock
   
   def test_runnable_code_initialization():
       """Test basic initialization of RunnableCode."""
       code = RunnableCode(debug=True, verbose=True)
       assert code.debug is True
       assert code.verbose is True
       assert code.prompt_response is None
       assert code.prompt_response_dict is None
       assert code.code_response_dict is None
       assert code.answer is None
       assert code.error is None
   
   def test_code_ran_to_completion():
       """Test code_ran_to_completion method."""
       code = RunnableCode()
       
       # Test with None response dict
       assert code.code_ran_to_completion() is False
       
       # Test with error return code
       code.code_response_dict = {"return_code": 1}
       assert code.code_ran_to_completion() is False
       
       # Test with success return code
       code.code_response_dict = {"return_code": 0}
       assert code.code_ran_to_completion() is True
   
   def test_run_code_success(mock_code_runner):
       """Test successful code execution."""
       code = RunnableCode(debug=True)
       code.prompt_response_dict = {
           "code": ["def say_hello():", "    return 'Hello, World!'"],
           "example": "solution = say_hello()",
           "returns": "string"
       }
       
       result = code.run_code()
       
       assert code.error is None
       assert code.answer == "Hello, World!"
       assert result["return_code"] == 0
       assert result["output"] == "Hello, World!"
   ```

### Phase 4: Broader Test Coverage

Gradually expand test coverage to more components:

1. **LLM Client Testing**
   - Mock API responses
   - Test client factory pattern
   - Test error handling

2. **Agent Base Testing**
   - Mock run_prompt/run_code to isolate agent behavior
   - Test XML parsing
   - Test formatter integration

3. **Individual Agent Testing**
   - Create mock data for each agent type
   - Test specialized methods

### GitHub Actions Workflow

```yaml
name: CoSA Tests

on:
  push:
    branches: [ main, develop, "feature/*", "bugfix/*" ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
        pip install pytest pytest-cov
    
    - name: Test with pytest
      run: |
        # Phase 1: Run util tests only
        pytest src/cosa/tests/unit/utils/ -v
        
        # For later phases, expand test scope:
        # pytest src/cosa/tests/ -v --cov=src/cosa --cov-report=xml
    
    # For later phases, add code coverage reporting
    # - name: Upload coverage to Codecov
    #   uses: codecov/codecov-action@v3
    #   with:
    #     file: ./coverage.xml
    #     fail_ci_if_error: true
```

## Migration Schedule / Todo List

| Task | Priority | Status | Est. Effort | Notes |
|------|----------|--------|-------------|-------|
| Create test directory structure | High | ⏳ Not Started | 1 hour | Initial setup |
| Implement `conftest.py` with fixtures | High | ⏳ Not Started | 2 hours | Define common fixtures |
| Create `test_util.py` | High | ⏳ Not Started | 4 hours | First utility module test |
| Setup GitHub Actions workflow | High | ⏳ Not Started | 2 hours | Basic workflow file |
| Create `test_runnable_code.py` | Medium | ⏳ Not Started | 3 hours | Test agent foundations |
| Test LLM client and factory | Medium | ⏳ Not Started | 4 hours | Mock API responses |
| Test AgentBase class | Medium | ⏳ Not Started | 4 hours | Test base functionality |
| Test MathAgent | Low | ⏳ Not Started | 3 hours | First concrete agent test |
| Add integration tests | Low | ⏳ Not Started | 8 hours | Test component interactions |

**Legend:**
- ✅ Completed
- 🔄 In Progress
- ⏳ Not Started
- ❌ Blocked

## Implementation Examples

### Example 1: test_util.py

```python
import os
import pytest
import tempfile
from datetime import datetime

import cosa.utils.util as du

class TestDateTimeFunctions:
    """Tests for date and time utility functions."""
    
    def test_get_current_datetime_raw(self):
        """Test get_current_datetime_raw returns correct timezone."""
        # Test default timezone
        dt_default = du.get_current_datetime_raw()
        assert dt_default.tzinfo is not None
        assert "US/Eastern" in str(dt_default.tzinfo)
        
        # Test specific timezone
        dt_pacific = du.get_current_datetime_raw("US/Pacific")
        assert "US/Pacific" in str(dt_pacific.tzinfo)
        
        # Test days offset
        tomorrow = du.get_current_datetime_raw(days_offset=1)
        today = du.get_current_datetime_raw()
        assert (tomorrow - today).days == 1
    
    def test_get_current_datetime(self):
        """Test get_current_datetime returns correctly formatted string."""
        dt_str = du.get_current_datetime()
        assert isinstance(dt_str, str)
        assert "@" in dt_str
        assert ":" in dt_str
        
        # Test with different timezone
        dt_str_pst = du.get_current_datetime("US/Pacific")
        assert "PST" in dt_str_pst or "PDT" in dt_str_pst

class TestFileOperations:
    """Tests for file IO utility functions."""
    
    def test_get_file_as_list(self):
        """Test reading file as list with various options."""
        with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp:
            temp.write("Line1\nLine2\nLine3\n")
            temp_path = temp.name
        
        try:
            # Basic read
            lines = du.get_file_as_list(temp_path)
            assert len(lines) == 4  # Last line is empty
            assert lines[0] == "Line1\n"
            
            # With lowercase
            lines = du.get_file_as_list(temp_path, lower_case=True)
            assert lines[0] == "line1\n"
            
            # With strip
            lines = du.get_file_as_list(temp_path, clean=True)
            assert lines[0] == "Line1"
            
            # With strip_newlines
            lines = du.get_file_as_list(temp_path, strip_newlines=True)
            assert lines[0] == "Line1"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    
    def test_write_lines_to_file(self):
        """Test writing lines to a file."""
        test_lines = ["Line1", "Line2", "Line3"]
        with tempfile.NamedTemporaryFile(delete=False) as temp:
            temp_path = temp.name
        
        try:
            # Write and verify
            du.write_lines_to_file(temp_path, test_lines)
            with open(temp_path, 'r') as f:
                content = f.read()
            assert content == "Line1\nLine2\nLine3"
            
            # Test with blank line stripping
            du.write_lines_to_file(temp_path, ["Line1", "", "Line3"], strip_blank_lines=True)
            with open(temp_path, 'r') as f:
                content = f.read()
            assert content == "Line1\nLine3"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
```

### Example 2: test_runnable_code.py

```python
import pytest
from unittest.mock import patch, MagicMock

import cosa.utils.util as du
from cosa.agents.v010.runnable_code import RunnableCode

@pytest.fixture
def simple_code_example():
    """Fixture providing a simple code example."""
    return {
        "code": [
            "def say_hello():",
            "    return 'Hello, World!'"
        ],
        "example": "solution = say_hello()",
        "returns": "string"
    }

class TestRunnableCodeInitialization:
    """Tests for RunnableCode initialization."""
    
    def test_init_default_values(self):
        """Test initialization with default values."""
        rc = RunnableCode()
        assert rc.debug is False
        assert rc.verbose is False
        assert rc.prompt_response is None
        assert rc.prompt_response_dict is None
        assert rc.code_response_dict is None
        assert rc.answer is None
        assert rc.error is None
    
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        rc = RunnableCode(debug=True, verbose=True)
        assert rc.debug is True
        assert rc.verbose is True

class TestCodeRunning:
    """Tests for code execution functionality."""
    
    @patch('cosa.utils.util_code_runner.assemble_and_run_solution')
    def test_run_code_success(self, mock_runner, simple_code_example):
        """Test successful code execution."""
        # Configure mock to return success
        mock_runner.return_value = {
            "return_code": 0,
            "output": "Hello, World!"
        }
        
        # Create RunnableCode instance and set response dict
        rc = RunnableCode(debug=True)
        rc.prompt_response_dict = simple_code_example
        
        # Run the code
        result = rc.run_code()
        
        # Verify the runner was called correctly
        mock_runner.assert_called_once()
        
        # Verify results
        assert rc.error is None
        assert rc.answer == "Hello, World!"
        assert result["return_code"] == 0
    
    @patch('cosa.utils.util_code_runner.assemble_and_run_solution')
    def test_run_code_failure(self, mock_runner, simple_code_example):
        """Test failed code execution."""
        # Configure mock to return error
        error_msg = "NameError: name 'undefined_var' is not defined"
        mock_runner.return_value = {
            "return_code": 1,
            "output": error_msg
        }
        
        # Create RunnableCode instance and set response dict
        rc = RunnableCode(debug=True)
        rc.prompt_response_dict = simple_code_example
        
        # Run the code
        result = rc.run_code()
        
        # Verify results
        assert rc.error == error_msg
        assert rc.answer is None
        assert result["return_code"] == 1
```

## Special Considerations

### Test Environment Configuration

The test environment must manage several key challenges:

1. **Mock Configuration Manager**
   - Create a test configuration manager that doesn't read from disk
   - Provide standard values through fixtures

2. **Handle File System Operations**
   - Use temporary directories/files for file operations
   - Mock file operations where possible

3. **Mock External Services**
   - Create mock LLM clients that return predefined responses
   - Avoid actual API calls during tests

### Test Coverage Monitoring

Once basic tests are implemented, track coverage to identify high-priority areas:

1. **Configure Coverage Reporting**
   ```bash
   pytest --cov=src/cosa --cov-report=xml --cov-report=term
   ```

2. **Prioritize uncovered critical paths**
   - Agent initialization
   - LLM client interactions
   - Error handling

### Parallelizing Tests

As the test suite grows, consider optimizing test speed:

1. **Split tests into groups**
   - Unit tests (fast, independent)
   - Integration tests (slower, dependent)

2. **Configure pytest for parallelization**
   ```bash
   pip install pytest-xdist
   pytest -n auto src/cosa/tests/
   ```

## Conclusion

This implementation plan offers a pragmatic approach to introducing formal testing into the CoSA framework. By preserving the existing main-block tests while gradually building a proper pytest infrastructure, the plan minimizes disruption to the current workflow while providing long-term benefits:

**Key Benefits:**
- ✅ Automated verification of code changes on push/PR
- ✅ More robust detection of regressions
- ✅ Better documentation of expected behavior
- ✅ Support for CI/CD pipelines
- ✅ Improved code quality through test-driven development

The phased approach allows for incremental adoption, starting with core utilities and expanding to agent-specific functionality based on priority and complexity.

**Next Steps:**
1. Implement the basic directory structure and GitHub workflow
2. Create the first test module for `cosa.utils.util`
3. Verify automated test execution on push
4. Expand to additional modules based on priority