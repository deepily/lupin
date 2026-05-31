import os
import stat
import pwd
import grp
import regex as re
import random
import sys
from datetime import datetime as dt
from datetime import timedelta as td
import pytz
import json
import traceback
from typing import Any, Optional, Union, Set, Callable

debug = False


def init(d: bool) -> None:
    """
    Initialize the debug flag for the utility module.
    
    Requires:
        - d is a boolean value
        
    Ensures:
        - Global debug flag is set to the provided value
        
    Args:
        d: Boolean value to set the debug flag to
    """
    global debug
    debug = d

def add_to_path(path: str, idx: int = None) -> None:
    """
    Add a path to the Python module search path (sys.path).
    
    Requires:
        - path is a valid string path
        
    Ensures:
        - path is added to sys.path if not already present
        - Appropriate message is printed to console
        
    Args:
        path: The directory path to add to sys.path
    """
    if path not in sys.path:
        if idx is not None:
            sys.path.insert(idx, path)
            print(f"Inserted [{path}] into sys.path at index {idx}")
        else:
            sys.path.append(path)
        print(f"Added [{path}] to sys.path")
    else:
        print(f"Path [{path}] already in sys.path")


def get_current_datetime_raw(tz_name: str = "US/Eastern", days_offset: int = 0) -> dt:
    """
    Get a datetime object for the current time in a specified timezone with optional offset.
    
    Requires:
        - tz_name is a valid timezone string recognized by pytz
        - days_offset is an integer (positive or negative)
        
    Ensures:
        - Returns a datetime object in the specified timezone
        - The datetime is offset by the specified number of days from the current time
        
    Args:
        tz_name: The name of the timezone (default: "US/Eastern")
        days_offset: Number of days to offset from current time (default: 0)
        
    Returns:
        A datetime object in the specified timezone, offset by days_offset
        
    Raises:
        pytz.exceptions.UnknownTimeZoneError: If tz_name is not a valid timezone
    """
    # Get the current UTC time plus or minus the specified days_offset
    # FIXED: Start with UTC-aware datetime to ensure correct timezone conversion
    # (Previously used naive dt.now() which assumes system local timezone)
    now = dt.now( pytz.UTC )
    delta = td( days=days_offset )
    now = now + delta
    tz = pytz.timezone( tz_name )
    tz_date = now.astimezone( tz )

    return tz_date


def get_current_datetime(tz_name: str = "US/Eastern", format_str: str = '%Y-%m-%d @ %H:%M:%S %Z') -> str:
    """
    Get a formatted string of the current date and time in the specified timezone.
    
    Requires:
        - tz_name is a valid timezone string recognized by pytz
        - format_str is a valid strftime format string
        
    Ensures:
        - Returns a formatted date-time string using the specified format
        - Default format: "YYYY-MM-DD @ HH:MM:SS TZ"
        - Microsecond format: "YYYY-MM-DD @ HH:MM:SS.ffffff TZ"
        
    Args:
        tz_name: The name of the timezone (default: "US/Eastern")
        format_str: strftime format string (default: '%Y-%m-%d @ %H:%M:%S %Z')
        
    Returns:
        A formatted date-time string
        
    Raises:
        pytz.exceptions.UnknownTimeZoneError: If tz_name is not a valid timezone
    """
    tz_date = get_current_datetime_raw(tz_name)

    return tz_date.strftime(format_str)


def get_current_datetime_iso( tz_name: str = "US/Eastern" ) -> str:
    """
    Get an ISO 8601 formatted datetime string with timezone offset.

    Designed for frontend-facing timestamps where JavaScript's new Date()
    needs to parse the string correctly regardless of browser timezone.

    Requires:
        - tz_name is a valid timezone string recognized by pytz

    Ensures:
        - Returns an ISO 8601 string with UTC offset (e.g., "2026-04-08T14:08:19.123456-04:00")
        - Timezone-aware: JavaScript new Date() correctly handles the offset
        - Consistent with the system's Eastern timezone convention

    Args:
        tz_name: The name of the timezone (default: "US/Eastern")

    Returns:
        An ISO 8601 formatted datetime string with timezone offset

    Raises:
        pytz.exceptions.UnknownTimeZoneError: If tz_name is not a valid timezone
    """
    return get_current_datetime_raw( tz_name ).isoformat()


