#!/bin/bash
# Opt-in coverage flags for the pytest tiers, shared so the frame is named ONCE.
#
# WHY THIS EXISTS (row e2099400, 2026-08-29). Until today NOTHING in the build asked
# for coverage: pytest.ini's addopts carried no --cov, no runner passed one, and
# TestSuiteJob injected none. So pyproject's `fail_under` was enforced only when a
# human typed --cov by hand, and every run of the merge pyramid computed no Python
# coverage at all. A gate nobody invokes is not a lenient gate; it is no gate.
#
# ⚠️ THE FLAG IS BARE `--cov`, WITH NO VALUE, AND THAT IS THE WHOLE POINT.
# `--cov=<path>` OVERRIDES pyproject's `source`, which would put the frame in two
# places and let them drift — on a row that exists because a frame silently measured
# less than it claimed, that is the last mistake to repeat. Bare `--cov` tells
# pytest-cov to use the config's own source list. Verified 2026-08-29: a bare --cov
# run reports exactly the seven configured packages with the same per-package file
# counts as an explicitly-flagged run.
#
# DEFAULT IS OFF. An ad-hoc `run-unit-tests.sh -k foo` must not silently produce a
# partial coverage number — a scoped run reporting a tier-wide figure is this row's
# own recurring defect (68.11% / 70.68% were produced exactly that way on 2026-08-29
# and had to be thrown out). Coverage turns on only when LUPIN_COVERAGE is set, which
# run-all-tests.sh does for the pyramid.
#
# NO PER-TIER FLOOR. Each tier passes --cov-fail-under=0 because no single tier can
# meet the whole-system floor: the unit tier ALONE measures ~70% against the full
# frame, since cosa's ~8,700 tests have not run yet. Enforcement belongs to
# run-coverage-gate.sh, after every tier has appended to one data file.

# Emit the coverage flags for a tier, or nothing at all when coverage is off.
#
# Requires:
#   - COVERAGE_FILE is exported by the caller when LUPIN_COVERAGE is set, so tiers
#     append to ONE isolated data file rather than the repo-root default
# Ensures:
#   - prints the flags on stdout, space separated, for word-splitting by the caller
#   - prints NOTHING when LUPIN_COVERAGE is unset or empty
#   - refuses, loudly and non-zero, when coverage is requested without an isolated
#     COVERAGE_FILE — a shared root .coverage lets a concurrent run silently re-scope
#     the measurement (measured 2026-08-26: one tier reported 96.59% green with
#     ~28,000 statements absent from the denominator)
coverage_opt_in_flags() {
    if [ -z "${LUPIN_COVERAGE:-}" ]; then
        return 0
    fi
    if [ -z "${COVERAGE_FILE:-}" ]; then
        echo "LUPIN_COVERAGE is set but COVERAGE_FILE is not." >&2
        echo "  Coverage tiers append to ONE data file; without an isolated path they" >&2
        echo "  write the repo-root .coverage, which any concurrent run erases at" >&2
        echo "  startup. Measured 2026-08-26: a tier reported 96.59% 'green' with" >&2
        echo "  ~28,000 statements silently outside the denominator." >&2
        echo "  Fix: export COVERAGE_FILE=<an isolated path> before running." >&2
        return 1
    fi
    # Bare --cov: use pyproject's `source`. Never --cov=<path> (see the note above).
    echo "--cov --cov-report= --cov-fail-under=0 --cov-append"
}
