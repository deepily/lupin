#!/bin/bash
#################################################################
# secret-scan-gate.sh
#
# HARD GATE: aborts (non-zero exit) if any high-entropy / known-key
# pattern is detected in the build context. Wired as the FIRST step of
# cloud-run-build.sh (before `docker build`) so no image carrying a
# plaintext secret can be built and pushed to a remote registry.
#
# Tool: gitleaks (fast, CI-friendly, pattern + entropy). Install:
#   https://github.com/gitleaks/gitleaks  (e.g. `brew install gitleaks`
#   or download a release binary).
#
# Usage:
#   ./src/scripts/secret-scan-gate.sh [scan-path]   # default: repo root
#################################################################

set -e

SCAN_PATH="${1:-.}"

if ! command -v gitleaks > /dev/null 2>&1; then
    echo "❌ SECRET-SCAN GATE: gitleaks not installed — cannot verify the build context is secret-free."
    echo "   Install gitleaks (https://github.com/gitleaks/gitleaks) before building for a remote registry."
    exit 1
fi

echo "🔍 secret-scan gate: scanning '$SCAN_PATH' with gitleaks..."
if gitleaks detect --source "$SCAN_PATH" --no-banner --redact; then
    echo "✓ secret-scan gate passed"
else
    echo "❌ SECRET-SCAN GATE FAILED — secrets detected; build aborted"
    exit 1
fi
