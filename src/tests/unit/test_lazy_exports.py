#!/usr/bin/env python3
"""
cosa.utils.lazy_exports: the hook the db and repositories packages share.

A throwaway package on disk stands in, so the real SQLAlchemy stack is never touched.

Venue: :7999-eligible / local, pure.
"""
import importlib
import os
import sys

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.utils.lazy_exports import lazy_exports


@pytest.fixture
def lazy_package( tmp_path, monkeypatch ):
    """A package `lazypkg_t` whose submodule `heavy` records that it was imported."""
    pkg = tmp_path / "lazypkg_t"
    pkg.mkdir()
    ( pkg / "heavy.py" ).write_text( "import builtins\nbuiltins.LAZYPKG_IMPORTS = getattr( builtins, 'LAZYPKG_IMPORTS', 0 ) + 1\nvalue = object()\nother = object()\n" )
    ( pkg / "__init__.py" ).write_text(
        "from cosa.utils.lazy_exports import lazy_exports\n"
        "_LAZY_EXPORTS = { 'value': 'heavy', 'other': 'heavy' }\n"
        "__all__ = list( _LAZY_EXPORTS )\n"
        "__getattr__, __dir__ = lazy_exports( __name__, globals(), _LAZY_EXPORTS )\n" )
    monkeypatch.syspath_prepend( str( tmp_path ) )
    import builtins
    monkeypatch.setattr( builtins, "LAZYPKG_IMPORTS", 0, raising=False )
    for name in [ n for n in sys.modules if n.startswith( "lazypkg_t" ) ]:
        monkeypatch.delitem( sys.modules, name )
    yield importlib.import_module( "lazypkg_t" )
    for name in [ n for n in sys.modules if n.startswith( "lazypkg_t" ) ]:
        del sys.modules[ name ]


def test_importing_the_package_does_not_import_the_submodule( lazy_package ):
    import builtins
    assert builtins.LAZYPKG_IMPORTS == 0
    assert "lazypkg_t.heavy" not in sys.modules


def test_first_access_imports_once_and_caches_the_name( lazy_package ):
    import builtins
    first = lazy_package.value
    assert builtins.LAZYPKG_IMPORTS == 1
    assert "value" in vars( lazy_package )
    assert lazy_package.value is first
    assert lazy_package.other is sys.modules[ "lazypkg_t.heavy" ].other
    assert builtins.LAZYPKG_IMPORTS == 1


def test_an_unmapped_name_raises_attribute_error_naming_the_module( lazy_package ):
    with pytest.raises( AttributeError, match="module 'lazypkg_t' has no attribute 'nope'" ):
        lazy_package.nope
    assert not hasattr( lazy_package, "nope" )


def test_dir_lists_the_real_attributes_and_the_lazy_names_together( lazy_package ):
    names = dir( lazy_package )
    assert "value" in names and "other" in names and "lazy_exports" in names
    assert names == sorted( names )


def test_the_two_real_packages_use_the_shared_hook():
    import cosa.rest.db as db
    import cosa.rest.db.repositories as repositories
    assert db._LAZY_EXPORTS[ "get_db" ] == "database"
    assert repositories._LAZY_EXPORTS[ "TrustStateRepository" ] == "proxy_decision_repository"
    assert db.__getattr__.__module__ == "cosa.utils.lazy_exports"
    assert repositories.__getattr__.__module__ == "cosa.utils.lazy_exports"