def get_current_date(tz_name: str = "US/Eastern", return_prose: bool = False, offset: int = 0) -> str:
    """
    Get the current date in the specified timezone with optional formatting.
    
    Requires:
        - tz_name is a valid timezone string recognized by pytz
        - return_prose is a boolean indicating format preference
        - offset is an integer (positive or negative)
        
    Ensures:
        - Returns a date string in either YYYY-MM-DD format or prose format
        - The date is offset by the specified number of days from current date
        
    Args:
        tz_name: The name of the timezone (default: "US/Eastern")
        return_prose: Whether to return the date in prose format (default: False)
            If True, returns format: "Monday, January 01, 2021"
            If False, returns format: "2021-01-01"
        offset: Number of days to offset from the current date (default: 0)
        
    Returns:
        A formatted date string
        
    Raises:
        pytz.exceptions.UnknownTimeZoneError: If tz_name is not a valid timezone
    """
    tz_date = get_current_datetime_raw(tz_name, days_offset=offset)

    if return_prose:
        return tz_date.strftime("%A, %B %d, %Y")
    else:
        return tz_date.strftime("%Y-%m-%d")


def get_current_time(tz_name: str = "US/Eastern", include_timezone: bool = True, format: str = "%H:%M:%S") -> str:
    """
    Get the current time in a specified timezone with optional timezone information.
    
    Requires:
        - tz_name is a valid timezone string recognized by pytz
        - include_timezone is a boolean indicating whether to include timezone in output
        - format is a valid datetime format string for strftime
        
    Ensures:
        - Returns a formatted time string according to the specified format
        - Includes timezone abbreviation if include_timezone is True
        
    Args:
        tz_name: The name of the timezone (default: "US/Eastern")
        include_timezone: Whether to include timezone information (default: True)
        format: The format string for time formatting (default: "%H:%M:%S")
        
    Returns:
        A formatted time string
        
    Raises:
        pytz.exceptions.UnknownTimeZoneError: If tz_name is not a valid timezone
        ValueError: If format string contains invalid directives
    """
    tz_date = get_current_datetime_raw(tz_name)

    if include_timezone:
        return tz_date.strftime(format + " %Z")
    else:
        return tz_date.strftime(format)


def get_timestamp_ms() -> dt:
    """
    Get current timestamp with millisecond precision for LanceDB compatibility.

    Requires:
        - Nothing

    Ensures:
        - Returns datetime object with microseconds truncated to millisecond precision
        - Compatible with PyArrow timestamp('ms') schema fields
        - Avoids LanceDB casting errors from microsecond to millisecond precision

    Returns:
        datetime object with millisecond precision
    """
    now = dt.now()
    # Truncate to milliseconds to match LanceDB schema expectations
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def get_name_value_pairs(arg_list: list[str], debug: bool = False, verbose: bool = False) -> dict[str, str]:
    """
    Parses a list of strings -- name=value -- into dictionary format { "name":"value" }

    Requires:
        - arg_list is a list of strings
        
    Ensures:
        - Returns dictionary mapping names to values
        - Skips the first element in arg_list
        - Only processes strings containing "="
        
    Args:
        arg_list: Space delimited input from CLI
        debug: Whether to print debug information
        verbose: Whether to print verbose output
        
    Returns:
        Dictionary of name=value pairs
    """

    # Quick sanity check. Do we have anything to iterate?
    if debug: print("Length of arg_list [{}]".format(len(arg_list)))
    if len(arg_list) <= 1: return {}

    name_value_pairs = {}

    # add a little whitespace
    if debug: print()

    for i, arg in enumerate(arg_list):

        if debug: print("[{0}]th arg = [{1}]... ".format(i, arg_list[i]), end="")

        if "=" in arg:
            pair = arg.split("=")
            name_value_pairs[pair[0]] = pair[1]
            if debug: print("done!")
        else:
            if debug: print("SKIPPING, name=value format not found")

    if debug: print()
    if debug: print("Name value dictionary pairs:", end="\n\n")

    # get max width for right justification
    if name_value_pairs:
        max_len = max([len(key) for key in name_value_pairs.keys()]) + 1
    else:
        max_len = 1  # Default width when no pairs exist

    # iterate keys and print values w/ this format:
    #       [foo] = [bar]
    # [flibberty] = [jibbet]
    names = list(name_value_pairs.keys())
    names.sort()

    for name in names:
        if debug and verbose: print("[{0}] = [{1}]".format(("[ " + name).rjust(max_len, " "), name_value_pairs[name]))
    if debug and verbose: print()

    return name_value_pairs


