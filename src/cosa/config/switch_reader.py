#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
The one reader for a boolean INI switch that must never stop its caller.

A switch read can fail when the settings file is missing or malformed. The callers of this module
treat that as "off", print one line saying so, and carry on. Each caller keeps its own key, its own
default and its own printed line; only the read and the fall-back to off live here.

Dependency Rule:
    - Imports nothing from the agents, the REST layer or the research package.
    - The caller hands in the configuration manager class, so a test can patch it where the caller looks it up.
"""

ENV_VAR_NAME = "LUPIN_CONFIG_MGR_CLI_ARGS"


def read_switch( manager, key, default, on_unreadable ):
    """
    Read one boolean INI switch, answering off when the setting cannot be read.

    Requires:
        - manager is the ConfigurationManager class, or a stand-in taking env_var_name and offering get( key, default, return_type )
        - key names the INI setting
        - default is the value get() is given when the key is absent
        - on_unreadable is a function taking the exception and returning the one line to print

    Ensures:
        - returns the switch's value as get() answers it with return_type "boolean"
        - returns False and prints on_unreadable( error ) when the manager or the read raises
        - raises nothing the read itself raises
    """
    try:
        return manager( env_var_name=ENV_VAR_NAME ).get( key, default=default, return_type="boolean" )
    except Exception as error:
        print( on_unreadable( error ) )
        return False
