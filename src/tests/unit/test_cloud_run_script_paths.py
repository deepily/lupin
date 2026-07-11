"""
Unit tests for the LUPIN_ROOT path-drift fix in the deploy scripts (Phase-1 Fix 1).

Pure string assertions on script + Dockerfile contents — no gcloud, no Docker.
:7999-eligible / AI-discretionary. These are the regression locks that fail CI
in milliseconds instead of as a cryptic Cloud Run boot crash.
"""
import os

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()


def _read( rel_path ):
    with open( os.path.join( PROJECT_ROOT, rel_path ), "r" ) as f:
        return f.read()


# NOTE (2026-07-11, Rio): test_deploy_script_uses_var_lupin_root removed —
# src/scripts/cloud-run-deploy.sh was retired (monolith-on-Cloud-Run path, Rick
# ruled; triggered by audit finding F1). The build script + Dockerfile checks below
# remain the live regression locks.


def test_build_script_uses_var_lupin_root():
    text = _read( "src/scripts/cloud-run-build.sh" )
    assert "LUPIN_ROOT=/app" not in text
    assert "LUPIN_ROOT=/var/lupin" in text


def test_dockerfile_config_mgr_args_are_project_root_relative():
    # config_path / splainer_path are PROJECT-ROOT-RELATIVE (start "/src/…"): the
    # ConfigurationManager prepends get_project_root() (LUPIN_ROOT=/var/lupin) at
    # runtime (configuration_manager.py:147). An ABSOLUTE "/var/lupin/src/conf/…"
    # baked here double-prefixes to "/var/lupin/var/lupin/src/conf/…" → boot-time
    # AssertionError — the exact GCP boot crash commit c2b02065 (d57f38bd) fixed by
    # reverting the baked default to the relative form. The pre-d57f38bd absolute
    # expectation WAS the bug (born alongside it in 53fef419); do NOT regress this
    # assertion back to it. (Bug 490fe5db was mis-titled "Dockerfile drift"; the
    # Dockerfile is correct and this stale test was the actual defect.)
    text = _read( "docker/lupin/Dockerfile" )
    assert "LUPIN_CONFIG_MGR_CLI_ARGS=" in text
    assert "config_path=/src/conf/" in text
    assert "config_path=/var/lupin/src/conf/" not in text
