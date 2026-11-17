#!/usr/bin/env python3
"""
Lazy package re-exports, shared by the packages that keep their `__init__` light.

A package lists which submodule each public name lives in. The name is imported on first
access, so importing the package never loads the submodule or what it pulls in.
"""

import importlib


def lazy_exports( package_name, package_globals, lazy_map ):
    """
    Build the module `__getattr__` and `__dir__` for a package's lazy re-exports.

    Requires:
        - package_name is the package's __name__
        - package_globals is the package's globals(), the dict the names are cached in
        - lazy_map maps each public name to the submodule it lives in

    Ensures:
        - returns ( __getattr__, __dir__ ), to be bound at the package's top level
        - __getattr__ imports the submodule on first access, caches the name in package_globals
          and returns it, so later reads skip the hook
        - an unmapped name raises AttributeError, so a real submodule import still resolves normally
        - __dir__ lists the real attributes and the lazy names together
    """
    def __getattr__( name ):
        submodule = lazy_map.get( name )
        if submodule is None:
            raise AttributeError( f"module {package_name!r} has no attribute {name!r}" )
        value = getattr( importlib.import_module( f".{submodule}", package_name ), name )
        package_globals[ name ] = value
        return value

    def __dir__():
        return sorted( set( package_globals ) | set( lazy_map ) )

    return __getattr__, __dir__
