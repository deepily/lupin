#!/usr/bin/env python3
"""
Manual debug test for Gister XML parsing issue
"""

import sys
import os

# Add the cosa module to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from cosa.memory.gister import Gister

def test_gister_manually():
    """Test Gister with the exact strings that were causing errors"""

    print("=" * 80)
    print("MANUAL GISTER DEBUG TEST")
    print("=" * 80)

    # Initialize with debug and verbose flags
    print("Initializing Gister with debug=True, verbose=True...")
    gister = Gister(debug=True, verbose=True)

    # The exact test strings from our earlier debug
    test_strings = [
        "State monitoring test job 1",  # This one worked
        "State monitoring test job 2",  # This one failed
        "State monitoring test job 3"   # This one also failed
    ]

    results = []

    for i, test_string in enumerate(test_strings, 1):
        print(f"\n{'='*60}")
        print(f"TEST {i}: Processing '{test_string}'")
        print(f"{'='*60}")

        try:
            print(f"\n[MANUAL TEST] Calling gister.get_gist('{test_string}')")
            result = gister.get_gist(test_string)
            print(f"\n[MANUAL TEST] ✅ SUCCESS: Got result: '{result}'")
            results.append((test_string, "SUCCESS", result))

        except Exception as e:
            print(f"\n[MANUAL TEST] ❌ ERROR: {str(e)}")
            print(f"[MANUAL TEST] Exception type: {type(e).__name__}")

            # Print full traceback for debugging
            import traceback
            traceback.print_exc()

            results.append((test_string, "ERROR", str(e)))

    # Summary
    print(f"\n{'='*80}")
    print("MANUAL GISTER TEST SUMMARY")
    print(f"{'='*80}")

    for i, (test_string, status, result) in enumerate(results, 1):
        status_icon = "✅" if status == "SUCCESS" else "❌"
        print(f"{i}. '{test_string}': {status_icon} {status}")
        if status == "SUCCESS":
            print(f"   Result: '{result}'")
        else:
            print(f"   Error: {result[:100]}...")

    print(f"\n{'='*80}")

if __name__ == "__main__":
    test_gister_manually()