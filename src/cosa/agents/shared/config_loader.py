"""
Load a config dataclass from ConfigurationManager INI keys.

BugFixExpediterConfig, SweTeamConfig and TestFixExpediterConfig each map their fields to INI
keys and coerce by the field's type; this is the one loop they share.
"""

from dataclasses import fields


def load_kwargs_from_ini( cls, config_mgr, key_map, debug=False, label=None ):
    """
    Read one INI value per mapped field of a config dataclass, as constructor kwargs.

    Requires:
        - cls is a dataclass whose mapped fields have defaults
        - config_mgr is a ConfigurationManager
        - key_map maps field names of cls to INI key names
        - label is the name shown in debug lines; it defaults to cls.__name__

    Ensures:
        - returns { field_name: value } with one entry per key_map entry
        - each value is config_mgr.get( ini_key, default=<field default>, return_type=... ),
          where return_type is "boolean" for bool, "int" for int, "float" for float and
          "string" for anything else (a string annotation such as "bool" counts too)
        - a field absent from the INI takes its dataclass default
        - with debug, prints one line per field naming the INI key

    Raises:
        - KeyError if a key_map name is not a field of cls
    """
    label     = cls.__name__ if label is None else label
    kwargs    = {}
    dc_fields = { f.name: f for f in fields( cls ) }

    for field_name, ini_key in key_map.items():
        dc_field   = dc_fields[ field_name ]
        default    = dc_field.default
        field_type = dc_field.type

        if field_type == "bool" or field_type is bool:
            return_type = "boolean"
        elif field_type == "int" or field_type is int:
            return_type = "int"
        elif field_type == "float" or field_type is float:
            return_type = "float"
        else:
            return_type = "string"

        value = config_mgr.get( ini_key, default=default, return_type=return_type )
        kwargs[ field_name ] = value

        if debug: print( f"  [{label}] {field_name} = {value} (from INI: {ini_key})" )

    return kwargs


def load_dataclass_from_ini( cls, config_mgr, key_map, debug=False, label=None ):
    """
    Build a config dataclass from INI values, one key per mapped field.

    Requires:
        - the same as load_kwargs_from_ini

    Ensures:
        - returns cls( **load_kwargs_from_ini( ... ) )
    """
    return cls( **load_kwargs_from_ini( cls, config_mgr, key_map, debug=debug, label=label ) )
