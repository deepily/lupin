#!/bin/bash
# Lupin Unified Smoke Test Runner
# 
# Orchestrates all smoke testing for the Lupin project by calling existing test scripts
# and adding new test categories for comprehensive coverage
#
# Usage:
#   ./run-lupin-smoke-tests.sh [options]
#
# Options:
#   --category CATEGORY  Run only specific category (websockets, basic, notifications, audio, queues, filtering, all)
#   --quick              Run quick subset of critical tests (under 2 minutes)
#   --pre-polish         Run as pre-polish baseline test
#   --post-polish        Run as post-polish validation test
#   --help               Show this help message

set -e  # Exit on any error

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Shared venv-pytest resolution — never a bare `python3 -m pytest` (rows c98bce3f,
# fc74c1d4). Sourced here so run_filtering_tests can call resolve_venv_pytest.
source "$PROJECT_ROOT/src/scripts/lib/resolve-venv-pytest.sh"
TESTS_DIR="$SCRIPT_DIR"

# Existing test script paths
WEBSOCKET_TESTS="$PROJECT_ROOT/src/scripts/run-websocket-smoke-tests.sh"
BASIC_TESTS="$TESTS_DIR/smoke_test.sh"

# New test category paths (to be implemented)
LUPIN_SMOKE_DIR="$TESTS_DIR/lupin_smoke"
NOTIFICATIONS_TESTS="$LUPIN_SMOKE_DIR/test_notifications.py"
AUDIO_TESTS="$LUPIN_SMOKE_DIR/test_audio_tts.py"
QUEUE_TESTS="$LUPIN_SMOKE_DIR/test_queue_workflow.py"
# The one pytest-SHAPED file in this directory. It is driven by pytest rather
# than as a script, and until row e5e964f4 this runner named the other three
# and never touched it — so its tests ran nowhere routinely.
FILTERING_TESTS="$LUPIN_SMOKE_DIR/test_queue_filtering_smoke.py"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
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

log_category() {
    echo -e "${CYAN}[CATEGORY]${NC} $1"
}

# Function to show help
show_help() {
    cat << EOF
Lupin Unified Smoke Test Runner

USAGE:
    $0 [OPTIONS]

DESCRIPTION:
    Orchestrates comprehensive smoke testing for the Lupin project by running
    existing test scripts and new test categories. Provides unified interface
    and reporting for all smoke testing needs.

OPTIONS:
    --category CATEGORY     Run only specific category:
                           • websockets  - WebSocket functionality (existing)
                           • basic       - Basic FastAPI endpoints (existing) 
                           • notifications - Notification system tests (new)
                           • audio       - TTS/Audio streaming tests (new)
                           • queues      - Job queue workflow tests (new)
                           • all         - Run all categories (default)
    
    --quick                 Run quick subset of critical tests (under 2 minutes)
    --pre-polish           Run as pre-polish baseline (saves results for comparison)
    --post-polish          Run as post-polish validation (compares with baseline)
    --help                 Show this help message

EXAMPLES:
    $0                              # Run all smoke tests
    $0 --category websockets        # Run only WebSocket tests
    $0 --category notifications     # Run only notification tests
    $0 --quick                      # Run quick critical tests only
    $0 --pre-polish                 # Save baseline before polish work
    $0 --post-polish                # Validate after polish work

REQUIREMENTS:
    - FastAPI server running on http://localhost:7999
    - Python 3.7+ with asyncio, websockets, httpx packages
    - Existing WebSocket smoke test infrastructure

TEST CATEGORIES:
    websockets     - Connection, authentication, sessions, events
    basic          - Health checks, API endpoints, simple validation
    notifications  - Notification API, queue operations, WebSocket delivery
    audio          - TTS endpoints, audio streaming, caching
    queues         - Job lifecycle, state transitions, completion events

FILES:
    Existing Tests: $WEBSOCKET_TESTS
                   $BASIC_TESTS
    New Tests:     $LUPIN_SMOKE_DIR/

EOF
}

# Function to check if server is running
check_server_health() {
    log_info "Checking FastAPI server health at http://localhost:7999..."
    
    if command -v curl >/dev/null 2>&1; then
        if curl -s -f "http://localhost:7999/health" >/dev/null; then
            log_success "Server is healthy and responding"
            return 0
        else
            log_error "Server health check failed"
            return 1
        fi
    else
        log_warning "curl not available - skipping health check"
        log_warning "Assuming server is running on http://localhost:7999"
        return 0
    fi
}

# Function to run WebSocket tests
run_websocket_tests() {
    log_category "Running WebSocket Smoke Tests"
    
    if [ ! -f "$WEBSOCKET_TESTS" ]; then
        log_error "WebSocket test script not found: $WEBSOCKET_TESTS"
        return 1
    fi
    
    # Pass through any additional arguments
    if "$WEBSOCKET_TESTS" "$@"; then
        log_success "WebSocket tests completed successfully"
        return 0
    else
        log_error "WebSocket tests failed"
        return 1
    fi
}

# Function to run basic FastAPI tests
run_basic_tests() {
    log_category "Running Basic FastAPI Smoke Tests"
    
    if [ ! -f "$BASIC_TESTS" ]; then
        log_error "Basic test script not found: $BASIC_TESTS"
        return 1
    fi
    
    if "$BASIC_TESTS" "$@"; then
        log_success "Basic tests completed successfully"
        return 0
    else
        log_error "Basic tests failed"
        return 1
    fi
}

# Function to run notification tests
run_notification_tests() {
    log_category "Running Notification System Tests"
    
    if [ ! -f "$NOTIFICATIONS_TESTS" ]; then
        log_error "Notification tests missing: $NOTIFICATIONS_TESTS"
        return 1
    fi
    
    # Run the test
    if python3 "$NOTIFICATIONS_TESTS"; then
        log_success "Notification tests completed successfully"
        return 0
    else
        log_error "Notification tests failed"
        return 1
    fi
}

# Function to run audio/TTS tests
run_audio_tests() {
    log_category "Running Audio/TTS System Tests"
    
    if [ ! -f "$AUDIO_TESTS" ]; then
        log_error "Audio tests missing: $AUDIO_TESTS"
        return 1
    fi
    
    # Run the test
    if python3 "$AUDIO_TESTS"; then
        log_success "Audio tests completed successfully"
        return 0
    else
        log_error "Audio tests failed"
        return 1
    fi
}

# Function to run queue workflow tests
run_queue_tests() {
    log_category "Running Job Queue Workflow Tests"
    
    if [ ! -f "$QUEUE_TESTS" ]; then
        log_error "Queue tests missing: $QUEUE_TESTS"
        return 1
    fi
    
    # Run the test
    if python3 "$QUEUE_TESTS"; then
        log_success "Queue tests completed successfully"
        return 0
    else
        log_error "Queue tests failed"
        return 1
    fi
}

# Function to run queue-filtering tests (pytest-shaped, not a script)
run_filtering_tests() {
    log_category "Running Queue Filtering Tests"

    if [ ! -f "$FILTERING_TESTS" ]; then
        log_error "Queue filtering tests missing: $FILTERING_TESTS"
        return 1
    fi

    # This file declares ordinary pytest functions, so it is RUN BY PYTEST —
    # invoking it as a script would execute nothing and exit 0, which is the
    # same silent-pass shape row e5e964f4 exists to close.
    #
    # And it must be the VENV pytest, not a bare python3: an under-provisioned
    # interpreter under-collects and the reduced count gets reported as the whole
    # suite (rows c98bce3f, fc74c1d4). This script was the sixth runner carrying the
    # fallback and was found by the property test, not by grep — see
    # src/tests/unit/test_runner_venv_pytest_guard.py.
    resolve_venv_pytest || return $?
    if "$PYTEST" "$FILTERING_TESTS" -q --no-header; then
        log_success "Queue filtering tests completed successfully"
        return 0
    else
        log_error "Queue filtering tests failed"
        return 1
    fi
}

# Function to run all test categories
run_all_tests() {
    local failed_categories=()
    local total_categories=0
    local passed_categories=0
    
    log_info "Running all Lupin smoke test categories..."
    echo ""
    
    # Run each category and track results
    categories=("websockets" "basic" "notifications" "audio" "queues" "filtering")
    
    for category in "${categories[@]}"; do
        total_categories=$((total_categories + 1))
        echo "=================================================================================="
        
        case $category in
            "websockets")
                if run_websocket_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("websockets")
                fi
                ;;
            "basic")
                if run_basic_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("basic")
                fi
                ;;
            "notifications")
                if run_notification_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("notifications")
                fi
                ;;
            "audio")
                if run_audio_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("audio")
                fi
                ;;
            "queues")
                if run_queue_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("queues")
                fi
                ;;
            "filtering")
                if run_filtering_tests "$@"; then
                    passed_categories=$((passed_categories + 1))
                else
                    failed_categories+=("filtering")
                fi
                ;;
        esac
        
        echo ""
    done
    
    # Summary report
    echo "=================================================================================="
    echo "                     Lupin Smoke Test Suite Summary"
    echo "=================================================================================="
    echo "Total Categories: $total_categories"
    echo "Passed: $passed_categories"
    echo "Failed: ${#failed_categories[@]}"
    echo ""
    
    if [ ${#failed_categories[@]} -eq 0 ]; then
        log_success "All test categories passed! 🎉"
        echo "✅ websockets    - WebSocket functionality"
        echo "✅ basic         - FastAPI endpoints"
        echo "✅ notifications - Notification system"
        echo "✅ audio         - TTS/Audio streaming"
        echo "✅ queues        - Job queue workflows"
        return 0
    else
        log_error "Some test categories failed:"
        for category in "${failed_categories[@]}"; do
            echo "❌ $category"
        done
        echo ""
        log_info "Passed categories:"
        for category in "${categories[@]}"; do
            if [[ ! " ${failed_categories[*]} " =~ " ${category} " ]]; then
                echo "✅ $category"
            fi
        done
        return 1
    fi
}

# Function to run quick tests only
run_quick_tests() {
    log_info "Running quick smoke tests (critical functionality only)..."
    
    # For quick mode, run a subset of each category
    local failed_tests=()
    
    echo "=================================================================================="
    log_category "Quick WebSocket Test"
    if run_websocket_tests --quick; then
        log_success "Quick WebSocket test passed"
    else
        failed_tests+=("websockets")
        log_error "Quick WebSocket test failed"
    fi
    
    echo ""
    echo "=================================================================================="
    log_category "Quick Basic Test"
    if run_basic_tests; then
        log_success "Quick basic test passed"
    else
        failed_tests+=("basic")
        log_error "Quick basic test failed"
    fi
    
    # Quick notification check (placeholder)
    echo ""
    echo "=================================================================================="
    log_category "Quick Notification Test"
    if run_notification_tests; then
        log_success "Quick notification test passed"
    else
        failed_tests+=("notifications")
        log_error "Quick notification test failed"
    fi
    
    # Summary
    echo ""
    echo "=================================================================================="
    echo "                     Quick Smoke Test Summary"
    echo "=================================================================================="
    
    if [ ${#failed_tests[@]} -eq 0 ]; then
        log_success "All quick tests passed! ⚡"
        return 0
    else
        log_error "Quick tests failed in: ${failed_tests[*]}"
        return 1
    fi
}

# Main execution function
main() {
    local category="all"
    local quick_mode=false
    local run_mode="normal"
    local additional_args=()
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --category)
                category="$2"
                shift 2
                ;;
            --quick)
                quick_mode=true
                shift
                ;;
            --pre-polish)
                run_mode="pre-polish"
                additional_args+=("--pre-polish")
                shift
                ;;
            --post-polish)
                run_mode="post-polish"
                additional_args+=("--post-polish")
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
    echo "                     Lupin Unified Smoke Test Runner"
    echo "=================================================================================="
    echo "Category: $category"
    echo "Mode: $run_mode"
    echo "Quick: $quick_mode"
    echo "Server: http://localhost:7999"
    echo "Time: $(date)"
    echo "=================================================================================="
    echo ""
    
    # Pre-flight checks
    log_info "Running pre-flight checks..."
    
    if ! check_server_health; then
        log_error "Server is not healthy. Please start the FastAPI server on port 7999"
        log_info "Run: cd src && python -m uvicorn lupin_app.main:app --port 7999"
        exit 1
    fi
    
    log_success "Pre-flight checks passed"
    echo ""
    
    # Run tests based on category and mode
    local start_time=$(date +%s)
    local success=false
    
    if [ "$quick_mode" = true ]; then
        if run_quick_tests "${additional_args[@]}"; then
            success=true
        fi
    else
        case $category in
            "websockets")
                if run_websocket_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "basic")
                if run_basic_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "notifications")
                if run_notification_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "audio")
                if run_audio_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "queues")
                if run_queue_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "filtering")
                if run_filtering_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            "all")
                if run_all_tests "${additional_args[@]}"; then
                    success=true
                fi
                ;;
            *)
                log_error "Unknown category: $category"
                log_info "Valid categories: websockets, basic, notifications, audio, queues, filtering, all"
                exit 1
                ;;
        esac
    fi
    
    # Final results
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo ""
    echo "=================================================================================="
    
    if [ "$success" = true ]; then
        log_success "Lupin smoke tests completed successfully in ${duration}s! 🎉"
        echo ""
        echo "✅ All tests passed"
        echo "⚡ System is healthy and ready for development"
        echo ""
        
        if [ "$run_mode" = "pre-polish" ]; then
            log_info "Baseline saved. You can now begin polish work."
            log_info "Run with --post-polish after making changes to validate."
        elif [ "$run_mode" = "post-polish" ]; then
            log_info "Polish validation complete. Changes look good!"
        fi
        
        exit 0
    else
        log_error "Lupin smoke tests failed after ${duration}s"
        echo ""
        echo "❌ Some tests failed"
        echo "🔧 Check the output above for specific failures"
        echo ""
        
        if [ "$run_mode" = "post-polish" ]; then
            log_warning "Polish validation failed - consider reviewing changes"
        fi
        
        exit 1
    fi
}

# Execute main function with all arguments
main "$@"