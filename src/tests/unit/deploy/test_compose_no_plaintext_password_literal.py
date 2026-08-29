"""
No password-shaped LITERAL survives in a tracked compose file — row `856882e4`.

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
`POSTGRES_PASSWORD: dev_password` and `PGADMIN_DEFAULT_PASSWORD: admin` sat in
plaintext in `docker-compose.yml` at the tip of a PUBLIC repo. Found 2026-08-17 by
Chloé's rewritten secret scanner during sweep `8827dbe8`.

WHY THE PREVIOUS INSTRUMENT WALKED PAST THEM, which is the part worth encoding:
the old scanner matched secret names with `\\b` word boundaries, and **`\\b` does not
fire between an underscore and a letter**. Every SCREAMING_SNAKE secret name was
therefore invisible to it, and it reported clean because it could not see. The regex
below deliberately anchors on `[A-Z0-9_]*PASSWORD` with NO `\\b` — the same names the
old boundary hid.

WHAT IT ASSERTS
---------------
Every `*_PASSWORD` assignment in a tracked compose file is either a `${VAR:?…}`
fail-loud interpolation or a non-value placeholder. **Comment lines are scanned too**
— the pgadmin literal that this row also names lives inside a commented-out block,
and a literal is committed to the public tip whether or not docker reads it.

SCOPE — what a green here does NOT mean: it says nothing about the Python fallbacks
(`os.environ.get( "DB_PASSWORD", "dev_password" )`, 6 call sites), which are a
separate, larger blast radius and were NOT part of Rick's ruling. This holds the
compose surface only.

Venue: :7999-eligible. Pure file reads; no docker, no network.
"""
import os
import re

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
)

# No \b anywhere: that boundary is exactly what hid these names for months.
ASSIGNMENT = re.compile( r"([A-Z][A-Z0-9_]*PASSWORD)\s*[:=]\s*(\S.*?)\s*$" )


def _existing_compose_files():
    return [ f for f in COMPOSE_FILES if os.path.exists( os.path.join( PROJECT_ROOT, f ) ) ]


def _password_assignments( filename ):
    """
    Every `*_PASSWORD: <value>` assignment in one compose file, comments included.

    Requires:
        - filename is a compose file relative to the project root

    Ensures:
        - returns a list of ( line_number, variable_name, raw_value ) triples
        - commented-out lines ARE included — a literal on the public tip is a
          literal whether docker reads it or not
    """
    path = os.path.join( PROJECT_ROOT, filename )
    found = []
    with open( path, "r" ) as f:
        for n, line in enumerate( f, start=1 ):
            m = ASSIGNMENT.search( line )
            if m: found.append( ( n, m.group( 1 ), m.group( 2 ) ) )
    return found


def _is_safe( value ):
    """A value is safe iff it interpolates from the environment, or is a placeholder."""
    if value.startswith( "${" ): return True          # ${VAR:?…} / ${VAR:-…} / ${VAR}
    if value.startswith( "<" ) and value.endswith( ">" ): return True   # <placeholder>
    return False


def test_the_scanner_regex_sees_screaming_snake_names():
    """
    The instrument that reports clean must be able to see the thing it is clearing.

    This is the negative control for the control: the predecessor scanner used `\\b`
    and matched NOTHING here, then reported clean. If this assertion ever fails, the
    tests below are passing because they are blind, not because the tree is clean.
    """
    assert ASSIGNMENT.search( "      POSTGRES_PASSWORD: dev_password" )
    assert ASSIGNMENT.search( "  #     PGADMIN_DEFAULT_PASSWORD: admin" )
    assert not ASSIGNMENT.search( "      POSTGRES_USER: lupin_dev" )


@pytest.mark.parametrize( "compose_file", _existing_compose_files() )
def test_no_password_literal_in_compose( compose_file ):
    """
    Every `*_PASSWORD` in a tracked compose file interpolates; none is a literal.

    Ensures:
        - each assignment's value starts with `${` or is a `<placeholder>`
        - the failure message names file, line, and variable so the fix is one edit
    """
    offenders = [ ( n, name, val ) for n, name, val in _password_assignments( compose_file )
                  if not _is_safe( val ) ]
    assert not offenders, (
        f"{compose_file} carries a plaintext password literal at the tip of a PUBLIC repo: "
        + "; ".join( f"line {n}: {name}" for n, name, _ in offenders )
        + " — convert to the fail-loud ${VAR:?…} form and put the value in the untracked .env (row 856882e4)."
    )


def test_postgres_password_is_the_fail_loud_form_specifically():
    """
    `docker-compose.yml` must use `:?`, not `:-`: an unset value has to ABORT `up`.

    Ensures:
        - a `${POSTGRES_PASSWORD:-default}` form fails this test even though it
          would pass the literal check above — a default silently reinstates the
          very literal the row removed
    """
    path = os.path.join( PROJECT_ROOT, "docker-compose.yml" )
    with open( path, "r" ) as f: text = f.read()
    assert re.search( r"POSTGRES_PASSWORD:\s*\$\{POSTGRES_PASSWORD:\?", text ), (
        "docker-compose.yml must interpolate POSTGRES_PASSWORD in the fail-loud "
        "${POSTGRES_PASSWORD:?…} form — a `:-` default would silently restore a literal."
    )
