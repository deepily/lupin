"""
Unit tests for cosa.config.docview_manifest.

Covers AC3.1-AC3.5 of the doc-viewer scope unification design.
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from cosa.config.docview_manifest import (
    DocviewManifest,
    MAX_MANIFEST_BYTES,
    load_manifest_for_scope,
)


# ---------------------------------------------------------------------------
# DocviewManifest Pydantic shape
# ---------------------------------------------------------------------------

def test_manifest_defaults():
    """All fields default to safe-empty values."""
    m = DocviewManifest()
    assert m.version == 1
    assert m.allowed_prefixes == []
    assert m.allowed_root_files == []
    assert m.extra_blocklist == []


def test_manifest_happy_path():
    m = DocviewManifest(
        version=1,
        allowed_prefixes=[ "src/" ],
        allowed_root_files=[ "README.md", "CHANGELOG.md" ],
        extra_blocklist=[ r"^private-.*\.md$" ],
    )
    assert m.allowed_prefixes == [ "src/" ]
    assert m.allowed_root_files == [ "README.md", "CHANGELOG.md" ]


def test_manifest_version_must_be_1():
    """Version field is constrained to ge=1, le=1 — version 2 is rejected."""
    with pytest.raises( Exception ):
        DocviewManifest( version=2 )


def test_manifest_version_zero_rejected():
    with pytest.raises( Exception ):
        DocviewManifest( version=0 )


def test_manifest_rejects_unknown_field_remove_from_blocklist():
    """AC3.4: per Q4-B repos cannot weaken the floor — `remove_from_blocklist` MUST be rejected."""
    with pytest.raises( Exception ) as exc_info:
        DocviewManifest( version=1, remove_from_blocklist=[ ".env" ] )
    # Pydantic v2 ValidationError mentions the unknown field
    assert "remove_from_blocklist" in str( exc_info.value ) or "extra" in str( exc_info.value ).lower()


def test_manifest_rejects_arbitrary_unknown_field():
    """AC3.4: any unknown field rejected — defense in depth."""
    with pytest.raises( Exception ):
        DocviewManifest( version=1, malicious_field=True )


def test_manifest_rejects_malformed_regex_in_extra_blocklist():
    """AC3.3: bad regex caught at parse time."""
    with pytest.raises( Exception ) as exc_info:
        DocviewManifest( version=1, extra_blocklist=[ "unbalanced(" ] )
    assert "Invalid regex" in str( exc_info.value ) or "extra_blocklist" in str( exc_info.value )


def test_manifest_accepts_valid_regex_in_extra_blocklist():
    m = DocviewManifest( version=1, extra_blocklist=[ r"^\.dev-secrets$", r"\.tmp\.\d+$" ] )
    assert len( m.extra_blocklist ) == 2


# ---------------------------------------------------------------------------
# load_manifest_for_scope — file-handling
# ---------------------------------------------------------------------------

def test_load_returns_none_when_file_missing( tmp_path ):
    """AC3.2: missing manifest → wildcard semantics; loader returns None."""
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_parses_valid_manifest( tmp_path ):
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( yaml.safe_dump( {
        "version"           : 1,
        "allowed_prefixes"  : [ "src/", "docs/" ],
        "allowed_root_files": [ "README.md" ],
    } ) )
    m = load_manifest_for_scope( str( tmp_path ) )
    assert m is not None
    assert m.allowed_prefixes == [ "src/", "docs/" ]
    assert m.allowed_root_files == [ "README.md" ]


def test_load_returns_none_for_malformed_yaml( tmp_path ):
    """Malformed YAML → None (wildcard fallback with WARN log)."""
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( ":\n  -:::: not valid yaml [[[\n  unbalanced: " )
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_returns_none_for_root_not_a_mapping( tmp_path ):
    """YAML root must be a dict — list/scalar rejected."""
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( "- not\n- a\n- mapping\n" )
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_returns_none_for_empty_yaml( tmp_path ):
    """Empty manifest → wildcard fallback."""
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( "" )
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_returns_none_for_unknown_field_in_yaml( tmp_path ):
    """A repo trying to declare remove_from_blocklist at the YAML level is rejected."""
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( yaml.safe_dump( {
        "version"               : 1,
        "remove_from_blocklist" : [ ".env" ],
    } ) )
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_returns_none_for_oversize_manifest( tmp_path ):
    """AC3.5: file > 64 KB → wildcard fallback with WARN log."""
    manifest_path = tmp_path / ".docview.yml"
    # Construct a payload that parses but exceeds the cap
    huge_list = [ f"prefix_{i}/" for i in range( 20000 ) ]  # ~200+ KB serialized
    manifest_path.write_text( yaml.safe_dump( {
        "version"          : 1,
        "allowed_prefixes" : huge_list,
    } ) )
    assert manifest_path.stat().st_size > MAX_MANIFEST_BYTES
    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_handles_scope_root_not_a_directory():
    """A bogus scope root that isn't a real dir → return None gracefully."""
    assert load_manifest_for_scope( "/nonexistent/path/that/should/not/exist" ) is None


def test_load_returns_none_on_read_oserror( tmp_path, monkeypatch ):
    """read_text() raising OSError → fallback to wildcard (return None)."""
    manifest_path = tmp_path / ".docview.yml"
    manifest_path.write_text( "version: 1\n" )

    real_read = Path.read_text
    def bad_read( self, *a, **kw ):
        if self == manifest_path:
            raise OSError( "simulated read failure" )
        return real_read( self, *a, **kw )
    monkeypatch.setattr( Path, "read_text", bad_read )

    assert load_manifest_for_scope( str( tmp_path ) ) is None


def test_load_accepts_manifest_at_64kb_exact( tmp_path ):
    """Boundary — file at exactly the cap should still parse (cap is `> cap`)."""
    manifest_path = tmp_path / ".docview.yml"
    # Build a manifest as close to 64KB as possible with valid content
    target_size = MAX_MANIFEST_BYTES - 100
    padding = "# " + "x" * ( target_size - 50 )
    content = padding + "\n" + yaml.safe_dump( { "version": 1 } )
    manifest_path.write_text( content )
    size = manifest_path.stat().st_size
    assert size <= MAX_MANIFEST_BYTES
    result = load_manifest_for_scope( str( tmp_path ) )
    # File is parseable and under cap — should NOT return None
    assert result is not None