def get_file_as_source_code_with_line_numbers(path: str) -> str:
    """
    Read a file and return its contents with line numbers prepended.
    
    Requires:
        - path is a valid file path
        
    Ensures:
        - Returns file contents as a string with line numbers
        - Line numbers are formatted as 3-digit zero-padded numbers
        
    Args:
        path: The path to the file to read
        
    Returns:
        File contents with line numbers prepended
    """
    source_code = get_file_as_list(path, lower_case=False, clean=False, randomize=False)
    return get_source_code_with_line_numbers(source_code)


def get_source_code_with_line_numbers(source_code: list[str], join_str: str = "") -> str:
    """
    Add line numbers to source code lines and join them into a single string.
    
    Requires:
        - source_code is a list of strings representing code lines
        - join_str is a string to use for joining lines
        
    Ensures:
        - Returns a string with line numbers prepended to each line
        - Line numbers are formatted as 3-digit zero-padded numbers
        - Lines are joined with the specified join_str
        
    Args:
        source_code: List of source code lines
        join_str: String to use for joining lines (default: empty string)
        
    Returns:
        Source code with line numbers as a single string
    """
    # iterate through the source code and prepend the line number to each line
    for i in range(len(source_code)):
        source_code[i] = f"{i + 1:03d} {source_code[i]}"

    # join the lines back together into a single string
    source_code = join_str.join(source_code)

    return source_code


def get_file_as_list( path: str, lower_case: bool = False, clean: bool = False, randomize: bool = False, seed: int = 42,
                      strip_newlines: bool = False, skip_empty: bool = False, skip_comments: bool = False ) -> list[str]:
    """Load a plain text file as a list of lines.

    Requires:
        - path is a valid file path

    Ensures:
        - Returns list of lines from file
        - Applies transformations based on parameters
        - Lines are lowercased if lower_case=True
        - Lines are stripped if clean=True
        - Empty lines are removed if skip_empty=True
        - Lines starting with '#' are removed if skip_comments=True
        - List is shuffled if randomize=True
    """

    with open( path, "r", encoding="utf-8" ) as file:
        lines = file.readlines()

    if lower_case:
        lines = [line.lower() for line in lines]

    if clean:
        lines = [line.strip() for line in lines]

    if strip_newlines:
        lines = [line.strip( "\n" ) for line in lines]

    if skip_empty:
        lines = [line for line in lines if line.strip()]

    if skip_comments:
        lines = [line for line in lines if not line.strip().startswith( "#" )]

    if randomize:
        random.seed( seed )
        random.shuffle( lines )

    return lines


