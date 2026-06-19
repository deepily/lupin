# Python Package Distribution Plan for CoSA

> **Created:** 2025-05-16

## Executive Summary

This document outlines a comprehensive plan for creating and automating the distribution of the CoSA (Collection of Small Agents) Python package. The automation will trigger whenever a version tag (e.g., v0.0.5) is pushed to the main branch, resulting in automatic testing, building, and publishing to PyPI.

## Current State Analysis

### Existing Structure
- CoSA is a submodule within the genie-in-the-box project
- Has its own requirements.txt
- No existing setup.py or pyproject.toml
- Follows semantic versioning convention
- Contains multiple agent implementations in versioned directories (v000, v010)

### Requirements
- Python 3.8+ compatibility (based on requirements.txt)
- Support for multiple agent versions
- Clean namespace organization
- Automated release process
- Minimal manual intervention

## Implementation Plan

### Phase 1: Package Structure Setup

#### 1.1 Create pyproject.toml
Modern Python packaging recommends pyproject.toml over setup.py. Here's the proposed structure:

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "cosa"
description = "CoSA: Collection of Small Agents - A modular AI agent framework"
authors = [{name = "Your Name", email = "your.email@example.com"}]
readme = "README.md"
license = {file = "LICENSE"}
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.8",
    "Programming Language :: Python :: 3.9",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
requires-python = ">=3.8"
dependencies = [
    # Will be populated from requirements.txt
]
dynamic = ["version"]

[project.urls]
"Homepage" = "https://github.com/deepily/cosa"
"Bug Tracker" = "https://github.com/deepily/cosa/issues"
"Documentation" = "https://github.com/deepily/cosa#readme"

[tool.setuptools.dynamic]
version = {attr = "cosa.__version__"}

[tool.setuptools.packages.find]
include = ["cosa*"]

[tool.setuptools.package-data]
cosa = ["*.md", "*.txt", "*.ini"]
```

#### 1.2 Update __init__.py for Version Management

```python
# cosa/__init__.py
"""
CoSA: Collection of Small Agents

A modular framework for creating and managing AI agents with specialized capabilities.
"""

__version__ = "0.0.5"  # This will be automatically updated by CI/CD

from . import agents
from . import app
from . import memory
from . import tools
from . import utils

__all__ = [
    'agents',
    'app', 
    'memory',
    'tools',
    'utils',
    '__version__'
]
```

#### 1.3 Create MANIFEST.in

```
include README.md
include LICENSE
include requirements.txt
include CLAUDE.md
recursive-include cosa *.ini
recursive-include cosa *.md
recursive-include docs *.png
recursive-exclude * __pycache__
recursive-exclude * *.py[co]
```

### Phase 2: GitHub Actions Workflow

#### 2.1 Create .github/workflows/release.yml

```yaml
name: Release to PyPI

