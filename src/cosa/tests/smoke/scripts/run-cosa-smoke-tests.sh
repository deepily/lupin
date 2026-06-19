#!/bin/bash
# CoSA Framework Smoke Test Suite Master Script
# 
# Runs comprehensive CoSA smoke tests for all framework components
# Designed to be run before and after v000 deprecation work to detect regressions
#
# Usage:
#   ./run-cosa-smoke-tests.sh [options]
#
# Options:
#   --pre-deprecation    Run as pre-deprecation baseline test
#   --post-deprecation   Run as post-deprecation validation test
#   --category CATEGORY  Run only specific category (core, agents, rest, training, integration)
#   --quick              Run quick subset of tests (under 2 minutes)
#   --help               Show this help message

set -e  # Exit on any error

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SMOKE_TEST_DIR="$PROJECT_ROOT/tests/smoke"
RUNNER_SCRIPT="$SMOKE_TEST_DIR/infrastructure/cosa_smoke_runner.py"
CONFIG_FILE="$SMOKE_TEST_DIR/config/smoke_test_config.ini"

# CoSA framework configuration (this script is in CoSA directory)
COSA_ROOT="$PROJECT_ROOT"
PYTHONPATH_BASE="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show help
show_help() {
    cat << EOF
CoSA Framework Smoke Test Suite

USAGE:
    $0 [OPTIONS]

DESCRIPTION:
    Runs comprehensive CoSA framework smoke tests for all components.
    Designed for pre/post v000 deprecation validation to detect regressions.

OPTIONS:
    --pre-deprecation       Run as pre-deprecation baseline (saves results for comparison)
    --post-deprecation      Run as post-deprecation validation (compares with baseline)  
    --category CATEGORY     Run only specific category: core, agents, rest, training, integration
    --quick                 Run quick subset of critical tests (under 2 minutes)
    --baseline-update       Update performance baselines with current results
    --help                  Show this help message

EXAMPLES:
    $0                          # Run all smoke tests
    $0 --quick                  # Run quick test subset
    $0 --category agents        # Run only agent tests
    $0 --pre-deprecation        # Save baseline before v000 deprecation work
    $0 --post-deprecation       # Validate after v000 deprecation work

REQUIREMENTS:
    - Python 3.7+ with CoSA framework dependencies
    - CoSA framework properly configured
    - PYTHONPATH includes CoSA framework directory
    - All quick_smoke_test() functions available in CoSA modules

FILES:
    Configuration: $CONFIG_FILE
    Test Runner:   $RUNNER_SCRIPT
    
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
    local required_dirs=("agents" "config" "utils" "memory" "rest")
    for dir in "${required_dirs[@]}"; do
        if [ ! -d "$COSA_ROOT/$dir" ]; then
            log_error "Required CoSA directory missing: $COSA_ROOT/$dir"
            return 1
        fi
    done
    
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

# Function to check test infrastructure
check_test_infrastructure() {
    log_info "Checking test infrastructure..."
    
    # Check if test files exist
    if [ ! -f "$RUNNER_SCRIPT" ]; then
        log_error "Test runner not found: $RUNNER_SCRIPT"
        return 1
    fi
    
    # Check if test utilities exist
    local utils_file="$SMOKE_TEST_DIR/infrastructure/test_utilities.py"
    if [ ! -f "$utils_file" ]; then
        log_error "Test utilities not found: $utils_file"
        return 1
    fi
    
    # Configuration file is optional - will be created if missing
    if [ ! -f "$CONFIG_FILE" ]; then
        log_warning "Configuration file not found: $CONFIG_FILE"
        log_info "Will use default configuration"
    fi
    
    log_success "Test infrastructure is ready"
    return 0
}

# Function to run smoke tests
run_smoke_tests() {
    local args=("$@")
    
    log_info "Starting CoSA Framework Smoke Test Suite..."
    log_info "Test Directory: $SMOKE_TEST_DIR"
    log_info "CoSA Root: $COSA_ROOT"
    log_info "Configuration: $CONFIG_FILE"
    
    # Change to the infrastructure directory so imports work correctly
    cd "$SMOKE_TEST_DIR/infrastructure" || {
        log_error "Failed to change to test directory"
        return 1
    }
    
    # Run the test suite
    local python_cmd="python3"
    if ! command -v python3 >/dev/null 2>&1; then
        python_cmd="python"
    fi
    
    log_info "Executing: $python_cmd cosa_smoke_runner.py ${args[*]}"
    
    # Run with explicit error handling
    if $python_cmd cosa_smoke_runner.py "${args[@]}"; then
        log_success "Smoke tests completed successfully"
        return 0
    else
        local exit_code=$?
        log_error "Smoke tests failed with exit code $exit_code"
        return $exit_code
    fi
}

# Function to save baseline results (for pre-deprecation)
save_baseline() {
    log_info "Saving baseline for v000 deprecation comparison..."
    
    # The test runner will handle baseline saving with --save-baseline flag
    # This creates detailed performance and functional baselines
    log_success "Baseline saved by test runner"
    log_info "Use --post-deprecation after making v000 changes to detect regressions"
}

# Function to compare with baseline (for post-deprecation)
compare_baseline() {
    log_info "Baseline comparison completed by test runner"
    
    # The test runner handles baseline comparison with --compare-baseline flag
    # Results are displayed in the test output above
    local baseline_file="$SMOKE_TEST_DIR/config/baselines/latest_baseline.json"
    
    if [ -f "$baseline_file" ]; then
        local baseline_time=$(grep -o '"timestamp":"[^"]*' "$baseline_file" | cut -d'"' -f4)
        log_info "Compared against baseline from: $baseline_time"
    else
        log_warning "No baseline file found - comparison may not have been possible"
    fi
}

# Main execution function
main() {
    local run_mode="normal"
    local test_category=""
    local runner_args=()
    local quick_mode=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --pre-deprecation)
                run_mode="pre-deprecation"
                shift
                ;;
            --post-deprecation)
                run_mode="post-deprecation"
                shift
                ;;
            --category)
                test_category="$2"
                runner_args+=("--category" "$2")
                shift 2
                ;;
            --quick)
                quick_mode=true
                shift
                ;;
            --baseline-update)
                runner_args+=("--baseline-update")
                shift
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
    
    # Show header
    echo "=================================================================================="
    echo "               CoSA Framework Smoke Test Suite"
    echo "=================================================================================="
    echo "Mode: $run_mode"
    echo "CoSA Root: $COSA_ROOT"
    echo "Time: $(date)"
    echo "=================================================================================="
    
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
    
    if ! check_test_infrastructure; then
        log_error "Test infrastructure is incomplete"
        log_info "Some test components may not be implemented yet"
        # Don't exit - allow partial testing during development
    fi
    
    log_success "Pre-flight checks completed"
    echo ""
    
    # Configure runner args based on mode
    if [ "$quick_mode" = true ]; then
        log_info "Running in quick mode (critical tests only)"
        runner_args+=("--quick")
    fi
    
    # Add baseline flags based on mode
    case $run_mode in
        "pre-deprecation")
            runner_args+=("--save-baseline")
            log_info "Will save baseline for future comparison"
            ;;
        "post-deprecation")
            runner_args+=("--compare-baseline")
            log_info "Will compare results with saved baseline"
            ;;
    esac
    
    # Run the tests
    local start_time=$(date +%s)
    
    if run_smoke_tests "${runner_args[@]}"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        log_success "Smoke test suite completed in ${duration}s"
        
        # Handle post-test actions based on mode
        case $run_mode in
            "pre-deprecation")
                save_baseline
                log_info "Ready to begin v000 deprecation work. Run with --post-deprecation after changes."
                ;;
            "post-deprecation")
                compare_baseline
                log_info "v000 deprecation validation complete."
                ;;
            *)
                log_info "Test execution complete."
                ;;
        esac
        
        exit 0
    else
        local exit_code=$?
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        
        log_error "Smoke test suite failed after ${duration}s"
        
        if [ "$run_mode" = "post-deprecation" ]; then
            log_error "v000 deprecation validation failed - consider reverting changes"
        fi
        
        exit $exit_code
    fi
}

# Execute main function with all arguments
main "$@"