import configparser
import os
import json
import ast
from typing import Optional, Union, Any, Callable

import cosa.utils.util as du

# Idea for the "singleton" decorator: https://stackabuse.com/creating-a-singleton-in-python/
def singleton( cls: type ) -> Callable[..., Any]:
    """
    Decorator that implements the Singleton pattern.

    Requires:
        - cls is a valid class type

    Ensures:
        - Only one instance of cls is created
        - All calls return the same instance
        - Prints messages about instance creation/reuse
        - Provides a reset method for testing

    Testing:
        - Use _reset_singleton=True parameter for atomic reset+recreate:
            obj = ConfigurationManager(env_var_name="...", _reset_singleton=True)
        - Use reset_for_testing() method for explicit reset:
            ConfigurationManager.reset_for_testing()

    Notes:
        - _reset_singleton parameter is intercepted by decorator (never reaches class)
        - Underscore prefix signals "special testing hook, not normal API"
        - Atomic reset pattern (_reset_singleton=True) preferred over two-step reset

    Raises:
        - None
    """
    
    instances = { }
    
    def wrapper( *args: Any, **kwargs: Any ) -> Any:
        
        # Check for the special _reset_singleton flag for testing
        if kwargs.pop( "_reset_singleton", False ):
            if cls in instances:
                print( "Resetting ConfigurationManager() singleton for testing..." )
                del instances[ cls ]
            else:
                print( "No ConfigurationManager() singleton instance to reset" )
        
        if cls not in instances:
            # print( "Instantiating ConfigurationManager() singleton...", end="\n\n" )
            instances[ cls ] = cls( *args, **kwargs )
        # else:
        #     if instances[ cls ].get( "app debug", default=False, return_type="boolean" ):
        #         print( "Reusing ConfigurationManager() singleton..." )
            
        return instances[ cls ]
    
    # Add reset method to the wrapper function itself
    def reset_for_testing():
        """Reset the singleton instance for testing purposes"""
        if cls in instances:
            print( "Resetting ConfigurationManager() singleton..." )
            del instances[ cls ]
            return True
        return False
    
    wrapper.reset_for_testing = reset_for_testing
    
    return wrapper

