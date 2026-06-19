"""
Branch Analyzer Custom Exceptions

Provides hierarchical exception types for specific error conditions in the
branch analysis workflow. All exceptions inherit from BranchAnalyzerError
for easy catching of any package-specific errors.

Exception Hierarchy:
    BranchAnalyzerError (base)
    ├── GitCommandError (git subprocess failures)
    ├── ConfigurationError (config file/validation issues)
    ├── ParserError (diff parsing problems)
    └── ClassificationError (file/line classification issues)

Usage:
    from cosa.repo.branch_analyzer.exceptions import GitCommandError

    try:
        result = run_git_command( 'diff', 'main...HEAD' )
    except GitCommandError as e:
        print( f"Git error: {e.message}" )
        print( f"Command: {e.command}" )
        print( f"Return code: {e.return_code}" )

Design Principles:
- Specific exception types for different failure modes
- Context preservation (original exceptions, command details)
- Human-readable error messages with recovery suggestions
- Support for programmatic error handling
"""


class BranchAnalyzerError( Exception ):
    """
    Base exception for all branch analyzer errors.

    All package-specific exceptions inherit from this class, allowing
    consumers to catch any branch analyzer error with a single except clause.

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


class GitCommandError( BranchAnalyzerError ):
    """
    Exception raised when git command execution fails.

    This exception captures details about the failed git command including
    the command itself, return code, and stderr output for debugging.

    Attributes:
        message (str): Human-readable error message
        command (list): The git command that was executed
        return_code (int): Process return code
        stderr (str): Standard error output from git
        stdout (str): Standard output from git (if any)

    Example:
        raise GitCommandError(
            message     = "Failed to get git diff",
            command     = ['git', 'diff', 'main...HEAD'],
            return_code = 128,
            stderr      = "fatal: ambiguous argument 'main...HEAD'"
        )
    """

    def __init__( self, message, command=None, return_code=None, stderr=None, stdout=None ):
        """
        Initialize git command error.

        Requires:
            - message is non-empty string
            - command is None or list of strings
            - return_code is None or integer
            - stderr is None or string
            - stdout is None or string

        Ensures:
            - Exception initialized with command execution details
        """
        context = {
            'command'     : command,
            'return_code' : return_code,
            'stderr'      : stderr[:200] if stderr else None,  # Truncate long errors
            'stdout'      : stdout[:200] if stdout else None
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.command     = command
        self.return_code = return_code
        self.stderr      = stderr
        self.stdout      = stdout


class ConfigurationError( BranchAnalyzerError ):
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
            message     = "Invalid file type mapping",
            config_path = "/path/to/config.yaml",
            field       = "file_types.extensions",
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


class ParserError( BranchAnalyzerError ):
    """
    Exception raised when diff parsing encounters problems.

    This exception is raised when the git diff output cannot be parsed
    correctly, typically due to unexpected format, encoding issues, or
    malformed diff hunks.

    Attributes:
        message (str): Human-readable error message
        line_number (int): Line number where parsing failed (if applicable)
        line_content (str): Content of problematic line (if applicable)
        parser_stage (str): Stage of parsing where error occurred

    Example:
        raise ParserError(
            message      = "Malformed diff hunk header",
            line_number  = 42,
            line_content = "@@ invalid hunk @@",
            parser_stage = "hunk_header"
        )
    """

    def __init__( self, message, line_number=None, line_content=None, parser_stage=None ):
        """
        Initialize parser error.

        Requires:
            - message is non-empty string
            - line_number is None or positive integer
            - line_content is None or string
            - parser_stage is None or string

        Ensures:
            - Exception initialized with parsing context
        """
        context = {
            'line_number'  : line_number,
            'line_content' : line_content[:100] if line_content else None,
            'parser_stage' : parser_stage
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.line_number  = line_number
        self.line_content = line_content
        self.parser_stage = parser_stage


class ClassificationError( BranchAnalyzerError ):
    """
    Exception raised when file or line classification fails.

    This exception is raised when the classifier encounters unexpected
    input or internal errors during classification operations.

    Attributes:
        message (str): Human-readable error message
        filename (str): File being classified (if applicable)
        line_content (str): Line being classified (if applicable)
        classifier_type (str): Type of classifier (file/line)

    Example:
        raise ClassificationError(
            message         = "Unexpected line format",
            filename        = "test.py",
            line_content    = "\x00\x01\x02",
            classifier_type = "line"
        )
    """

    def __init__( self, message, filename=None, line_content=None, classifier_type=None ):
        """
        Initialize classification error.

        Requires:
            - message is non-empty string
            - filename is None or string
            - line_content is None or string
            - classifier_type is None or string in ('file', 'line')

        Ensures:
            - Exception initialized with classification context
        """
        context = {
            'filename'        : filename,
            'line_content'    : line_content[:100] if line_content else None,
            'classifier_type' : classifier_type
        }
        # Remove None values
        context = { k: v for k, v in context.items() if v is not None }

        super().__init__( message, context )
        self.filename        = filename
        self.line_content    = line_content
        self.classifier_type = classifier_type
