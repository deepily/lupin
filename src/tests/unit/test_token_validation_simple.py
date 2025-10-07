#!/usr/bin/env python3
"""
Simple test script for token validation (no pytest dependency)
"""

import asyncio

# Python path configured by src/tests/conftest.py

# Import the validation function we need to test
from cosa.rest.auth import verify_firebase_token

def test_token_validation():
    """Test token validation behavior"""

    print("="*60)
    print("TOKEN VALIDATION TEST")
    print("="*60)

    # Test valid tokens (should pass)
    print("\n✅ Testing valid tokens")
    valid_tokens = [
        "mock_token_user123",
        "mock_token_test_user",
        "mock_token_email_user@example.com",
        "mock_token_email_test@domain.com"
    ]

    valid_failures = 0
    for token in valid_tokens:
        try:
            result = asyncio.run(verify_firebase_token(token))
            status = "✅ ACCEPTED"
            print(f"  '{token}': {status}")
        except Exception as e:
            status = f"❌ REJECTED ({str(e)[:50]}...)"
            print(f"  '{token}': {status}")
            valid_failures += 1

    # Test invalid tokens that should be rejected (CRITICAL ISSUE)
    print("\n🚨 CRITICAL: Testing invalid tokens that should be rejected")
    invalid_tokens = [
        None,                                    # Null token
        "",                                      # Empty token
        "invalid_prefix_user123",                # Wrong prefix
        "mock_token_",                          # Empty user ID
        "mock_token_email_",                    # Empty email
        "mock_token_email_invalid_email",       # Invalid email format
        12345,                                  # Numeric token
        {"token": "mock_token_user"},           # JSON object
        ["mock_token_user"]                     # Array
    ]

    invalid_accepted = 0
    for token in invalid_tokens:
        try:
            result = asyncio.run(verify_firebase_token(token))
            status = "❌ ACCEPTED"
            print(f"  '{repr(token)}': {status}")
            invalid_accepted += 1
        except Exception as e:
            status = "✅ REJECTED"
            print(f"  '{repr(token)}': {status}")

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Valid token failures: {valid_failures}/{len(valid_tokens)}")
    print(f"Invalid tokens incorrectly accepted: {invalid_accepted}/{len(invalid_tokens)} (CRITICAL)")

    if invalid_accepted > 0:
        print(f"\n🚨 CRITICAL SECURITY ISSUE: {invalid_accepted} invalid tokens incorrectly accepted!")
        print("This matches the baseline smoke test findings.")
        return False
    else:
        print("\n✅ Token validation working correctly")
        return True

if __name__ == "__main__":
    test_token_validation()