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

# --no-git is LOAD-BEARING, not a speed knob (fixed 2026-08-24, row a3c23605).
# `gitleaks detect` without it scans GIT HISTORY — on 2026-08-24 that meant 3529
# commits and 9 findings, none of which could ever reach an image: history is not
# the build context. What ships is the WORKING TREE minus .dockerignore, and that
# is what this gate exists to guard, per the header above. Scanning history instead
# made the gate fail every build while never once looking at what Docker copies.
echo "🔍 secret-scan gate: scanning build context '$SCAN_PATH' with gitleaks (--no-git)..."
if gitleaks detect --source "$SCAN_PATH" --no-git --no-banner --redact; then
    echo "✓ secret-scan gate passed"
else
    echo "❌ SECRET-SCAN GATE FAILED — secrets detected; build aborted"
    exit 1
fi
