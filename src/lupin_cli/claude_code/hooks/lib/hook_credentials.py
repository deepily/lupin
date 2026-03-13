#!/usr/bin/env python3
"""
Credential resolution for Claude Code hook infrastructure.

Reads per-project credentials from the unified config file ~/.lupin/config.

Used by the CC Notification Listener and hook scripts that need authenticated
access to the Lupin API.

INI Format (unified ~/.lupin/config):
    [lupin]
    email = claude.code@lupin.deepily.ai
    password = ...

    [cosa]
    email = claude.code@cosa.deepily.ai
    password = ...

    [environments]
    default = local

    [local]
    api_url = http://localhost:7999
    ...

Resolution:
    1. Derive project name from cwd (basename of project root)
    2. Read ~/.lupin/config (fail hard if missing)
    3. Read matching INI section
    4. Return (email, password) tuple

Usage:
    from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
    email, password = get_hook_credentials()
"""

import configparser
import os
from pathlib import Path
from typing import Tuple, Optional


# ── Constants ─────────────────────────────────────────────────────────────────

CREDENTIALS_FILE = Path.home() / ".lupin" / "config"


# ── Public API ────────────────────────────────────────────────────────────────

def get_hook_credentials( project: Optional[str] = None ) -> Tuple[str, str]:
    """
    Resolve hook credentials from INI file for the current project.

    Requires:
        - ~/.lupin/config exists
        - INI file has a section matching the project name

    Ensures:
        - Returns ( email, password ) tuple on success
        - Raises FileNotFoundError if ~/.lupin/config not found
        - Raises ValueError if project section or required keys are missing

    Args:
        project: Explicit project name. If None, derived from cwd basename.

    Returns:
        Tuple[str, str]: ( email, password )

    Raises:
        FileNotFoundError: If no credentials file exists
        ValueError: If project section or required keys not found
    """
    if project is None:
        project = _derive_project_name()

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"~/.lupin/config not found.\n"
            f"Create it with: lupin-config init\n"
            f"Or migrate from legacy files: lupin-config migrate"
        )

    result = _read_credentials_from_file( CREDENTIALS_FILE, project )
    if result is not None:
        return result

    # File exists but project section not found
    raise ValueError(
        f"No [{project}] section found in {CREDENTIALS_FILE}\n"
        f"Add a [{project}] section with 'email' and 'password' keys."
    )


def _read_credentials_from_file( file_path: Path, project: str ) -> Optional[Tuple[str, str]]:
    """
    Read credentials for a project from a specific INI file.

    Requires:
        - file_path exists and is readable
        - project is a non-empty string

    Ensures:
        - Returns ( email, password ) tuple if section found with valid keys
        - Returns None if project section not found
        - Raises ValueError if section found but keys missing/empty

    Args:
        file_path: Path to INI file
        project: Project section name to look for

    Returns:
        Optional[Tuple[str, str]]: ( email, password ) or None if section not found

    Raises:
        ValueError: If section found but email/password missing or empty
    """
    config = configparser.ConfigParser()
    config.read( str( file_path ) )

    if project not in config:
        return None

    section  = config[ project ]
    email    = section.get( "email", "" ).strip()
    password = section.get( "password", "" ).strip()

    if not email:
        raise ValueError( f"Missing 'email' in [{project}] section of {file_path}" )
    if not password:
        raise ValueError( f"Missing 'password' in [{project}] section of {file_path}" )

    return email, password


def _derive_project_name() -> str:
    """
    Derive project name from current working directory.

    Uses LUPIN_ROOT env var if set, otherwise falls back to cwd basename.

    Ensures:
        - Returns lowercase project name string
        - Never returns empty string

    Returns:
        str: Project name (e.g., "lupin", "cosa")
    """
    lupin_root = os.environ.get( "LUPIN_ROOT", "" )
    if lupin_root:
        return Path( lupin_root ).name.lower()

    return Path.cwd().name.lower()


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    print( f"Credentials file: {CREDENTIALS_FILE}" )
    print( f"  Exists: {CREDENTIALS_FILE.exists()}" )
    print( f"Derived project: {_derive_project_name()}" )

    try:
        email, password = get_hook_credentials()
        print( f"Email: {email}" )
        print( f"Password: {'*' * len( password )}" )
    except ( FileNotFoundError, ValueError ) as e:
        print( f"Error: {e}" )
