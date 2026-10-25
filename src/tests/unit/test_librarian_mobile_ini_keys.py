"""
The four mobile librarian keys sit in the INI and the splainer.
"""
import configparser
import os

import cosa.repo.symindex.librarian_tick as lt

ROOT = os.environ[ "LUPIN_ROOT" ]
KEYS = [ lt.MOBILE_ROOT_KEY, lt.MOBILE_INDEX_KEY, lt.MOBILE_OWNER_KEY, lt.MOBILE_MANAGER_KEY ]


def load( name ):
    parser = configparser.ConfigParser( interpolation=None, delimiters=( "=", ) )
    parser.optionxform = str
    parser.read( os.path.join( ROOT, "src", "conf", name ) )
    return { key: value for section in parser.sections() for key, value in parser.items( section ) }


def test_all_four_mobile_keys_are_in_the_ini_and_explained_in_the_splainer():
    ini, splainer = load( "lupin-app.ini" ), load( "lupin-app-splainer.ini" )
    assert len( KEYS ) == 4
    for key in KEYS:
        assert key in ini, key
        assert splainer[ key ].strip(), key


def test_the_shipped_ini_values_give_the_documented_defaults():
    ini    = load( "lupin-app.ini" )
    corpus = lt.read_mobile_corpus( reader=ini.get, lupin_root="/no/such/checkout" )
    assert corpus is None                                                        # blank root, no sibling folder: skipped
    ini[ lt.MOBILE_ROOT_KEY ] = "/m"
    corpus = lt.read_mobile_corpus( reader=ini.get )
    assert corpus[ "owner" ] == "tiffany" and corpus[ "manager" ] == "tiffany" and corpus[ "index_dir" ] is None
