---
capability: lupin-config-cli
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.lupin_config.get_config_path@118bcf619d
  - scripts.lupin_config.print_header@10d4f4187e
  - scripts.lupin_config.print_success@fa7ffd2879
  - scripts.lupin_config.print_error@9d26a7719d
  - scripts.lupin_config.cmd_init@436b58ebe7
  - scripts.lupin_config.cmd_show@aaef580104
  - scripts.lupin_config.cmd_list@568e6408a4
  - scripts.lupin_config.cmd_add@b15cee283d
  - scripts.lupin_config.cmd_use@be69cfa449
  - scripts.lupin_config.cmd_test@949c77bff0
  - scripts.lupin_config.cmd_migrate@c056c612bd
  - scripts.lupin_config.main@948aa62c76
---
# The lupin-config command
`src/scripts/lupin_config.py` manages the multi-environment configuration of the Lupin command line tools. It keeps its file at `~/.lupin/config`.
- `get_config_path` returns that path. `print_header`, `print_success` and `print_error` format its output.
- `cmd_init` creates the config directory and a file with a `[local]` environment, and is safe to run twice.
- `cmd_show` shows the active configuration, with the precedence and any environment variable overrides.
- `cmd_list` lists the configured environments and marks the default.
- `cmd_add` adds an environment from flags or prompts, and refuses a name that already exists.
- `cmd_use` changes the default environment, which must exist.
- `cmd_test` tests that the configuration loads and that the environment authenticates.
- `cmd_migrate` merges the legacy credential and notification config files into the unified file.
- `main` dispatches the sub-command and returns 0 on success and 1 on error.
