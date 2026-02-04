#!/bin/bash
# WebSocket Smoke Test Suite Master Script
# 
# Runs comprehensive WebSocket smoke tests against the FastAPI server on localhost:7999
# Designed to be run before and after polish sessions to detect regressions
#
# Usage:
#   ./run-websocket-smoke-tests.sh [options]
#
# Options:
#   --pre-polish     Run as pre-polish baseline test
#   --post-polish    Run as post-polish validation test
#   --category CATEGORY  Run only specific category (core, integration, performance, load)
#   --quick          Run quick subset of tests (under 2 minutes)
#   --help           Show this help message

set -e  # Exit on any error

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SMOKE_TEST_DIR="$PROJECT_ROOT/tests/websocket_smoke"
RUNNER_SCRIPT="$SMOKE_TEST_DIR/infrastructure/smoke_test_runner.py"
CONFIG_FILE="$SMOKE_TEST_DIR/config/smoke_test_config.ini"

# Server configuration
SERVER_URL="http://localhost:7999"
HEALTH_ENDPOINT="$SERVER_URL/health"

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
WebSocket Smoke Test Suite

USAGE:
    $0 [OPTIONS]

DESCRIPTION:
    Runs comprehensive WebSocket smoke tests against FastAPI server on localhost:7999.
    Designed for pre/post polish session validation to detect regressions.

OPTIONS:
    --pre-polish        Run as pre-polish baseline (saves results for comparison)
    --post-polish       Run as post-polish validation (compares with baseline)  
    --category CATEGORY Run only specific category: core, integration, performance, load
    --quick             Run quick subset of critical tests (under 2 minutes)
    --baseline-update   Update performance baselines with current results
    --help              Show this help message

EXAMPLES:
    $0                          # Run all smoke tests
    $0 --quick                  # Run quick test subset
    $0 --category core          # Run only core tests
    $0 --pre-polish             # Save baseline before polish work
    $0 --post-polish            # Validate after polish work

REQUIREMENTS:
    - FastAPI server running on http://localhost:7999
    - Python 3.7+ with asyncio, websockets, httpx packages
    - WebSocket endpoints /ws/queue/ and /ws/audio/ accessible
    - LUPIN_TEST_EMAIL and LUPIN_TEST_PASSWORD environment variables set

FILES:
    Configuration: $CONFIG_FILE
    Test Runner:   $RUNNER_SCRIPT
    
EOF
}

# Function to check if server is running
check_server_health() {
    log_info "Checking FastAPI server health at $SERVER_URL..."
    
    if command -v curl >/dev/null 2>&1; then
        # Use curl if available
        if curl -s -f "$HEALTH_ENDPOINT" >/dev/null; then
            log_success "Server is healthy and responding"
            return 0
        else
            log_error "Server health check failed"
            return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        # Use wget as fallback
        if wget -q --spider "$HEALTH_ENDPOINT"; then
            log_success "Server is healthy and responding"
            return 0
        else
            log_error "Server health check failed"
            return 1
        fi
    else
        log_warning "Neither curl nor wget available - skipping health check"
        log_warning "Assuming server is running on $SERVER_URL"
        return 0
    fi
}

