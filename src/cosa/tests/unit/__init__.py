"""
CoSA Framework Unit Test Suite

Self-contained unit testing framework for CoSA components with comprehensive
mocking of external dependencies to enable reliable CICD pipeline execution.

This package provides:
- Isolated unit tests with zero external service dependencies
- Comprehensive mocking framework for APIs, file systems, and databases
- Fast execution suitable for continuous integration
- Tiered testing approach by component criticality

Usage:
    # Run all unit tests
    ./tests/unit/scripts/run-cosa-unit-tests.sh
    
    # Run specific tier
    ./tests/unit/scripts/run-cosa-unit-tests.sh --category core
    
    # Run in CI mode
    ./tests/unit/scripts/run-cosa-unit-tests.sh --ci-mode
"""