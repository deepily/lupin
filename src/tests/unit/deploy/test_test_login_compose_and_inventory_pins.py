"""
Pins for the test role's login across compose, the env contract and terraform.

Each of these was changed by hand in review and left every test green. File reads only.
"""
import os
import re

import pytest
import yaml

import cosa.utils.util as cu

ROOT        = cu.get_project_root()
LOCAL       = os.path.join( ROOT, "docker-compose.yml" )
CLOUD_GPU   = os.path.join( ROOT, "docker-compose.cloud-gpu.yml" )
CONTRACT    = os.path.join( ROOT, "src/conf/env-contract.tsv" )
SECRETS_TF  = os.path.join( ROOT, "src/terraform/modules/secret-manager/variables.tf" )
PREFIX      = "LUPIN_TEST_DB_"


def _test_login_keys( compose_path ):
    """
    Return { key: value } for every LUPIN_TEST_DB_* entry in any service's environment block.

    Ensures:
        - parsed as yaml, so a key in the wrong block or a commented line is not counted
        - handles both the mapping and the list form of `environment:`
    """
    with open( compose_path ) as handle: compose = yaml.safe_load( handle )
    found = { }
    for service in compose[ "services" ].values():
        env = service.get( "environment" ) or { }
        if isinstance( env, list ): env = dict( item.split( "=", 1 ) for item in env if "=" in item )
        found.update( { k: str( v ) for k, v in env.items() if k.startswith( PREFIX ) } )
    return found


def _contract_names():
    with open( CONTRACT ) as handle:
        return { line.split( "\t" )[ 0 ] for line in handle if line.strip() and not line.startswith( "#" ) }


def test_the_instruments_find_the_keys_they_police():
    assert set( _test_login_keys( LOCAL ) ) == { "LUPIN_TEST_DB_USER", "LUPIN_TEST_DB_PASSWORD_FILE" }
    assert set( _test_login_keys( CLOUD_GPU ) ) == { "LUPIN_TEST_DB_USER", "LUPIN_TEST_DB_PASSWORD" }


@pytest.mark.parametrize( "compose_path", [ LOCAL, CLOUD_GPU ] )
def test_every_test_login_key_a_compose_service_sets_has_a_contract_row( compose_path ):
    keys = _test_login_keys( compose_path )
    assert keys, f"{compose_path} sets no {PREFIX}* key: the loop would pass over nothing"
    missing = sorted( set( keys ) - _contract_names() )
    assert not missing, f"{os.path.basename( compose_path )} sets {missing} with no row in env-contract.tsv"


def test_the_cloud_gpu_test_password_is_never_required():
    value = _test_login_keys( CLOUD_GPU )[ "LUPIN_TEST_DB_PASSWORD" ]
    assert value == "${LUPIN_TEST_DB_PASSWORD:-}", f"an empty password must keep plain mode, got {value!r}"
    assert ":?" not in "".join( _test_login_keys( CLOUD_GPU ).values() ), "a test login key became required (:?)"


def test_the_default_test_login_is_lupin_test_on_both_venues():
    assert _test_login_keys( LOCAL )[ "LUPIN_TEST_DB_USER" ] == "lupin_test"
    assert _test_login_keys( CLOUD_GPU )[ "LUPIN_TEST_DB_USER" ] == "${LUPIN_TEST_DB_USER:-lupin_test}"


def test_the_terraform_secret_inventory_names_the_test_password():
    with open( SECRETS_TF ) as handle: text = handle.read()
    block = re.search( r'variable\s+"secret_ids"\s*\{.*?^\}', text, re.DOTALL | re.MULTILINE )
    assert block, 'variable "secret_ids" not found'
    ids = re.findall( r'^\s*"([^"]+)"\s*,', block.group( 0 ), re.MULTILINE )
    assert len( ids ) > 5, f"parsed too few ids to trust the parse: {ids}"
    assert "lupin-db-test-password" in ids
    assert "lupin-db-password" in ids, "the app password's entry is the control that the parse sees the list"
