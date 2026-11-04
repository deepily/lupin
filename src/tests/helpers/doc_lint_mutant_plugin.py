"""
Pytest plugin that runs a test session against one mutated doc_lint module.

Loaded with `-p tests.helpers.doc_lint_mutant_plugin` and told what to mutate by the
DOC_LINT_MUTANT environment variable, a JSON object with module, old and new. The module's
source is edited once, loaded under its real name before anything imports it, and every
function it defines drops the findings whose rule is SENTINEL. A mutant that renames a rule to
SENTINEL therefore disables that rule outright, instead of only changing its name.
"""

import functools
import importlib
import importlib.util
import json
import os
import sys
import types

SENTINEL = "_mutant_disabled_rule"
PACKAGE  = "cosa.repo.doc_lint"


def _drop_sentinel( func ):
    """
    Wrap func so a returned list loses the findings whose rule is SENTINEL.

    Requires:
        - func is a plain function

    Ensures:
        - a list result is filtered; any other result is returned untouched

    Raises:
        - nothing beyond func's own
    """
    @functools.wraps( func )
    def wrapper( *args, **kwargs ):
        result = func( *args, **kwargs )
        if not isinstance( result, list ): return result
        return [ f for f in result if not ( type( f ).__name__ == "Finding" and f.rule == SENTINEL ) ]
    return wrapper


def load_mutant( module, old, new ):
    """
    Load one doc_lint module with a single text edit applied.

    Requires:
        - module is a module name inside cosa.repo.doc_lint, not yet imported
        - old occurs exactly once in its source

    Ensures:
        - sys.modules holds the mutated module under its real name, so later imports get it
        - the edit is a no-op when new equals old, which makes a control run

    Raises:
        - AssertionError when old does not occur exactly once
    """
    importlib.import_module( PACKAGE )
    name   = f"{PACKAGE}.{module}"
    path   = os.path.join( os.path.dirname( sys.modules[ PACKAGE ].__file__ ), f"{module}.py" )
    source = open( path, encoding="utf-8" ).read()
    assert source.count( old ) == 1, f"anchor must match exactly once in {module}: {old!r}"
    spec = importlib.util.spec_from_file_location( name, path )
    mod  = importlib.util.module_from_spec( spec )
    sys.modules[ name ] = mod
    exec( compile( source.replace( old, new ), path, "exec" ), mod.__dict__ )
    for key, value in list( mod.__dict__.items() ):
        if isinstance( value, types.FunctionType ) and value.__module__ == name:
            setattr( mod, key, _drop_sentinel( value ) )
    return mod


spec_json = os.environ.get( "DOC_LINT_MUTANT" )
if spec_json is not None:
    _spec = json.loads( spec_json )
    load_mutant( _spec[ "module" ], _spec[ "old" ], _spec[ "new" ] )
