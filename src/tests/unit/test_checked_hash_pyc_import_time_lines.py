"""
Re-execute checked_hash_pyc's module body under the coverage tracer.

Requires:
    - cosa.utils.checked_hash_pyc is importable

Ensures:
    - the module-level statements and every `def` line are traced in this run

`src/sitecustomize.py` imports checked_hash_pyc at interpreter start, before pytest-cov starts
tracing. So every line that runs at import (constants, class body, each `def`) reads as missed even
though it ran. Running the file again with runpy into a fresh namespace traces those lines without
touching sys.modules, so the live patch state (`_installed`, `_original`) of this process is untouched.
"""

import runpy

import pytest

from cosa.utils import checked_hash_pyc as chp


@pytest.fixture( scope="module" )
def fresh_ns():
    """Run the module body once into a private namespace and hand back its globals."""
    return runpy.run_path( chp.__file__, run_name="checked_hash_pyc_rerun" )


def test_flag_constants_name_the_three_header_modes( fresh_ns ):
    """Checked-hash is exactly bits 0 and 1 together; unchecked is bit 0 alone."""
    assert fresh_ns[ "_FLAG_HASH_BASED" ]   == 0b01
    assert fresh_ns[ "_FLAG_CHECK_SOURCE" ] == 0b10
    assert fresh_ns[ "_CHECKED_HASH" ]      == 0b11
    assert fresh_ns[ "_HEADER_LEN" ]        == 16


def test_vendored_trees_stay_excluded( fresh_ns ):
    """The exclusion set matches the migration script's population."""
    assert fresh_ns[ "_EXCLUDED_PARTS" ] == frozenset( ( ".venv", "node_modules", ".git", "__pypackages__", "site-packages" ) )
    assert fresh_ns[ "_LEDGER_RELATIVE" ] == "io/pyc-mode-ledger.jsonl"


def test_install_outcome_refuses_a_truth_value( fresh_ns ):
    """Both non-install outcomes raise on bool() and name the remedy; they stay printable."""
    for name in ( "ALREADY_INSTALLED", "UNSUPPORTED_INTERPRETER" ):
        outcome = fresh_ns[ name ]
        with pytest.raises( TypeError, match="no truth value" ):
            bool( outcome )
        assert str( outcome ) in ( "already-installed", "unsupported-interpreter" )
    assert fresh_ns[ "ALREADY_INSTALLED" ] != fresh_ns[ "UNSUPPORTED_INTERPRETER" ]


def test_rerun_starts_unpatched_whatever_this_process_is( fresh_ns ):
    """A fresh body begins with no patch, no original and zero conversions."""
    assert fresh_ns[ "_installed" ] is False
    assert fresh_ns[ "_original" ] is None
    assert fresh_ns[ "_converted" ] == 0


def test_every_public_entry_point_is_defined_again( fresh_ns ):
    """Each function exists in the rerun namespace, distinct from the live module's object."""
    for name in ( "pyc_mode", "to_checked_hash", "_in_scope", "install", "uninstall", "is_installed",
                  "converted_count", "_default_roots", "actor", "ledger_path", "record", "census", "main" ):
        assert callable( fresh_ns[ name ] ), name
        assert fresh_ns[ name ] is not getattr( chp, name ), name