@singleton
class ConfigurationManager():
    """
    Manages application configuration with inheritance and override capabilities.
    
    This singleton class handles configuration loading from INI files, supports
    inheritance between configuration blocks, environment variable overrides,
    and provides explanatory documentation for configuration keys.
    """
    
    def __init__( self, env_var_name: Optional[str]=None, config_path: Optional[str]=None, splainer_path: Optional[str]=None, config_block_id: str="default", debug: bool=False, verbose: bool=False, silent: bool=False, mute_splainer: bool=False, cli_args: Optional[dict[str, str]]=None ) -> None:

        """
        Initialize the configuration manager.

        Requires:
            - If env_var_name is provided, the environment variable must exist and contain valid config info
            - Either env_var_name OR (config_path and splainer_path) must be provided
            - config_path and splainer_path must be valid file paths if provided

        Ensures:
            - Singleton instance is created or reused
            - Configuration is loaded from explicitly provided filepaths or specified by an environment variable
            - Inheritance hierarchy is calculated
            - Default values are applied
            - CLI overrides are processed
            - Splainer definitions are loaded

        Testing:
            - To reset singleton in tests, use _reset_singleton=True parameter:
                config_mgr = ConfigurationManager(
                    env_var_name="TEST_ENV_VAR",
                    _reset_singleton=True  # Atomic reset for clean test state
                )
            - This parameter is intercepted by @singleton decorator and never reaches __init__
            - Preferred over ConfigurationManager.reset_for_testing() for atomic operation

        Raises:
            - ValueError if env_var_name is provided but not found in environment
            - ValueError if no initialization parameters are provided (zero-argument case)
            - ValueError if conflicting initialization parameters are provided
            - FileNotFoundError if config_path or splainer_path don't exist
            - AssertionError if config_block_id doesn't exist in configuration
        """
        self.debug           = debug
        self.verbose         = verbose
        self.silent          = silent
        self.mute_splainer   = mute_splainer
        
        # Zero-argument constructor check
        if env_var_name is None and config_path is None and splainer_path is None:
            raise ValueError(
                "ConfigurationManager initialization error: No initialization parameters provided.\n"
                "RECOMMENDED: Use ConfigurationManager(env_var_name=\"LUPIN_CONFIG_MGR_CLI_ARGS\")\n"
                "ALTERNATIVE: Provide explicit config_path and splainer_path arguments"
            )
            
        # Check for conflicting initialization methods
        if env_var_name is not None and (config_path is not None or splainer_path is not None):
            raise ValueError(
                "ConfigurationManager initialization error: Conflicting initialization parameters.\n"
                "Either provide env_var_name OR provide both config_path and splainer_path, not both."
            )
        
        if env_var_name is not None:
            
            print( f"Using environment variables to instantiate configuration manager" )
            
            if env_var_name not in os.environ: raise ValueError( f"[{env_var_name}] is NOT set" )
            
            # take the environment string, split it into a list and then convert that list into a dictionary
            cli_args = os.environ[ env_var_name ].split( " " )
            cli_args = du.get_name_value_pairs( cli_args )
            
            # Three arguments need to be set when using env_var_name variables
            self.config_path     = du.get_project_root() + cli_args[ "config_path" ]
            self.splainer_path   = du.get_project_root() + cli_args[ "splainer_path" ]
            self.config_block_id = cli_args[ "config_block_id" ]
            # Decode URL-encoded spaces (plus signs) back to actual spaces
            self.config_block_id = self.config_block_id.replace( "+", " " )
            
            # Now delete those three keys from cli_args
            del cli_args[ "config_path" ]
            del cli_args[ "splainer_path" ]
            del cli_args[ "config_block_id" ]
        
        else:
            # If using explicit paths, both must be provided
            if config_path is None or splainer_path is None:
                raise ValueError(
                    "ConfigurationManager initialization error: Incomplete explicit path configuration.\n"
                    "When using explicit paths, both config_path and splainer_path must be provided."
                )
                
            self.config_path     = config_path
            self.splainer_path   = splainer_path
            self.config_block_id = config_block_id

        # set by call below
        self.config          = None
        self.splainer        = None
        
        self.init(
            config_block_id=self.config_block_id, config_path=self.config_path, splainer_path=self.splainer_path, debug=debug, verbose=verbose, silent=silent, cli_args=cli_args
        )

    def init( self, config_block_id: Optional[str]=None, config_path: Optional[str]=None, splainer_path: Optional[str]=None, silent: bool=False, debug: bool=False, verbose: bool=False, cli_args: Optional[dict[str, str]]=None ) -> None:
        """
        Initialize or reinitialize the configuration.
        
        Requires:
            - config_path and splainer_path must be valid files if provided
            - config_block_id must exist in the configuration if provided
            
        Ensures:
            - Configuration is loaded from specified files
            - Block ID is updated if provided
            - Inheritance hierarchy is recalculated
            - Default values are applied
            - CLI overrides are processed
            - Splainer definitions are loaded
            
        Raises:
            - FileNotFoundError if paths don't exist
            - AssertionError if config_block_id not found
        """

        # update paths, if provided
        if config_path is not None:
            self.config_path = config_path.strip()
        if splainer_path is not None:
            self.splainer_path = splainer_path.strip()

        du.sanity_check_file_path( self.config_path,   silent=silent )
        du.sanity_check_file_path( self.splainer_path, silent=silent )
        
        if not self.silent:
            du.print_banner( f"Initializing configuration_manager [{self.config_path}]", prepend_nl=True, end="\n" )
            print( f"Splainer path [{self.splainer_path}]", end="\n\n" )

        self.silent          = silent
        self.config          = configparser.ConfigParser()
        if config_block_id is not None:
            self.config_block_id = config_block_id

        self.config.read( self.config_path )

        self._sanity_check_config_block( self.config_block_id )

        if self.debug and self.verbose and not self.silent:
            print( "Path:", config_path )
            print( "Block ID:", config_block_id, end="\n\n" )

        if not self.silent: self.print_sections()
        self._calculate_inheritance()
        self._calculate_defaults()
        self._override_configuration( cli_args )
        self._load_splainer_definitions()

    def _override_configuration( self, cli_args: Optional[dict[str, str]] ) -> None:
        """
        Override configuration values with CLI arguments.
        
        Requires:
            - cli_args is None or a dictionary of key-value pairs
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Configuration values are updated with cli_args values
            - config_path and config_block_id are not overridden (immutable)
            - Prints status messages for each override
            
        Raises:
            - None
        """

        # overwrite current configuration values if the cli_args {} has anything to add...
        if cli_args is not None and len( cli_args ) > 0:

            for key in cli_args.keys():

                # ...but don't override config_path and config_block_id, they're immutable
                if key != "config_path" and key != "config_block_id":

                    print( "Overriding [{0}] with [{1}]".format( key, cli_args[ key ] ) )
                    self.set_config( key, cli_args[ key ] )

                elif key == "config_path":
                    print( "Skipping override of [config_path], it's immutable" )
                else:
                    print( "Skipping override of [config_block_id], it's immutable" )
            print()

        else:

            if self.debug: print( "Skipping cli_args processing" )

    def _calculate_defaults( self ) -> None:
        """
        Apply default values to the current configuration block.
        
        Requires:
            - self.config is initialized with sections
            - self.config_block_id is set
            - 'default' section exists in configuration
            
        Ensures:
            - All keys from 'default' section are added to current block
            - Existing keys in current block are not overwritten
            - Nothing happens if current block is 'default'
            
        Raises:
            - None
        """

        if not self.silent: du.print_banner( "Calculating defaults...", prepend_nl=True )

        # All configurations get default values, except for the default config
        if self.config_block_id != "default":

            for key in self.config.options( "default" ):

                if self.debug and self.verbose: print( "Inserting default key [{0}] = [{1}] into [{2}]".format( key, self.config.get( "default", key ), self.config_block_id ) )
                self.config.set( self.config_block_id, key, self.config.get( "default", key ) )

        else:
            if not self.silent: print( "Not adding default key=pair values because we're already in the 'default' block" )

    def _calculate_inheritance( self ) -> None:
        """
        Calculate and apply configuration inheritance.
        
        Requires:
            - self.config and self.config_block_id are initialized
            - If 'inherits' key exists, it points to valid block or file
            
        Ensures:
            - Inheritance hierarchy is resolved recursively
            - Inherited values are applied to current block
            - Immutable keys (starting with '@_') are handled properly
            - Values in current block override inherited values
            
        Raises:
            - AssertionError if inherited block doesn't exist
            - FileNotFoundError if inherited file doesn't exist
        """

        if not self.silent: du.print_banner( "Calculating inheritance... * = parent block" )

        parent_block_keys = self.config.options( self.config_block_id )

        if "inherits" in parent_block_keys:

            inherits_from = self.get( "inherits" )

            # Only sanity check inheritance if it's not a file
            if not os.path.isfile( inherits_from ):

                self._sanity_check_config_block( inherits_from )
                inheritance_list = [ inherits_from ]
            else:
                inheritance_list = []

            if not self.silent: print( "* [{0}] inherits from [{1}]".format( self.config_block_id, inherits_from ) )

            # Entry point for recursive list building is the originally specified configuration block ID's inherits key
            inheritance_list = self._build_inheritance_list( inherits_from, inheritance_list )

            # flip it...
            inheritance_list.reverse()

            key_value_pairs = dict()
            if self.debug and self.verbose: print( "Reading key=value pairs in inheritance_list, reversed:", end="\n\n" )

            # iterate blocks, grabbing key=value pairs and stashing them in a dictionary
            for idx, block_id in enumerate( inheritance_list ):

                if self.debug and self.verbose: print( "[{0}]th block id [{1}]".format( idx, block_id ) )

                if os.path.isfile( block_id ):

                    key_value_pairs = self._load_key_value_pairs_from_file( block_id, key_value_pairs )

                else:

                    keys = self.config.options( block_id )

                    for key in keys:

                        key_value_pairs[ key ] = self.config.get( block_id, key )
                        if self.debug and self.verbose: print(
                            "[{0}]th block id [{1}] [{2}]=[{3}]".format( idx, block_id, key, key_value_pairs[ key ] ) )

            # print()
            self._scan_and_update_keys( key_value_pairs, parent_block_keys )

        else:

            if not self.silent: print( "No inheritance flag found" )

        # print()

    def _load_key_value_pairs_from_file( self, config_path: str, key_value_pairs: dict[str, str] ) -> dict[str, str]:
        """
        Load key-value pairs from a configuration file.
        
        Requires:
            - config_path is a valid file path
            - key_value_pairs is a dictionary to update
            - File contains a 'base' section
            
        Ensures:
            - Returns updated dictionary with values from file
            - Existing values in key_value_pairs may be overwritten
            - Only reads from 'base' section of the file
            
        Raises:
            - AssertionError if 'base' section not found
            - FileNotFoundError if config_path doesn't exist
        """

        if self.verbose and self.debug: print( "_load_key_value_pairs_from_file(...) called" )
        temp_config = configparser.ConfigParser()
        temp_config.read( config_path )

        # Assumes that "base" is the default block
        block_id = "base"

        # Sanity check: is the base block present?
        fail_msg = "Configuration block doesn't exist: [{0}] Check spelling?".format( block_id )
        assert block_id in temp_config.sections(), fail_msg

        keys = temp_config.options( "base" )

        # Iterate and update key value pairs
        if self.debug and self.verbose: print()
        for key in keys:

            value = temp_config.get( block_id, key )
            key_value_pairs[ key ] = value
            if self.debug and self.verbose: print( "  From [{0}], [{1}] = [{2}]".format( config_path, key, value ) )

        if self.debug and self.verbose: print()

        return key_value_pairs

    def _scan_and_update_keys( self, key_value_pairs: dict[str, str], parent_block_keys: list[str] ) -> None:
        """
        Scan and update configuration keys respecting immutability rules.
        
        Requires:
            - key_value_pairs contains inherited key-value pairs
            - parent_block_keys contains keys in current block
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Immutable keys (starting with '@_') are removed/ignored
            - Inherited values are added if not already present
            - Existing values in parent block are not overwritten
            - Status messages are printed for violations
            
        Raises:
            - None
        """

        if not self.silent: print( "Scanning for immutable keys..." )
        found = False

        # Scan parent_block keys for immutables found outside default block
        rule = "{0} [{1}]: Keys that start with '@_' -- outside of the 'default' block -- violate immutability and scoping rule"
        keys = self.config.options( self.config_block_id )
        for key in keys:
            if key.startswith( "@_" ):
                if not found: print()
                print( rule.format( "Removing", key ) )
                self.config.remove_option( self.config_block_id, key )
                found = True

        # Now that we've got all the inherited values, add them to config block ID...
        # ...Taking care not to overwrite values in config block ID
        for key in key_value_pairs.keys():

            if key.startswith( "@_" ):
                if not found: print()
                print( rule.format( "Ignoring", key ) )
                found = True
            elif key not in parent_block_keys:
                self.config.set( self.config_block_id, key, key_value_pairs[ key ] )
            else:
                if self.debug and self.verbose: print( "Skipping key [{0}], it's already set in [{1}]".format( key, self.config_block_id ) )

        if found: print()
        if not self.silent: print( "Scanning for immutable keys... Done!" )

    def _build_inheritance_list( self, block_id: str, inheritance_list: list[str] ) -> list[str]:
        """
        Recursively build the inheritance hierarchy list.
        
        Requires:
            - block_id is a valid configuration block or file path
            - inheritance_list is an existing list to append to
            
        Ensures:
            - Returns list with complete inheritance chain
            - Handles both block IDs and file paths
            - Recursively follows 'inherits' keys
            - Avoids duplicate entries for files
            
        Raises:
            - AssertionError if block_id not found (unless it's a file)
        """

        if self.debug and self.verbose: print( "_build_inheritance_list() called for [{0}]...".format( block_id ) )

        # kludgey little Short circuit for when the block ID is a file reference
        if os.path.isfile( block_id ):

            if not self.debug and self.verbose: print( "block_id is a file [{0}]".format( block_id ) )
            # TODO: Why is this necessary? block ID was being added twice to this list!?!
            if block_id not in inheritance_list:
                inheritance_list.append( block_id )
            # else:
                # print( "Skipping adding [{0}], it's already in the inheritance list?!?".format( block_id ) )

            return inheritance_list

        # Continue with standard inheritance this building
        this_blocks_keys = self.config.options( block_id )

        if "inherits" not in this_blocks_keys:

            if self.debug and self.verbose: print( "No inheritance flag found in [{0}]".format( block_id ) )

        else:

            inherits_from = self.config.get( block_id, "inherits" )

            # Perform sanity check if it's not a file
            if not os.path.isfile( inherits_from ):
                self._sanity_check_config_block( inherits_from )

            inheritance_list.append( inherits_from )
            if not self.silent: print( "  [{0}] inherits from [{1}]".format( block_id, inherits_from ) )

            inheritance_list = self._build_inheritance_list( inherits_from, inheritance_list )

        return inheritance_list

    def _sanity_check_config_block( self, block_id: str ) -> None:
        """
        Verify that a configuration block exists.
        
        Requires:
            - block_id is a non-empty string
            - self.config is initialized
            
        Ensures:
            - Returns normally if block exists
            - Raises AssertionError if block doesn't exist
            
        Raises:
            - AssertionError with descriptive message if block not found
        """

        fail_msg = "Configuration block doesn't exist: [{0}] Check spelling?".format( block_id )
        assert block_id in self.config.sections(), fail_msg

    def print_sections( self ) -> None:
        """
        Print all configuration sections to console.
        
        Requires:
            - self.config is initialized with sections
            - self.config_block_id is set
            
        Ensures:
            - Prints sorted list of sections
            - Current block marked with asterisk
            - Banner is displayed
            
        Raises:
            - None
        """

        sections = self.config.sections()
        sections.sort()

        du.print_banner( "Sections, '*' = current block ID" )

        for section in sections:

            if section == self.config_block_id:
                print( "*", section )
            else:
                print( " ", section )

        print()

    def set_config( self, config_key: str, value: Any ) -> None:
        """
        Set or update a configuration value.
        
        Requires:
            - config_key is a non-empty string
            - value can be converted to string
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Configuration value is updated in current block
            - Value is converted to string before storage
            - Existing values are overwritten
            
        Raises:
            - None
        """

        self.config.set( self.config_block_id, config_key, str( value ) )

    def in_config( self, config_key: str ) -> bool:
        """
        Check if configuration key exists (DEPRECATED).
        
        Requires:
            - config_key is a non-empty string
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Returns True if key exists in current block
            - Returns False otherwise
            - Prints deprecation warning
            
        Raises:
            - None
        """
        print( "DEPRECATED: Use config_mgr.exists( key ) instead" )
        return config_key in self.config.options( self.config_block_id )

    def exists( self, config_key: str ) -> bool:
        """
        Checks if the specified configuration key exists in the current config block.
        
        Requires:
            - config_key: A non-empty string representing the configuration key to check
            - self.config_block_id: A valid configuration block ID
            
        Ensures:
            - Returns True if the key exists in the current configuration block
            - Returns False if the key does not exist
            - Case-insensitive matching (forces config_key to lowercase)
            
        Notes:
            - ConfigParser automatically lowercases all keys when reading configuration files
            - Therefore this method must perform case-insensitive comparison
            - Always converts the input config_key to lowercase before checking
            
        Args:
            config_key: The configuration key to check for existence
            
        Returns:
            Boolean indicating whether the key exists in the current configuration block
        """
        # Key must be forced to lowercase because configparser lowercases all keys internally
        # Handle None config_key gracefully
        if config_key is None: return False
        return config_key.lower() in self.config.options( self.config_block_id )

    def print_configuration( self, brackets: bool=True, include_sections: bool=True, prefixes: Optional[list[str]]=None ) -> None:
        """
        Print configuration key-value pairs to console.
        
        Requires:
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Prints configuration sorted by key
            - Optionally filters by prefixes
            - Optionally includes section information
            - Values optionally wrapped in brackets
            
        Raises:
            - None
        """

        # Let them know what this configuration set is based on
        if include_sections: self.print_sections()

        keys     = self.config.options( self.config_block_id )
        block_id = self.config_block_id

        # filter by prefixes?
        # Using None as the default to address the 'prefixes is mutable object' objection:
        # https://stackoverflow.com/questions/41686829/warning-about-mutable-default-argument-in-pycharm
        if prefixes is not None and len( prefixes ) > 0:

            matches = []

            for key in keys:
                for prefix in prefixes:
                    if key.startswith( prefix ):
                        matches.append( key )

            # reduce dupes?
            keys = list( set( matches ) )

            # bail if there's nothing to print
            if len( keys ) == 0:
                print( "No configuration keys to print" )
                return

        du.print_banner( "Configuration for [{0}]".format( self.config_block_id ), end="\n" )
        self.print_configuration_to_stdout( keys, self.config, block_id, brackets )

    def get_keys( self ) -> list[str]:
        """
        Get all keys in the current configuration block.
        
        Requires:
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Returns list of all keys in current block
            - List may be empty if no keys exist
            
        Raises:
            - None
        """

        return self.config.options( self.config_block_id )

    def print_configuration_to_stdout( self, keys: list[str], configuration: configparser.ConfigParser, block_id: str, brackets: bool=True ) -> None:
        """
        Print configuration keys and values to stdout.
        
        Requires:
            - keys is a list of valid configuration keys
            - configuration contains the specified block_id
            - All keys exist in the specified block
            
        Ensures:
            - Keys are sorted alphabetically
            - Values are left-justified for alignment
            - Empty lines inserted between different key stems
            - Values optionally wrapped in brackets
            
        Raises:
            - None
        """

        keys.sort()

        # brackets, by default
        lb = "["
        rb = "]"

        # remove brackets?
        if not brackets: lb = rb = ""

        # get max key len for left justification
        max_len = max( len( key ) for key in keys )
        last_stem = ""

        for key in keys:

            # inserts blank line between different stems
            stem = key.split()[ 0 ]
            if stem != last_stem: print()
            last_stem = stem

            value = configuration.get( block_id, key )
            print( "{0} = {1}{2}{3}".format( key.ljust( max_len, ' ' ), lb, value, rb ) )
            
        print()

    def get( self, key: str, default: Union[str, int, float, bool, list]="@@@_None_@@@", silent: bool=False, return_type: str="string" ) -> Optional[Union[str, int, float, bool, list, dict]]:
    
        """
        Get a configuration value with optional type conversion.
        
        Requires:
            - key is a non-empty string
            - return_type is one of: 'boolean', 'float', 'int', 'string', 'list-string', 'json', 'dict'
            - self.config and self.config_block_id are initialized
            
        Ensures:
            - Returns typed value if key exists
            - Returns typed default if key doesn't exist and default provided
            - Returns None if key doesn't exist and no default
            - Provides splainer explanation for missing keys unless silent
            
        Raises:
            - ValueError if return_type is invalid
            - JSON/AST parsing errors for json/dict types
        """
    
        if self.exists( key ):

            # Get the value
            value = self.config.get( self.config_block_id, key )
            # value = self.config.get( key )

            # Resolve ${ENV_VAR} patterns in config values
            value = os.path.expandvars( value )

            return self._get_typed_value( value, return_type )
    
        else:
    
            # If there's a default specified, then return it
            if default != "@@@_None_@@@":
    
                # only 'splain them when called for
                if not silent and not self.mute_splainer:
    
                    du.print_banner( "Key [{0}] NOT found, returning default [{1}]".format( key, default ), end="\n" )
                    self.splain_me( key )
    
                # return typed default
                return self._get_typed_value( default, return_type )
    
            else:
            
                print()
                du.print_banner( "Key [{0}] NOT found".format( key ), end="\n" )
                self.splain_me( key )
    
                return None

    def _get_typed_value( self, value: Any, return_type: str ) -> Union[str, int, float, bool, list, dict]:
        """
        Convert a configuration value to the requested type.
        
        Requires:
            - value can be converted to the requested type
            - return_type is a valid type identifier (case-insensitive)
            
        Ensures:
            - Returns value converted to specified type
            - Handles boolean conversion from string 'True'
            - Handles list-string by splitting on ', '
            - Handles JSON and dict parsing
            
        Raises:
            - ValueError if return_type is invalid
            - Type conversion errors for the specific type
        """
        # Force return type to lowercase
        return_type = return_type.lower()

        if return_type == "boolean":
            # Handle already-boolean values
            if isinstance( value, bool ):
                return value
            # Case-insensitive string comparison
            return str( value ).lower() == "true"
        elif return_type == "float":
            return float( value )
        elif return_type.startswith( "int" ):
            return int( value )
        elif return_type.startswith( "str" ):
            return value
        elif return_type == "list-string":
            return value.split( ", " )
        elif return_type == "json":
            return json.loads( value )
        elif return_type == "dict":
            return ast.literal_eval( value )
        else:
            raise ValueError( f"Return type [{return_type}] is invalid.  Accepts: 'boolean', 'float', 'int', 'string', 'list-string' and 'json'".format( return_type ) )
        
    def splain_me( self, key: str, end: str="\n\n" ) -> None:
        """
        Explain a configuration key using the splainer documentation.
        
        Requires:
            - key is a non-empty string
            - self.splainer is initialized
            
        Ensures:
            - Prints explanation if key found in splainer
            - Prints error message if key not found
            - Uses specified line ending for formatting
            
        Raises:
            - None
        """

        if key in self.splainer.sections():

            definition = self.splainer.get( "default", key )
            print()
            print( "'Splainer says: [{0}] = {1}".format( key, definition ), end=end )

        else:

            print( "\n'Splainer says: ¿WUH? The key [{0}] NOT found in the 'splainer.ini file. "
                   "Check spelling and/or contact the project maintainer?".format( key ), end=end )

    def _load_splainer_definitions( self ) -> None:
        """
        Load explanatory documentation for configuration keys.
        
        Requires:
            - self.splainer_path is set to a valid file path
            - Splainer file is in valid INI format
            
        Ensures:
            - self.splainer is populated with ConfigParser object
            - Splainer definitions are available for use
            - Status message is printed
            
        Raises:
            - FileNotFoundError if splainer file doesn't exist
            - ConfigParser errors if file format is invalid
        """

        du.print_banner( f"Loading splainer file [{self.splainer_path}]..." )
        splainer = configparser.ConfigParser()
        splainer.read( du.get_project_root() + self.splainer_path )
        # print( len( splainer ) )
        # print( splainer.sections() )
        # print( du.get_file_as_string( self.splainer_path ) )
        
        self.splainer = splainer
    
