#!/bin/bash
# CoSA Framework Unit Test Suite Master Script
# 
# Runs comprehensive CoSA unit tests for all framework components
# with zero external dependencies for reliable CICD pipeline execution
#
# Usage:
#   ./run-cosa-unit-tests.sh [options]
#
# Options:
#   --category CATEGORY  Run only specific category (core, agents, memory, rest, tools, training)
#   --ci-mode           Run in CI-optimized mode with machine-readable output
#   --debug             Enable debug output for troubleshooting
#   --timeout SECONDS   Set test timeout (default: 30 seconds)
#   --report FILE       Save detailed test report to file
#   --help              Show this help message

set -e  # Exit on any error

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
UNIT_TEST_DIR="$PROJECT_ROOT/tests/unit"
RUNNER_SCRIPT="$UNIT_TEST_DIR/infrastructure/unit_test_runner.py"

# CoSA framework configuration (this script is in CoSA directory)
COSA_ROOT="$PROJECT_ROOT"
PYTHONPATH_BASE="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src"

# Color codes for output (disabled in CI mode)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Global flags
CI_MODE=false
DEBUG_MODE=false

# Logging functions
log_info() {
    if [ "$CI_MODE" = true ]; then
        echo "[INFO] $1"
    else
        echo -e "${BLUE}[INFO]${NC} $1"
    fi
}

log_success() {
    if [ "$CI_MODE" = true ]; then
        echo "[SUCCESS] $1"
    else
        echo -e "${GREEN}[SUCCESS]${NC} $1"
    fi
}

log_warning() {
    if [ "$CI_MODE" = true ]; then
        echo "[WARNING] $1"
    else
        echo -e "${YELLOW}[WARNING]${NC} $1"
    fi
}

log_error() {
    if [ "$CI_MODE" = true ]; then
        echo "[ERROR] $1"
    else
        echo -e "${RED}[ERROR]${NC} $1"
    fi
}

# Function to show help
show_help() {
    cat << EOF
CoSA Framework Unit Test Suite

USAGE:
    $0 [OPTIONS]

DESCRIPTION:
    Runs comprehensive CoSA framework unit tests with zero external dependencies.
    Designed for both local development and CICD pipeline execution.

OPTIONS:
    --category CATEGORY     Run only specific category: core, agents, memory, rest, tools, training
    --ci-mode              Run in CI-optimized mode with machine-readable output
    --debug                Enable debug output for troubleshooting
    --timeout SECONDS      Set test timeout in seconds (default: 30)
    --report FILE          Save detailed test report to specified file
    --help                 Show this help message

EXAMPLES:
    $0                          # Run all unit tests
    $0 --category core          # Run only core component tests
    $0 --ci-mode --timeout 60   # Run in CI mode with 60-second timeout
    $0 --debug --report report.txt  # Run with debug output and save report

REQUIREMENTS:
    - Python 3.7+ with CoSA framework dependencies
    - CoSA framework properly configured
    - PYTHONPATH includes CoSA framework directory
    - All isolated_unit_test() functions available in CoSA modules

FILES:
    Test Runner:   $RUNNER_SCRIPT
    CoSA Root:     $COSA_ROOT
    
EOF
}

# Function to check CoSA framework health
check_cosa_health() {
    log_info "Checking CoSA framework health..."
    
    # Check if CoSA directory exists
    if [ ! -d "$COSA_ROOT" ]; then
        log_error "CoSA framework directory not found: $COSA_ROOT"
        return 1
    fi
    
    # Check for key CoSA components
    local required_dirs=("agents" "config" "utils" "memory" "rest" "tests")
    for dir in "${required_dirs[@]}"; do
        if [ ! -d "$COSA_ROOT/$dir" ]; then
            log_error "Required CoSA directory missing: $COSA_ROOT/$dir"
            return 1
        fi
    done
    
    # Check if unit test infrastructure exists
    if [ ! -d "$UNIT_TEST_DIR" ]; then
        log_error "Unit test directory not found: $UNIT_TEST_DIR"
        return 1
    fi
    
    log_success "CoSA framework structure is valid"
    return 0
}

# Function to check Python dependencies
check_python_deps() {
    log_info "Checking Python dependencies..."
    
    # Check if Python is available
    if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
        log_error "Python not found. Please install Python 3.7+"
        return 1
    fi
    
    # Determine Python command
    PYTHON_CMD="python3"
    if ! command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python"
    fi
    
    # Set up PYTHONPATH for CoSA imports
    export PYTHONPATH="$PYTHONPATH_BASE:$PYTHONPATH"
    log_info "PYTHONPATH set to: $PYTHONPATH_BASE"
    
    # Check if we can import basic CoSA modules
    if ! $PYTHON_CMD -c "import cosa.utils.util as du" 2>/dev/null; then
        log_warning "CoSA utils module not importable - may affect some tests"
    fi
    
    if ! $PYTHON_CMD -c "import cosa.config.configuration_manager" 2>/dev/null; then
        log_warning "CoSA configuration manager not importable - may affect some tests"
    fi
    
    log_success "Python environment is ready"
    return 0
}

