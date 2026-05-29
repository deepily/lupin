# COSA Versioning and CI/CD Strategy

> **Date:** 2025-05-28  
> **Author:** Analysis by Claude  
> **Purpose:** Define versioning strategy and CI/CD automation for COSA package distribution

## Executive Summary

This document outlines a comprehensive strategy for version management and automated CI/CD pipeline for building and distributing the COSA package, synchronized with the main branch versioning.

## Versioning Strategy

### Version Synchronization Approach

Since COSA tracks the parent project versions (currently v0.0.5), we'll implement a synchronized versioning strategy:

1. **Main Branch Tags**: Version tags on main branch trigger package builds
2. **Version Format**: Semantic versioning (MAJOR.MINOR.PATCH)
3. **Pre-releases**: Support for alpha/beta/rc releases from feature branches

### Version Sources

```python
# cosa/_version.py
# Single source of truth for version
__version__ = "0.0.5"
__version_info__ = (0, 0, 5)
```

### Dynamic Version Management

Use `setuptools-scm` for automatic version detection from git tags:

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=61.0", "setuptools-scm>=8.0", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools_scm]
# Version derived from git tags
version_scheme = "post-release"
local_scheme = "no-local-version"
write_to = "cosa/_version.py"
write_to_template = '''
# Automatically generated - do not edit
__version__ = "{version}"
__version_info__ = {version_tuple}
'''
```

## CI/CD Pipeline Architecture

### GitHub Actions Workflow

#### 1. Development Workflow (on every push)

```yaml
# .github/workflows/test.yml
name: Test Suite