def quick_smoke_test():
    """Quick smoke test to validate ConfigurationManager functionality."""
    import cosa.utils.util_stopwatch as sw
    
    du.print_banner( "ConfigurationManager Smoke Test", prepend_nl=True )
    
    # Reset singleton before each test to ensure clean testing
    ConfigurationManager.reset_for_testing()
    
    # Test 1: Zero-argument constructor (should fail)
    timer = sw.Stopwatch( msg="Testing zero-argument constructor...", silent=False )
    try:
        config_mgr = ConfigurationManager( _reset_singleton=True )
        print( "❌ ERROR: Zero-argument constructor succeeded but should have failed" )
    except ValueError as e:
        print( f"✅ Expected error: {str( e )}" )
    timer.print( "Test complete", use_millis=True )
    
    # Test 2: Environment variable constructor
    timer = sw.Stopwatch( msg="Testing env_var_name constructor...", silent=False )
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS", _reset_singleton=True )
        print( f"✅ Successfully initialized with env_var_name" )
    except ValueError as e:
        print( f"❌ Error: {str( e )}" )
    timer.print( "Test complete", use_millis=True )
    
    # Test 3: Explicit paths constructor
    timer = sw.Stopwatch( msg="Testing explicit paths constructor...", silent=False )
    try:
        config_path     = du.get_project_root() + "/src/conf/lupin-app.ini"
        splainer_path   = du.get_project_root() + "/src/conf/lupin-app-splainer.ini"
        config_block_id = "default"
        
        config_mgr = ConfigurationManager(
            config_path=config_path,
            splainer_path=splainer_path, 
            config_block_id=config_block_id,
            silent=True,
            _reset_singleton=True
        )
        print( f"✅ Successfully initialized with explicit paths" )
    except ValueError as e:
        print( f"❌ Error: {str( e )}" )
    timer.print( "Test complete", use_millis=True )
    
    # Test 4: Conflicting parameters (should fail)
    timer = sw.Stopwatch( msg="Testing conflicting parameters...", silent=False )
    try:
        config_mgr = ConfigurationManager(
            env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS",
            config_path="/some/path",
            splainer_path="/some/path",
            _reset_singleton=True
        )
        print( "❌ ERROR: Conflicting parameters succeeded but should have failed" )
    except ValueError as e:
        print( f"✅ Expected error: {str( e )}" )
    timer.print( "Test complete", use_millis=True )
    
    # Test 5: Incomplete explicit paths (should fail)
    timer = sw.Stopwatch( msg="Testing incomplete paths...", silent=False )
    try:
        # Only provide config_path without splainer_path
        config_mgr = ConfigurationManager(
            config_path="/some/path", 
            _reset_singleton=True
        )
        print( "❌ ERROR: Incomplete paths succeeded but should have failed" )
    except ValueError as e:
        print( f"✅ Expected error: {str( e )}" )
    timer.print( "Test complete", use_millis=True )
    
    du.print_banner( "All tests completed", prepend_nl=True, chunk="✨ " )


if __name__ == "__main__":
    quick_smoke_test()