# Function to check unit test infrastructure
check_unit_test_infrastructure() {
    log_info "Checking unit test infrastructure..."
    
    # Check if test runner exists
    if [ ! -f "$RUNNER_SCRIPT" ]; then
        log_error "Unit test runner not found: $RUNNER_SCRIPT"
        return 1
    fi
    
    # Check if infrastructure modules exist
    local infra_dir="$UNIT_TEST_DIR/infrastructure"
    local required_files=("mock_manager.py" "test_fixtures.py" "unit_test_runner.py")
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$infra_dir/$file" ]; then
            log_error "Required infrastructure file missing: $infra_dir/$file"
            return 1
        fi
    done
    
    # Test that infrastructure modules can be imported
    cd "$infra_dir" || return 1
    
    if ! $PYTHON_CMD -c "from mock_manager import MockManager; MockManager()" 2>/dev/null; then
        log_error "MockManager cannot be imported or instantiated"
        return 1
    fi
    
    if ! $PYTHON_CMD -c "from test_fixtures import CoSATestFixtures; CoSATestFixtures()" 2>/dev/null; then
        log_error "CoSATestFixtures cannot be imported or instantiated"
        return 1
    fi
    
    cd - >/dev/null
    
    log_success "Unit test infrastructure is ready"
    return 0
}

# Function to run unit tests
run_unit_tests() {
    local args=("$@")
    
    log_info "Starting CoSA Framework Unit Test Suite..."
    log_info "Test Directory: $UNIT_TEST_DIR"
    log_info "CoSA Root: $COSA_ROOT"
    log_info "Runner Script: $RUNNER_SCRIPT"
    
    # Change to the infrastructure directory so imports work correctly
    cd "$UNIT_TEST_DIR/infrastructure" || {
        log_error "Failed to change to unit test infrastructure directory"
        return 1
    }
    
    # Run the unit test suite
    local python_cmd="python3"
    if ! command -v python3 >/dev/null 2>&1; then
        python_cmd="python"
    fi
    
    log_info "Executing: $python_cmd unit_test_runner.py ${args[*]}"
    
    # Run with explicit error handling
    if $python_cmd unit_test_runner.py "${args[@]}"; then
        log_success "Unit tests completed successfully"
        return 0
    else
        local exit_code=$?
        log_error "Unit tests failed with exit code $exit_code"
        return $exit_code
    fi
}

# Function to validate test categories
validate_category() {
    local category="$1"
    local valid_categories=("core" "agents" "memory" "rest" "tools" "training")
    
    for valid_cat in "${valid_categories[@]}"; do
        if [ "$category" = "$valid_cat" ]; then
            return 0
        fi
    done
    
    log_error "Invalid category: $category"
    log_info "Valid categories: ${valid_categories[*]}"
    return 1
}

# Main execution function
main() {
    local test_category=""
    local runner_args=()
    local timeout="30"
    local report_file=""
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --category)
                test_category="$2"
                if ! validate_category "$test_category"; then
                    exit 1
                fi
                runner_args+=("--category" "$2")
                shift 2
                ;;
            --ci-mode)
                CI_MODE=true
                runner_args+=("--ci-mode")
                shift
                ;;
            --debug)
                DEBUG_MODE=true
                runner_args+=("--debug")
                shift
                ;;
            --timeout)
                timeout="$2"
                runner_args+=("--timeout" "$2")  
                shift 2
                ;;
            --report)
                report_file="$2"
                runner_args+=("--report" "$2")
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # Show header (unless in CI mode)
    if [ "$CI_MODE" != true ]; then
        echo "=================================================================================="
        echo "               CoSA Framework Unit Test Suite"
        echo "=================================================================================="
        echo "Mode: Unit Testing (Zero External Dependencies)"
        echo "CoSA Root: $COSA_ROOT"
        echo "Category: ${test_category:-all}"
        echo "Timeout: ${timeout}s"
        echo "Time: $(date)"
        echo "=================================================================================="
    fi
    
    # Pre-flight checks
    log_info "Running pre-flight checks..."
    
    if ! check_cosa_health; then
        log_error "CoSA framework is not healthy. Please check installation"
        exit 1
    fi
    
    if ! check_python_deps; then
        log_error "Python dependencies not satisfied"
        exit 1
    fi
    
    if ! check_unit_test_infrastructure; then
        log_error "Unit test infrastructure is incomplete"
        exit 1
    fi
    
    log_success "Pre-flight checks completed"
    
    if [ "$CI_MODE" != true ]; then
        echo ""
    fi
    
    # Run the tests
    local start_time=$(date +%s)
    
    if run_unit_tests "${runner_args[@]}"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        log_success "Unit test suite completed in ${duration}s"
        
        if [ -n "$report_file" ]; then
            log_info "Test report saved to: $report_file"
        fi
        
        exit 0
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        log_error "Unit test suite failed after ${duration}s"
        exit $exit_code
    fi
}

# Execute main function with all arguments
main "$@"