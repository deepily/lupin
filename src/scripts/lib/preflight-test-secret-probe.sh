#!/usr/bin/env bash
#
# preflight-test-secret-probe.sh — the test-login secret probe of preflight-test-container.sh, as a function.
#
# Source it, then call probe_test_login_secret. It needs the caller's say_ok, say_warn, say_fail and remedy functions.
# The test container mounts /etc/lupin/secrets/db_test_password as a compose secret, so a recreate fails
# when the file is missing, and the container cannot read it when its mode or owner is wrong. The file is
# root:1002 mode 0440, so a seat cannot read it: this probe looks at the file's metadata and its size, and
# never at its content.
#
# TEST_LOGIN_SECRET_FILE overrides the path, and TEST_LOGIN_SECRET_OWNER and TEST_LOGIN_SECRET_MODE override
# what is expected, so a test can stand in a scratch file for the real one.

# shellcheck source=preflight-vm-lib.sh
source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" && pwd )/preflight-vm-lib.sh"

# probe_test_login_secret_state
#
# Requires:  $1 = path, $2 = expected uid:gid, $3 = expected octal mode
# Ensures:   prints one word and returns 0 only for OK. The words are DIR-NOT-SEARCHABLE, ABSENT, EMPTY,
#            UNREADABLE-METADATA, WRONG-OWNER and WRONG-MODE, checked in that order, so the first thing wrong is
#            the one named. The directory is /etc/lupin/secrets, mode 0750 root:1002, so a login outside that
#            group cannot see any file in it: a file there is neither present nor absent to that login.
probe_test_login_secret_state() {
    local path="$1" want_owner="$2" want_mode="$3" owner mode
    [ -x "$( dirname -- "$path" )" ] || { printf 'DIR-NOT-SEARCHABLE'; return 6; }
    [ -e "$path" ] || { printf 'ABSENT'; return 1; }
    [ -s "$path" ] || { printf 'EMPTY'; return 2; }
    owner="$( stat -c '%u:%g' "$path" 2>/dev/null )"
    mode="$( stat -c '%a' "$path" 2>/dev/null )"
    if [ -z "$owner" ] || [ -z "$mode" ]; then printf 'UNREADABLE-METADATA'; return 3; fi
    pfv_owner_matches "$owner" "$want_owner" || { printf 'WRONG-OWNER'; return 4; }
    pfv_mode_matches  "$mode"  "$want_mode"  || { printf 'WRONG-MODE'; return 5; }
    printf 'OK'
}

probe_test_login_secret() {
    local path="${TEST_LOGIN_SECRET_FILE:-/etc/lupin/secrets/db_test_password}"
    local want_owner="${TEST_LOGIN_SECRET_OWNER:-0:1002}" want_mode="${TEST_LOGIN_SECRET_MODE:-440}"
    local state
    state="$( probe_test_login_secret_state "$path" "$want_owner" "$want_mode" )"
    case "$state" in
        OK) say_ok "test login secret ${path} is present (owner ${want_owner}, mode ${want_mode})" ;;
        DIR-NOT-SEARCHABLE) say_warn "test login secret ${path} cannot be inspected: this login cannot search $( dirname -- "$path" )"
                remedy "run this as root, or as a member of group ${want_owner#*:}, or check it with: docker run --rm -v $( dirname -- "$path" ):/s:ro busybox stat -c '%u:%g %a' /s/$( basename -- "$path" )" ;;
        ABSENT) say_fail "test login secret ${path} is missing"
                remedy "src/scripts/provision-db-roles.sh --secrets-dir /etc/lupin/secrets (needs root), then docker compose up -d --force-recreate lupin-rest-test" ;;
        EMPTY) say_fail "test login secret ${path} is empty"
               remedy "src/scripts/provision-db-roles.sh --secrets-dir /etc/lupin/secrets (needs root)" ;;
        WRONG-OWNER|WRONG-MODE) say_fail "test login secret ${path} has the wrong ${state#WRONG-} (want ${want_owner}, mode ${want_mode})"
               remedy "sudo chown ${want_owner} ${path} && sudo chmod ${want_mode} ${path}" ;;
        *) say_fail "test login secret ${path} could not be inspected (${state})"
           remedy "check that ${path} is readable by stat" ;;
    esac
}