def get_file_as_string(path: str) -> str:
    """
    Read a file and return its contents as a string.
    
    Requires:
        - path is a valid file path
        - File exists and is readable
        
    Ensures:
        - Returns the entire contents of the file as a string
        
    Args:
        path: The path to the file to read
        
    Returns:
        The contents of the file as a string
        
    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If the file cannot be read due to permissions
    """
    with open(path, "r") as file:
        return file.read()


def get_file_as_json(path: str) -> Any:
    """
    Read a JSON file and return its parsed contents.
    
    Requires:
        - path is a valid file path
        - File exists and contains valid JSON
        
    Ensures:
        - Returns the parsed JSON content as Python objects
        
    Args:
        path: The path to the JSON file to read
        
    Returns:
        The parsed JSON content (could be dict, list, etc.)
        
    Raises:
        FileNotFoundError: If the file does not exist
        json.JSONDecodeError: If the file contains invalid JSON
    """
    with open(path, "r") as file:
        return json.load(file)


def get_file_as_dictionary(path: str, lower_case: bool = False, omit_comments: bool = True, debug: bool = False,
                           verbose: bool = False) -> dict[str, str]:
    """Load a file as a dictionary with key=value pairs.
    
    Requires:
        - path is a valid file path
        - File contains lines in format "key = value"
        
    Ensures:
        - Returns dictionary of key-value pairs
        - Skips comment lines starting with # or //
        - Removes pipe symbols from start/end of keys/values
        
    Note:
        The pipe symbol is a reserved character used to delimit white space.
    """

    lines = get_file_as_list(path, lower_case=lower_case)

    lines_as_dict = {}

    # Delete the first and last type symbols if they're there
    pipe_regex = re.compile( r"^\||\|$" )

    for line in lines:

        # Skip comments: if a line starts with # or // then skip it
        if omit_comments and (line.startswith("#") or line.startswith("//")):
            continue

        pair = line.strip().split(" = ")
        if len(pair) > 1:
            if debug and verbose: print("[{}] = [{}]".format(pair[0], pair[1]))
            # Only pull pipes after the key and values have been stripped.
            p0 = pipe_regex.sub("", pair[0].strip())
            p1 = pipe_regex.sub("", pair[1].strip())
            lines_as_dict[p0] = p1
        # else:
        #     if debug: print("ERROR: [{}]".format(pair[0]))

    return lines_as_dict


def write_lines_to_file(path: str, lines: list[str], strip_blank_lines: bool = False,
                        world_read_write: bool = False) -> None:
    """
    Write a list of lines to a file.
    
    Requires:
        - path is a valid writable file path
        - lines is a list of strings
        
    Ensures:
        - Writes lines to file joined by newlines
        - Strips blank lines if requested
        - Sets world read/write permissions if requested
    """

    if strip_blank_lines:
        lines = [line for line in lines if line.strip() != ""]

    with open(path, "w") as outfile:
        outfile.write("\n".join(lines))

    if world_read_write: os.chmod(path, 0o666)


def write_string_to_file(path: str, string: str) -> None:
    """
    Write a string to a file.
    
    Requires:
        - path is a valid writable file path
        - string is the content to write
        
    Ensures:
        - Writes string to file
        - Overwrites existing file if present
    """

    with open(path, "w") as outfile:
        outfile.write(string)


import subprocess


def print_simple_file_list(path: str) -> None:
    """
    Prints a detailed file listing for the specified directory.
    
    Preconditions:
        - path must be a string representing a file system path
        - path must exist in the file system
        - Current user must have read permissions for the specified path
    
    Postconditions:
        - Detailed file listing is printed to stdout
        - Each line of output is printed separately
        - Original path remains unchanged
    
    Parameters:
        path (str): The directory path to list files from
    
    Raises:
        FileNotFoundError: When path does not exist
        subprocess.CalledProcessError: When shell command execution fails
    """
    # Verify that the path exists
    if not os.path.exists(path):
        raise FileNotFoundError(f"The path '{path}' does not exist.")

    # Construct the command
    command = ['ls', '-alh', path]

    try:
        # Execute the command and capture the output
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        print_list(result.stdout.split("\n"))
    except subprocess.CalledProcessError as e:
        # Handle errors in the execution of the command
        raise subprocess.CalledProcessError(e.returncode, e.cmd, output=e.output, stderr=e.stderr)


