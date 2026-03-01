#!/usr/bin/env python3
"""
Credential resolution for Claude Code hook infrastructure.

Reads per-project credentials from ~/.claude/notification-hooks-credentials.ini.
Used by the CC Notification Listener and hook scripts that need authenticated
access to the Lupin API.

INI Format:
    [lupin]
    email = claude.code@lupin.deepily.ai
    password = ...

    [cosa]
    email = claude.code@cosa.deepily.ai
    password = ...

Resolution:
    1. Derive project name from cwd (basename of project root)
    2. Read matching INI section
    3. Return (email, password) tuple

Usage:
    from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
    email, password = get_hook_credentials()
"""

import configparser
import os
from pathlib import Path
from typing import Tuple, Optional


# ── Constants ─────────────────────────────────────────────────────────────────

CREDENTIALS_FILE = Path.home() / ".claude" / "notification-hooks-credentials.ini"


# ── Public API ────────────────────────────────────────────────────────────────

def get_hook_credentials( project: Optional[str] = None ) -> Tuple[str, str]:
    """
    Resolve hook credentials from INI file for the current project.

    Requires:
        - ~/.claude/notification-hooks-credentials.ini exists
        - INI file has a section matching the project name

    Ensures:
        - Returns ( email, password ) tuple on success
        - Raises FileNotFoundError if credentials file is missing
        - Raises ValueError if project section or required keys are missing

    Args:
        project: Explicit project name. If None, derived from cwd basename.

    Returns:
        Tuple[str, str]: ( email, password )

    Raises:
        FileNotFoundError: If credentials file does not exist
        ValueError: If project section or required keys not found
    """
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Credentials file not found: {CREDENTIALS_FILE}\n"
            f"Create it with:\n"
            f"  mkdir -p ~/.claude\n"
            f"  cat > {CREDENTIALS_FILE} << 'EOF'\n"
            f"  [lupin]\n"
            f"  email = claude.code@lupin.deepily.ai\n"
            f"  password = your-password-here\n"
            f"  EOF\n"
            f"  chmod 600 {CREDENTIALS_FILE}"
        )

    if project is None:
        project = _derive_project_name()

    config = configparser.ConfigParser()
    config.read( str( CREDENTIALS_FILE ) )

    if project not in config:
        available = [ s for s in config.sections() ]
        raise ValueError(
            f"No [{project}] section in {CREDENTIALS_FILE}\n"
            f"Available sections: {available}"
        )

    section = config[ project ]
    email    = section.get( "email", "" ).strip()
    password = section.get( "password", "" ).strip()

    if not email:
        raise ValueError( f"Missing 'email' in [{project}] section of {CREDENTIALS_FILE}" )
    if not password:
        raise ValueError( f"Missing 'password' in [{project}] section of {CREDENTIALS_FILE}" )

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
    print( f"File exists: {CREDENTIALS_FILE.exists()}" )
    print( f"Derived project: {_derive_project_name()}" )

    try:
        email, password = get_hook_credentials()
        print( f"Email: {email}" )
        print( f"Password: {'*' * len( password )}" )
    except ( FileNotFoundError, ValueError ) as e:
        print( f"Error: {e}" )
