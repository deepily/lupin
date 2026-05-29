# Branch Analyzer - Comprehensive Git Branch Change Analysis

A professional, COSA framework-compliant tool for analyzing git branch changes with detailed categorization by file type and separation of code from documentation.

## Overview

Branch Analyzer provides comprehensive statistics about code changes between git branches, including:

- **Overall summaries**: Total lines added/removed, net changes, files changed
- **File type categorization**: Automatic classification by extension
- **Code vs Documentation**: Separates code from comments/docstrings for Python, JavaScript, and TypeScript
- **Multiple output formats**: Console (human-readable), JSON (machine-readable), Markdown (documentation-friendly)
- **Configurable**: All settings customizable via YAML configuration files
- **Robust error handling**: Clear error messages with recovery suggestions
- **COSA standards compliant**: Design by Contract docstrings, proper error handling, smoke tests

## Quick Start

```bash
# Basic usage (defaults: current directory, HEAD → main)
python -m cosa.repo.run_branch_analyzer

# Analyze a different repository (e.g., COSA repo from Lupin src directory)
cd /path/to/lupin/src
python -m cosa.repo.run_branch_analyzer --repo-path cosa

# Compare specific branches
python -m cosa.repo.run_branch_analyzer --base develop --head feature-branch

# JSON output
python -m cosa.repo.run_branch_analyzer --output json > analysis.json

# Save to file
python -m cosa.repo.run_branch_analyzer --save-output report.txt
```

### Understanding Defaults

**By default, the tool compares your current branch (HEAD) to main:**
- `--repo-path` defaults to `.` (current directory)
- `--base` defaults to `main` (configurable)
- `--head` defaults to `HEAD` (your currently checked-out branch)

**HEAD Resolution**: When you use `HEAD`, the tool automatically resolves it to your actual branch name. For example, if you're on branch `wip-v0.0.9-feature`, the output will show `wip-v0.0.9-feature → main` (not `HEAD → main`).

## Installation

### Requirements

- Python 3.8+
- git (command-line tool)
- PyYAML (for configuration files)

```bash
# Install PyYAML if not already installed
pip install pyyaml
```

### Package Structure

```
cosa/repo/
├── branch_change_analysis.py          # Original (preserved as reference)
├── branch_analyzer/                    # New implementation package
│   ├── __init__.py
│   ├── analyzer.py                    # Main orchestrator
│   ├── config_loader.py               # YAML configuration handling
│   ├── file_classifier.py             # File type detection
│   ├── line_classifier.py             # Code vs comment detection
│   ├── git_diff_parser.py             # Git command execution
│   ├── statistics_collector.py        # Data aggregation
│   ├── report_formatter.py            # Multiple output formats
│   ├── exceptions.py                  # Custom exception hierarchy
│   └── default_config.yaml            # Default configuration
├── branch_analyzer.py                 # CLI entry point
└── README-branch-analyzer.md          # This file
```

## Usage

### Command Line Interface

```bash
python -m cosa.repo.run_branch_analyzer [OPTIONS]

Options:
  --repo-path PATH      Path to git repository to analyze
                        Default: . (current directory)

  --base BRANCH         Base branch for comparison (what you're comparing FROM)
                        Default: main (configurable via config file)

  --head BRANCH         Head branch for comparison (what you're comparing TO)
                        Default: HEAD (your currently checked-out branch)
                        Note: HEAD is automatically resolved to actual branch name

  --config FILE         Configuration file path
                        Default: embedded default_config.yaml

  --output FORMAT       Output format: console, json, markdown
                        Default: console

  --save-output FILE    Save output to file instead of stdout

  --verbose, -v         Verbose output (show progress)

  --debug, -d           Debug mode (show internal operations and branch resolution)

  --help, -h            Show help message
```

### Understanding Arguments

**`--base` (baseline branch)**:
- The "old" state you're comparing FROM
- Usually `main`, `master`, or `develop`
- Shows what existed before your changes
- Default: `main`