def print_banner(msg: str, expletive: bool = False, chunk: str = "¡@#!-$?%^_¿",
                 end: str = "\n\n", prepend_nl: bool = False, flex: bool = False) -> None:
    """
    Print a message to console with decorative header/footer lines.
    
    Requires:
        - msg is a string to display in the banner
        - expletive is a boolean controlling display style
        - chunk is a string used for decoration in expletive mode
        
    Ensures:
        - Prints the message with decorative lines above and below
        - Uses expletive decoration style if expletive=True
        - Uses flexible width if flex=True
        - Prepends a newline if prepend_nl=True
        
    Args:
        msg: The message to print in the banner
        expletive: Whether to use "cartoon-style" error decoration (default: False)
        chunk: The string to use for expletive decoration (default: "¡@#!-$?%^_¿")
        end: The string to print after the banner (default: "\n\n")
        prepend_nl: Whether to print a newline before the banner (default: False)
        flex: Whether to adapt line length to message length (default: False)
        
    Returns:
        None, prints to console
    """
    if prepend_nl: print()

    max_len = 120
    if expletive:

        bar_str = ""
        while len(bar_str) < max_len:
            bar_str += chunk

    elif flex:

        # Get max length of string, Splitting onCharacters
        bar_len = max([len(line) for line in msg.split("\n")] + [max_len]) + 2
        print(bar_len)
        bar_str = ""
        while len(bar_str) < bar_len:
            bar_str += "-"

    else:

        bar_str = ""
        while len(bar_str) < max_len:
            bar_str += "-"

    print(bar_str)
    if expletive:
        print(chunk)
        print(chunk, msg)
        print(chunk)
    else:
        print("-", msg)
    print(bar_str, end=end)


def get_project_root() -> str:
    """
    Get the root directory path of the project.
    
    Requires:
        - None
        
    Ensures:
        - Returns a valid directory path for the project root
        - Uses environment variable if available
        - Falls back to default path if needed
        
    Returns:
        The absolute path to the project root directory
        
    Notes:
        If running in a Docker container, returns the container's root path.
        Otherwise, uses the LUPIN_ROOT environment variable.
    """
    if debug:
        print(f" LUPIN_ROOT [{os.getenv('LUPIN_ROOT')}]")
        print(f"os.getcwd() [{os.getcwd()}]")

    if "LUPIN_ROOT" in os.environ:
        return os.environ["LUPIN_ROOT"]
    else:
        path = "/var/lupin"
        print(f"WARNING: LUPIN_ROOT not found in environment variables. Returning default path '{path}'")
        return path


def get_tts_interaction_mode() -> str:
    """
    Get the global TTS interaction mode from configuration.

    Requires:
        - ConfigurationManager is importable
        - "tts interaction mode" key may or may not be set in lupin-app.ini
        - LUPIN_CONFIG_MGR_CLI_ARGS env var is set on first singleton init (subsequent
          calls reuse the existing instance and the kwarg is ignored)

    Ensures:
        - returns "solo" or "chorus" (string)
        - returns "chorus" if key is absent (the operational default per 2026-05-12)
        - returns "chorus" if key is present but has an invalid value (fail-closed to default)
        - never raises (config errors fall back to "chorus")

    Raises:
        - never
    """
    from cosa.config.configuration_manager import ConfigurationManager
    try:
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        mode       = config_mgr.get( "tts interaction mode", default="chorus", return_type="string" )
    except Exception:
        return "chorus"
    if mode not in ( "solo", "chorus" ):
        return "chorus"
    return mode


