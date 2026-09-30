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
    1. Derive project name via session_bridge.resolve_project_name (the ONE
       shared resolver — bridge-cwd-anchored, so a non-lupin session reads
       its OWN credential section instead of always collapsing to [lupin];
       see bug 9bf1dc4a)
    2. Read ~/.lupin/config (fail hard if missing)
    3. Read matching INI section
    4. Return (email, password) tuple

Usage:
    from lupin_cli.claude_code.hooks.lib.hook_credentials import get_hook_credentials
    email, password = get_hook_credentials()
"""

import configparser
from pathlib import Path
from typing import Tuple, Optional

from lupin_cli.claude_code.hooks.lib.session_bridge import resolve_project_name


# ── Constants ─────────────────────────────────────────────────────────────────

CREDENTIALS_FILE = Path.home() / ".lupin" / "config"


# ── Worktree collapse — CREDENTIALS ONLY ──────────────────────────────────────
#
# 🔴 DO NOT PROMOTE THIS TO A SHARED HELPER — deliberate duplication, labelled.
#
# `memento_io` performs what LOOKS like the same operation, and the memento path
# wants the MAIN checkout too, so "they disagree about the answer" is NOT the
# reason to keep them apart. (That reason was offered and withdrawn on
# 2026-09-04; it is recorded here because a right decision resting on a wrong
# reason survives into the next decision.)
#
# THE REASON IS THE CARVE-OUTS, and they belong to the memento resolver alone:
# a NESTED repo owns its own records, and a SUBMODULE's common dir is not a
# working tree. Credentials need neither — one service account per repo, and a
# nested repo has its own section. Folding this into the memento resolver would
# drag those cases into a lookup that must stay boring. John's reason, ratified
# by María 2026-09-04.
#
# ⚠️ Related and NOT fixed here: the memento WRITER was corrected in July
# (row af0c5700) and the Lupin READERS were not — `memento_io` uses
# `--git-common-dir` while `memento_slot.resolve_repo_root` uses
# `--show-toplevel`, and a docstring asserts a parity that does not hold. That
# is John's row, not this one. This helper touches neither module and shells out
# to git not at all — it reads the `.git` file directly — so it cannot drift
# with either of them.

_WORKTREES_MARKER = "/.git/worktrees/"


def _main_checkout_name( start ) -> Optional[str]:
    """
    Name the MAIN checkout of the git tree containing `start`.

    A linked worktree's `.git` is a FILE holding `gitdir: <main>/.git/worktrees/<name>`,
    and `session_bridge.resolve_project_name()` tests `( parent / ".git" ).exists()`
    — true for a file — so it names a worktree by the worktree's OWN directory
    (`lupin-wt-cc-author-maria-1`). `~/.lupin/config` has one section per REPO, so
    that name never matches and credential resolution raises.

    Requires:
        - start is a path-like (need not exist)

    Ensures:
        - Returns the lowercase basename of the MAIN checkout when `start` is inside
          a linked worktree
        - Returns the lowercase basename of the repo root when `start` is inside an
          ordinary checkout (`.git` is a directory) — the same answer the caller
          already has, so the caller must compare before retrying
        - Returns None when no `.git` ancestor exists, or the `.git` file is
          unreadable or not in `gitdir:` form
        - Never raises

    Args:
        start: directory to walk up from

    Returns:
        str or None: main-checkout basename, lowercased
    """
    try:
        candidate = Path( start ).resolve()
    except OSError:
        return None

    for parent in [ candidate, *candidate.parents ]:
        dot_git = parent / ".git"
        try:
            if not dot_git.exists():
                continue
            if dot_git.is_dir():
                return parent.name.lower()
            pointer = dot_git.read_text().strip()
        except OSError:
            return None
        if not pointer.startswith( "gitdir:" ):
            return None
        gitdir = pointer.split( ":", 1 )[ 1 ].strip()
        head, sep, _tail = gitdir.partition( _WORKTREES_MARKER )
        if not sep:
            return None
        return Path( head ).name.lower()

    return None


def _credential_search_roots():
    """
    Directories to attempt the worktree collapse from, most authoritative first.

    Ensures:
        - Yields the bridge `cwd` that `resolve_project_name()` itself resolved
          from, when one is available — so the retry asks about the SAME directory
          that produced the failing name
        - Then yields the live cwd, which is the seat's tree for a hook and for
          the listener it spawns
        - Never raises; yields nothing rather than propagating a lookup failure
    """
    try:
        from lupin_cli.claude_code.hooks.lib.session_bridge import _find_session_file
        import json

        found = _find_session_file()
        if found:
            path, _source = found
            with open( path ) as fh:
                bridge_cwd = json.load( fh ).get( "cwd" )
            if bridge_cwd:
                yield bridge_cwd
    except Exception:
        pass

    try:
        yield Path.cwd()
    except OSError:
        pass


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
        project = resolve_project_name()

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"~/.lupin/config not found.\n"
            f"Create it with: lupin-config init\n"
            f"Or migrate from legacy files: lupin-config migrate"
        )

    result = _read_credentials_from_file( CREDENTIALS_FILE, project )
    if result is not None:
        return result

    # No section for that name. Before failing, ask whether the name came from a
    # git WORKTREE — see _main_checkout_name above for the mechanism, and for why
    # this collapse stays local to credentials. Measured 2026-09-04: this raise
    # killed the CC notification listener ~0.1s into startup on every worktree seat,
    # before its first log line, leaving 33 unattributed lines in the shared
    # centralized log and a fleet of sessions that could not hear a DM.
    #
    # A collapsed name is accepted ONLY if it has a section, so a wrong guess fails
    # closed to exactly today's error rather than to somebody else's account.
    for start in _credential_search_roots():
        collapsed = _main_checkout_name( start )
        if collapsed and collapsed != project:
            result = _read_credentials_from_file( CREDENTIALS_FILE, collapsed )
            if result is not None:
                return result

    # File exists but project section not found
    raise ValueError(
        f"No [{project}] section found in {CREDENTIALS_FILE}\n"
        f"Add a [{project}] section with 'email' and 'password' keys."
    )


def get_owner_credentials() -> Tuple[str, str]:
    """
    Resolve the HUMAN OWNER's credentials from ~/.lupin/config [owner] section.

    Writer-side follow-up to the 2026-05-14 Option C design. Used by
    cc_notification_listener._stamp_owner_user_id_on_bridge to resolve the
    human owner's user_id via /auth/login and stamp it on the bridge file.

    Distinct from `get_hook_credentials()`: that returns the per-PROJECT
    SERVICE-account credentials used for the listener's OWN login (e.g.,
    `claude.code@lupin.deepily.ai`). This returns the HUMAN owner's
    credentials (e.g., `ricardo.felipe.ruiz@gmail.com`), which is what
    the broadcast UI's same-user filter actually compares against.

    INI section shape:
        [owner]
        email = <human_owner_email>
        password = <human_owner_password>

    See: src/rnd/v0.1.7/2026.05.17-owner-user-id-stamper-writer-side/01-design.md

    Requires:
        - ~/.lupin/config exists
        - INI file has an [owner] section with non-empty email + password keys

    Ensures:
        - Returns ( email, password ) tuple on success
        - Raises FileNotFoundError if ~/.lupin/config not found
        - Raises ValueError if [owner] section or required keys are missing

    Returns:
        Tuple[str, str]: ( email, password )

    Raises:
        FileNotFoundError: If no credentials file exists
        ValueError: If [owner] section or required keys not found
    """
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"~/.lupin/config not found.\n"
            f"Create it with: lupin-config init\n"
            f"Or migrate from legacy files: lupin-config migrate"
        )

    result = _read_credentials_from_file( CREDENTIALS_FILE, "owner" )
    if result is not None:
        return result

    raise ValueError(
        f"No [owner] section found in {CREDENTIALS_FILE}\n"
        f"Add an [owner] section with 'email' and 'password' keys for the human owner.\n"
        f"This is distinct from the per-project service-account credentials."
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


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":

    print( f"Credentials file: {CREDENTIALS_FILE}" )
    print( f"  Exists: {CREDENTIALS_FILE.exists()}" )
    print( f"Derived project: {resolve_project_name()}" )

    try:
        email, password = get_hook_credentials()
        print( f"Email: {email}" )
        print( f"Password: {'*' * len( password )}" )
    except ( FileNotFoundError, ValueError ) as e:
        print( f"Error: {e}" )

    print()
    print( f"--- Owner credentials ([owner] section) ---" )
    try:
        owner_email, owner_password = get_owner_credentials()
        print( f"Owner email: {owner_email}" )
        print( f"Owner password: {'*' * len( owner_password )}" )
    except ( FileNotFoundError, ValueError ) as e:
        print( f"Owner error: {e}" )