**`--head` (target branch)**:
- The "new" state you're comparing TO
- Use `HEAD` to compare your current branch
- `HEAD` automatically resolves to actual branch name
- Default: `HEAD` (current branch)

**`--repo-path` (repository location)**:
- Path to the git repository to analyze
- Can be absolute or relative path
- Useful for analyzing submodules or separate repos
- Default: `.` (current directory)

### Examples

```bash
# Compare current branch with main (current directory)
python -m cosa.repo.run_branch_analyzer

# Analyze COSA repo from Lupin src directory
cd /path/to/lupin/src
python -m cosa.repo.run_branch_analyzer --repo-path cosa

# Compare specific branches in a different repo
python -m cosa.repo.run_branch_analyzer --repo-path /path/to/repo --base main --head feature-xyz

# Use custom configuration
python -m cosa.repo.run_branch_analyzer --config my_config.yaml

# Generate JSON output
python -m cosa.repo.run_branch_analyzer --output json > stats.json

# Generate Markdown report
python -m cosa.repo.run_branch_analyzer --output markdown > report.md

# Save console output to file
python -m cosa.repo.run_branch_analyzer --save-output analysis.txt

# Verbose mode for progress updates
python -m cosa.repo.run_branch_analyzer --verbose

# Debug mode for troubleshooting
python -m cosa.repo.run_branch_analyzer --debug

# Analyze COSA repo with debug output
python -m cosa.repo.run_branch_analyzer --repo-path cosa --debug
```

### Programmatic Usage

```python
from cosa.repo.branch_analyzer import BranchChangeAnalyzer

# Simple usage (analyze current directory)
analyzer = BranchChangeAnalyzer()
stats = analyzer.analyze()
output = analyzer.format_results( stats, format='console' )
print( output )

# Analyze a different repository
analyzer = BranchChangeAnalyzer( repo_path='cosa' )
stats = analyzer.analyze()

# Advanced usage
analyzer = BranchChangeAnalyzer(
    config_path = 'my_config.yaml',
    base_branch = 'develop',
    head_branch = 'feature-branch',
    repo_path   = '/path/to/repository',
    debug       = True,
    verbose     = True
)

stats = analyzer.analyze()

# Multiple output formats
console_output  = analyzer.format_results( stats, format='console' )
json_output     = analyzer.format_results( stats, format='json' )
markdown_output = analyzer.format_results( stats, format='markdown' )
```

## Configuration

Branch Analyzer uses YAML configuration files for all settings. A comprehensive default configuration is embedded in `default_config.yaml`.

### Creating a Custom Configuration

Create a YAML file with only the settings you want to override:

```yaml
# my_config.yaml

# Override git settings
git:
  default_base_branch: develop  # Change from 'main' to 'develop'
  diff_algorithm: patience      # Change from 'histogram' to 'patience'

# Add custom file type mappings
file_types:
  extensions:
    '.tsx': typescript  # Already in defaults, but shown for example
    '.vue': javascript  # Add Vue files as JavaScript
    '.go': golang       # Add Go language

# Customize output
output:
  default_format: markdown  # Default to Markdown instead of console
  show_percentages: true
  decimal_places: 2         # Show percentages with 2 decimal places
```

### Configuration Sections

#### Git Settings
```yaml
git:
  default_base_branch: main        # Base branch for comparisons
  default_head_branch: HEAD        # Head branch for comparisons
  diff_algorithm: histogram        # myers, minimal, patience, histogram
  extra_diff_options: []           # Additional git diff options
```

#### File Type Mappings
```yaml
file_types:
  extensions:
    '.py': python
    '.js': javascript
    '.tsx': typescript
    # ... add custom mappings
```

#### Analysis Settings
```yaml
analysis:
  separate_code_comments: true     # Separate code from comments
  track_docstrings: true           # Track Python docstrings separately
  multiline_comment_detection: true
  supported_languages:
    - python
    - javascript
    - typescript
```

#### Output Settings
```yaml
output:
  default_format: console          # console, json, markdown
  color_output: true               # Enable colors in console
  show_percentages: true           # Show percentages in reports
  decimal_places: 1                # Decimal places for percentages
```

