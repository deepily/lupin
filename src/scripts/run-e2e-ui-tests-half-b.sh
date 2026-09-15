#!/bin/bash
#
# Half B of the E2E UI suite (row 2818dad7): the files in src/tests/e2e_ui/partition/half-b.txt.
# Registered in TestSuiteJob as the suite "e2e_b", because SUITE_SCRIPTS maps a suite name to a
# script path and has no room for arguments. Every other argument passes through unchanged.
#
# `exec`, not a plain call: TestSuiteJob's timeout signals the process it started (bug 8b93bcf5).
# A wrapper that stayed alive would take that signal while the real runner kept going.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec bash "$SCRIPT_DIR/run-e2e-ui-tests.sh" --half b "$@"
