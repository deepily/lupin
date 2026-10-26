"""
A usable :8000 server-coverage directory, for tests that drive the real coverage gate.

The gate folds the test server's coverage of main.py into its data file and answers exit 2
without it. A test about something else in the gate points LUPIN_SERVER_COVERAGE_DIR here.
The directory is built with the module's own writers and main.py's real content hash.
It goes stale the moment main.py changes under the test.
"""

import json
import os

import coverage

import cosa.utils.server_coverage as sc
import cosa.utils.util as cu


def make_server_dir( directory ):
    """
    Build a server data directory the gate accepts for this tree.

    Requires:
        - directory is a path that may not exist yet

    Ensures:
        - holds one parallel data file recording main.py arcs under the container path
        - holds a sidecar whose main_py_hash is this tree's main.py hash
        - returns the directory as a string
    """
    directory = str( directory )
    os.makedirs( directory, exist_ok=True )
    data = coverage.CoverageData( basename=os.path.join( directory, sc.DATA_PREFIX + ".fixture.1.a" ) )
    data.add_arcs( { f"{sc.CONTAINER_ROOT}/{sc.MAIN_PY_REL}": [ ( -1, 1 ) ] } )
    data.write()
    main_py = os.path.join( cu.get_project_root(), sc.MAIN_PY_REL )
    with open( os.path.join( directory, sc.BOOT_NAME ), "w", encoding="utf-8" ) as handle:
        json.dump( { "main_py_hash": sc.blob_hash( main_py ) }, handle )
    return directory
