#!/usr/bin/env python3
"""
Training data distribution analysis for LORA fine-tuning.

Loads the full JSONL training data and prints per-command sample counts,
category breakdowns, and summary statistics. No server, GPU, or vLLM needed.

Usage:
    cd /mnt/DATA01/include/www.deepily.ai/projects/lupin/src
    python scripts/analyze-training-distribution.py

Created: 2026-02-04
"""

import json
import os
import sys

# Bootstrap path setup
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    sys.path.insert( 0, os.path.join( lupin_root, "src" ) )
else:
    # Fallback: derive from script location
    script_dir = os.path.dirname( os.path.abspath( __file__ ) )
    src_dir    = os.path.dirname( script_dir )
    sys.path.insert( 0, src_dir )
    lupin_root = os.path.dirname( src_dir )

import pandas as pd

DATA_DIR = os.path.join( lupin_root, "src", "ephemera", "prompts", "data" )

FILES = {
    "voice-commands-xml-train.jsonl"    : "Voice Commands (train)",
    "voice-commands-xml-test.jsonl"     : "Voice Commands (test)",
    "voice-commands-xml-validate.jsonl" : "Voice Commands (validate)",
}


def categorize_command( cmd ):
    """
    Categorize a command string into a high-level group.

    Requires:
        - cmd is a non-empty string

    Ensures:
        - Returns one of: 'Agent Router', 'Browser Search', 'Browser Navigation', 'Other'
    """
    if cmd.startswith( "agent router" ):
        return "Agent Router"
    elif cmd.startswith( "search" ):
        return "Browser Search"
    elif cmd.startswith( "go to" ):
        return "Browser Navigation"
    else:
        return "Other"


def print_separator( char="-", width=100 ):
    print( char * width )


def main():

    # ── Section 1: File inventory ──────────────────────────────────────────────

    print_separator( "=" )
    print( "  LORA TRAINING DATA DISTRIBUTION ANALYSIS" )
    print_separator( "=" )
    print()
    print( f"  Data directory: {DATA_DIR}" )
    print()

    print_separator()
    print( "  FILE INVENTORY" )
    print_separator()
    print( f"  {'File':<45} {'Rows':>8}   Description" )
    print_separator( "." )

    total_rows = 0
    for filename, description in FILES.items():
        path = os.path.join( DATA_DIR, filename )
        if os.path.exists( path ):
            with open( path, "r" ) as f:
                count = sum( 1 for _ in f )
            total_rows += count
            print( f"  {filename:<45} {count:>8}   {description}" )
        else:
            print( f"  {filename:<45} {'MISSING':>8}   {description}" )

    print_separator( "." )
    print( f"  {'TOTAL':<45} {total_rows:>8}" )
    print()

    # ── Section 2: Load unified training file ──────────────────────────────────

    train_path = os.path.join( DATA_DIR, "voice-commands-xml-train.jsonl" )
    if not os.path.exists( train_path ):
        print( f"ERROR: Training file not found: {train_path}" )
        sys.exit( 1 )

    df = pd.read_json( train_path, lines=True )

    print_separator( "=" )
    print( "  FULL COMMAND DISTRIBUTION (voice-commands-xml-train.jsonl)" )
    print_separator( "=" )
    print( f"  Total training samples: {len( df )}" )
    print( f"  Unique commands: {df[ 'command' ].nunique()}" )
    print()

    # ── Section 3: Per-command counts (sorted by count desc) ───────────────────

    counts = df[ "command" ].value_counts()

    print_separator()
    print( f"  {'#':<4} {'Command':<55} {'Count':>7} {'Pct':>7}" )
    print_separator( "." )

    for i, ( cmd, count ) in enumerate( counts.items(), 1 ):
        pct = 100.0 * count / len( df )
        print( f"  {i:<4} {cmd:<55} {count:>7} {pct:>6.1f}%" )

    print_separator( "." )
    print( f"  {'':4} {'TOTAL':<55} {counts.sum():>7} {'100.0%':>7}" )
    print()

    # ── Section 4: Category breakdown ──────────────────────────────────────────

    df[ "category" ] = df[ "command" ].apply( categorize_command )
    cat_counts = df[ "category" ].value_counts()

    print_separator( "=" )
    print( "  CATEGORY BREAKDOWN" )
    print_separator( "=" )
    print( f"  {'Category':<30} {'Commands':>10} {'Samples':>10} {'Pct':>7}" )
    print_separator( "." )

    for cat in [ "Browser Search", "Browser Navigation", "Agent Router", "Other" ]:
        if cat in cat_counts:
            n_samples  = cat_counts[ cat ]
            n_commands = df[ df[ "category" ] == cat ][ "command" ].nunique()
            pct        = 100.0 * n_samples / len( df )
            print( f"  {cat:<30} {n_commands:>10} {n_samples:>10} {pct:>6.1f}%" )

    print_separator( "." )
    print()

    # ── Section 5: Agent Router detail ─────────────────────────────────────────

    agent_df = df[ df[ "category" ] == "Agent Router" ]
    if len( agent_df ) > 0:
        agent_counts = agent_df[ "command" ].value_counts()

        print_separator( "=" )
        print( "  AGENT ROUTER COMMANDS (detail)" )
        print_separator( "=" )
        print( f"  {'Command':<55} {'Count':>7} {'Pct of Total':>14}" )
        print_separator( "." )

        for cmd, count in agent_counts.items():
            pct = 100.0 * count / len( df )
            print( f"  {cmd:<55} {count:>7} {pct:>13.2f}%" )

        print_separator( "." )
        print( f"  {'SUBTOTAL':<55} {agent_counts.sum():>7} {100.0 * agent_counts.sum() / len( df ):>13.2f}%" )
        print()

    # ── Section 6: Summary statistics ──────────────────────────────────────────

    print_separator( "=" )
    print( "  SUMMARY STATISTICS (samples per command)" )
    print_separator( "=" )
    print( f"  Min    : {counts.min():>7}" )
    print( f"  Max    : {counts.max():>7}" )
    print( f"  Mean   : {counts.mean():>7.1f}" )
    print( f"  Median : {counts.median():>7.1f}" )
    print( f"  Std Dev: {counts.std():>7.1f}" )
    print()

    # ── Section 7: Imbalance detection ─────────────────────────────────────────

    ratio = counts.max() / counts.min() if counts.min() > 0 else float( "inf" )

    print_separator( "=" )
    print( "  IMBALANCE ANALYSIS" )
    print_separator( "=" )
    print( f"  Max/Min ratio     : {ratio:.1f}x" )
    print( f"  Most samples      : {counts.idxmax()} ({counts.max()})" )
    print( f"  Fewest samples    : {counts.idxmin()} ({counts.min()})" )

    if ratio > 10:
        print( f"\n  ⚠ WARNING: {ratio:.0f}x imbalance detected — consider rebalancing" )
    elif ratio > 5:
        print( f"\n  ⚡ MODERATE: {ratio:.0f}x imbalance — may affect underrepresented commands" )
    else:
        print( f"\n  ✓ Distribution looks reasonably balanced ({ratio:.1f}x ratio)" )

    print()
    print_separator( "=" )


if __name__ == "__main__":
    main()