on:
  push:
    branches: [ main, develop, 'wip-*' ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.8", "3.9", "3.10", "3.11"]
    
    steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # Full history for setuptools-scm
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -e .[dev]
    
    - name: Run tests
      run: |
        pytest tests/
    
    - name: Check code style
      run: |
        flake8 cosa/
        black --check cosa/
```

#### 2. Package Build Workflow (on version tags)

```yaml
# .github/workflows/build-package.yml
name: Build and Publish Package

on:
  push:
    tags:
      - 'v*.*.*'  # Trigger on version tags (v0.0.5, v1.0.0, etc.)
  workflow_dispatch:  # Allow manual trigger

jobs:
  build:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # Full history for version detection
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Install build tools
      run: |
        python -m pip install --upgrade pip
        pip install build twine
    
    - name: Verify version tag matches branch
      run: |
        # Extract version from tag
        VERSION=${GITHUB_REF#refs/tags/v}
        echo "Building version: $VERSION"
        
        # Verify it matches expected pattern
        if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
          echo "Invalid version format: $VERSION"
          exit 1
        fi
    
    - name: Build package
      run: |
        python -m build
        
    - name: Check package
      run: |
        twine check dist/*
        
    - name: Upload artifacts
      uses: actions/upload-artifact@v3
      with:
        name: dist-packages
        path: dist/

  test-package:
    needs: build
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.8", "3.11"]
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Download artifacts
      uses: actions/download-artifact@v3
      with:
        name: dist-packages
        path: dist/
    
    - name: Test installation
      run: |
        # Test wheel installation
        pip install dist/*.whl
        python -c "import cosa; print(cosa.__version__)"
        
        # Test that key imports work
        python -c "from cosa import MathAgent, ConfigurationManager"
        
    - name: Test with dependencies
      run: |
        pip install dist/*.whl[llm-openai,llm-groq]
        python -c "import cosa; print('Optional deps test passed')"

  publish-test-pypi:
    needs: test-package
    runs-on: ubuntu-latest
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
    
    steps:
    - name: Download artifacts
      uses: actions/download-artifact@v3
      with:
        name: dist-packages
        path: dist/
    
    - name: Publish to Test PyPI
      uses: pypa/gh-action-pypi-publish@release/v1
      with:
        repository-url: https://test.pypi.org/legacy/
        password: ${{ secrets.TEST_PYPI_API_TOKEN }}
        skip-existing: true

  publish-pypi:
    needs: publish-test-pypi
    runs-on: ubuntu-latest
    environment: production  # Requires manual approval
    if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
    
    steps:
    - name: Download artifacts
      uses: actions/download-artifact@v3
      with:
        name: dist-packages
        path: dist/
    
    - name: Publish to PyPI
      uses: pypa/gh-action-pypi-publish@release/v1
      with:
        password: ${{ secrets.PYPI_API_TOKEN }}
```

#### 3. Pre-release Workflow

```yaml
# .github/workflows/pre-release.yml
name: Build Pre-release

on:
  push:
    branches:
      - 'release/*'
      - 'rc/*'
  workflow_dispatch:
    inputs:
      prerelease_type:
        description: 'Pre-release type'
        required: true
        default: 'alpha'
        type: choice
        options:
          - alpha
          - beta
          - rc

jobs:
  build-prerelease:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    
    - name: Generate pre-release version
      run: |
        # Get base version from last tag
        LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
        BASE_VERSION=${LAST_TAG#v}
        
        # Generate pre-release version
        if [[ "${{ github.event_name }}" == "workflow_dispatch" ]]; then
          PRERELEASE_TYPE="${{ inputs.prerelease_type }}"
        else
          # Determine from branch name
          if [[ "${{ github.ref }}" == *"rc"* ]]; then
            PRERELEASE_TYPE="rc"
          else
            PRERELEASE_TYPE="beta"
          fi
        fi
        
        # Create version string
        TIMESTAMP=$(date +%Y%m%d%H%M%S)
        VERSION="${BASE_VERSION}.${PRERELEASE_TYPE}${TIMESTAMP}"
        
        echo "PRERELEASE_VERSION=$VERSION" >> $GITHUB_ENV
        
    - name: Build pre-release
      run: |
        # Override version for this build
        echo "__version__ = '${{ env.PRERELEASE_VERSION }}'" > cosa/_version.py
        python -m build
        
    - name: Upload pre-release artifacts
      uses: actions/upload-artifact@v3
      with:
        name: prerelease-${{ env.PRERELEASE_VERSION }}
        path: dist/
```

## Release Process

### 1. Automated Release Notes

```yaml
# .github/release.yml
changelog:
  categories:
    - title: 🚀 Features
      labels:
        - feature
        - enhancement
    - title: 🐛 Bug Fixes
      labels:
        - bug
        - fix
    - title: 📚 Documentation
      labels:
        - documentation
    - title: 🔧 Maintenance
      labels:
        - chore
        - maintenance
    - title: ⚡ Performance
      labels:
        - performance
```

### 2. Release Checklist Action

```yaml
# .github/workflows/release-checklist.yml
name: Release Checklist

on:
  pull_request:
    branches: [ main ]
    types: [ opened, synchronize ]

jobs:
  checklist:
    if: startsWith(github.head_ref, 'release/')
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Check version bump
      run: |
        # Verify _version.py has been updated
        git diff origin/main -- cosa/_version.py | grep -q "^+__version__" || \
          (echo "::error::Version not bumped in cosa/_version.py" && exit 1)
    
    - name: Check CHANGELOG
      run: |
        # Verify CHANGELOG.md has been updated
        git diff origin/main -- CHANGELOG.md | grep -q "^+" || \
          (echo "::error::CHANGELOG.md not updated" && exit 1)
    
    - name: Verify imports
      run: |
        # Check that v000 imports have been removed
        ! grep -r "from cosa.agents.v000" cosa/ || \
          (echo "::error::Found v000 imports" && exit 1)
```

## Version Management Commands

### Makefile for Common Tasks

```makefile
# Makefile
.PHONY: version-patch version-minor version-major

# Get current version
CURRENT_VERSION := $(shell python -c "from cosa._version import __version__; print(__version__)")

version-patch:
	@echo "Current version: $(CURRENT_VERSION)"
	@NEW_VERSION=$$(python -c "v='$(CURRENT_VERSION)'.split('.'); v[-1]=str(int(v[-1])+1); print('.'.join(v))") && \
	echo "New version: $$NEW_VERSION" && \
	echo "__version__ = '$$NEW_VERSION'" > cosa/_version.py && \
	git add cosa/_version.py && \
	git commit -m "Bump version to $$NEW_VERSION" && \
	git tag -a "v$$NEW_VERSION" -m "Release version $$NEW_VERSION"

version-minor:
	@echo "Current version: $(CURRENT_VERSION)"
	@NEW_VERSION=$$(python -c "v='$(CURRENT_VERSION)'.split('.'); v[1]=str(int(v[1])+1); v[2]='0'; print('.'.join(v))") && \
	echo "New version: $$NEW_VERSION" && \
	echo "__version__ = '$$NEW_VERSION'" > cosa/_version.py && \
	git add cosa/_version.py && \
	git commit -m "Bump version to $$NEW_VERSION" && \
	git tag -a "v$$NEW_VERSION" -m "Release version $$NEW_VERSION"

version-major:
	@echo "Current version: $(CURRENT_VERSION)"
	@NEW_VERSION=$$(python -c "v='$(CURRENT_VERSION)'.split('.'); v[0]=str(int(v[0])+1); v[1]='0'; v[2]='0'; print('.'.join(v))") && \
	echo "New version: $$NEW_VERSION" && \
	echo "__version__ = '$$NEW_VERSION'" > cosa/_version.py && \
	git add cosa/_version.py && \
	git commit -m "Bump version to $$NEW_VERSION" && \
	git tag -a "v$$NEW_VERSION" -m "Release version $$NEW_VERSION"

release:
	@echo "Preparing release..."
	@git push origin main
	@git push origin --tags
```

## Integration with Development Workflow

### Branch Protection Rules

Configure main branch protection:
- Require PR reviews
- Require status checks (tests, linting)
- Require up-to-date branches
- Include administrators

### Release Branch Workflow

```bash
# Create release branch
git checkout -b release/0.0.6

# Update version
make version-patch

# Update CHANGELOG
# ... edit CHANGELOG.md ...

# Create PR to main
git push origin release/0.0.6
# Create PR via GitHub

# After merge, tag will trigger package build
```

## Monitoring and Notifications

### Slack/Discord Integration

```yaml
# In build workflow
- name: Notify success
  if: success()
  uses: slackapi/slack-github-action@v1
  with:
    payload: |
      {
        "text": "COSA ${{ github.ref_name }} published to PyPI successfully!"
      }
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK }}
```

### Package Statistics

Monitor package downloads and usage:
- PyPI download statistics
- GitHub release download counts
- Test PyPI validation metrics

## Security Considerations

### Secret Management
- `PYPI_API_TOKEN`: Production PyPI token
- `TEST_PYPI_API_TOKEN`: Test PyPI token
- `SLACK_WEBHOOK`: Notification webhook
- Use GitHub environments for production deploys

### Supply Chain Security
- Pin action versions
- Use dependabot for action updates
- Verify package integrity before publishing
- Sign releases with GPG

## Summary

This CI/CD strategy provides:
1. **Automated version management** synchronized with git tags
2. **Multi-stage testing** before publication
3. **Pre-release support** for testing
4. **Automated deployment** to PyPI
5. **Release safety** with Test PyPI validation
6. **Manual approval** for production releases

The workflow ensures that every version tagged on the main branch automatically builds, tests, and publishes a pip-installable package, maintaining version consistency between the repository and the distributed package.