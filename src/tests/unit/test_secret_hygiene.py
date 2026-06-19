"""
Unit tests for Phase-1 secret hygiene (Fix 2a image-exclusion + Fix 2d scan gate).

Regression locks that fail CI the instant someone re-adds the key bake or moves
the secret-scan gate after the build. Pure string/ordering assertions — no Docker,
no gcloud, no live gitleaks. :7999-eligible / AI-discretionary.
"""
import os
import re

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()


def _read( rel_path ):
    with open( os.path.join( PROJECT_ROOT, rel_path ), "r" ) as f:
        return f.read()


def test_dockerignore_excludes_keys():
    text = _read( ".dockerignore" )
    assert "src/conf/keys/" in text


def test_dockerfile_has_no_keys_copy():
    """The COPY src/conf/keys bake must be gone (the real image-layer leak vector)."""
    text = _read( "docker/lupin/Dockerfile" )
    copy_keys = re.compile( r"^\s*COPY\b.*src/conf/keys", re.MULTILINE )
    assert copy_keys.search( text ) is None


def test_secret_scan_gate_runs_before_docker_build():
    """The scan gate must be invoked before the `docker build` COMMAND so it cannot be skipped."""
    text = _read( "src/scripts/cloud-run-build.sh" )
    gate_idx   = text.find( "secret-scan-gate.sh" )
    # Match the command at line-start (not the prose comment that mentions "docker build").
    build_match = re.search( r"^docker build\b", text, re.MULTILINE )
    assert gate_idx != -1,   "secret-scan-gate.sh invocation not found in cloud-run-build.sh"
    assert build_match,      "docker build command not found in cloud-run-build.sh"
    assert gate_idx < build_match.start(), "secret-scan gate must run BEFORE the docker build command"


def test_secret_scan_gate_script_fails_loud_without_gitleaks():
    """The gate script aborts (exit 1) rather than silently passing when gitleaks is absent."""
    text = _read( "src/scripts/secret-scan-gate.sh" )
    assert "command -v gitleaks" in text
    assert "exit 1" in text
