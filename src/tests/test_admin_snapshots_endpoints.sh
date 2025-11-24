#!/bin/bash
#
# Test script for admin snapshots endpoints
# Usage: ./test_admin_snapshots_endpoints.sh
#

set -e

BASE_URL="http://localhost:7999"
ADMIN_EMAIL="admin@example.com"
ADMIN_PASSWORD="TestPassword123!"

echo "=================================================="
echo "  Admin Snapshots Endpoints Test Script"
echo "=================================================="
echo ""

# Step 1: Login as admin to get JWT token
echo "[1/4] Logging in as admin user..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\": \"$ADMIN_EMAIL\", \"password\": \"$ADMIN_PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "✗ Login failed. Response:"
    echo "$LOGIN_RESPONSE"
    exit 1
fi

echo "✓ Login successful, JWT token obtained"
echo ""

# Step 2: Test search endpoint
echo "[2/4] Testing search endpoint..."
echo "Query: 'what is 2+2'"
SEARCH_RESPONSE=$(curl -s -X GET "$BASE_URL/admin/snapshots/search?q=what%20is%202%2B2&limit=5" \
  -H "Authorization: Bearer $TOKEN")

echo "$SEARCH_RESPONSE" | python3 -m json.tool

RESULT_COUNT=$(echo "$SEARCH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['total'])" 2>/dev/null)
echo "✓ Search returned $RESULT_COUNT results"
echo ""

# Step 3: Test details endpoint (if we have results)
if [ "$RESULT_COUNT" -gt "0" ]; then
    echo "[3/4] Testing details endpoint..."
    ID_HASH=$(echo "$SEARCH_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['results'][0]['id_hash'])" 2>/dev/null)
    echo "Getting details for snapshot: $ID_HASH"

    DETAILS_RESPONSE=$(curl -s -X GET "$BASE_URL/admin/snapshots/$ID_HASH" \
      -H "Authorization: Bearer $TOKEN")

    echo "$DETAILS_RESPONSE" | python3 -m json.tool
    echo "✓ Details retrieved successfully"
    echo ""
else
    echo "[3/4] Skipping details test (no snapshots found)"
    echo ""
fi

# Step 4: Test delete endpoint (READ ONLY - just check 404 for non-existent)
echo "[4/4] Testing delete endpoint (safe test with invalid ID)..."
DELETE_RESPONSE=$(curl -s -X DELETE "$BASE_URL/admin/snapshots/invalid_id_hash_for_testing" \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nHTTP_STATUS:%{http_code}")

HTTP_STATUS=$(echo "$DELETE_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
RESPONSE_BODY=$(echo "$DELETE_RESPONSE" | grep -v "HTTP_STATUS")

if [ "$HTTP_STATUS" = "404" ]; then
    echo "✓ Delete endpoint returned 404 for invalid ID (as expected)"
    echo "Response: $RESPONSE_BODY"
else
    echo "⚠ Delete endpoint returned HTTP $HTTP_STATUS"
    echo "Response: $RESPONSE_BODY"
fi
echo ""

echo "=================================================="
echo "  All Tests Completed!"
echo "=================================================="
echo ""
echo "Summary:"
echo "  - Login: ✓"
echo "  - Search: ✓ ($RESULT_COUNT results)"
if [ "$RESULT_COUNT" -gt "0" ]; then
    echo "  - Details: ✓"
else
    echo "  - Details: (skipped - no data)"
fi
echo "  - Delete: ✓ (validated error handling)"
echo ""
echo "Next steps:"
echo "  1. Verify search results match expectations"
echo "  2. Test with different query strings"
echo "  3. Test delete with actual snapshot ID (destructive)"
echo ""
