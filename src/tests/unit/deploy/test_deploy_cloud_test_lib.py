"""
Unit tests for src/scripts/lib/deploy-cloud-test-lib.sh — the pure (VM-uncoupled)
helpers extracted from deploy-cloud-test.sh (task d8c699aa).

Strategy: source the bash lib in a subprocess and exercise each pure function
against a THROWAWAY git repo built per-test in a TemporaryDirectory. No gcloud,
no SSH, no Docker — :7999-eligible / AI-discretionary, runs in milliseconds.

Coverage note (100% mandate): bash line-coverage tooling (kcov/bashcov) is NOT
part of the Lupin pytest --cov / c8 gate, so the lib cannot be line-instrumented
here. Instead this suite asserts EVERY BRANCH of EVERY pure function
behaviorally — both returns of dctl_resolve_sha, all four arg cases + the two
error paths of dctl_parse_args, the empty-prev / code / deps branches of
dctl_detect_axis, both rc paths of dctl_check_clean, and the stamp/sanitize
transforms. The Python in this file is itself 100%-covered when the suite runs.
"""
import os
import subprocess

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
LIB_PATH     = os.path.join( PROJECT_ROOT, "src/scripts/lib/deploy-cloud-test-lib.sh" )
SCRIPT_PATH  = os.path.join( PROJECT_ROOT, "src/scripts/deploy-cloud-test.sh" )


def _run_lib( cwd, snippet ):
    """
    Source the lib (with the canonical dep-paths) and run a bash snippet in cwd.

    Requires:
        - cwd is a directory (typically a throwaway git repo)
        - snippet is a bash one-liner that calls the lib functions

    Ensures:
        - returns the CompletedProcess (stdout/stderr captured, text mode)
        - DCTL_DEP_PATHS is set BEFORE the source so the lib keeps our paths
    """
    full = (
        "set -uo pipefail; "
        "DCTL_DEP_PATHS=( pyproject.toml uv.lock ); "
        f"source '{LIB_PATH}'; "
        + snippet
    )
    return subprocess.run(
        [ "bash", "-c", full ],
        cwd=cwd, capture_output=True, text=True
    )


def _git( cwd, *args ):
    """Run a git command in cwd, raising on failure."""
    subprocess.run( [ "git", *args ], cwd=cwd, check=True,
                    capture_output=True, text=True )


def _make_repo( path ):
    """
    Build a throwaway git repo with src/, pyproject.toml, uv.lock and an
    initial commit. Returns the first commit's full SHA.
    """
    _git( path, "init", "-q" )
    _git( path, "config", "user.email", "test@lupin.local" )
    _git( path, "config", "user.name", "Test Harness" )
    os.makedirs( os.path.join( path, "src" ), exist_ok=True )
    _write( path, "src/app.py",       "print( 'v1' )\n" )
    _write( path, "pyproject.toml",   "[project]\nname='x'\ndependencies=[]\n" )
    _write( path, "uv.lock",          "# lock v1\n" )
    _git( path, "add", "-A" )
    _git( path, "commit", "-q", "-m", "c1" )
    return _rev( path, "HEAD" )


def _write( path, rel, text ):
    with open( os.path.join( path, rel ), "w" ) as f:
        f.write( text )


def _rev( path, ref ):
    out = subprocess.run( [ "git", "rev-parse", ref ], cwd=path,
                          check=True, capture_output=True, text=True )
    return out.stdout.strip()


# ----------------------------------------------------------------------------
# DCTL_DEP_PATHS default branch (sourced with the var UNSET)
# ----------------------------------------------------------------------------
def test_dep_paths_default_applied_when_unset( tmp_path ):
    # Source the lib WITHOUT pre-setting DCTL_DEP_PATHS so the lib's own
    # default-assignment branch runs; assert the canonical dep list is pinned.
    full = (
        "set -uo pipefail; unset DCTL_DEP_PATHS 2>/dev/null || true; "
        f"source '{LIB_PATH}'; "
        'printf "%s\\n" "${DCTL_DEP_PATHS[@]}"'
    )
    r = subprocess.run( [ "bash", "-c", full ], cwd=tmp_path,
                        capture_output=True, text=True )
    assert r.returncode == 0
    assert r.stdout.split() == [ "pyproject.toml", "uv.lock" ]


