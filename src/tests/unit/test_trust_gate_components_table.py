"""
The components table lists every switch under the decision proxy's INI sections.

The table is in src/docs/proxy-admin-guide/07-fields-and-components.md. A key added to the INI without a row there fails
here, and a row whose key left the INI fails too. `swe team enabled` must read "Dormant" in the INI comment, the splainer
and the table, because nothing reads it.
"""
import re

import cosa.utils.util as cu


_ROOT      = cu.get_project_root()
_INI       = _ROOT + "/src/conf/lupin-app.ini"
_SPLAINER  = _ROOT + "/src/conf/lupin-app-splainer.ini"
_GUIDE     = _ROOT + "/src/docs/proxy-admin-guide/07-fields-and-components.md"
_PREFIXES  = ( "decision proxy ", "swe team trust proxy ", "swe team trust mode", "swe team enabled" )
_STATES    = ( "Live", "Dormant", "Unreachable" )
_ROW       = re.compile( r"^\| `([^`]+)` \| `([^`]*)` \| (\w+) \| (.+) \|$" )


def _read( path ):
    with open( path, encoding="utf-8" ) as handle: return handle.read()


def ini_keys( text ):
    """
    List the decision proxy's keys in an INI text.

    Requires:
        - text is the text of lupin-app.ini

    Ensures:
        - returns the key of every uncommented line that starts with one of the decision proxy's prefixes, in file order
    """
    keys = []
    for line in text.split( "\n" ):
        if line.startswith( _PREFIXES ) and "=" in line: keys.append( line.split( "=", 1 )[ 0 ].strip() )
    return keys


def table_rows( text ):
    """
    Read the components table of the guide part.

    Requires:
        - text is the text of 07-fields-and-components.md

    Ensures:
        - returns a dict from key to ( value, state, reader ) for every row that has the four columns
    """
    return { m.group( 1 ) : ( m.group( 2 ), m.group( 3 ), m.group( 4 ) ) for m in map( _ROW.match, text.split( "\n" ) ) if m }


def missing_from_table( keys, rows ):
    """
    Name the INI keys that have no row in the table.

    Requires:
        - keys is a list of INI keys; rows is the dict table_rows returns

    Ensures:
        - returns the keys with no row, in the order given
    """
    return [ key for key in keys if key not in rows ]


def test_the_ini_holds_the_keys_this_test_guards():
    keys = ini_keys( _read( _INI ) )
    assert len( keys ) >= 40, f"expected at least 40 decision proxy keys, found {len( keys )}: the prefix list or the INI moved"
    assert "swe team enabled" in keys and "decision proxy enabled" in keys and "swe team trust proxy bald enabled" in keys


def test_every_decision_proxy_ini_key_has_a_row_in_the_components_table():
    missing = missing_from_table( ini_keys( _read( _INI ) ), table_rows( _read( _GUIDE ) ) )
    assert missing == [], f"add a row for each to {_GUIDE}: {missing}"


def test_no_row_names_a_key_the_ini_no_longer_holds():
    stale = [ key for key in table_rows( _read( _GUIDE ) ) if key not in ini_keys( _read( _INI ) ) ]
    assert stale == [], f"rows with no INI key: {stale}"


def test_the_check_fails_when_a_key_is_missing_from_the_table():
    rows = table_rows( _read( _GUIDE ) )
    del rows[ "swe team trust proxy conformal alpha" ]
    assert missing_from_table( ini_keys( _read( _INI ) ), rows ) == [ "swe team trust proxy conformal alpha" ]


def test_every_row_has_one_of_the_three_states_and_a_reader():
    rows = table_rows( _read( _GUIDE ) )
    assert len( rows ) >= 40
    bad = { key : row for key, row in rows.items() if row[ 1 ] not in _STATES or not row[ 2 ].strip() }
    assert bad == {}, f"rows with an unknown state or no reader: {bad}"


def test_the_table_values_are_the_ini_values():
    ini = { line.split( "=", 1 )[ 0 ].strip() : line.split( "=", 1 )[ 1 ].strip() for line in _read( _INI ).split( "\n" ) if line.startswith( _PREFIXES ) and "=" in line }
    rows = table_rows( _read( _GUIDE ) )
    drift = { key : ( rows[ key ][ 0 ], ini[ key ] ) for key in ini if key in rows and rows[ key ][ 0 ] != ( ini[ key ] or "(empty)" ) }
    assert drift == {}, f"the table shows a value the INI does not hold: {drift}"


def test_swe_team_enabled_is_marked_dormant_in_the_ini_comment_the_splainer_and_the_table():
    ini_lines = _read( _INI ).split( "\n" )
    at        = ini_lines.index( next( line for line in ini_lines if line.startswith( "swe team enabled" ) ) )
    comment   = "\n".join( line for line in ini_lines[ max( 0, at - 4 ) : at ] if line.startswith( "#" ) )
    assert "Dormant" in comment, f"the comment above swe team enabled must say Dormant, got: {comment!r}"
    splainer  = next( line for line in _read( _SPLAINER ).split( "\n" ) if line.startswith( "swe team enabled" ) )
    assert "Dormant" in splainer and "503" not in splainer, "the splainer must say Dormant and must not promise a 503"
    assert table_rows( _read( _GUIDE ) )[ "swe team enabled" ][ 1 ] == "Dormant"
