# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## IMPORTANT: Repository Context
- This COSA repo is a git subproject/submodule contained within the parent "Lupin" project
- When working within the COSA directory, only manage this repository (not the parent project)
- Do not stage, commit, or push changes to the parent repository from here
- NEVER commit or push changes automatically - ALWAYS wait for user review and explicit approval before committing
- The global Claude Code Configuration file found in my home directory will direct you to update the parent "Lupin" project history.md file as a part of your end of session ritual..
- After updating the Lupin repo, I want you to duplicate your history entry in this repo's history.md

## PROJECT SHORT NAMES
- This repo's SHORT_PROJECT_PREFIX is [COSA]

## Commands
- Run tests: `pytest tests/`
- Run single test: `pytest tests/test_file.py::test_function -v`
- Run lint: `flake8 .`
- Format code: `black .`
- Run COSA modules from the cosa directory:
  ```bash
  # First, add the parent src directory to PYTHONPATH
  export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"
  # Then you can run modules like:
  python -m cosa.agents.foo_bar
  ```

## Memories
- Don't forget to add the following path to the Python path environment variable so that you can call Cosa objects from within the Cosa Directory: `Bash(export PYTHONPATH="/mnt/DATA01/include/www.deepily.ai/projects/lupin/src:$PYTHONPATH"`
- The configuration manager always needs an environment variable when it's instantiated, like this `self.config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )`
- Every time that you add, modify or delete a new key value pair to the configuration manager contained `lupin-app.ini` I want you to make sure that there is an explainer value provided for the same key value in `lupin-app-splainer.ini`
- When you start up, I want you to read two Two history files: 1) The history file that is at your repo root, and 2) The history file contained within the parent `Genie in the box project` root found in `../..` These two histories are related.

## Code Style
- **Imports**: Group by stdlib, third-party, local packages
- **Indentation**: 4 spaces (not tabs)
- **Naming**: snake_case for functions/methods, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **Documentation**: Use Design by Contract docstrings for all functions and methods
  ```python
  def process_input(text, max_length=100):
      """
      Process the input text according to specified parameters.
      
      Requires:
          - text is a non-empty string
          - max_length is a positive integer
          
      Ensures:
          - returns a processed string no longer than max_length
          - preserves the case of the original text
          - removes any special characters
          
      Raises:
          - ValueError if text is empty
          - TypeError if max_length is not an integer
      """
  ```
- **Error handling**: Catch specific exceptions with context in messages
- **XML Formatting**: Use XML tags for structured agent responses
- **Variable Alignment**: Maintain vertical alignment of equals signs within code blocks
  ```python
  # CORRECT - keep vertical alignment
  self.debug           = debug
  self.verbose         = verbose
  self.path_prefix     = path_prefix
  self.model_name      = model_name
  ```
- **Spacing**: Use spaces inside parentheses and square brackets
  ```python
  # CORRECT - with spaces inside parentheses/square brackets
  if requested_length is not None and requested_length > len( placeholders ):
  for command in commands.keys():
  words = text.split()
  
  # INCORRECT - no spaces inside parentheses/square brackets
  if requested_length is not None and requested_length > len(placeholders):
  for command in commands.keys():
  words = text.split()
  ```
  
- **One-line conditionals**: Use one-line format for simple, short conditionals
  ```python
  # CORRECT - one-line conditionals for simple checks
  if debug: print( f"Debug: {value}" )
  if verbose: du.print_banner( "Processing complete" )
  
  # CORRECT - multi-line for more complex operations
  if condition:
      perform_complex_operation()
      update_something_else()
  ```
- **Dictionary Alignment**: Align dictionary contents vertically centered on the colon symbol
  ```python
  # CORRECT - vertically aligned colons in dictionaries
  config = {
      "model_name"  : "gpt-4",
      "temperature" : 0.7,
      "max_tokens"  : 1024,
      "top_p"       : 1.0
  }
  
  # INCORRECT - unaligned dictionary
  config = {
      "model_name": "gpt-4",
      "temperature": 0.7,
      "max_tokens": 1024,
      "top_p": 1.0
  }
  ```

## Key Components
- **AgentBase**: Abstract base class for all agents
- **Llm**: Handles interactions with language models (OpenAI, Groq, Google)
- **ConfigurationManager**: Manages settings with inheritance capabilities
- **RunnableCode**: Handles code generation and execution

## Debug Practices
- Most classes accept `debug` and `verbose` parameters
- Use `print_banner()` from `utils.py` for formatted messages
- Track state with constants (STATE_INITIALIZED, STATE_RUNNING, etc.)

## Testing Standards
- **Smoke Testing**: All modules should include a `quick_smoke_test()` function
  - Tests complete workflow execution, not just object creation
  - Uses `du.print_banner()` for consistent formatting
  - Includes try/catch blocks with ✓/✗ status indicators
  - Professional output with clear progress messages
  - When creating new modules, always ask the user if they want a smoke test included

## Recent Changes
- **Standardized Smoke Testing (December 2025)**: All 21 core modules refactored with consistent `quick_smoke_test()` patterns
- Refactoring to use external LLM services instead of in-memory models
- Implementing router for directing requests to appropriate LLM endpoints

## Installed Workflows

**Session Management**:
- `/plan-session-start` - Initialize work session (load history, identify TODOs)
- `/plan-session-end` - Complete end-of-session ritual (history, commits, notifications)

**History Management**:
- `/plan-history-management` - Archive, check, and analyze history.md token health (4 modes)

**Planning is Prompting Core**:
- `/p-is-p-00-start-here` - Entry point with decision matrix and philosophy
- `/p-is-p-01-planning` - Work planning workflow (classify → pattern → breakdown)
- `/p-is-p-02-documentation` - Implementation documentation (for large/complex work)

**Installation Management**:
- `/plan-about` - View installed workflows with version comparison
- `/plan-install-wizard` - Run installation wizard to add/update workflows
- `/plan-uninstall-wizard` - Remove workflows safely with confirmation

**Testing Workflows** (Planning is Prompting):
- `/plan-test-baseline` - Establish pre-change baseline (COSA: smoke + unit tests)
- `/plan-test-remediation` - Post-change verification and remediation
- `/plan-test-harness-update` - Test maintenance planning (analyze changes, identify missing tests)

**Legacy Testing Workflows** (old naming convention - preserved):
- `/smoke-test-baseline` - Pre-change baseline collection (legacy)
- `/smoke-test-remediation` - Post-change verification (legacy)

**Backup Infrastructure**:
- `/plan-backup-check` - Check backup script version against canonical
- `/plan-backup` - Dry-run backup preview (safe default)
- `/plan-backup-write` - Execute actual backup (explicit write mode)
- Script: `src/scripts/backup.sh` - Configured for COSA → DATA02
- Config: `src/scripts/conf/rsync-exclude.txt` - Exclusion patterns

**Meta-Workflow Tools**:
- `/plan-workflow-audit` - Execution compliance audit with automatic remediation

**Custom Workflows** (legacy - preserved):
- `/cosa-session-end` - COSA-specific session end workflow (legacy)

## Planning Workflows

**Entry Point**: See planning-is-prompting → workflow/p-is-p-00-start-here.md

**Two-Step Process**:
1. **Plan the Work** (planning-is-prompting → workflow/p-is-p-01-planning-the-work.md) - Always required
2. **Document Implementation** (planning-is-prompting → workflow/p-is-p-02-documenting-the-implementation.md) - Only for Pattern 1, 2, 5

**Decision Matrix**: Use `/p-is-p-00-start-here` to determine which workflows you need
