---
capability: swe-team-cli-and-config
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.swe_team.__main__.main@5d2f7a5ae8
  - cosa.agents.swe_team.config.SweTeamConfig@8ef6639f4d
---
# SWE team command line and config

`python -m cosa.agents.swe_team "<task>"` runs one task through the orchestrator in [[swe-team-orchestrator]]. `SweTeamConfig` holds every limit and switch the run reads.

## What it does
- `main` takes a positional task and the flags `--dry-run`, `--debug`, `--verbose`, `--lead-model`, `--worker-model`, `--budget` and `--timeout`.
- `--user-visible-args` prints the JSON list `task`, `budget`, `timeout`, `dry_run` and exits with 0. The runtime argument expeditor uses it.
- A missing task is a parser error. A run that returns a result exits with 0, and a failed run exits with 1.
- The command line builds its config from the dataclass defaults plus the flags. It reads the INI only for the two model ids.
- Without `--lead-model` or `--worker-model`, the ids come from `swe team lead model` and `swe team worker model`. A missing key raises `MissingConfigKeyError`.
- `SweTeamConfig` holds the two model names, which have no default in code.
- It also holds the iteration, token, wall-clock, failure and file-change limits, a budget in dollars, and the check-in and message switches.
- `enabled` and `dry_run` default to false. `trust_mode` defaults to `shadow`.
- `SweTeamConfig.from_config` reads 16 fields from keys that start with `swe team`. A missing key keeps the dataclass default. The read goes through `load_dataclass_from_ini` ([[agent-ini-config-loader]]).

## Don't
- Don't expect `--budget` or `--timeout` of 0 to apply. A falsy value is ignored and the default stays.
- Don't treat `SAFETY_LIMITS` and the config as one source. The guard's iteration, failure and time limits come from the config, and the file-change limit is the constant (see [[swe-team-orchestrator]]).
