# COSA Framework Smoke Test Prompts

This directory contains smoke test prompts specifically designed for COSA framework development and testing.

## COSA Framework Prompts

### 🔧 Framework-Specific Testing

#### `cosa-baseline-smoke-test-prompt.md`
**Role**: Establishes COSA framework baseline for standalone development
- **When to use**: Before major COSA framework changes when working in COSA-only context
- **Scope**: COSA framework modules only (Core, Agents, REST, Memory, Training)
- **Mode**: Pure data collection focused on framework health
- **Output**: COSA-specific baseline report with framework module analysis
- **Key features**:
  - Works independently of Lupin project
  - Optional notification integration (uses parent Lupin notification if available)
  - Framework-focused performance metrics
  - COSA-specific test category breakdown

#### `cosa-post-change-smoke-test-prompt.md`
**Role**: Verifies COSA framework health and fixes regressions in standalone context
- **When to use**: After COSA framework changes in standalone development
- **Scope**: COSA framework modules only
- **Mode**: Framework-focused comparison and remediation
- **Output**: COSA framework remediation report with module-specific fixes
- **Key features**:
  - Standalone operation with COSA-specific remediation workflows
  - Framework module regression analysis
  - COSA-focused performance comparison
  - Emergency escalation for critical framework issues

## 🤔 When to Use COSA Prompts vs Lupin Prompts

### Use COSA Prompts When:
✅ **Working solely within COSA framework**
✅ **COSA-only development session**
✅ **Framework refactoring that doesn't affect Lupin**
✅ **COSA module development (agents, memory, training, etc.)**
✅ **Framework testing without Lupin dependencies**

### Use Lupin Prompts Instead When:
❌ **Changes affect both Lupin and COSA**
❌ **Working in full Lupin project context**
❌ **Changes to Lupin's integration with COSA**
❌ **Full system testing required**

## Decision Matrix

| Change Type | Prompt Location | Prompt File | Scope |
|-------------|-----------------|-------------|--------|
| COSA agents only | `/src/cosa/rnd/prompts/` | `cosa-baseline-*` | Framework |
| COSA memory only | `/src/cosa/rnd/prompts/` | `cosa-baseline-*` | Framework |
| COSA training only | `/src/cosa/rnd/prompts/` | `cosa-baseline-*` | Framework |
| Lupin + COSA | `/src/rnd/prompts/` | `baseline-*` (TEST_SCOPE="full") | Full system |
| Lupin only | `/src/rnd/prompts/` | `baseline-*` (TEST_SCOPE="lupin") | Lupin only |

## COSA Framework Testing Workflow

### 1. Before Framework Changes
```bash
# Navigate to COSA directory
cd /path/to/cosa

# Use COSA baseline prompt to establish framework health
# Copy and follow: cosa-baseline-smoke-test-prompt.md
```

### 2. After Framework Changes
```bash
# Navigate to COSA directory
cd /path/to/cosa

# Use COSA post-change prompt to verify and fix issues
# Copy and follow: cosa-post-change-smoke-test-prompt.md
# Remember: Must have baseline report from step 1
```

### 3. Integration Testing
```bash
# Navigate to Lupin root
cd /path/to/lupin

# Use Lupin prompts to test COSA integration
# Follow: /src/rnd/prompts/baseline-smoke-test-prompt.md (TEST_SCOPE="full")
```

## COSA-Specific Features

### Framework Module Coverage
- **Core**: Basic COSA framework functionality
- **Agents**: All agent implementations and base classes
- **REST**: API endpoints and routing
- **Memory**: Data persistence and caching
- **Training**: ML training and model management

### Standalone Operation
- **Independent**: No Lupin dependencies required
- **Optional Integration**: Uses parent notification system if available
- **Framework Focus**: Metrics and analysis specific to COSA modules
- **Isolated Testing**: Tests only COSA framework components

### Performance Metrics
- **Module Loading**: COSA import and initialization times
- **Memory Usage**: Framework memory footprint
- **Test Execution**: COSA test suite performance
- **Framework Operations**: Core COSA functionality timing

## Environment Setup

### Required Dependencies
```bash
# COSA framework must be accessible
export PYTHONPATH="/path/to/parent/src:$PYTHONPATH"

# Verify COSA can be imported
python -c "import cosa; print('✓ COSA framework accessible')"
```

### Optional Dependencies
```bash
# Parent Lupin notification system (if available)
# Will be detected and used automatically if present
/path/to/lupin/src/scripts/notify.sh
```

## File Structure

```
src/cosa/rnd/prompts/
├── README.md                              # This file
├── cosa-baseline-smoke-test-prompt.md     # Framework baseline
└── cosa-post-change-smoke-test-prompt.md  # Framework verification
```

## Related Documentation

- **Parent Lupin Prompts**: `/src/rnd/prompts/` (for full system testing)
- **Universal Templates**: `/src/rnd/prompts/templates/` (for other projects)
- **COSA Framework Docs**: `/src/cosa/README.md`
- **COSA Testing Infrastructure**: `/src/cosa/tests/`

## Quick Start

### Establishing COSA Framework Baseline
1. Navigate to COSA directory: `cd /path/to/cosa`
2. Copy `cosa-baseline-smoke-test-prompt.md` contents
3. Follow the prompt instructions step by step
4. Save the generated baseline report for later comparison

### Verifying COSA Framework After Changes
1. Ensure you have a baseline report from previous step
2. Navigate to COSA directory: `cd /path/to/cosa`
3. Copy `cosa-post-change-smoke-test-prompt.md` contents
4. Follow the prompt instructions for verification and remediation
5. Document all fixes and final results

Remember: COSA prompts are designed for framework-only development. For full system testing that includes Lupin integration, use the parent Lupin prompts with appropriate TEST_SCOPE settings.