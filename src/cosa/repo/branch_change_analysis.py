#!/usr/bin/env python3
"""
Analyze git diff between current branch and main branch.
Categorize changes by file type and separate code from comments for Python/JS.
"""

import subprocess
import re
from collections import defaultdict
from pathlib import Path

def get_file_type(filename):
    """Categorize file by extension."""
    if not filename or filename == '/dev/null':
        return 'other'

    ext = Path(filename).suffix.lower()

    type_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.md': 'markdown',
        '.html': 'html',
        '.css': 'css',
        '.sh': 'shell',
        '.ini': 'config',
        '.sql': 'sql',
        '.db': 'binary',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.txt': 'text',
        '.xml': 'xml',
    }

    return type_map.get(ext, 'other')

def is_python_comment_or_docstring(line):
    """Check if a Python line is a comment or docstring."""
    stripped = line.strip()

    # Skip empty lines
    if not stripped:
        return None

    # Single-line comments
    if stripped.startswith('#'):
        return 'comment'

    # Docstrings (simplified detection)
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return 'docstring'
    if stripped.endswith('"""') or stripped.endswith("'''"):
        return 'docstring'

    return 'code'

def is_javascript_comment(line):
    """Check if a JavaScript line is a comment."""
    stripped = line.strip()

    # Skip empty lines
    if not stripped:
        return None

    # Single-line comments
    if stripped.startswith('//'):
        return 'comment'

    # Multi-line comment markers
    if stripped.startswith('/*') or stripped.startswith('*') or stripped.endswith('*/'):
        return 'comment'

    return 'code'