#### Formatting Settings
```yaml
formatting:
  column_widths:
    file_type: 15
    counts: 10
    net_change: 12
  border_char: "="
  separator_char: "-"
```

## Output Formats

### Console Format (Human-Readable)

The console output includes comprehensive comparison context followed by detailed statistics:

```
================================================================================
BRANCH COMPARISON ANALYSIS
================================================================================

Repository:     /mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa
Base branch:    main
Current branch: wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups

Comparing: wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups → main
(Shows what you added/changed in 'wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups' compared to 'main')

OVERALL SUMMARY
  Total lines added:   1,234
  Total lines removed: 567
  Net change:          +667
  Files changed:       23

BREAKDOWN BY FILE TYPE
File Type            Added    Removed   Net Change
--------------------------------------------------
Python                856        234       +622
JavaScript            245         89       +156
Markdown              133        244       -111

PYTHON FILES - SOURCE vs DOCUMENTATION
  Added lines:
    Source code:        720  (84.1%)
    Comments (#):        56   (6.5%)
    Docstrings:          80   (9.3%)
    Total added:        856
  Removed lines:        234
  Net change:          +622

================================================================================
```

**Output Header Explanation**:
- **Repository**: Absolute path to the analyzed git repository
- **Base branch**: The baseline/starting point (what you're comparing FROM)
- **Current branch**: The target/ending point (what you're comparing TO)
  - If you used `HEAD`, this shows the actual resolved branch name
- **Comparing**: Visual indicator showing direction of comparison (TO → FROM)
- **Explanation**: Only shown when using `HEAD`, clarifies what the analysis means

### JSON Format (Machine-Readable)

The JSON format includes resolved branch names and repository path:

```json
{
  "base_branch": "main",
  "head_branch": "wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups",
  "repository": "/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa",
  "metadata": {
    "generated_at": "2025-10-06T14:30:00",
    "format": "json",
    "version": "1.0"
  },
  "statistics": {
    "overall": {
      "total_added": 1234,
      "total_removed": 567,
      "net_change": 667,
      "files_changed": 23
    },
    "by_file_type": [
      {
        "file_type": "python",
        "added": 856,
        "removed": 234,
        "net": 622
      }
    ],
    "language_details": {
      "python": {
        "code": 720,
        "comment": 56,
        "docstring": 80,
        "removed": 234,
        "percentages": {
          "code": 84.1,
          "comment": 6.5,
          "docstring": 9.3
        }
      }
    }
  }
}
```

**Key Fields**:
- `base_branch`: Resolved base branch name (not symbolic refs)
- `head_branch`: Resolved current branch name (HEAD → actual branch)
- `repository`: Absolute path to analyzed repository

### Markdown Format (Documentation-Friendly)

The Markdown format includes branch information in the header:

```markdown
# Branch Comparison Analysis: wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups → main

**Repository**: `/mnt/DATA01/include/www.deepily.ai/projects/lupin/src/cosa`
**Base branch**: `main`
**Current branch**: `wip-v0.0.9-2025.09.27-refactoring-snapshot-lookups`
**Generated**: 2025-10-06 14:30:00

## Overall Summary

- **Total lines added**: 1,234
- **Total lines removed**: 567
- **Net change**: +667
- **Files changed**: 23

## Breakdown by File Type

| File Type | Added | Removed | Net Change |
|-----------|-------|---------|------------|
| Python | 856 | 234 | +622 |
| JavaScript | 245 | 89 | +156 |
| Markdown | 133 | 244 | -111 |

## Language-Specific Details

### Python
- **Code**: 720 (84.1%)
- **Comments**: 56 (6.5%)
- **Docstrings**: 80 (9.3%)
- **Removed**: 234
- **Net change**: +622
```

**Markdown Header Elements**:
- Title shows directional comparison with arrow (→)
- Repository path in code formatting
- Resolved branch names (HEAD becomes actual branch)
- Timestamp for documentation purposes

## Testing

### Running Smoke Tests

```bash
# Test all components
cd src/cosa/repo/branch_analyzer
python -m analyzer

# Or directly
python src/cosa/repo/branch_analyzer/analyzer.py
```

Expected output:
```
==================================================
  Branch Analyzer Smoke Test
==================================================

Testing configuration loading...
✓ Configuration loaded successfully
Testing file classification...
✓ File classification working
Testing line classification (Python)...
✓ Python line classification working
Testing line classification (JavaScript)...
✓ JavaScript line classification working
Testing statistics collection...
✓ Statistics collection working
Testing console formatting...
✓ Console formatting working
Testing JSON formatting...
✓ JSON formatting working
Testing Markdown formatting...
✓ Markdown formatting working
Testing exception hierarchy...
✓ Exception hierarchy valid

✓ All smoke tests passed successfully!
```

### Integration Testing

```bash
# Test on actual git repository
cd /path/to/git/repo
python /path/to/branch_analyzer.py --verbose

# Test different formats
python /path/to/branch_analyzer.py --output json | python -m json.tool
python /path/to/branch_analyzer.py --output markdown
```

## Architecture

### Component Overview

1. **ConfigLoader**: Loads and validates YAML configuration
2. **FileTypeClassifier**: Maps file extensions to categories
3. **LineClassifier**: Separates code from comments/docstrings
4. **GitDiffParser**: Executes git commands safely with error handling
5. **StatisticsCollector**: Aggregates line-level data into summaries
6. **ReportFormatter**: Formats statistics in multiple output formats
7. **BranchChangeAnalyzer**: Main orchestrator coordinating all components

### Design Principles

- **Separation of Concerns**: Each component has a single, well-defined responsibility
- **Configuration-Driven**: All behavior customizable without code changes
- **Error Handling**: Comprehensive exception handling with clear error messages
- **Design by Contract**: All functions documented with Requires/Ensures/Raises
- **COSA Standards**: Follows all COSA framework coding conventions
- **Extensibility**: Easy to add new file types, languages, output formats

### Exception Hierarchy

```
BranchAnalyzerError (base)
├── GitCommandError (git subprocess failures)
├── ConfigurationError (config file/validation issues)
├── ParserError (diff parsing problems)
└── ClassificationError (file/line classification issues)
```

## Troubleshooting

### Common Issues

**Issue**: `Git command not found`
**Solution**: Install git and ensure it's in your PATH

**Issue**: `Configuration file not found`
**Solution**: Verify config file path, or omit --config to use defaults

**Issue**: `ModuleNotFoundError: No module named 'yaml'`
**Solution**: Install PyYAML: `pip install pyyaml`

**Issue**: `fatal: ambiguous argument 'main...HEAD'`
**Solution**: Verify branch names exist in repository

### Debug Mode

Enable debug mode to see detailed internal operations:

```bash
python branch_analyzer.py --debug
```

This shows:
- Configuration loading details
- Git commands being executed
- File classification decisions
- Line classification logic
- Statistics updates

## Contributing

### Adding New File Types

1. Edit your configuration file:
```yaml
file_types:
  extensions:
    '.rs': rust
    '.swift': swift
```

2. Optionally add language-specific line classification in `line_classifier.py`

### Adding New Output Formats

1. Add format method to `ReportFormatter` class
2. Update CLI --output choices
3. Add format to documentation

## Comparison with Original

| Feature | Original | New Implementation |
|---------|----------|-------------------|
| Lines of code | 261 | ~2,400 (modular) |
| Error handling | Minimal | Comprehensive |
| Configuration | Hardcoded | YAML-driven |
| Output formats | Console only | Console/JSON/Markdown |
| Documentation | Basic | Design by Contract |
| Testing | None | Smoke tests |
| Extensibility | Difficult | Easy (plugins) |
| COSA compliance | No | Yes (full) |

## License

Part of the COSA framework. See parent project license.

## Contact

For issues or questions, see COSA framework documentation.
