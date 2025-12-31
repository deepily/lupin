#!/bin/bash
#################################################################
# cloud-run-validate.sh
#
# Purpose: Validate Cloud Run deployment
# Usage: ./src/scripts/cloud-run-validate.sh <service-url>
#
# Arguments:
#   service-url - Cloud Run service URL (e.g., https://lupin-xxx.run.app)
#
# Example:
#   ./src/scripts/cloud-run-validate.sh https://lupin-12345-uc.a.run.app
#################################################################

set -e  # Exit on any error

# Configuration
SERVICE_URL="$1"
PROJECT_ID="hello-world-foo-423219"
REGION="us-central1"
SERVICE_NAME="lupin"

if [ -z "$SERVICE_URL" ]; then
    echo "Usage: $0 <service-url>"
    echo "Example: $0 https://lupin-12345-uc.a.run.app"
    exit 1
fi

echo "================================================================"
echo "  Lupin Cloud Run - Validation"
echo "================================================================"
echo ""
echo "Service URL: $SERVICE_URL"
echo ""

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to report test results
test_result() {
    local test_name="$1"
    local status="$2"

    if [ "$status" == "PASS" ]; then
        echo "✓ $test_name"
        ((TESTS_PASSED++))
    else
        echo "✗ $test_name"
        ((TESTS_FAILED++))
    fi
}

echo "[1/6] Testing health endpoint..."
if curl -s -f "$SERVICE_URL/health" > /dev/null 2>&1; then
    test_result "Health endpoint" "PASS"
else
    test_result "Health endpoint" "FAIL"
fi
echo ""

echo "[2/6] Testing root endpoint..."
if curl -s -f "$SERVICE_URL/" > /dev/null 2>&1; then
    test_result "Root endpoint" "PASS"
else
    test_result "Root endpoint" "FAIL"
fi
echo ""

echo "[3/6] Testing authentication endpoints..."
# Test login endpoint structure (should return 422 with no body, not 404)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$SERVICE_URL/auth/login" -H "Content-Type: application/json")
if [ "$HTTP_CODE" == "422" ] || [ "$HTTP_CODE" == "400" ]; then
    test_result "Auth login endpoint accessible" "PASS"
else
    test_result "Auth login endpoint accessible (got $HTTP_CODE)" "FAIL"
fi
echo ""

echo "[4/6] Testing notification endpoint (should require API key)..."
# Should get 401 without API key
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$SERVICE_URL/api/notify?message=test&type=task&priority=low")
if [ "$HTTP_CODE" == "401" ]; then
    test_result "Notification endpoint requires auth" "PASS"
else
    test_result "Notification endpoint requires auth (got $HTTP_CODE)" "FAIL"
fi
echo ""

echo "[5/6] Checking Cloud Run logs for errors..."
RECENT_ERRORS=$(gcloud run services logs read $SERVICE_NAME \
    --region=$REGION \
    --project=$PROJECT_ID \
    --limit=50 \
    --format="value(textPayload)" \
    2>/dev/null | grep -i "error\|exception\|fatal" | wc -l)

if [ "$RECENT_ERRORS" -eq 0 ]; then
    test_result "No errors in recent logs" "PASS"
else
    test_result "Found $RECENT_ERRORS errors in logs" "FAIL"
    echo "   Run this to view errors:"
    echo "   gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --limit=50 | grep -i error"
fi
echo ""

echo "[6/6] Checking service configuration..."
SERVICE_INFO=$(gcloud run services describe $SERVICE_NAME --region=$REGION --project=$PROJECT_ID --format=json 2>/dev/null)

# Check port configuration
PORT=$(echo "$SERVICE_INFO" | grep -o '"containerPort":[0-9]*' | head -1 | cut -d':' -f2)
if [ ! -z "$PORT" ]; then
    test_result "Port configured ($PORT)" "PASS"
else
    test_result "Port configuration" "FAIL"
fi

# Check memory
MEMORY=$(echo "$SERVICE_INFO" | grep -o '"memory":"[^"]*"' | head -1 | cut -d'"' -f4)
if [ ! -z "$MEMORY" ]; then
    test_result "Memory configured ($MEMORY)" "PASS"
else
    test_result "Memory configuration" "FAIL"
fi

# Check secret mount
SECRET_MOUNT=$(echo "$SERVICE_INFO" | grep -o "notification-api-key" | head -1)
if [ ! -z "$SECRET_MOUNT" ]; then
    test_result "Secret mounted" "PASS"
else
    test_result "Secret mount" "FAIL"
fi

echo ""
echo "================================================================"
echo "  Validation Results"
echo "================================================================"
echo ""
printf "%-30s: %d\n" "Tests Passed" "$TESTS_PASSED"
printf "%-30s: %d\n" "Tests Failed" "$TESTS_FAILED"
echo ""

if [ "$TESTS_FAILED" -eq 0 ]; then
    echo "✅ All validation tests passed!"
    echo ""
    echo "Service is ready for use:"
    echo "  Service URL: $SERVICE_URL"
    echo ""
    echo "Next steps:"
    echo "  1. Update ~/.notifications/config with this URL"
    echo "  2. Test notifications: notify-claude-async \"Test from local to Cloud Run\""
    echo "  3. Open Fresh Queue UI: $SERVICE_URL/queue-fresh.html"
else
    echo "⚠️  Some validation tests failed"
    echo ""
    echo "Debugging:"
    echo "  1. View logs: gcloud run services logs read $SERVICE_NAME --region=$REGION --limit=100"
    echo "  2. Check service: gcloud run services describe $SERVICE_NAME --region=$REGION"
    echo "  3. Test locally: docker run -p 8080:8080 gcr.io/$PROJECT_ID/lupin:latest"
fi
echo ""

exit $TESTS_FAILED