def analyze_diff():
    """Analyze the git diff and categorize changes."""

    # Get the full diff
    result = subprocess.run(
        ['git', 'diff', 'main...HEAD'],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Error running git diff: {result.stderr}")
        return

    diff_lines = result.stdout.split('\n')

    # Statistics by file type
    stats = defaultdict(lambda: {'added': 0, 'removed': 0})

    # Python/JS breakdown
    python_stats = {'code': 0, 'comment': 0, 'docstring': 0, 'removed': 0}
    js_stats = {'code': 0, 'comment': 0, 'removed': 0}

    current_file = None
    current_type = None
    in_python_docstring = False
    in_js_multiline_comment = False

    for line in diff_lines:
        # Track current file
        if line.startswith('diff --git'):
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].lstrip('b/')
                current_type = get_file_type(current_file)
                in_python_docstring = False
                in_js_multiline_comment = False

        # Skip non-content lines
        if not line or line.startswith('diff ') or line.startswith('index ') or \
           line.startswith('--- ') or line.startswith('+++ ') or \
           line.startswith('@@ ') or line.startswith('Binary '):
            continue

        # Analyze added/removed lines
        if line.startswith('+') and not line.startswith('+++'):
            added_line = line[1:]  # Remove the '+' prefix
            stats[current_type]['added'] += 1

            # Analyze Python code vs comments
            if current_type == 'python':
                # Track docstring state
                if '"""' in added_line or "'''" in added_line:
                    in_python_docstring = not in_python_docstring

                if in_python_docstring:
                    python_stats['docstring'] += 1
                else:
                    line_type = is_python_comment_or_docstring(added_line)
                    if line_type == 'comment':
                        python_stats['comment'] += 1
                    elif line_type == 'docstring':
                        python_stats['docstring'] += 1
                    elif line_type == 'code':
                        python_stats['code'] += 1

            # Analyze JavaScript code vs comments
            elif current_type == 'javascript':
                # Track multiline comment state
                stripped = added_line.strip()
                if '/*' in stripped:
                    in_js_multiline_comment = True
                if '*/' in stripped:
                    in_js_multiline_comment = False

                if in_js_multiline_comment:
                    js_stats['comment'] += 1
                else:
                    line_type = is_javascript_comment(added_line)
                    if line_type == 'comment':
                        js_stats['comment'] += 1
                    elif line_type == 'code':
                        js_stats['code'] += 1

        elif line.startswith('-') and not line.startswith('---'):
            stats[current_type]['removed'] += 1

            if current_type == 'python':
                python_stats['removed'] += 1
            elif current_type == 'javascript':
                js_stats['removed'] += 1

    # Print results
    print("=" * 80)
    print("CODE CHANGES ANALYSIS: Current Branch vs Main")
    print("=" * 80)
    print()

    # Overall summary
    total_added = sum(s['added'] for s in stats.values())
    total_removed = sum(s['removed'] for s in stats.values())

    print(f"OVERALL SUMMARY")
    print(f"  Total lines added:   {total_added:,}")
    print(f"  Total lines removed: {total_removed:,}")
    print(f"  Net change:          {total_added - total_removed:+,}")
    print()

    # By file type
    print("BREAKDOWN BY FILE TYPE")
    print(f"{'File Type':<15} {'Added':>10} {'Removed':>10} {'Net Change':>12}")
    print("-" * 50)

    # Sort by total changes (added + removed)
    sorted_types = sorted(stats.items(),
                         key=lambda x: x[1]['added'] + x[1]['removed'],
                         reverse=True)

    for file_type, counts in sorted_types:
        added = counts['added']
        removed = counts['removed']
        net = added - removed
        print(f"{file_type.capitalize():<15} {added:>10,} {removed:>10,} {net:>+12,}")

    print()

    # Python breakdown
    if stats['python']['added'] > 0:
        print("PYTHON FILES - SOURCE vs DOCUMENTATION")
        py_total = python_stats['code'] + python_stats['comment'] + python_stats['docstring']
        py_removed = python_stats['removed']

        print(f"  Added lines:")
        print(f"    Source code:      {python_stats['code']:>8,}  ({100*python_stats['code']/py_total if py_total > 0 else 0:>5.1f}%)")
        print(f"    Comments (#):     {python_stats['comment']:>8,}  ({100*python_stats['comment']/py_total if py_total > 0 else 0:>5.1f}%)")
        print(f"    Docstrings:       {python_stats['docstring']:>8,}  ({100*python_stats['docstring']/py_total if py_total > 0 else 0:>5.1f}%)")
        print(f"    Total added:      {py_total:>8,}")
        print(f"  Removed lines:      {py_removed:>8,}")
        print(f"  Net change:         {py_total - py_removed:>+8,}")
        print()

    # JavaScript breakdown
    if stats['javascript']['added'] > 0:
        print("JAVASCRIPT FILES - SOURCE vs DOCUMENTATION")
        js_total = js_stats['code'] + js_stats['comment']
        js_removed = js_stats['removed']

        print(f"  Added lines:")
        print(f"    Source code:      {js_stats['code']:>8,}  ({100*js_stats['code']/js_total if js_total > 0 else 0:>5.1f}%)")
        print(f"    Comments:         {js_stats['comment']:>8,}  ({100*js_stats['comment']/js_total if js_total > 0 else 0:>5.1f}%)")
        print(f"    Total added:      {js_total:>8,}")
        print(f"  Removed lines:      {js_removed:>8,}")
        print(f"  Net change:         {js_total - js_removed:>+8,}")
        print()

    # File count by type
    print("FILES CHANGED BY TYPE")
    result = subprocess.run(
        ['git', 'diff', '--name-only', 'main...HEAD'],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        files = result.stdout.strip().split('\n')
        file_counts = defaultdict(int)

        for f in files:
            if f:
                file_counts[get_file_type(f)] += 1

        sorted_counts = sorted(file_counts.items(), key=lambda x: x[1], reverse=True)

        print(f"{'File Type':<15} {'Count':>8}")
        print("-" * 25)
        for file_type, count in sorted_counts:
            print(f"{file_type.capitalize():<15} {count:>8}")

        print(f"\n  Total files:      {len(files):>8}")

    print()
    print("=" * 80)

if __name__ == '__main__':
    analyze_diff()
