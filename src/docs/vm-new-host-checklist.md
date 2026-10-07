# VM host configuration checklist

Configuration a Lupin host needs that lives **outside git**, so a fresh VM or a re-created
container does not have it. Each item below was once missing on `lupin-host-test` and each
is now asserted by `src/scripts/preflight-vm.sh`, which `src/scripts/lupin-vm.sh deploy`
runs before and after every deploy.

Run it on its own at any time:

```bash
src/scripts/lupin-vm.sh preflight full
```

A failing check prints the fix as a paste-ready line. This page says what each check means,
so the symptom can be recognised without the script.

## The four items (found 2026-09-30, bug `08691779`)

| check | what must exist | level | symptom when missing |
|---|---|---|---|
| **A8** | `~/.claude/settings.json` has `heartbeat.enabled`, `heartbeat.owed_source_from_store` and `task_store.enabled`, all true | block | The Stop hook runs and never pokes. No error anywhere; seats simply go idle |
| **A9** | `~/.claude/fleet-roster.env` has at least one `COSA_VOICE_MANAGERS__<PROJECT>="<Persona>"` line | block | No seat on the host is a manager. Every manager-gated store write answers 403: "is not a manager", "P1 requires the operator or a manager" |
| **C11** | a roster line for every project actually worked on the host | warn | The same 403s, for that project only |
| **C9** | the flow-ratio override file in the container's `LUPIN_FLOW_RATIO_DIR` holds the ruled window and ratio | warn | The gate runs the shipped defaults (24h / 1.0). On a near-empty store almost every create is refused: "created 1 and closed 0" |
| **C10** | `git rev-parse HEAD` works inside the rest container for every `/var/external-projects/*` mount | block | git answers "dubious ownership" (container uid 1001, different host owner). Before `a4ba937cc` the receipt check reported this as "commit not found" |

## How each is fixed

**A8, the heartbeat block.** Schema and defaults: [lupin-claude-hooks-settings-reference.md](lupin-claude-hooks-settings-reference.md).
Back the file up, add the two blocks, and the next Stop picks them up. No restart.

**A9 and C11, the manager roster.** Copy `src/conf/fleet-roster.env.template` to
`~/.claude/fleet-roster.env` and set one line per project. The project key is the repo name
upper-cased with `-` turned into `_`, for example `WEIL_NDA_DRAFTING_SUITE`. The stamp is
written at session start only, so a seat that is already running must be restarted through
`src/scripts/start-cc-with-tmux.sh` before it becomes a manager.

**C9, the flow-ratio override.** The file is read live, no restart:

```bash
docker exec -w /var/lupin <container> python -c \
  "import cosa.rest.flow_ratio_settings as f; f.set_overrides( window_hours=24, allow_below=2.0 )"
```

The ruled values for the test host are the constants `PFV_FLOW_RATIO_WINDOW_HOURS` and
`PFV_FLOW_RATIO_ALLOW_BELOW` in `src/scripts/lib/preflight-vm-lib.sh`. Change the ruling
there, not on the host alone, or the next preflight reports the host as wrong.

**C10, git trust for the mounts.** `docker-compose.cloud-gpu.yml` carries one
`GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n` pair per external-project bind, and
`test_compose_service_parity.py` fails when the two lists differ. Environment is read when
a container is **created**, so a new mount needs:

```bash
docker compose -f docker-compose.cloud-gpu.yml up -d --no-deps --force-recreate <service>
```

A `docker restart` does not pick it up. A hand-run `git config --global --add safe.directory`
inside the container works until the next recreate and then is gone.

## Three things that tripped the first deploy (found 2026-10-01, row `72781b05`)

Not preflight checks: they happen before the preflight can run, or are an instance of C11 above.

| symptom | cause | what to do |
|---|---|---|
| `gcloud` answers "You cannot start a suspended instance. Use the 'resume' verb instead." | The test VM is **suspended** by default, and `instances start` only works on a terminated one | `src/scripts/lupin-vm.sh vm-start`. It reads the state, runs `resume` for SUSPENDED and `start` for TERMINATED, does nothing for RUNNING, and says which verb ran (`10943d5b9`). Before that fix, resume by hand: `gcloud compute instances resume <vm> --zone=<zone> --project=<id>` |
| `lupin-vm.sh` stops with "LUPIN_GCP_PROJECT_ID is not set" | Every subcommand that calls gcloud needs the project id in the shell; the script does not fall back to `gcloud config`, which may name a different project | `export LUPIN_GCP_PROJECT_ID=<your-project-id>`, then re-run. `--dry-run` prints a placeholder instead of stopping |
| Preflight C11 warns "no roster line for `COSA_VOICE_MANAGERS__WEIL_PARALLEL_SEARCH`" | A project is worked on the VM (it has a Claude Code project dir) but `~/.claude/fleet-roster.env` has no line for it | Add `COSA_VOICE_MANAGERS__WEIL_PARALLEL_SEARCH="<Persona>"` to `~/.claude/fleet-roster.env`. This is the C11 fix above applied to that project; the persona is Rick's choice, so the check cannot supply it |

