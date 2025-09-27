#!/usr/bin/env python3
"""
Simple test script for session ID validation (no pytest dependency)
"""

import sys
import os

# Add the cosa module to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Import the validation function we need to test
from cosa.rest.routers.websocket import is_valid_session_id

def test_session_id_validation():
    """Test session ID validation behavior"""

    print("="*60)
    print("SESSION ID VALIDATION TEST")
    print("="*60)

    # Test current behavior with tab characters (CRITICAL ISSUE)
    print("\n🚨 CRITICAL: Testing tab character rejection")
    tab_test_cases = [
        "wise\tpenguin",      # Tab between words - SHOULD FAIL
        "\twise penguin",     # Tab at start - SHOULD FAIL
        "wise penguin\t",     # Tab at end - SHOULD FAIL
    ]

    tab_failures = 0
    for session_id in tab_test_cases:
        result = is_valid_session_id(session_id)
        status = "✅ REJECTED" if not result else "❌ ACCEPTED"
        print(f"  '{repr(session_id)}': {status}")
        if result:  # If it was accepted, that's a failure
            tab_failures += 1

    # Test current behavior with newline characters (CRITICAL ISSUE)
    print("\n🚨 CRITICAL: Testing newline character rejection")
    newline_test_cases = [
        "wise\npenguin",      # Newline between words - SHOULD FAIL
        "\nwise penguin",     # Newline at start - SHOULD FAIL
        "wise penguin\n",     # Newline at end - SHOULD FAIL
    ]

    newline_failures = 0
    for session_id in newline_test_cases:
        result = is_valid_session_id(session_id)
        status = "✅ REJECTED" if not result else "❌ ACCEPTED"
        print(f"  '{repr(session_id)}': {status}")
        if result:  # If it was accepted, that's a failure
            newline_failures += 1

    # Test valid cases (should pass)
    print("\n✅ Testing valid session IDs")
    valid_test_cases = [
        "wise penguin",
        "happy cat",
        "smart dog"
    ]

    valid_failures = 0
    for session_id in valid_test_cases:
        result = is_valid_session_id(session_id)
        status = "✅ ACCEPTED" if result else "❌ REJECTED"
        print(f"  '{session_id}': {status}")
        if not result:  # If it was rejected, that's a failure
            valid_failures += 1

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Tab character failures: {tab_failures}/{len(tab_test_cases)} (CRITICAL)")
    print(f"Newline character failures: {newline_failures}/{len(newline_test_cases)} (CRITICAL)")
    print(f"Valid ID failures: {valid_failures}/{len(valid_test_cases)}")

    total_critical_failures = tab_failures + newline_failures
    if total_critical_failures > 0:
        print(f"\n🚨 CRITICAL SECURITY ISSUE: {total_critical_failures} whitespace characters incorrectly accepted!")
        print("This matches the baseline smoke test findings.")
        return False
    else:
        print("\n✅ Session ID validation working correctly")
        return True

if __name__ == "__main__":
    test_session_id_validation()