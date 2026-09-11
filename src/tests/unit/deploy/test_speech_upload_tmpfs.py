"""
The speech upload directory is a tmpfs on every service that runs the upload doors
(row 27bcdd79).

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
The MP3 door wrote every upload to one fixed file, io/recording.mp3, on the host disk
and never deleted it — two concurrent uploads could transcribe each other's audio, and
the last spoken question stayed readable forever. The fix writes one new file per
request into `speech upload temp dir` and removes it when the request ends. The tmpfs
is the second layer: audio that a crash leaves behind lives in memory and dies with
the container instead of sitting on a disk.

A tmpfs line dropped from one compose file would not fail any request — the doors
would silently write to the container's disk again. So this reads the parsed YAML
of both compose files, not their text, and checks the mount target is the directory
the shipped INI names.

Venue: :7999-eligible / AI-discretionary. Static, no docker, runs in milliseconds.
"""
import configparser
import os

import pytest
import yaml

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

UPLOAD_DIR = "/tmp/lupin-stt"
TMPFS_SPEC = f"{UPLOAD_DIR}:size=256m,mode=1777"

# Every service that runs src/cosa/rest/routers/speech.py.
SERVICES = [
    ( "docker-compose.yml",           "lupin-rest-dev"  ),
    ( "docker-compose.yml",           "lupin-rest-test" ),
    ( "docker-compose.cloud-gpu.yml", "lupin-rest"      ),
]


def _service( compose_rel, name ):
    with open( os.path.join( PROJECT_ROOT, compose_rel ) ) as f:
        return yaml.safe_load( f )[ "services" ][ name ]


@pytest.mark.parametrize( "compose_rel,name", SERVICES, ids=[ f"{c}:{s}" for c, s in SERVICES ] )
def test_service_mounts_the_upload_dir_as_tmpfs( compose_rel, name ):
    tmpfs = _service( compose_rel, name ).get( "tmpfs" ) or [ ]
    assert TMPFS_SPEC in tmpfs, f"{compose_rel} {name} tmpfs is {tmpfs!r}"


def test_the_shipped_ini_names_the_mounted_directory():
    """A mount at one path and an INI naming another would put the uploads back on disk."""
    parser = configparser.ConfigParser( interpolation=None, strict=False )
    parser.read( os.path.join( PROJECT_ROOT, "src/conf/lupin-app.ini" ) )
    assert parser.get( "Lupin: Development", "speech upload temp dir" ) == UPLOAD_DIR
    assert not parser.has_option( "Lupin: Development", "path to audio recording file" )