# Function to check test credentials
check_test_credentials() {
    log_info "Checking test credentials..."

    if [ -z "$LUPIN_TEST_EMAIL" ] || [ -z "$LUPIN_TEST_PASSWORD" ]; then
        log_error "Test credentials not set!"
        log_info "WebSocket tests require JWT authentication."
        log_info "Set these environment variables:"
        log_info "  export LUPIN_TEST_EMAIL='your@email.com'"
        log_info "  export LUPIN_TEST_PASSWORD='yourpassword'"
        return 1
    fi

    log_success "Test credentials configured (LUPIN_TEST_EMAIL=$LUPIN_TEST_EMAIL)"
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

    # Check required packages
    local missing_packages=()

    if ! $PYTHON_CMD -c "import asyncio" 2>/dev/null; then
        missing_packages+=("asyncio")
    fi

    if ! $PYTHON_CMD -c "import websockets" 2>/dev/null; then
        missing_packages+=("websockets")
    fi

    if ! $PYTHON_CMD -c "import httpx" 2>/dev/null; then
        missing_packages+=("httpx")
    fi

    if [ ${#missing_packages[@]} -eq 0 ]; then
        log_success "All Python dependencies available"
        return 0
    else
        log_error "Missing Python packages: ${missing_packages[*]}"
        log_info "Install with: pip install ${missing_packages[*]}"
        return 1
    fi
}

# Function to check test infrastructure
check_test_infrastructure() {
    log_info "Checking test infrastructure..."
    
    # Check if test files exist
    if [ ! -f "$RUNNER_SCRIPT" ]; then
        log_error "Test runner not found: $RUNNER_SCRIPT"
        return 1
    fi
    
    if [ ! -f "$CONFIG_FILE" ]; then
        log_error "Configuration file not found: $CONFIG_FILE"
        return 1
    fi
    
    # Check if test utilities exist
    local utils_file="$SMOKE_TEST_DIR/infrastructure/test_utilities.py"
    if [ ! -f "$utils_file" ]; then
        log_error "Test utilities not found: $utils_file"
        return 1
    fi
    
    log_success "Test infrastructure is complete"
    return 0
}

# Function to run smoke tests
run_smoke_tests() {
    local args=("$@")

    log_info "Starting WebSocket Smoke Test Suite..."
    log_info "Test Directory: $SMOKE_TEST_DIR"
    log_info "Configuration: $CONFIG_FILE"

    # Set up Python path for proper module imports
    export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

    # JWT authentication is used - credentials from LUPIN_TEST_EMAIL/PASSWORD env vars
    # No longer using AUTH_MODE=mock as server runs in JWT mode

    # Run the test suite as a module from project root
    local python_cmd="python3"
    if ! command -v python3 >/dev/null 2>&1; then
        python_cmd="python"
    fi

    cd "$PROJECT_ROOT" || {
        log_error "Failed to change to src directory"
        return 1
    }

    log_info "Executing: $python_cmd -m tests.websocket_smoke.infrastructure.smoke_test_runner ${args[*]}"

    # Run with explicit error handling
    if $python_cmd -m tests.websocket_smoke.infrastructure.smoke_test_runner "${args[@]}"; then
        log_success "Smoke tests completed successfully"
        return 0
    else
        local exit_code=$?
        log_error "Smoke tests failed with exit code $exit_code"
        return $exit_code
    fi
}

# Function to save baseline results (for pre-polish)
save_baseline() {
    log_info "Saving baseline for future comparison..."
    
    # The test runner will handle baseline saving with --save-baseline flag
    # This creates detailed performance and functional baselines
    log_success "Baseline saved by test runner"
    log_info "Use --post-polish after making changes to detect regressions"
}

# Function to compare with baseline (for post-polish)
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
            --pre-polish)
                run_mode="pre-polish"
                shift
                ;;
            --post-polish)
                run_mode="post-polish"
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
    echo "               WebSocket Smoke Test Suite"
    echo "=================================================================================="
    echo "Mode: $run_mode"
    echo "Server: $SERVER_URL"
    echo "Time: $(date)"
    echo "=================================================================================="
    
    # Pre-flight checks
    log_info "Running pre-flight checks..."

    if ! check_test_credentials; then
        log_error "Test credentials not configured"
        exit 1
    fi

    if ! check_server_health; then
        log_error "Server is not healthy. Please start the FastAPI server on port 7999"
        log_info "Run: cd src && python -m uvicorn fastapi_app.main:app --port 7999"
        exit 1
    fi

    if ! check_python_deps; then
        log_error "Python dependencies not satisfied"
        exit 1
    fi

    if ! check_test_infrastructure; then
        log_error "Test infrastructure is incomplete"
        exit 1
    fi
    
    log_success "All pre-flight checks passed"
    echo ""
    
    # Configure runner args based on mode
    if [ "$quick_mode" = true ]; then
        log_info "Running in quick mode (critical tests only)"
        # TODO: Add quick mode configuration
    fi
    
    # Add baseline flags based on mode
    case $run_mode in
        "pre-polish")
            runner_args+=("--save-baseline")
            log_info "Will save baseline for future comparison"
            ;;
        "post-polish")
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
            "pre-polish")
                save_baseline
                log_info "Ready to begin polish work. Run with --post-polish after changes."
                ;;
            "post-polish")
                compare_baseline
                log_info "Polish validation complete."
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
        
        if [ "$run_mode" = "post-polish" ]; then
            log_error "Polish validation failed - consider reverting changes"
        fi
        
        exit $exit_code
    fi
}

# Execute main function with all arguments
main "$@"