def get_api_key(key_name: str, project_root: str = None) -> Optional[str]:
    """
    Get an API key from the configuration directory.
    
    Requires:
        - key_name is a non-empty string
        - project_root is a valid directory path or None
        
    Ensures:
        - Returns the API key as a string if found
        - Returns None if the key file doesn't exist
        - Prints error message if key isn't found
        
    Args:
        key_name: The name of the API key to fetch
        project_root: The project root directory (default: result of get_project_root())
        
    Returns:
        The API key as a string, or None if not found
    """
    if project_root is None:
        project_root = get_project_root()

    path = project_root + f"/src/conf/keys/{key_name}"
    if debug: print(f"Fetching [{key_name}] from [{path}]...")

    # Test path to see if key exists
    if not os.path.exists(path):
        print_banner(f"ERROR: Key [{key_name}] not found at [{path}]")
        return None

    return get_file_as_string(path).strip()


def generate_domain_names(count: int = 10, remove_dots: bool = False, debug: bool = False) -> list[str]:
    """
    Generate a list of random domain names.
    
    Requires:
        - count is a positive integer
        - remove_dots is a boolean
        
    Ensures:
        - Returns a list of 'count' random domain names
        - Domain names follow pattern: [subdomain][adjective][noun][tld]
        - Dots are removed from domains if remove_dots is True
        - Domains are printed to console if debug is True
        
    Args:
        count: Number of domain names to generate (default: 10)
        remove_dots: Whether to remove dots from domains (default: False)
        debug: Whether to print domains to console (default: False)
        
    Returns:
        A list of randomly generated domain names
    """
    adjectives = ["amazing", "beautiful", "exciting", "fantastic", "hilarious", "incredible", "jubilant", "magnificent",
                  "remarkable", "spectacular", "wonderful"]
    nouns = ["apple", "banana", "cherry", "dolphin", "elephant", "giraffe", "hamburger", "iceberg", "jellyfish",
             "kangaroo", "lemur", "mango", "november", "octopus", "penguin", "quartz", "rainbow", "strawberry",
             "tornado", "unicorn", "volcano", "walrus", "xylophone", "yogurt", "zebra"]

    top_level_domains = [".com", ".org", ".gov", ".info", ".net", ".io"]
    sub_domains = ["", "", "www.", "blog.", "login.", "mail.", "dev.", "beta.", "alpha.", "test.", "stage.", "prod."]

    if remove_dots:
        top_level_domains = [tld.replace(".", "") for tld in top_level_domains]
        sub_domains = [sub.replace(".", "") for sub in sub_domains]

    domain_names = []
    for _ in range(count):

        adj = random.choice(adjectives)
        noun = random.choice(nouns)
        tld = random.choice(top_level_domains)
        sub = random.choice(sub_domains)

        domain_name = f"{sub}{adj}{noun}{tld}"
        domain_names.append(domain_name)

        if debug: print(domain_name)

    return domain_names


# def get_search_terms( requested_length ):
#
#     # Load search terms file
#     search_terms = get_file_as_list( get_project_root() + "/src/ephemera/prompts/data/search-terms.txt", lower_case=False, clean=True, randomize=True )
#
#     # If we don't have enough search terms, append copies of the search term list until we do
#     while requested_length > len( search_terms ):
#         search_terms += search_terms
#
#     # Truncate the search terms list to equal the requested len
#     search_terms = search_terms[ :requested_length ]
#
#     return search_terms

def is_jsonl(string: str) -> bool:
    """
    Check if a string is a valid JSONL (JSON Lines) format.
    
    Requires:
        - string is a string value to check
        
    Ensures:
        - Returns True if each line in the string is valid JSON
        - Returns False if any line fails to parse as JSON
        
    Args:
        string: The string to check for JSONL format
        
    Returns:
        True if the string is valid JSONL, False otherwise
    """
    try:
        # Split the string into lines
        lines = string.splitlines()

        # Iterate over each line and validate as JSON
        for line in lines:
            json.loads(line)

        return True

    except json.JSONDecodeError:
        return False


