#!/bin/bash
#
# Test Container Startup Script
#
# Differences from run-fastapi-lupin.sh (dev):
#   1. Seeds companion credentials from dev DB into test DB before starting
#   2. Does NOT source ~/.lora_env (test container doesn't need LoRA paths)
#   3. LUPIN_ENV=testing set via docker-compose environment block
#   4. uvicorn starts with reload=False (LUPIN_ENV=testing triggers the
#      is_production_or_test check in main.py)
#
# Created: 2026-04-12 Session 248e740e (dual-container architecture)

cd /var/lupin/src

# Seed companion credentials from dev DB into test DB (idempotent, <100ms)
python3 scripts/seed_test_companions.py

# Source test environment credentials (for scheduled test jobs that run
# inside this container and need LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* vars)
[ -f /home/rruiz/.lupin/test-env.sh ] && source /home/rruiz/.lupin/test-env.sh

# Start FastAPI (LUPIN_ENV=testing set by docker-compose env block)
python3 -m lupin_app.main