## The voice-server registration (found 2026-10-02, row `c9252819`)

| check | what must exist | level | symptom when missing |
|---|---|---|---|
| **A3b** | every `cosa-voice` entry in `~/.claude.json` (the user-scope one and any local-scope one under `projects`) has `LUPIN_CONFIG_MGR_CLI_ARGS` in its `env`, and each value is words separated by single spaces that name a settings file, a splainer file and a block that exist under the preflight's `LUPIN_ROOT`. A `cosa-voice` entry in the repo's `.mcp.json` is held to the same rule | block when an entry exists without it or with a value that does not resolve; block when a file is the wrong shape or cannot be read; warn when `~/.claude.json` has no entry; silent when `.mcp.json` is absent or has none | Every spawned worker gets no `--model` and runs on the user's default model. The spawn result shows `"model": null`. No error anywhere |

**How it is fixed.** The entry is written by `src/scripts/install-cosa-voice.sh`. It is per user and
per host, so a bundle push does not deliver it. From the dev box:

```bash
src/scripts/lupin-vm.sh install-voice
```

It needs these first, in this order: a checkout, `install-cli`, `push-env` (writes
`~/.lupin/config`) and `push-unversioned` (delivers the notification key). Without one of them the
installer stops and names what is missing.

It is safe to re-run, and a re-run does more than register:

- It removes and re-adds the entry, so any `env` added to it by hand is dropped.
- The settings block defaults to `Lupin:+Development`. To register another, set it on the dev box:
  `LUPIN_MCP_CONFIG_BLOCK=Lupin:+Testing-GCS src/scripts/lupin-vm.sh install-voice`.
- It overwrites the `hooks` key of `~/.claude/settings.json` from `src/conf/claude-code-hooks.json`
  and keeps a `.bak-<epoch>` copy of the old file each run.
- It may build `~/.venv-lupin-mcp`, add its export to `~/.bashrc`, and send one test notification.

It ends by reading every entry back and printing each scope and value. If a scope lacks the
variable, or a value names no settings block, it stops and says which. A block name that is not in
this checkout's `src/conf/lupin-app.ini` is refused on the dev box, before anything is sent.

`install-voice` rewrites the user-scope entry only. A local-scope entry is removed with
`claude mcp remove cosa-voice -s local`, run in that project directory; an entry in a project
`.mcp.json` is removed by hand. The preflight prints all three when it blocks.

Not checked: the values are resolved against the preflight's own `LUPIN_ROOT` (its checkout when
that is unset), not against the `LUPIN_ROOT` in the entry's `env`. An entry that points at another
tree is judged against the preflight's.

Also not the same as the settings reader: a header followed by other text on its line is a block
to that reader and not to this check, so this check can refuse a file the reader takes.

A session picks the new entry
up when it next starts; a session already running keeps the entry it started with.

## The two git hooks

| check | what must exist | level | symptom when missing |
|---|---|---|---|
| **B7** | `.git/hooks/pre-commit` links to `src/scripts/pre-commit-chain.sh`, and `.git/hooks/pre-push` links to `src/scripts/pre-push-chain.sh` | warn | Nothing. A commit or push the hook would have refused goes through; the first sign is a red `doclint` step in the merge pyramid |

Git does not carry `.git/hooks`, so a fresh clone has neither link and an updated checkout keeps
whatever it had.

**How it is fixed.** A person runs these in the clone's main checkout. A Claude seat cannot: a
guard refuses any seat that writes the hooks folder.

```bash
ln -sf ../../src/scripts/pre-commit-chain.sh .git/hooks/pre-commit
ln -sf ../../src/scripts/pre-push-chain.sh   .git/hooks/pre-push
```

One pair serves every worktree of that clone. A second clone, such as the VM's, needs its own.

`pre-commit` runs the secret scan, the R&D write guard and the documentation lint gate.
`pre-push` refuses a push whose tip holds a docstring lint finding in a swept Python file.
`git push --no-verify` skips it; the pyramid's `doclint` step cannot be skipped.

If the preflight says the checkout "predates the hook", update the checkout first, then link.

The check reads the folder git runs hooks from, so it follows `core.hooksPath`. A relative or an
absolute link passes. A copied file warns, because a copy does not follow the script.
Not checked: that the linked script is executable.

## Adding a new item to this list

When a host turns out to be missing configuration that git does not carry:

1. Add an assertion to `preflight-vm.sh` with a remedy line, and a test beside
   `src/tests/unit/deploy/test_preflight_vm_host_test_fixes.py`.
2. Add a row to the table above with the symptom as it was first seen.
3. If the value can live in the compose file or the repo instead of on the host, move it there.
   A check catches a gap; a committed value removes it.