def truncate_string(string: str, max_len: int = 64) -> str:
    """
    Truncate a string if it exceeds a maximum length and add ellipsis.
    
    Requires:
        - string is a string to potentially truncate
        - max_len is a positive integer
        
    Ensures:
        - Returns the original string if its length is <= max_len
        - Returns a truncated string with ellipsis if length > max_len
        - Total length of returned string will be max_len + 3 (for "...")
        
    Args:
        string: The string to truncate if needed
        max_len: Maximum length before truncation (default: 64)
        
    Returns:
        The original or truncated string
    """
    if len(string) > max_len:
        string = string[:max_len] + "..."

    return string


def find_files_with_prefix_and_suffix(directory: str, prefix: str, suffix: str) -> list[str]:
    """
    Find files in a directory that match a specific prefix and suffix.
    
    Requires:
        - directory is a valid directory path
        - prefix and suffix are strings to match against filenames
        
    Ensures:
        - Returns a list of full file paths that match both prefix and suffix
        - Searches only in the specified directory (not recursively)
        
    Args:
        directory: The directory to search in
        prefix: The filename prefix to match
        suffix: The filename suffix to match
        
    Returns:
        A list of matching file paths
        
    Raises:
        FileNotFoundError: If the directory does not exist
        PermissionError: If the directory cannot be accessed
    """
    matching_files = []
    for file_name in os.listdir(directory):
        if file_name.startswith(prefix) and file_name.endswith(suffix):
            file_path = os.path.join(directory, file_name)
            matching_files.append(file_path)

    return matching_files


def get_files_as_strings(file_paths: list[str]) -> list[str]:
    """
    Read multiple files and return their contents as strings.
    
    Requires:
        - file_paths is a list of valid file paths
        - All files exist and are readable
        
    Ensures:
        - Returns a list of file contents as strings
        - Order of contents matches order of file_paths
        
    Args:
        file_paths: A list of file paths to read
        
    Returns:
        A list of file contents as strings
        
    Raises:
        FileNotFoundError: If any file does not exist
        PermissionError: If any file cannot be read
    """
    contents = []

    for file_path in file_paths:
        contents.append(get_file_as_string(file_path))

    return contents


def print_list(list_to_print: list[Any], end: str = "\n") -> None:
    """
    Print each item in a list to the console.
    
    Requires:
        - list_to_print is a list of items that can be converted to strings
        
    Ensures:
        - Prints each item in the list to the console
        - Uses the specified end character after each item
        
    Args:
        list_to_print: The list of items to print
        end: The string to print after each item (default: newline)
    """
    for item in list_to_print:
        print(item, end=end)


def print_stack_trace(exception: Exception, explanation: str = "Unknown reason",
                      caller: str = "Unknown caller", prepend_nl: bool = True,
                      debug: bool = False) -> None:
    """
    Print a formatted stack trace for an exception.

    Requires:
        - exception is an Exception object with a traceback
        - explanation and caller are strings describing the error context

    Ensures:
        - Prints a banner with error message
        - Prints exception type and message (always)
        - Prints full stack trace if debug=True

    Args:
        exception: The exception to print stack trace for
        explanation: Description of what went wrong (default: "Unknown reason")
        caller: Name of the function/method where exception occurred (default: "Unknown caller")
        prepend_nl: Whether to add a newline before the banner (default: True)
        debug: Whether to print full stack trace (default: False)
    """
    msg = f"ERROR: {explanation} in {caller}"
    print_banner(msg, prepend_nl=prepend_nl, expletive=True)

    # ALWAYS print exception type and message (the key improvement!)
    exception_info = traceback.format_exception_only( type( exception ), exception )
    for line in exception_info:
        print( line.rstrip() )

    # Print full stack trace only if debug=True
    if debug:
        print( "\nFull stack trace:" )
        stack_trace = traceback.format_tb( exception.__traceback__ )
        for line in stack_trace:
            print( line.rstrip() )


