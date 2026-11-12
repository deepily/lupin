"""
A ConfigurationManager stand-in whose get() converts the answer the way the real one does.

A fake that ignores return_type cannot tell `get( key, return_type="boolean" )` from `get( key )`.
The same string comes back for both.
`test_typed_config_fake.py` compares this conversion with the real manager's, value by value.
"""

import ast
import json

_NO_VALUE = object()


def _typed( value, return_type ):
    """
    Convert value as ConfigurationManager._get_typed_value does.

    Requires:
        - return_type is boolean, float, int, string, list-string, json or dict, in any case

    Ensures:
        - boolean: a bool stays, anything else is True only when its lower-cased text is "true"
        - an int or string type name matches by prefix, as the manager does
        - a return_type outside the list raises ValueError
    """
    return_type = return_type.lower()
    if return_type == "boolean":
        return value if isinstance( value, bool ) else str( value ).lower() == "true"
    if return_type == "float":              return float( value )
    if return_type.startswith( "int" ):     return int( value )
    if return_type.startswith( "str" ):     return value
    if return_type == "list-string":        return value.split( ", " )
    if return_type == "json":               return json.loads( value )
    if return_type == "dict":               return ast.literal_eval( value )
    raise ValueError( f"Return type [{return_type}] is invalid." )


class TypedConfigFake:
    """
    Answer get() from a dict, or with one value for every key, converted by return_type.

    Requires:
        - values is a dict of key to stored value, or None
        - every_key, when given, is the one stored value returned for any key

    Ensures:
        - get( key, default, silent, return_type ) converts the stored value, or the default
          when the key is absent, with the manager's conversion
        - an unknown return_type raises ValueError, as the real manager does
        - set_every_key( value ) replaces the value returned for every key
    """

    def __init__( self, values=None, every_key=_NO_VALUE ):
        self._values    = {} if values is None else values
        self._every_key = every_key

    def get( self, key, default=None, silent=False, return_type="string" ):
        if self._every_key is not _NO_VALUE: raw = self._every_key
        elif key in self._values:            raw = self._values[ key ]
        else:                                raw = default
        return _typed( raw, return_type )

    def set_every_key( self, value ):
        self._every_key = value
