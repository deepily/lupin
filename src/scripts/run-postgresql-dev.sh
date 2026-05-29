#!/bin/bash
#
# PostgreSQL Development Container Startup Script
#
# Features:
# - Validates LUPIN_ROOT environment variable
# - Starts PostgreSQL container via docker-compose if not running
# - Creates test database (lupin_db_test) if missing
# - Applies schema to test database
# - Idempotent (safe to run multiple times)
# - Works from any directory (aliasable)
#
# Usage:
#   ./src/scripts/run-postgresql-dev.sh
#
# Requirements:
#   - LUPIN_ROOT environment variable must be set
#   - Docker and docker-compose installed
#   - docker-compose.yml in LUPIN_ROOT directory
#
# Example alias:
#   export LUPIN_ROOT="/mnt/DATA01/include/www.deepily.ai/projects/lupin"
#   alias lupin-db="$LUPIN_ROOT/src/scripts/run-postgresql-dev.sh"
#

set -e  # Exit on error

# ============================================================
# Configuration
# ============================================================
CONTAINER_NAME="lupin-postgres"
DB_USER="lupin_dev"
DB_PASSWORD="dev_password"
DB_NAME="lupin_db_dev"
TEST_DB_NAME="lupin_db_test"
MAX_WAIT=30  # Maximum seconds to wait for PostgreSQL startup

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================
# Logging Functions
# ============================================================
log_info()    { echo -e "${BLUE}[POSTGRES]${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error()   { echo -e "${RED}✗${NC} $1"; }

# ============================================================
# LUPIN_ROOT Validation
# ============================================================
validate_lupin_root() {
    if [ -z "$LUPIN_ROOT" ]; then
        echo ""
        log_error "LUPIN_ROOT environment variable not set"
        echo ""
        echo "Please set LUPIN_ROOT before running this script:"
        echo "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin"
        echo ""
        echo "Add to your ~/.bashrc or ~/.zshrc for persistence:"
        echo "  echo 'export LUPIN_ROOT=/path/to/lupin' >> ~/.bashrc"
        echo "  source ~/.bashrc"
        echo ""
        exit 1
    fi

    if [ ! -d "$LUPIN_ROOT" ]; then
        log_error "LUPIN_ROOT points to non-existent directory: $LUPIN_ROOT"
        exit 1
    fi

    if [ ! -f "$LUPIN_ROOT/docker-compose.yml" ]; then
        log_error "docker-compose.yml not found in LUPIN_ROOT: $LUPIN_ROOT"
        exit 1
    fi
}

# ============================================================
# Check if Container is Running
# ============================================================
check_container_running() {
    if docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "^$CONTAINER_NAME$"; then
        return 0  # Running
    else
        return 1  # Not running
    fi
}

# ============================================================
# Start PostgreSQL Container
# ============================================================
start_postgres_container() {
    log_info "Starting PostgreSQL container via docker-compose..."

    # Change to LUPIN_ROOT so docker compose finds its config
    cd "$LUPIN_ROOT"

    # Start postgres service in detached mode
    docker compose up -d postgres

    log_success "Container started"
}

# ============================================================
# Wait for PostgreSQL to be Ready
# ============================================================
wait_for_postgres() {
    log_info "Waiting for PostgreSQL to be ready..."

    local waited=0

    until docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" > /dev/null 2>&1; do
        sleep 1
        waited=$((waited + 1))

        if [ $waited -ge $MAX_WAIT ]; then
            log_error "PostgreSQL failed to start within $MAX_WAIT seconds"
            echo ""
            echo "Container logs:"
            docker logs "$CONTAINER_NAME" | tail -20
            echo ""
            exit 1
        fi

        # Check if container is still running
        if ! docker ps --filter "name=$CONTAINER_NAME" --format "{{.Names}}" | grep -q "^$CONTAINER_NAME$"; then
            log_error "Container died during startup"
            echo ""
            echo "Container logs:"
            docker logs "$CONTAINER_NAME" | tail -20
            echo ""
            exit 1
        fi
    done

    log_success "PostgreSQL ready (took ${waited}s)"
}

# ============================================================
# Check if Database Exists
# ============================================================
database_exists() {
    local db_name="$1"

    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -lqt | cut -d \| -f 1 | grep -qw "$db_name"
    return $?
}

# ============================================================
# Create Test Database
# ============================================================
create_test_database() {
    log_info "Checking if test database exists..."

    if database_exists "$TEST_DB_NAME"; then
        log_success "Test database '$TEST_DB_NAME' already exists"
        return 0
    fi

    log_info "Creating test database '$TEST_DB_NAME'..."

    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "CREATE DATABASE $TEST_DB_NAME" > /dev/null

    if [ $? -eq 0 ]; then
        log_success "Test database created"
    else
        log_error "Failed to create test database"
        exit 1
    fi
}

# ============================================================
# Check if Schema is Applied to Database
# ============================================================
schema_exists() {
    local db_name="$1"

    # Check if 'users' table exists (primary table from schema)
    local table_count=$(docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$db_name" -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='users'" 2>/dev/null || echo "0")

    if [ "$table_count" = "1" ]; then
        return 0  # Schema exists
    else
        return 1  # Schema missing
    fi
}

# ============================================================
# Apply Schema to Test Database
# ============================================================
apply_schema_to_test_db() {
    log_info "Checking if schema is applied to test database..."

    if schema_exists "$TEST_DB_NAME"; then
        log_success "Schema already applied to test database"
        return 0
    fi

    log_info "Applying schema to test database..."

    # Apply schema from mounted init script
    docker exec "$CONTAINER_NAME" psql -U "$DB_USER" -d "$TEST_DB_NAME" -f /docker-entrypoint-initdb.d/01-schema.sql > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        log_success "Schema applied to test database"
    else
        log_error "Failed to apply schema to test database"
        exit 1
    fi
}

# ============================================================
# Display Connection Info
# ============================================================
display_connection_info() {
    echo ""
    echo "================================================================"
    log_success "PostgreSQL Development Environment Ready"
    echo "================================================================"
    echo ""
    echo "Container:  $CONTAINER_NAME"
    echo "Host:       localhost"
    echo "Port:       5432"
    echo "User:       $DB_USER"
    echo "Password:   $DB_PASSWORD"
    echo ""
    echo "Databases:"
    echo "  • $DB_NAME        (development)"
    echo "  • $TEST_DB_NAME   (integration tests)"
    echo ""
    echo "Data Location:"
    echo "  /mnt/DATA01/include/www.deepily.ai/projects/lupin-data/postgresql-dev-data/"
    echo ""
    echo "Management:"
    echo "  • Stop:   docker compose down"
    echo "  • Logs:   docker logs $CONTAINER_NAME"
    echo "  • pgAdmin: http://localhost:5050 (dev@lupin.local / admin)"
    echo ""
}

# ============================================================
# Main Function
# ============================================================
main() {
    # Parse command-line flags
    FOLLOW_LOGS=true
    for arg in "$@"; do
        case $arg in
            --no-follow-logs)
                FOLLOW_LOGS=false
                shift
                ;;
        esac
    done

    echo "================================================================"
    echo "  Lupin PostgreSQL Development Server"
    echo "================================================================"
    echo ""

    # Validate environment
    validate_lupin_root

    # Check if container is already running
    if check_container_running; then
        log_info "Container already running"
    else
        start_postgres_container
        wait_for_postgres
    fi

    # Ensure test database exists and has schema
    create_test_database
    apply_schema_to_test_db

    # Display connection information
    display_connection_info

    # Follow container logs (unless --no-follow-logs flag is set)
    if [ "$FOLLOW_LOGS" = true ]; then
        echo "================================================================"
        echo "  Following PostgreSQL Container Logs"
        echo "================================================================"
        echo ""
        log_info "Press Ctrl+C to stop following logs"
        echo ""

        docker logs -f "$CONTAINER_NAME"
    fi
}

# ============================================================
# Execute Main
# ============================================================
main "$@"