def sanity_check_file_path(file_path: str, silent: bool = False) -> None:
    """
    Check if a file exists and raise an assertion error if not.
    
    Requires:
        - file_path is a string path to check
        
    Ensures:
        - Raises AssertionError if the file doesn't exist
        - Prints success message if file exists and silent is False
        
    Args:
        file_path: The path to check
        silent: Whether to suppress output messages (default: False)
        
    Raises:
        AssertionError: If the file does not exist
    """
    fail_msg = f"That file doesn't exist: [{file_path}] Please correct path to file"
    assert os.path.isfile(file_path), fail_msg

    if not silent: print(f"File exists! [{file_path}]")


def get_name_value_pairs_v2(arg_list: list[str], decode_spaces: bool = True) -> dict[str, str]:
    """
    Parse a list of strings in "name=value" format into a dictionary (version 2).
    
    Requires:
        - arg_list is a list of strings
        
    Ensures:
        - Returns a dictionary mapping names to values
        - Skips the first element in arg_list (assumed to be script name)
        - Skips elements that don't contain "="
        - Replaces "+" with spaces in values if decode_spaces is True
        
    Args:
        arg_list: Space delimited input from CLI
        decode_spaces: Whether to replace "+" with spaces in values (default: True)
        
    Returns:
        A dictionary of name-value pairs
        
    Notes:
        Only elements after the first (index 0) are processed. The first element
        is assumed to be the name of the script being called.
    """
    name_value_pairs = {}

    # Quick sanity check. Do we have anything to iterate?
    if len(arg_list) <= 1:
        print("No name=value pairs found in arg_list")
        return {}

    for i, arg in enumerate(arg_list):
        print(f"[{i}]th arg = [{arg_list[i]}]... ", end="")

        if "=" in arg:
            pair = arg.split("=")
            value = pair[1].replace("+", " ") if decode_spaces else pair[1]
            name_value_pairs[pair[0]] = value
            print("done!")
        else:
            print("SKIPPING, name=value format not found")

    print()
    print("Name value dictionary pairs:", end="\n\n")

    # get max width for right justification
    if name_value_pairs:
        max_len = max([len(key) for key in name_value_pairs.keys()]) + 1

        # iterate keys and print values w/ this format:
        #       [foo] = [bar]
        # [flibberty] = [jibbet]
        names = list(name_value_pairs.keys())
        names.sort()

        for name in names:
            print(f"[{(name.rjust(max_len, ' '))}] = [{name_value_pairs[name]}]")
    print()

    return name_value_pairs


def quick_smoke_test():
    """Quick smoke test to validate utility functions."""
    print_banner("Utility Functions Smoke Test", prepend_nl=True)

    print(f"Current working directory: {os.getcwd()}")
    init_dict = get_name_value_pairs(sys.argv)
    print(f"Command line args: {init_dict}")

    # Test API key retrieval
    print("\nTesting API key functions:")
    openai_key = get_api_key("openai")
    print(f"OpenAI API key: {openai_key[:10] if openai_key else 'NOT FOUND'}...")

    # Test date/time functions
    print("\nTesting date/time functions:")
    print(f"Current date (prose): {get_current_date(return_prose=True)}")
    print(f"Current time (H:00): {get_current_time(format='%H:00')}")

    print(f"Yesterday: {get_current_datetime_raw(days_offset=-1)}")
    print(f"    Today: {get_current_datetime_raw(days_offset=0)}")
    print(f" Tomorrow: {get_current_datetime_raw(days_offset=1)}")

    # Test project root
    print(f"\nProject root: {get_project_root()}")

    print("\n✓ Utility smoke test completed")


if __name__ == "__main__":
    quick_smoke_test()
