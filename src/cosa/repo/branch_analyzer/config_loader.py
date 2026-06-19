"""
Configuration Loader for Branch Analyzer

Handles loading and validating YAML configuration files. Provides defaults
from embedded default_config.yaml and supports user overrides.

Design Principles:
- Fail fast with clear error messages
- Validate all configuration values at load time
- Support partial overrides (merge with defaults)
- Provide access helpers for nested configuration

Usage:
    from cosa.repo.branch_analyzer.config_loader import ConfigLoader

    loader = ConfigLoader( config_path='my_config.yaml', debug=True )
    config = loader.load()

    # Access nested values
    base_branch = config['git']['default_base_branch']
    file_types = config['file_types']['extensions']

    # Or use helper method
    base_branch = loader.get( 'git.default_base_branch', default='main' )
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from .exceptions import ConfigurationError


class ConfigLoader:
    """
    Loads and validates YAML configuration files.

    Provides configuration loading with defaults, validation, and
    convenient access methods for nested configuration values.
    """

    def __init__( self, config_path: Optional[str] = None, debug: bool = False ):
        """
        Initialize configuration loader.

        Requires:
            - config_path is None or valid file path
            - debug is boolean

        Ensures:
            - Loader initialized and ready to load configuration
            - Default config path identified

        Raises:
            - ConfigurationError if default config cannot be located
        """
        self.config_path = config_path
        self.debug       = debug
        self.config      = None

        # Locate default config file (in same directory as this module)
        module_dir         = Path( __file__ ).parent
        self.default_path  = module_dir / 'default_config.yaml'

        if not self.default_path.exists():
            raise ConfigurationError(
                message     = "Default configuration file not found",
                config_path = str( self.default_path )
            )

        if self.debug:
            print( f"[ConfigLoader] Default config: {self.default_path}" )
            if self.config_path:
                print( f"[ConfigLoader] User config: {self.config_path}" )

    def load( self ) -> Dict[str, Any]:
        """
        Load configuration from files.

        Loads default configuration first, then merges user configuration
        if provided. Validates the final configuration.

        Requires:
            - Default config file exists and is valid YAML

        Ensures:
            - Returns complete configuration dict
            - All required fields present
            - All values validated

        Raises:
            - ConfigurationError if loading or validation fails
        """
        # Load default configuration
        default_config = self._load_yaml_file( self.default_path )

        if self.debug:
            print( f"[ConfigLoader] Loaded default config: {len(default_config)} top-level keys" )

        # If no user config, use defaults
        if not self.config_path:
            self.config = default_config
        else:
            # Load user configuration
            user_config = self._load_yaml_file( Path( self.config_path ) )

            if self.debug:
                print( f"[ConfigLoader] Loaded user config: {len(user_config)} top-level keys" )

            # Merge configurations (user overrides defaults)
            self.config = self._merge_configs( default_config, user_config )

        # Validate configuration
        self._validate_config( self.config )

        if self.debug:
            print( "[ConfigLoader] Configuration validated successfully" )

        return self.config

    def get( self, key_path: str, default: Any = None ) -> Any:
        """
        Get configuration value by dot-separated key path.

        Example:
            value = loader.get( 'git.default_base_branch', default='main' )

        Requires:
            - key_path is non-empty string
            - Configuration has been loaded (self.config is not None)

        Ensures:
            - Returns configuration value if found
            - Returns default if key path not found

        Raises:
            - ValueError if configuration not loaded yet
        """
        if self.config is None:
            raise ValueError( "Configuration not loaded. Call load() first." )

        # Split key path and traverse config dict
        keys = key_path.split( '.' )
        current = self.config

        for key in keys:
            if isinstance( current, dict ) and key in current:
                current = current[key]
            else:
                return default

        return current

    def _load_yaml_file( self, path: Path ) -> Dict[str, Any]:
        """
        Load and parse YAML file.

        Requires:
            - path is Path object
            - File exists at path

        Ensures:
            - Returns dict parsed from YAML
            - Empty sections represented as empty dicts

        Raises:
            - ConfigurationError if file not found or invalid YAML
        """
        if not path.exists():
            raise ConfigurationError(
                message     = f"Configuration file not found: {path}",
                config_path = str( path )
            )

        try:
            with open( path, 'r', encoding='utf-8' ) as f:
                config = yaml.safe_load( f )

            # yaml.safe_load returns None for empty files
            if config is None:
                config = {}

            if not isinstance( config, dict ):
                raise ConfigurationError(
                    message     = "Configuration must be a YAML dictionary",
                    config_path = str( path ),
                    value       = type( config ).__name__
                )

            return config

        except yaml.YAMLError as e:
            raise ConfigurationError(
                message     = f"Invalid YAML syntax: {e}",
                config_path = str( path )
            )
        except Exception as e:
            raise ConfigurationError(
                message     = f"Failed to read configuration file: {e}",
                config_path = str( path )
            )

    def _merge_configs( self, default: Dict[str, Any], user: Dict[str, Any] ) -> Dict[str, Any]:
        """
        Recursively merge user config into default config.

        User values override defaults. For nested dicts, performs deep merge.

        Requires:
            - default is dict
            - user is dict

        Ensures:
            - Returns merged configuration dict
            - User values override defaults
            - Nested dicts are deep merged

        Raises:
            - ConfigurationError if merge creates invalid structure
        """
        merged = default.copy()

        for key, user_value in user.items():
            if key in merged and isinstance( merged[key], dict ) and isinstance( user_value, dict ):
                # Recursively merge nested dicts
                merged[key] = self._merge_configs( merged[key], user_value )
            else:
                # Override with user value
                merged[key] = user_value

        return merged

    def _validate_config( self, config: Dict[str, Any] ) -> None:
        """
        Validate configuration structure and values.

        Requires:
            - config is dict

        Ensures:
            - All required sections present
            - All values have valid types
            - Enum values are valid choices

        Raises:
            - ConfigurationError if validation fails
        """
        # Required top-level sections
        required_sections = ['git', 'file_types', 'analysis', 'output', 'formatting']

        for section in required_sections:
            if section not in config:
                raise ConfigurationError(
                    message = f"Missing required configuration section: {section}",
                    field   = section
                )

        # Validate git section
        self._validate_git_section( config['git'] )

        # Validate file_types section
        self._validate_file_types_section( config['file_types'] )

        # Validate analysis section
        self._validate_analysis_section( config['analysis'] )

        # Validate output section
        self._validate_output_section( config['output'] )

        # Validate formatting section
        self._validate_formatting_section( config['formatting'] )

    def _validate_git_section( self, git_config: Dict[str, Any] ) -> None:
        """Validate git configuration section."""
        required_fields = ['default_base_branch', 'default_head_branch', 'diff_algorithm']

        for field in required_fields:
            if field not in git_config:
                raise ConfigurationError(
                    message = f"Missing required git config field: {field}",
                    field   = f"git.{field}"
                )

        # Validate diff_algorithm
        valid_algorithms = ['myers', 'minimal', 'patience', 'histogram']
        algorithm = git_config['diff_algorithm']
        if algorithm not in valid_algorithms:
            raise ConfigurationError(
                message = f"Invalid diff_algorithm. Must be one of: {', '.join(valid_algorithms)}",
                field   = "git.diff_algorithm",
                value   = algorithm
            )

    def _validate_file_types_section( self, file_types_config: Dict[str, Any] ) -> None:
        """Validate file_types configuration section."""
        if 'extensions' not in file_types_config:
            raise ConfigurationError(
                message = "Missing required field: extensions",
                field   = "file_types.extensions"
            )

        extensions = file_types_config['extensions']
        if not isinstance( extensions, dict ):
            raise ConfigurationError(
                message = "extensions must be a dictionary mapping extensions to types",
                field   = "file_types.extensions",
                value   = type( extensions ).__name__
            )

    def _validate_analysis_section( self, analysis_config: Dict[str, Any] ) -> None:
        """Validate analysis configuration section."""
        # All analysis fields are optional booleans
        boolean_fields = [
            'separate_code_comments',
            'track_docstrings',
            'track_blank_lines',
            'multiline_comment_detection'
        ]

        for field in boolean_fields:
            if field in analysis_config and not isinstance( analysis_config[field], bool ):
                raise ConfigurationError(
                    message = f"{field} must be a boolean",
                    field   = f"analysis.{field}",
                    value   = analysis_config[field]
                )

    def _validate_output_section( self, output_config: Dict[str, Any] ) -> None:
        """Validate output configuration section."""
        if 'default_format' in output_config:
            valid_formats = ['console', 'json', 'markdown']
            format_val = output_config['default_format']
            if format_val not in valid_formats:
                raise ConfigurationError(
                    message = f"Invalid default_format. Must be one of: {', '.join(valid_formats)}",
                    field   = "output.default_format",
                    value   = format_val
                )

    def _validate_formatting_section( self, formatting_config: Dict[str, Any] ) -> None:
        """Validate formatting configuration section."""
        if 'column_widths' in formatting_config:
            widths = formatting_config['column_widths']
            if not isinstance( widths, dict ):
                raise ConfigurationError(
                    message = "column_widths must be a dictionary",
                    field   = "formatting.column_widths",
                    value   = type( widths ).__name__
                )
