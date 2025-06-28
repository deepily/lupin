# LUPIN DEVELOPMENT GUIDE

## COMMANDS
- Run FastAPI server: `src/scripts/run-fastapi-gib.sh` (Runs on port 7999)
- Run GUI client: `src/scripts/run-lupin-gui.sh`
- Docker build: `docker build -f docker/gib/Dockerfile .`
- Run GSM8K benchmarks: `src/scripts/run-gsm8k.sh --help`

## CODE STYLE
- **Imports**: Group by stdlib, third-party, local
- **Naming**: snake_case for functions, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **File Naming**:
  - Python files: Use underscores as separators (e.g., `example_implementation.py`)
  - All other files: Use dashes as separators (e.g., `websocket-design.md`, `gib-app.ini`)
  - Date prefixes: Use YYYY.MM.DD format (e.g., `2025.06.03-websocket-design.md`)
- **Formatting**: 4 spaces indentation, spaces around operators, spaces inside brackets
- **Error handling**: Catch specific exceptions, include context in error messages
- **Logging**: Currently uses print() statements rather than a logging framework
- **Types**: Dynamic typing is used (no type annotations)
- **Documentation**: Add docstrings to new functions and classes, follow existing style
- **XML Formatting**: Use XML tags for structured responses in agent communication

## CONFIGURATION
- Config files: `src/conf/gib-app.ini` and `src/conf/gib-app-splainer.ini`
- Environment variables override config file settings
- Use `ConfigurationManager` to access config values

## PROJECT STRUCTURE
- `/src/fastapi_app/`: FastAPI application directory
  - `/src/fastapi_app/main.py`: Main FastAPI server entry point
  - `/src/cosa/rest/routers/`: API endpoint routers
- `/src/cosa/`: Contains the CoSA (Collection of Small Agents) framework
  - **IMPORTANT**: `/src/cosa/` is a separate Git repository (git@github.com:deepily/cosa.git)
  - This directory employs the Git submodule/subtree pattern
  - CoSA has its own README.md and CLAUDE.md files
  - When working with CoSA code, be aware that changes may need to be committed to both repositories
  - **CRITICAL FOR CLAUDE**: Never attempt to manage the git state of the CoSA repository when working
    within the Lupin project. Do not offer to stage, commit, or push changes to the CoSA
    repository. Only manage git operations for the parent Lupin repository.
- `/src/cosa/agents/`: Agent implementations (math, calendar, etc.)
- `/src/cosa/app/`: Core application components
- `/src/cosa/memory/`: Data persistence and memory management
- `/src/cosa/tools/`: External integrations and tools
- `/src/cosa/utils/`: Shared utility functions
- `/src/lib/clients/`: Client interface implementations

## DEBUGGING
- Set `debug=True` and `verbose=True` parameters in class instantiations
- Use `du.print_banner()` from `utils.py` for formatted console messages

## STARTUP PROCEDURE
- The first thing you should do when you start a session is read the global Claude configuration file And follow its instructions.

## PROJECT SHORT NAMES
- This rep SHORT_PROJECT_PREFIX Is [LUPIN]