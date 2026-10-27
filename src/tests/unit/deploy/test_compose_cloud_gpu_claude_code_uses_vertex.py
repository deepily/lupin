"""
The cloud-gpu container's Claude Code calls Claude on Vertex AI Model Garden.

Without CLAUDE_CODE_USE_VERTEX, every claude_code job in that container answered "Not logged in".
The service has no Anthropic login, and its OAuth token is empty. The decision is to use Vertex.

This pins the three variables Claude Code reads, on the cloud-gpu service only. The dev services
keep the Max-plan login, so setting them there would bill Vertex for work the plan covers.

Venue: :7999 (unit, static, no docker).
"""

import os

import yaml

import cosa.utils.util as cu
import cosa.utils.vertex_env as ve

COMPOSE_FILE = "docker-compose.cloud-gpu.yml"
SERVICE      = "lupin-rest"


def _env( compose_file, service ):
    with open( os.path.join( cu.get_project_root(), compose_file ), encoding="utf-8" ) as f:
        env = yaml.safe_load( f )[ "services" ][ service ][ "environment" ]
    return env if isinstance( env, dict ) else dict( item.split( "=", 1 ) for item in env )


def test_the_cloud_gpu_service_turns_vertex_on():
    assert _env( COMPOSE_FILE, SERVICE ).get( "CLAUDE_CODE_USE_VERTEX" ) == "1"


def test_the_cloud_gpu_service_names_a_certified_region_by_default():
    value = _env( COMPOSE_FILE, SERVICE ).get( "CLOUD_ML_REGION" )
    assert value is not None, "CLOUD_ML_REGION is unset"
    assert value == "${" + ve.VERTEX_REGION_ENV_KEY + ":-global}", "the default must be the certified region"
    assert "global" in ve.CERTIFIED_VERTEX_REGIONS


def test_the_cloud_gpu_service_bills_the_lupin_project_and_fails_loud_without_it():
    value = _env( COMPOSE_FILE, SERVICE ).get( "ANTHROPIC_VERTEX_PROJECT_ID" )
    assert value is not None, "ANTHROPIC_VERTEX_PROJECT_ID is unset"
    assert value.startswith( "${LUPIN_GCP_PROJECT_ID:?" ), "never a literal; unset must abort `up`"


def test_the_dev_services_keep_the_max_plan_login():
    for service in ( "lupin-rest-dev", "lupin-rest-test" ):
        env = _env( "docker-compose.yml", service )
        assert "CLAUDE_CODE_USE_VERTEX" not in env, f"{service} would bill Vertex for plan-covered work"
