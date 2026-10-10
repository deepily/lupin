# CoSA development guide

> Rules for work under `src/cosa/`. The root `CLAUDE.md` governs git, testing and merging; this file adds only what is specific to CoSA.
> The text this file carried before the 2026-10-10 rewrite is kept in `src/docs/doctrine/claude-md-receipts-archive.md` under "Moved out of src/cosa/CLAUDE.md on 2026-10-10".

## Standing rules

### Repository context
- `src/cosa/` is a regular in-tree directory of the Lupin repository, not a submodule; the Lupin repo is the only git repo. The root `CLAUDE.md` governs git, testing and merging.
- Never commit or push without the user's explicit approval.
- Session history goes in the Lupin `history.md`, not in a history file here.
- The former CoSA repo's full history is kept off-tree at `/mnt/DATA02/cosa-git-archive-2026.05.29/`.
- This repo's SHORT_PROJECT_PREFIX is [COSA].

### Commands
- Run tests: `pytest tests/`; one test: `pytest tests/test_file.py::test_function -v`
- Lint: `flake8 .`; format: `black .`
- To run a CoSA module, put the Lupin `src` directory on `PYTHONPATH` and use `python -m cosa.agents.foo_bar`: `export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"`

### Configuration
- `ConfigurationManager` always needs an environment variable name when instantiated: `self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )`
- Every time you add, modify or delete a key in `lupin-app.ini`, give the same key an explainer value in `lupin-app-splainer.ini`.

### Code style
- **Imports**: group by stdlib, third-party, local packages
- **Indentation**: 4 spaces, not tabs
- **Naming**: snake_case for functions and methods, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **Documentation**: Design by Contract docstrings (Requires / Ensures / Raises) on all functions and methods; the eight rules are in `src/docs/docstring-standard.md`
- **Error handling**: catch specific exceptions with context in messages
- **XML formatting**: use XML tags for structured agent responses
- **Variable alignment**: keep the equals signs of consecutive assignments vertically aligned
- **Spacing**: spaces inside parentheses and square brackets: `len( placeholders )`, not `len(placeholders)`
- **One-line conditionals**: a simple, short conditional is one line: `if debug: print( f"Debug: {value}" )`; anything with more than one operation is multi-line
- **Dictionary alignment**: align dictionary contents vertically on the colon: `"model_name"  : "gpt-4",`

### Debugging
- Most classes accept `debug` and `verbose` parameters.
- Use `print_banner()` from `utils.py` for formatted messages.
- Track state with constants (`STATE_INITIALIZED`, `STATE_RUNNING`, and so on).

### Testing standards
- Every module includes a `quick_smoke_test()` function that runs the complete workflow, not just object creation, reports ✓/✗ per step, and uses `du.print_banner()`.
- When creating a new module, ask the user whether they want a smoke test included.

## Where to read more

| Topic | Read | When |
|---|---|---|
| Root rules: git, testing venues, merge gates, R&D read rule | `CLAUDE.md` | before any commit, test run or merge |
| Small-agent core: `AgentBase`, `RunnableCode`, `Llm` | `src/docs/wiki/capabilities/small-agents-core.md` | changing an agent base class |
| LLM clients | `src/docs/wiki/capabilities/agent-llm-clients.md` | changing how an agent calls a model |
| Configuration | `src/docs/wiki/capabilities/configuration.md` | adding or reading an INI key |
| Docstring rules | `src/docs/docstring-standard.md` | writing a docstring |
| Slash commands (`/plan-*`, `/p-is-p-*`) | `.claude/commands/` | looking for a workflow |
| Backup | `src/scripts/backup.sh`, `src/scripts/conf/rsync-exclude.txt` | running a backup (`/plan-backup-check`, `/plan-backup`, `/plan-backup-write`) |
| Everything this file used to say | `src/docs/doctrine/claude-md-receipts-archive.md` | tracing where a rule came from |
