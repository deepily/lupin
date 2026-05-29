"""
Directory Analyzer Custom Exceptions

Provides hierarchical exception types for specific error conditions in the
directory analysis workflow. All exceptions inherit from DirectoryAnalyzerError
for easy catching of any package-specific errors.

Exception Hierarchy:
    DirectoryAnalyzerError (base)
    ├── ScannerError (filesystem traversal issues)
    ├── ConfigurationError (config file/validation issues)
    └── FileReadError (file reading problems)

Usage:
    from cosa.repo.directory_analyzer.exceptions import ScannerError

    try:
        for file_info in scanner.scan( '/path/to/dir' ):
            process( file_info )
    except ScannerError as e:
        print( f"Scanner error: {e.message}" )
        print( f"Path: {e.path}" )

Design Principles:
- Specific exception types for different failure modes
- Context preservation (original exceptions, path details)
- Human-readable error messages with recovery suggestions
- Support for programmatic error handling
"""


class DirectoryAnalyzerError( Exception ):
    """
    Base exception for all directory analyzer errors.

    All package-specific exceptions inherit from this class, allowing
    consumers to catch any directory analyzer error with a single except clause.

    Attributes:
        message (str): Human-readable error message
        context (dict): Optional context information
    """

    def __init__( self, message, context=None ):
        """
        Initialize base exception.

        Requires:
            - message is non-empty string
            - context is None or dict

        Ensures:
            - Exception initialized with message and optional context
        """
        super().__init__( message )
        self.message = message
        self.context = context or {}

    def __str__( self ):
        """
        String representation of exception.

        Ensures:
            - Returns formatted error message with context if available
        """
        if self.context:
            context_str = ", ".join( f"{k}={v}" for k, v in self.context.items() )
            return f"{self.message} (Context: {context_str})"
        return self.message


class ScannerError( DirectoryAnalyzerError ):
    """
    Exception raised when directory scanning fails.

    This exception captures details about the failed scan operation including
    the path being scanned and any underlying error.

    Attributes:
        message (str): Human-readable error message
        path (str): The path that caused the error
        original_error (Exception): The underlying exception, if any

    Example:
        raise ScannerError(
            message        = "Cannot access directory",
            path           = "/protected/folder",
            original_error = PermissionError( "Access denied" )
        )
    """

    def __init__( self, message, path=None, original_error=None ):
        """
        Initialize scanner error.

        Requires:
            - message is non-empty string
            - path is None or string
            - original_error is None or Exception

        Ensures:
            - Exception initialized with scanner context
        """
        context = {
            'path'           : path,
            'original_error' : str( original_error )[:200] if original_error else None
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.path           = path
        self.original_error = original_error


class ConfigurationError( DirectoryAnalyzerError ):
    """
    Exception raised when configuration loading or validation fails.

    This exception is raised for various configuration problems including
    missing files, invalid YAML syntax, missing required fields, or
    invalid configuration values.

    Attributes:
        message (str): Human-readable error message
        config_path (str): Path to configuration file (if applicable)
        field (str): Specific configuration field causing error (if applicable)
        value (any): Invalid value (if applicable)

    Example:
        raise ConfigurationError(
            message     = "Invalid exclusion pattern",
            config_path = "/path/to/config.yaml",
            field       = "directory.exclude_dirs",
            value       = {"invalid": 123}
        )
    """

    def __init__( self, message, config_path=None, field=None, value=None ):
        """
        Initialize configuration error.

        Requires:
            - message is non-empty string
            - config_path is None or string
            - field is None or string
            - value is any type

        Ensures:
            - Exception initialized with configuration context
        """
        context = {
            'config_path' : config_path,
            'field'       : field,
            'value'       : str( value )[:100] if value is not None else None
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.config_path = config_path
        self.field       = field
        self.value       = value


class FileReadError( DirectoryAnalyzerError ):
    """
    Exception raised when file reading fails.

    This exception is raised when a file cannot be read, typically due to
    encoding issues, permission problems, or the file being binary.

    Attributes:
        message (str): Human-readable error message
        file_path (str): Path to the file that couldn't be read
        encoding (str): Encoding that was attempted (if applicable)
        original_error (Exception): The underlying exception, if any

    Example:
        raise FileReadError(
            message        = "Cannot decode file",
            file_path      = "/path/to/binary.dat",
            encoding       = "utf-8",
            original_error = UnicodeDecodeError( ... )
        )
    """

    def __init__( self, message, file_path=None, encoding=None, original_error=None ):
        """
        Initialize file read error.

        Requires:
            - message is non-empty string
            - file_path is None or string
            - encoding is None or string
            - original_error is None or Exception

        Ensures:
            - Exception initialized with file reading context
        """
        context = {
            'file_path'      : file_path,
            'encoding'       : encoding,
            'original_error' : str( original_error )[:200] if original_error else None
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.file_path      = file_path
        self.encoding       = encoding
        self.original_error = original_error