on:
  push:
    tags:
      - 'v*.*.*'  # Trigger on version tags

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.8', '3.9', '3.10', '3.11']
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python ${{ matrix.python-version }}
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install pytest flake8 black
    
    - name: Lint with flake8
      run: |
        flake8 cosa --count --select=E9,F63,F7,F82 --show-source --statistics
        flake8 cosa --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
    
    - name: Format check with black
      run: |
        black --check cosa
    
    - name: Test with pytest
      run: |
        pytest tests/ -v

  build:
    needs: test
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install build dependencies
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    
    - name: Extract version from tag
      id: tag_version
      run: |
        echo "VERSION=${GITHUB_REF#refs/tags/v}" >> $GITHUB_OUTPUT
    
    - name: Update version in __init__.py
      run: |
        sed -i "s/__version__ = .*/__version__ = \"${{ steps.tag_version.outputs.VERSION }}\"/" cosa/__init__.py
    
    - name: Build package
      run: |
        python -m build
    
    - name: Check package
      run: |
        twine check dist/*
    
    - name: Upload artifacts
      uses: actions/upload-artifact@v3
      with:
        name: dist
        path: dist/
  
  release:
    needs: build
    runs-on: ubuntu-latest
    environment: release
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Download artifacts
      uses: actions/download-artifact@v3
      with:
        name: dist
        path: dist/
    
    - name: Create GitHub Release
      uses: actions/create-release@v1
      env:
        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      with:
        tag_name: ${{ github.ref }}
        release_name: Release ${{ github.ref }}
        draft: false
        prerelease: false
    
    - name: Publish to TestPyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.TEST_PYPI_API_TOKEN }}
      run: |
        pip install twine
        twine upload --repository testpypi dist/*
    
    - name: Test installation from TestPyPI
      run: |
        pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple cosa
        python -c "import cosa; print(cosa.__version__)"
    
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: |
        twine upload dist/*
```

### Phase 3: Version Management Strategy

#### 3.1 Semantic Versioning
- Use standard semantic versioning: MAJOR.MINOR.PATCH
- Tag format: `v0.0.5`
- Automatically extract version from git tag during build
- Update `__version__` in code during CI/CD

#### 3.2 Version Synchronization Script

```python
# scripts/update_version.py
#!/usr/bin/env python3
import re
import sys
import subprocess

def get_git_tag():
    """Get the current git tag."""
    try:
        tag = subprocess.check_output(['git', 'describe', '--tags', '--exact-match'], 
                                    stderr=subprocess.DEVNULL).decode().strip()
        return tag
    except subprocess.CalledProcessError:
        return None

def update_version_file(version):
    """Update version in __init__.py."""
    init_file = 'cosa/__init__.py'
    
    with open(init_file, 'r') as f:
        content = f.read()
    
    # Update version using regex
    pattern = r'__version__ = ["\']([^"\']+)["\']'
    new_content = re.sub(pattern, f'__version__ = "{version}"', content)
    
    with open(init_file, 'w') as f:
        f.write(new_content)
    
    print(f"Updated version to {version}")

if __name__ == "__main__":
    tag = get_git_tag()
    if tag and tag.startswith('v'):
        version = tag[1:]  # Remove 'v' prefix
        update_version_file(version)
    else:
        print("No valid tag found")
        sys.exit(1)
```

### Phase 4: Pre-release Checklist

#### 4.1 Manual Steps Before Tagging
1. Update CHANGELOG.md with release notes
2. Run local tests: `pytest tests/`
3. Check code formatting: `black cosa/`
4. Update documentation if needed
5. Commit all changes
6. Create and push tag: `git tag v0.0.5 && git push origin v0.0.5`

#### 4.2 Automated Release Process
Once tag is pushed:
1. GitHub Actions workflow triggers
2. Tests run across Python versions
3. Package builds (sdist and wheel)
4. Version updates automatically
5. Uploads to TestPyPI for validation
6. Tests installation from TestPyPI
7. Publishes to PyPI
8. Creates GitHub release

### Phase 5: Setup Instructions

#### 5.1 Repository Configuration
1. Add PyPI API tokens as GitHub secrets:
   - `PYPI_API_TOKEN`: Production PyPI token
   - `TEST_PYPI_API_TOKEN`: TestPyPI token

2. Create accounts and tokens:
   ```bash
   # Create PyPI account at https://pypi.org
   # Create TestPyPI account at https://test.pypi.org
   # Generate API tokens for both
   ```

3. Configure GitHub repository settings:
   - Enable GitHub Actions
   - Add secrets mentioned above
   - Create "release" environment for production deployments

#### 5.2 Local Development Setup
```bash
# Install development dependencies
pip install -e .[dev]

# Run tests locally
pytest tests/

# Build package locally
python -m build

# Check package
twine check dist/*
```

### Phase 6: Testing Strategy

#### 6.1 Create tests/ Directory Structure
```
tests/
├── __init__.py
├── test_agents/
│   ├── __init__.py
│   ├── test_v010/
│   │   ├── test_date_and_time_agent.py
│   │   ├── test_math_agent.py
│   │   └── ...
│   └── test_agent_base.py
├── test_app/
│   ├── __init__.py
│   └── test_configuration_manager.py
└── test_utils/
    ├── __init__.py
    └── test_util.py
```

#### 6.2 Example Test
```python
# tests/test_package.py
import cosa

def test_version():
    """Test that version is accessible."""
    assert hasattr(cosa, '__version__')
    assert isinstance(cosa.__version__, str)

def test_imports():
    """Test that main modules are importable."""
    from cosa import agents, app, memory, tools, utils
    assert agents is not None
    assert app is not None
    assert memory is not None
    assert tools is not None
    assert utils is not None
```

### Phase 7: Documentation Updates

#### 7.1 Update README.md
Add installation instructions:
```markdown
## Installation

Install CoSA from PyPI:

```bash
pip install cosa
```

For development:
```bash
git clone https://github.com/deepily/cosa.git
cd cosa
pip install -e .[dev]
```
```

#### 7.2 Create CHANGELOG.md
```markdown
# Changelog

All notable changes to CoSA will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.5] - 2025-05-16
### Added
- Initial PyPI package release
- Automated CI/CD pipeline
- Comprehensive test suite

### Changed
- Migrated to pyproject.toml
- Updated package structure

### Fixed
- Import paths for v010 agents
```

## Implementation Timeline

### Week 1: Package Structure
- [ ] Create pyproject.toml
- [ ] Update __init__.py files
- [ ] Create MANIFEST.in
- [ ] Set up basic tests

### Week 2: CI/CD Pipeline
- [ ] Create GitHub Actions workflow
- [ ] Set up PyPI accounts and tokens
- [ ] Configure GitHub secrets
- [ ] Test workflow with dry run

### Week 3: Testing & Documentation
- [ ] Write comprehensive tests
- [ ] Update documentation
- [ ] Create release notes
- [ ] Perform test release to TestPyPI

### Week 4: Production Release
- [ ] Final review and testing
- [ ] Tag first release
- [ ] Monitor automated release
- [ ] Verify PyPI installation

## Troubleshooting Guide

### Common Issues

1. **Version Mismatch**
   - Ensure tag format is `v*.*.*`
   - Check __init__.py version update

2. **Build Failures**
   - Verify all dependencies in requirements.txt
   - Check Python version compatibility

3. **PyPI Upload Errors**
   - Verify API tokens are correct
   - Check package name availability
   - Ensure twine check passes

4. **Test Failures**
   - Run tests locally first
   - Check for missing test dependencies
   - Verify import paths

## Next Steps

1. Review and approve this plan
2. Create necessary accounts (PyPI, TestPyPI)
3. Generate API tokens
4. Implement changes incrementally
5. Test with a release candidate
6. Deploy first official release

## References

- [Python Packaging User Guide](https://packaging.python.org/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [PyPI Publishing Guide](https://pypi.org/help/#publishing)
- [Semantic Versioning](https://semver.org/)