# ----------------------------------------------------------------------------
# dctl_parse_args
# ----------------------------------------------------------------------------
def test_parse_args_defaults( tmp_path ):
    r = _run_lib( tmp_path,
        'dctl_parse_args; echo "$REF $TAKE_DEPS $DRY_RUN $ALLOW_DIRTY"' )
    assert r.returncode == 0
    assert r.stdout.strip() == "HEAD 0 0 0"


def test_parse_args_all_flags( tmp_path ):
    r = _run_lib( tmp_path,
        'dctl_parse_args --ref abc123 --deps --dry-run --allow-dirty; '
        'echo "$REF $TAKE_DEPS $DRY_RUN $ALLOW_DIRTY"' )
    assert r.returncode == 0
    assert r.stdout.strip() == "abc123 1 1 1"


def test_parse_args_unknown_arg_returns_2( tmp_path ):
    r = _run_lib( tmp_path, 'dctl_parse_args --bogus; echo "rc=$?"' )
    assert "rc=2" in r.stdout
    assert "unknown arg" in r.stderr


def test_parse_args_ref_missing_value_returns_2( tmp_path ):
    r = _run_lib( tmp_path, 'dctl_parse_args --ref; echo "rc=$?"' )
    assert "rc=2" in r.stdout
    assert "needs a value" in r.stderr


# ----------------------------------------------------------------------------
# dctl_resolve_sha
# ----------------------------------------------------------------------------
def test_resolve_sha_valid_ref( tmp_path ):
    sha = _make_repo( tmp_path )
    r = _run_lib( tmp_path, 'dctl_resolve_sha HEAD' )
    assert r.returncode == 0
    assert r.stdout.strip() == sha
    assert len( r.stdout.strip() ) == 40


def test_resolve_sha_invalid_ref_returns_1( tmp_path ):
    _make_repo( tmp_path )
    r = _run_lib( tmp_path, 'dctl_resolve_sha not_a_real_ref; echo "rc=$?"' )
    # function returns 1 and echoes nothing for the bad ref
    assert "rc=1" in r.stdout
    assert r.stdout.strip() == "rc=1"


# ----------------------------------------------------------------------------
# dctl_sanitize_sha
# ----------------------------------------------------------------------------
def test_sanitize_sha_strips_non_hex( tmp_path ):
    r = _run_lib( tmp_path,
        "dctl_sanitize_sha 'ef36d243 2026-06-23T18:40Z code'" )
    # keeps only [0-9a-f]: 'ef36d243' + hex chars from the timestamp string
    out = r.stdout.strip()
    assert out.startswith( "ef36d243" )
    assert all( c in "0123456789abcdef" for c in out )


def test_sanitize_sha_empty_when_no_hex( tmp_path ):
    # Hex-free input: no [0-9a-f] anywhere (uppercase non-hex letters + symbols).
    r = _run_lib( tmp_path, "dctl_sanitize_sha 'GHIJK-LMNOP-XYZ!!!'" )
    assert r.stdout.strip() == ""


# ----------------------------------------------------------------------------
# dctl_detect_axis
# ----------------------------------------------------------------------------
def test_detect_axis_empty_prev_is_deps( tmp_path ):
    sha = _make_repo( tmp_path )
    r = _run_lib( tmp_path, f'dctl_detect_axis "" "{sha}"' )
    assert r.stdout.strip() == "deps"


def test_detect_axis_same_sha_is_code( tmp_path ):
    sha = _make_repo( tmp_path )
    r = _run_lib( tmp_path, f'dctl_detect_axis "{sha}" "{sha}"' )
    assert r.stdout.strip() == "code"


