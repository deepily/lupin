# Smoke Test Prompts Directory

This directory contains comprehensive smoke test prompts for establishing baselines and verifying system health after changes.

## Prompt Types and Their Roles

### 🎯 Lupin Project Prompts (Production Ready)

#### `baseline-smoke-test-prompt.md`
**Role**: Establishes comprehensive baseline before major Lupin changes
- **When to use**: Before any significant refactoring, migrations, or infrastructure changes
- **Scope**: Configurable (Lupin + COSA or Lupin-only via TEST_SCOPE)
- **Mode**: Pure data collection - ZERO remediation attempts
- **Output**: Detailed baseline report with pass rates, performance metrics, and issue cataloging
- **Key feature**: Branching logic allows choosing full suite or Lupin-only testing

#### `post-change-smoke-test-prompt.md`
**Role**: Verifies system health after changes and systematically fixes regressions
- **When to use**: After implementing changes to validate and remediate any breaking issues
- **Scope**: Configurable (must match baseline scope)
- **Mode**: Comparison analysis with targeted remediation
- **Output**: Before/after comparison report with complete remediation documentation
- **Key feature**: Systematic regression identification and fix validation

### 🔧 COSA Framework Prompts (Framework Specific)

Located in: `/src/cosa/rnd/prompts/`

#### `cosa-baseline-smoke-test-prompt.md`
**Role**: Establishes COSA framework baseline for standalone COSA development
- **When to use**: Before major COSA framework changes when working in COSA-only context
- **Scope**: COSA framework modules only (Core, Agents, REST, Memory, Training)
- **Mode**: Pure data collection focused on framework health
- **Output**: COSA-specific baseline report with framework module analysis
- **Key feature**: Works independently of Lupin project, optional notification integration

#### `cosa-post-change-smoke-test-prompt.md`
**Role**: Verifies COSA framework health and fixes regressions in standalone context
- **When to use**: After COSA framework changes in standalone development
- **Scope**: COSA framework modules only
- **Mode**: Framework-focused comparison and remediation
- **Output**: COSA framework remediation report with module-specific fixes
- **Key feature**: Standalone operation with COSA-specific remediation workflows

### 📋 Universal Templates (Customizable)

Located in: `/templates/`

#### `baseline-smoke-test-template.md`
**Role**: Universal template for creating baseline prompts for any project
- **When to use**: When setting up smoke testing for new projects
- **Scope**: Completely customizable via placeholders
- **Mode**: Template requiring placeholder replacement and section customization
- **Output**: Project-specific baseline prompt after customization
- **Key feature**: Comprehensive placeholder system for easy adaptation

#### `post-change-smoke-test-template.md`
**Role**: Universal template for creating post-change verification prompts
- **When to use**: When setting up post-change testing for new projects
- **Scope**: Completely customizable via placeholders
- **Mode**: Template requiring placeholder replacement and workflow customization
- **Output**: Project-specific post-change prompt after customization
- **Key feature**: Adaptable remediation workflows for any project structure

## 🤔 Which Prompt Should I Use?

### Decision Tree

```
Are you working in the full Lupin project context?
├── YES: Are you making changes that affect both Lupin and COSA?
│   ├── YES: Use baseline-smoke-test-prompt.md with TEST_SCOPE="full"
│   └── NO: Use baseline-smoke-test-prompt.md with TEST_SCOPE="lupin"
│
└── NO: Are you working only within the COSA framework?
    ├── YES: Use /src/cosa/rnd/prompts/cosa-baseline-smoke-test-prompt.md
    └── NO: Are you setting up testing for a different project?
        └── YES: Use templates/ and customize for your project
```

### Quick Reference

| Scenario | Prompt to Use | Notes |
|----------|---------------|-------|
| Major Lupin refactoring affecting everything | `baseline-smoke-test-prompt.md` (TEST_SCOPE="full") | Full ecosystem testing |
| Lupin-specific changes (UI, API, etc.) | `baseline-smoke-test-prompt.md` (TEST_SCOPE="lupin") | Faster, focused testing |
| COSA framework development only | `/src/cosa/rnd/prompts/cosa-*` | Framework-focused |
| Setting up new project testing | `templates/*.md` | Requires customization |
| After making changes | Use corresponding post-change prompt | Must match baseline scope |

### Examples

**🎯 Full System Baseline Before Migration:**
```bash
# Use: baseline-smoke-test-prompt.md
# Set: TEST_SCOPE="full"
# Reason: Major migration affects both Lupin and COSA
```

