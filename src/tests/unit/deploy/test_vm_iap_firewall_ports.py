"""
The VM's IAP firewall ports: a declared list, an ensure verb and a read-only check.

The list is src/conf/vm-iap-ports.tsv. `lupin-vm.sh firewall ensure` creates each missing rule.
`firewall check` fails when a block-tier port has none. Neither needs a real project. A stateful
gcloud stub on the search path keeps the rule listing in a file and appends to it on a create.
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT   = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
SCRIPT = ROOT / "src" / "scripts" / "lupin-vm.sh"
LIB    = ROOT / "src" / "scripts" / "lib" / "preflight-vm-lib.sh"
PORTS  = ROOT / "src" / "conf" / "vm-iap-ports.tsv"
IAP    = "35.235.240.0/20"
TAB    = "\t"

STUB = r"""#!/bin/bash
echo "$*" >> "$STUB_CALLS"
case "$*" in
  *"instances describe"*) [ -n "${STUB_NO_NETWORK:-}" ] && exit 1
                          echo "https://www.googleapis.com/compute/v1/projects/p/global/networks/the-net"; exit 0 ;;
  *"firewall-rules list"*) [ -n "${STUB_LIST_FAIL:-}" ] && exit 1; cat "$STUB_RULES"; exit 0 ;;
  *"firewall-rules create lupin-iap-"*)
      port="$( echo "$*" | sed -n 's/.*--rules=tcp:\([0-9]*\).*/\1/p' )"
      printf 'lupin-iap-%s\tINGRESS\tFalse\t35.235.240.0/20\ttcp:%s\n' "$port" "$port" >> "$STUB_RULES"; exit 0 ;;