def test_detect_axis_src_only_change_is_code( tmp_path ):
    prev = _make_repo( tmp_path )
    _write( tmp_path, "src/app.py", "print( 'v2' )\n" )
    _git( tmp_path, "commit", "-aqm", "src-only" )
    sha = _rev( tmp_path, "HEAD" )
    r = _run_lib( tmp_path, f'dctl_detect_axis "{prev}" "{sha}"' )
    assert r.stdout.strip() == "code"


def test_detect_axis_dep_change_is_deps( tmp_path ):
    prev = _make_repo( tmp_path )
    _write( tmp_path, "pyproject.toml",
            "[project]\nname='x'\ndependencies=['firebase-admin']\n" )
    _git( tmp_path, "commit", "-aqm", "add-dep" )
    sha = _rev( tmp_path, "HEAD" )
    r = _run_lib( tmp_path, f'dctl_detect_axis "{prev}" "{sha}"' )
    assert r.stdout.strip() == "deps"


def test_detect_axis_uv_lock_change_is_deps( tmp_path ):
    prev = _make_repo( tmp_path )
    _write( tmp_path, "uv.lock", "# lock v2 changed\n" )
    _git( tmp_path, "commit", "-aqm", "bump-lock" )
    sha = _rev( tmp_path, "HEAD" )
    r = _run_lib( tmp_path, f'dctl_detect_axis "{prev}" "{sha}"' )
    assert r.stdout.strip() == "deps"


# ----------------------------------------------------------------------------
# dctl_check_clean
# ----------------------------------------------------------------------------
def test_check_clean_clean_tree_returns_0( tmp_path ):
    sha = _make_repo( tmp_path )
    r = _run_lib( tmp_path, f'dctl_check_clean "{sha}"; echo "rc=$?"' )
    assert "rc=0" in r.stdout


def test_check_clean_dirty_src_returns_1( tmp_path ):
    sha = _make_repo( tmp_path )
    _write( tmp_path, "src/app.py", "print( 'uncommitted' )\n" )
    r = _run_lib( tmp_path, f'dctl_check_clean "{sha}"; echo "rc=$?"' )
    assert "rc=1" in r.stdout


def test_check_clean_dirty_dep_returns_1( tmp_path ):
    sha = _make_repo( tmp_path )
    _write( tmp_path, "uv.lock", "# uncommitted lock churn\n" )
    r = _run_lib( tmp_path, f'dctl_check_clean "{sha}"; echo "rc=$?"' )
    assert "rc=1" in r.stdout


# ----------------------------------------------------------------------------
# dctl_compute_stamp
# ----------------------------------------------------------------------------
def test_compute_stamp_is_path_safe_and_ends_with_short( tmp_path ):
    sha = _make_repo( tmp_path )
    r = _run_lib( tmp_path, f'dctl_compute_stamp "{sha}"' )
    stamp = r.stdout.strip()
    assert ":" not in stamp           # colons stripped (path-safe)
    assert "+" not in stamp           # tz plus stripped
    assert stamp.endswith( sha[ :8 ] )
    assert "-" + sha[ :8 ] in stamp


# ----------------------------------------------------------------------------
# Static wiring assertions (mirror test_cloud_run_script_paths.py)
# ----------------------------------------------------------------------------
def test_script_sources_the_lib():
    with open( SCRIPT_PATH, "r" ) as f:
        text = f.read()
    assert "lib/deploy-cloud-test-lib.sh" in text
    assert "dctl_parse_args" in text
    assert "dctl_resolve_sha" in text
    assert "dctl_check_clean" in text


def test_lib_declares_all_pure_functions():
    with open( LIB_PATH, "r" ) as f:
        text = f.read()
    for fn in ( "dctl_parse_args", "dctl_resolve_sha", "dctl_sanitize_sha",
                "dctl_detect_axis", "dctl_check_clean", "dctl_compute_stamp" ):
        assert f"{fn}()" in text, f"missing function {fn}"