**⚡ Quick Lupin UI Changes:**
```bash
# Use: baseline-smoke-test-prompt.md
# Set: TEST_SCOPE="lupin"
# Reason: UI changes don't affect COSA framework
```

**🔧 COSA Agent Development:**
```bash
# Use: /src/cosa/rnd/prompts/cosa-baseline-smoke-test-prompt.md
# Reason: Working in COSA context, no Lupin dependency
```

## How to Use Templates

### 1. Copy Template
Copy the desired template to your project's `rnd/prompts/` directory

### 2. Replace Placeholders
Replace all placeholders with project-specific values:

| Placeholder | Description | Examples |
|-------------|-------------|----------|
| `{{PROJECT_NAME}}` | Project name | Lupin, COSA, MyProject |
| `{{PROJECT_PREFIX}}` | TodoWrite prefix | [LUPIN], [COSA], [MYPROJECT] |
| `{{PROJECT_ROOT}}` | Full path to project root | /path/to/project |
| `{{TEST_SCRIPT}}` | Path to test script | ./tests/run-tests.sh |
| `{{NOTIFICATION_SCRIPT}}` | Path to notification script | ./scripts/notify.sh |
| `{{SERVER_PORT}}` | Server port (if applicable) | 7999, 8000, N/A |
| `{{SERVER_HEALTH_URL}}` | Health check URL | http://localhost:7999/health |

### 3. Customize Sections
Modify sections as needed for your project:

- **Test Categories**: Update to match your project's test structure
- **Report Tables**: Adjust columns and categories
- **Performance Metrics**: Add/remove metrics relevant to your project
- **Notification Logic**: Adapt to your notification system
- **Dependencies**: Update environment setup commands

### 4. Remove Inapplicable Sections
Delete sections that don't apply to your project:

- Server health checks (for library projects)
- Notification system calls (if not available)
- Performance metrics (if not tracked)
- Specific test categories (if not relevant)

## Example Customization

### For a Python Library Project:

```markdown
# Replace placeholders
{{PROJECT_NAME}} → MyLibrary
{{PROJECT_PREFIX}} → [MYLIB]
{{PROJECT_ROOT}} → /home/user/projects/mylibrary
{{TEST_SCRIPT}} → ./scripts/run-tests.sh

# Remove sections
- Server health checks
- FastAPI-specific tests
- WebSocket tests

# Customize categories
| Category | Tests | Passed | Failed | Pass Rate | Status |
|----------|-------|--------|--------|-----------|---------|
| Unit Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Integration Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Performance Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
```

### For a Web Application Project:

```markdown
# Replace placeholders
{{PROJECT_NAME}} → WebApp
{{PROJECT_PREFIX}} → [WEBAPP]
{{SERVER_PORT}} → 3000
{{SERVER_HEALTH_URL}} → http://localhost:3000/api/health

# Customize categories
| Category | Tests | Passed | Failed | Pass Rate | Status |
|----------|-------|--------|--------|-----------|---------|
| Frontend Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Backend API Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| Database Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
| E2E Tests | [#] | [#] | [#] | [XX.X%] | [STATUS] |
```

## Placeholder Reference

### Required Placeholders
These must be replaced for templates to work:

- `{{PROJECT_NAME}}` - Used in titles and documentation
- `{{PROJECT_PREFIX}}` - Used in TodoWrite tasks
- `{{PROJECT_ROOT}}` - Used in path navigation
- `{{TEST_SCRIPT}}` - Used to execute tests

### Optional Placeholders
These can be removed if not applicable:

- `{{NOTIFICATION_SCRIPT}}` - Remove notification sections if not needed
- `{{SERVER_PORT}}` / `{{SERVER_HEALTH_URL}}` - Remove if no server component
- `{{PERFORMANCE_METRICS}}` - Remove if performance not tracked

### Context-Specific Placeholders
These need customization based on your project structure:

- Test category names and counts
- Report table columns
- Performance metric types
- File paths and directory structures

## Benefits of Using Templates

1. **Consistency**: Standardized format across projects
2. **Time Saving**: No need to create prompts from scratch
3. **Best Practices**: Incorporates lessons learned from Lupin/COSA
4. **Customizable**: Easy to adapt to any project needs
5. **Maintainable**: Single source for prompt improvements

## Template Maintenance

- **Updates**: Improvements made to Lupin/COSA prompts should be backported to templates
- **Versioning**: Consider versioning templates for compatibility
- **Documentation**: Keep this README updated with new placeholders or usage patterns