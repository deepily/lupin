"""
Load a config dataclass from ConfigurationManager INI keys.

BugFixExpediterConfig, SweTeamConfig, TestFixExpediterConfig and ResearchConfig each map their
fields to INI keys and coerce by the field's type; this is the one loop they share.
"""

import contextlib
import functools
import sys
from dataclasses import field, fields


def required_model_id( key, config_mgr=None ):
    """
    Read the Claude model id one agent config sends its prompts to, from lupin-app.ini.

    Requires:
        - key is an INI key that holds a model id
        - config_mgr has a ConfigurationManager `get_required` method, or is None to use the process's own

    Ensures:
        - returns the value of the key, read when called, so an INI edit needs no code change
        - there is no default in code: the INI file is the only place a model id is set
        - building the process's own manager writes its start-up banner to stderr, never stdout

    Raises:
        - MissingConfigKeyError naming the key, the block and the file when the key is absent or blank
    """
    from cosa.config.configuration_manager import ConfigurationManager
    if config_mgr is None:
        with contextlib.redirect_stdout( sys.stderr ): config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    return config_mgr.get_required( key, silent=True )


def model_field( key ):
    """
    Declare a dataclass field whose model id is read from an INI key at construction.

    Requires:
        - key is an INI key that holds a model id

    Ensures:
        - returns a dataclass field with no default value in code
        - a constructor call that omits the field reads `key` through required_model_id, and refuses a missing key
        - a constructor call that passes the field uses the value it passes
    """
    return field( default_factory=functools.partial( required_model_id, key ) )


def load_kwargs_from_ini( cls, config_mgr, key_map, debug=False, label=None, silent=False ):
    """
    Read one INI value per mapped field of a config dataclass, as constructor kwargs.

    Requires:
        - cls is a dataclass whose mapped fields have defaults, or are model_field fields, which have none
        - config_mgr is a ConfigurationManager
        - key_map maps field names of cls to INI key names
        - label is the name shown in debug lines; it defaults to cls.__name__
        - silent=True is passed to every config_mgr.get call, so the manager prints no banner for a key the INI lacks; with silent=False the argument is left out

    Ensures:
        - returns { field_name: value } with one entry per key_map entry
        - each value is config_mgr.get( ini_key, default=<field default>, return_type=... ),
          where return_type is "boolean" for bool, "int" for int, "float" for float and
          "string" for anything else (a string annotation such as "bool" counts too)
        - a field absent from the INI takes its dataclass default
        - a model_field field is read with config_mgr.get_required( ini_key ), so a missing or blank key raises MissingConfigKeyError
        - with debug, prints one line per field naming the INI key

    Raises:
        - KeyError if a key_map name is not a field of cls
    """
    label     = cls.__name__ if label is None else label
    get_extra = { "silent": True } if silent else {}
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

        if isinstance( dc_field.default_factory, functools.partial ) and dc_field.default_factory.func is required_model_id:
            value = config_mgr.get_required( ini_key, return_type=return_type, **get_extra )
        else:
            value = config_mgr.get( ini_key, default=default, return_type=return_type, **get_extra )
        kwargs[ field_name ] = value

        if debug: print( f"  [{label}] {field_name} = {value} (from INI: {ini_key})" )

    return kwargs


def load_dataclass_from_ini( cls, config_mgr, key_map, debug=False, label=None, silent=False ):
    """
    Build a config dataclass from INI values, one key per mapped field.

    Requires:
        - the same as load_kwargs_from_ini

    Ensures:
        - returns cls( **load_kwargs_from_ini( ... ) )
    """
    return cls( **load_kwargs_from_ini( cls, config_mgr, key_map, debug=debug, label=label, silent=silent ) )