esac
exit 0
"""


def _declared():
    """The (port, tier) pairs the committed list declares."""
    rows = [ l.split( TAB ) for l in PORTS.read_text().splitlines() if l.strip() and not l.startswith( "#" ) ]
    return [ ( r[ 0 ], r[ 1 ] ) for r in rows ]


def _rules_text( ports ):
    return "".join( f"lupin-iap-{p}{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:{p}\n" for p in ports )


@pytest.fixture
def world( tmp_path ):
    """A stub gcloud plus a rules file holding every declared port; returns a runner."""
    ( tmp_path / "gcloud" ).write_text( STUB )
    ( tmp_path / "gcloud" ).chmod( 0o755 )
    rules = tmp_path / "rules.txt"
    rules.write_text( _rules_text( [ p for p, _ in _declared() ] ) )
    calls = tmp_path / "calls.log"

    class World:
        pass

    w = World()
    w.rules = rules
    w.calls = calls

    def run( *args, dry=False, **extra ):
        env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_CALLS": str( calls ), "STUB_RULES": str( rules ),
                "LUPIN_GCP_PROJECT_ID": "a-real-looking-project", "HOME": str( tmp_path ), **extra }
        argv = [ "bash", str( SCRIPT ) ] + ( [ "--dry-run" ] if dry else [] ) + list( args )
        return subprocess.run( argv, capture_output=True, text=True, env=env )

    w.run = run
    w.seen = lambda: calls.read_text() if calls.exists() else ""
    w.delete = lambda port: rules.write_text(
        "".join( l + "\n" for l in rules.read_text().splitlines() if not l.startswith( f"lupin-iap-{port}{TAB}" ) ) )
    return w


def _lib( snippet ):
    return subprocess.run( [ "bash", "-c", f"set -uo pipefail; source '{LIB}'; {snippet}" ], capture_output=True, text=True )


# ── the declared list ────────────────────────────────────────────────────────

def test_the_declared_list_holds_7999_as_blocking_and_8000_as_a_warning():
    assert ( "7999", "block" ) in _declared()
    assert ( "8000", "warn" ) in _declared()
    assert [ t for _, t in _declared() if t not in ( "block", "warn" ) ] == []


# ── pfv_iap_rule_covering ────────────────────────────────────────────────────

@pytest.mark.parametrize( "rules, port, expect_rc, expect_name", [
    ( f"r1{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:7999", 7999, 0, "r1" ),
    ( f"r1{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:7999", 8000, 1, "" ),
    ( f"r2{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:22,tcp:7999", 7999, 0, "r2" ),
    ( f"r3{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:8000-8100", 8050, 0, "r3" ),
    ( f"r3{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:8000-8100", 8101, 1, "" ),
    ( f"r4{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp", 7999, 0, "r4" ),
    ( f"r5{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}all", 7999, 0, "r5" ),
    ( f"r6{TAB}INGRESS{TAB}False{TAB}10.0.0.0/8;{IAP}{TAB}tcp:7999", 7999, 0, "r6" ),
    ( f"r7{TAB}INGRESS{TAB}False{TAB}0.0.0.0/0{TAB}tcp:7999", 7999, 0, "r7" ),
    ( f"r8{TAB}INGRESS{TAB}False{TAB}10.0.0.0/8{TAB}tcp:7999", 7999, 1, "" ),
    ( f"r9{TAB}INGRESS{TAB}True{TAB}{IAP}{TAB}tcp:7999", 7999, 1, "" ),
    ( f"ra{TAB}EGRESS{TAB}False{TAB}{IAP}{TAB}tcp:7999", 7999, 1, "" ),
    ( f"rb{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}tcp:abc", 7999, 1, "" ),
    ( f"rc{TAB}INGRESS{TAB}False{TAB}{IAP}{TAB}icmp", 7999, 1, "" ),
    ( "", 7999, 1, "" ),
] )
def test_rule_covering_reads_the_gcloud_listing( rules, port, expect_rc, expect_name ):
    r = _lib( f"pfv_iap_rule_covering {port} \"$( printf '%s' '{rules}' )\"" )
    assert r.returncode == expect_rc, r.stderr
    assert r.stdout == expect_name


# ── pfv_iap_port_states ──────────────────────────────────────────────────────

def _states( tmp_path, ports_text, rules_text ):
    f = tmp_path / "ports.tsv"
    f.write_text( ports_text )
    return _lib( f"pfv_iap_port_states '{f}' \"$( printf '%s' '{rules_text}' )\"" )


def test_states_are_present_for_every_port_with_a_rule( tmp_path ):
    r = _states( tmp_path, f"7999{TAB}block{TAB}app\n8000{TAB}warn{TAB}test\n", _rules_text( [ 7999, 8000 ] ).rstrip( "\n" ) )
    assert r.returncode == 0
    assert r.stdout.splitlines() == [ "7999|block|PRESENT|lupin-iap-7999", "8000|warn|PRESENT|lupin-iap-8000" ]


def test_a_missing_block_port_returns_1_and_a_missing_warn_port_returns_0( tmp_path ):
    both = f"7999{TAB}block{TAB}app\n8000{TAB}warn{TAB}test\n"
    r = _states( tmp_path, both, _rules_text( [ 8000 ] ).rstrip( "\n" ) )
    assert r.returncode == 1 and "7999|block|ABSENT|" in r.stdout
    r = _states( tmp_path, both, _rules_text( [ 7999 ] ).rstrip( "\n" ) )
    assert r.returncode == 0 and "8000|warn|ABSENT|" in r.stdout


def test_an_unreadable_list_returns_2_and_names_nothing( tmp_path ):
    r = _lib( f"pfv_iap_port_states '{tmp_path}/nope.tsv' ''" )
    assert r.returncode == 2 and r.stdout == ""


@pytest.mark.parametrize( "row, why", [
    ( "7999\tblock\n", "bad row" ),
    ( f"abc{TAB}block{TAB}x\n", "bad port" ),
    ( f"7999{TAB}maybe{TAB}x\n", "bad tier" ),
] )
def test_a_malformed_row_returns_3_and_names_it( tmp_path, row, why ):
    r = _states( tmp_path, row, "" )
    assert r.returncode == 3 and why in r.stderr


def test_the_committed_list_parses_against_an_empty_listing():
    r = _lib( f"pfv_iap_port_states '{PORTS}' ''" )
    assert r.returncode == 1                                   # 7999 is blocking and absent
    assert len( r.stdout.splitlines() ) == len( _declared() )


# ── lupin-vm.sh firewall check ───────────────────────────────────────────────

def test_check_is_green_when_every_declared_port_has_a_rule( world ):
    out = world.run( "firewall", "check" )
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.count( "[OK]" ) == len( _declared() )
    assert "remedy" not in out.stdout


def test_a_host_with_the_7999_rule_deleted_fails_the_check_and_names_the_ensure_line( world ):
    world.delete( 7999 )
    out = world.run( "firewall", "check" )
    assert out.returncode == 1
    assert "[FAIL]  no IAP rule for tcp:7999 (blocking)" in out.stdout
    assert "src/scripts/lupin-vm.sh firewall ensure" in out.stdout


def test_a_missing_warn_port_warns_and_still_names_the_ensure_line( world ):
    world.delete( 8889 )
    out = world.run( "firewall", "check" )
    assert out.returncode == 0
    assert "[WARN]  no IAP rule for tcp:8889" in out.stdout
    assert "firewall ensure" in out.stdout


def test_check_makes_no_change( world ):
    world.delete( 7999 )
    world.run( "firewall", "check" )
    assert "firewall-rules create" not in world.seen()


def test_check_dies_when_the_rules_cannot_be_listed( world ):
    out = world.run( "firewall", "check", STUB_LIST_FAIL="1" )
    assert out.returncode != 0 and "could not list the firewall rules" in out.stderr


def test_check_dies_when_the_port_list_is_unreadable( world, tmp_path ):
    work = tmp_path / "tree"
    ( work / "src" / "scripts" / "lib" ).mkdir( parents=True )
    ( work / "src" / "scripts" / "lupin-vm.sh" ).write_text( SCRIPT.read_text() )
    out = subprocess.run( [ "bash", str( work / "src" / "scripts" / "lupin-vm.sh" ), "firewall", "check" ],
                          capture_output=True, text=True,
                          env={ "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_CALLS": str( world.calls ),
                                "STUB_RULES": str( world.rules ), "LUPIN_GCP_PROJECT_ID": "p", "HOME": str( tmp_path ) } )
    assert out.returncode != 0 and "IAP port list not readable" in out.stderr


def test_check_dies_when_the_lib_is_unreadable( world, tmp_path ):
    work = tmp_path / "tree2"
    ( work / "src" / "scripts" ).mkdir( parents=True )
    ( work / "src" / "conf" ).mkdir( parents=True )
    ( work / "src" / "scripts" / "lupin-vm.sh" ).write_text( SCRIPT.read_text() )
    ( work / "src" / "conf" / "vm-iap-ports.tsv" ).write_text( PORTS.read_text() )
    out = subprocess.run( [ "bash", str( work / "src" / "scripts" / "lupin-vm.sh" ), "firewall", "check" ],
                          capture_output=True, text=True,
                          env={ "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_CALLS": str( world.calls ),
                                "STUB_RULES": str( world.rules ), "LUPIN_GCP_PROJECT_ID": "p", "HOME": str( tmp_path ) } )
    assert out.returncode != 0 and "preflight lib not readable" in out.stderr


def test_check_dies_on_a_malformed_port_list( world, tmp_path ):
    work = tmp_path / "tree3"
    ( work / "src" / "scripts" / "lib" ).mkdir( parents=True )
    ( work / "src" / "conf" ).mkdir( parents=True )
    ( work / "src" / "scripts" / "lupin-vm.sh" ).write_text( SCRIPT.read_text() )
    ( work / "src" / "scripts" / "lib" / "preflight-vm-lib.sh" ).write_text( LIB.read_text() )
    ( work / "src" / "conf" / "vm-iap-ports.tsv" ).write_text( f"7999{TAB}maybe{TAB}x\n" )
    out = subprocess.run( [ "bash", str( work / "src" / "scripts" / "lupin-vm.sh" ), "firewall", "check" ],
                          capture_output=True, text=True,
                          env={ "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_CALLS": str( world.calls ),
                                "STUB_RULES": str( world.rules ), "LUPIN_GCP_PROJECT_ID": "p", "HOME": str( tmp_path ) } )
    assert out.returncode != 0 and "could not read the IAP port list" in out.stderr


# ── lupin-vm.sh firewall ensure ──────────────────────────────────────────────

def test_ensure_says_present_for_every_port_and_creates_nothing_on_a_healthy_host( world ):
    out = world.run( "firewall", "ensure" )
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.count( "present (lupin-iap-" ) == len( _declared() )
    assert "firewall-rules create" not in world.seen()


def test_ensure_brings_a_deleted_rule_back_and_the_check_goes_green( world ):
    world.delete( 7999 )
    world.delete( 8888 )
    assert world.run( "firewall", "check" ).returncode == 1
    out = world.run( "firewall", "ensure" )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "firewall ensure: 7999 created (lupin-iap-7999)" in out.stdout
    assert "firewall ensure: 8888 created (lupin-iap-8888)" in out.stdout
    assert "firewall ensure: 8000 present" in out.stdout
    assert world.seen().count( "firewall-rules create" ) == 2
    assert world.run( "firewall", "check" ).returncode == 0
    again = world.run( "firewall", "ensure" )                    # idempotent: a second run creates nothing
    assert "created" not in again.stdout and world.seen().count( "firewall-rules create" ) == 2


def test_ensure_creates_from_the_iap_range_on_the_vms_network( world ):
    world.delete( 7999 )
    world.run( "firewall", "ensure" )
    created = [ l for l in world.seen().splitlines() if "firewall-rules create lupin-iap-7999" in l ][ 0 ]
    assert "--network=the-net" in created and "--source-ranges=35.235.240.0/20" in created and "--rules=tcp:7999" in created


def test_a_dry_run_ensure_says_would_create_and_changes_nothing( world ):
    world.delete( 7999 )
    out = world.run( "firewall", "ensure", dry=True )
    assert out.returncode == 0
    assert "firewall ensure: 7999 would be created" in out.stdout
    assert "7999 created" not in out.stdout
    assert "firewall-rules create lupin-iap-7999" in out.stdout          # runit prints the line it would run
    assert "firewall-rules create" not in world.seen()                   # and the stub never saw it


def test_ensure_dies_when_the_vm_network_cannot_be_derived( world ):
    out = world.run( "firewall", "ensure", STUB_NO_NETWORK="1" )
    assert out.returncode != 0 and "could not derive the VM network" in out.stderr


def test_an_unknown_firewall_action_lists_ensure_and_check( world ):
    out = world.run( "firewall", "bogus" )
    assert out.returncode != 0 and "status | open [PORT] | ensure | check" in out.stderr


# ── the callers: deploy and preflight ────────────────────────────────────────

def test_a_dry_run_deploy_names_both_firewall_checks_and_runs_neither( world ):
    out = world.run( "deploy", dry=True )
    text = out.stdout + out.stderr
    assert "(dry-run) PRE-deploy IAP firewall check" in text and "(dry-run) POST-deploy IAP firewall check" in text
    assert "firewall-rules list" not in world.seen()


def test_deploy_stops_before_the_vm_preflight_when_a_blocking_port_has_no_rule( world ):
    world.delete( 7999 )
    out = world.run( "deploy" )
    assert out.returncode != 0 and "PRE-deploy IAP firewall check FAILED" in out.stderr
    assert "preflight-vm.sh" not in world.seen()


def test_the_skip_flag_skips_the_firewall_check_in_deploy( world ):
    world.delete( 7999 )
    out = world.run( "deploy", LUPIN_SKIP_PREFLIGHT="1" )
    assert "IAP firewall check" not in out.stdout + out.stderr
    assert "firewall-rules list" not in world.seen()


def test_a_green_deploy_runs_the_post_check_and_a_red_post_check_only_reports( world, tmp_path ):
    out = world.run( "deploy" )
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "POST-deploy IAP firewall check" in text and "reported a blocking port" not in text
    # the 7999 rule vanishes while the VM-side post preflight runs: the dev-side post check reports it, the deploy still exits 0
    ( tmp_path / "gcloud" ).write_text( STUB.replace(
        "esac\nexit 0",
        '  *"POST-deploy preflight"*) grep -v "^lupin-iap-7999" "$STUB_RULES" > "$STUB_RULES.new"; mv "$STUB_RULES.new" "$STUB_RULES"; exit 0 ;;\nesac\nexit 0' ) )
    out = world.run( "deploy" )
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "POST-deploy IAP firewall check reported a blocking port with no rule" in text


def test_preflight_runs_the_firewall_check_and_fails_when_it_does( world ):
    world.delete( 7999 )
    out = world.run( "preflight", "pre" )
    assert out.returncode == 1 and "[FAIL]  no IAP rule for tcp:7999" in out.stdout
    assert "preflight-vm.sh --phase pre" in world.seen()                # the VM-side check still ran


def test_preflight_is_green_when_the_rules_and_the_vm_check_are( world ):
    out = world.run( "preflight", "pre" )
    assert out.returncode == 0 and out.stdout.count( "[OK]" ) == len( _declared() )


def test_a_failing_vm_check_fails_preflight_even_with_the_rules_present( tmp_path, world ):
    ( tmp_path / "gcloud" ).write_text( STUB.replace( "esac\nexit 0", '  *"compute ssh"*) exit 1 ;;\nesac\nexit 0' ) )
    out = world.run( "preflight", "pre" )
    assert out.returncode == 1


def test_a_dry_run_preflight_names_the_firewall_check_and_does_not_run_it( world ):
    out = world.run( "preflight", "pre", dry=True )
    assert "(dry-run) dev-side IAP firewall check" in out.stdout
    assert "firewall-rules list" not in world.seen()
