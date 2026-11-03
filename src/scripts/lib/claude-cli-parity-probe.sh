#!/usr/bin/env bash
#
# claude-cli-parity-probe.sh — warn when a container's bundled Claude Code is behind the host's.
#
# Bounded Claude Code jobs run the CLI that ships inside the claude-agent-sdk wheel, and the image
# pins that wheel, so nothing moves the container's CLI until someone bumps the pin. Measured
# 2026-11-02: host 2.1.317, image 2.1.161, a lag of 156 releases nobody had noticed.
#
# This reads two version strings and compares them. It runs no Claude Code job and reads no token.
#
# Source this file, then call:  probe_claude_cli_parity <container>
#   CLAUDE_CLI_MAX_LAG   how many releases behind is tolerated (default 10)
# It prints "[OK]" or "[WARN]" through say_ok / say_warn when the caller defines them, else with printf.
# Return: 0 within the limit, 1 too far behind, 2 a version could not be read.

CLAUDE_CLI_MAX_LAG="${CLAUDE_CLI_MAX_LAG:-10}"

# cli_version_lag <host> <image> — print how many releases the image is behind.
# Both are "X.Y.Z". A different major or minor counts as the limit plus one, since the patch
# numbers of two minors cannot be subtracted. An image ahead of the host is a lag of 0.
cli_version_lag() {
    local host="$1" image="$2"
    local h_mm="${host%.*}" i_mm="${image%.*}"
    if [[ "${h_mm}" != "${i_mm}" ]]; then
        local h_key i_key
        h_key=$(( ${h_mm%%.*} * 100000 + ${h_mm##*.} ))
        i_key=$(( ${i_mm%%.*} * 100000 + ${i_mm##*.} ))
        if (( i_key > h_key )); then printf "0\n"; else printf "%s\n" $(( CLAUDE_CLI_MAX_LAG + 1 )); fi
        return 0
    fi
    local lag=$(( ${host##*.} - ${image##*.} ))
    (( lag < 0 )) && lag=0
    printf "%s\n" "${lag}"
}

_cli_parity_say() {
    local kind="$1" text="$2"
    if declare -F "say_${kind}" >/dev/null; then "say_${kind}" "${text}"; else printf "[%s] %s\n" "${kind^^}" "${text}"; fi
}

probe_claude_cli_parity() {
    local container="$1" host image lag
    host="$(claude --version 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+')"
    image="$(docker exec "${container}" python -c 'from claude_agent_sdk._cli_version import __cli_version__ as v; print(v)' 2>/dev/null | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+')"
    if [[ -z "${host}" || -z "${image}" ]]; then
        _cli_parity_say warn "could not read both Claude Code versions (host='${host}' image='${image}')"
        return 2
    fi
    lag="$(cli_version_lag "${host}" "${image}")"
    if (( lag > CLAUDE_CLI_MAX_LAG )); then
        _cli_parity_say warn "${container} bundles Claude Code ${image}, host runs ${host} (limit ${CLAUDE_CLI_MAX_LAG} releases)"
        printf "       remedy: bump claude-agent-sdk in pyproject.toml to the release whose _cli_version.py reads %s, uv lock, rebuild the image\n" "${host}"
        return 1
    fi
    _cli_parity_say ok "${container} bundles Claude Code ${image}, host runs ${host}"
    return 0
}
