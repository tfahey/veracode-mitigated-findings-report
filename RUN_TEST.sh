#!/bin/bash
# Run the integration test with your Veracode API credentials
#
# Usage:
#   export VERACODE_API_KEY_ID='your_key_id'
#   export VERACODE_API_KEY_SECRET='your_key_secret'
#   bash RUN_TEST.sh

set -e

echo "============================================================"
echo "Veracode Mitigated Findings Report - Integration Test"
echo "============================================================"
echo

# Check credentials
if [ -z "$VERACODE_API_KEY_ID" ] || [ -z "$VERACODE_API_KEY_SECRET" ]; then
    echo "❌ Missing credentials!"
    echo
    echo "Set these environment variables before running:"
    echo "  export VERACODE_API_KEY_ID='your_key_id'"
    echo "  export VERACODE_API_KEY_SECRET='your_key_secret'"
    exit 1
fi

echo "✅ API Credentials found"
echo "   Key ID: ${VERACODE_API_KEY_ID:0:8}...${VERACODE_API_KEY_ID: -4}"
echo

# Check HTTPie + plugin
echo "✅ Checking HTTPie + veracode_api_signing..."
python3 -c "import veracode_api_signing" && echo "   veracode_api_signing plugin: ✅ installed" || echo "   veracode_api_signing plugin: ❌ NOT installed"
echo

# Test API connectivity
echo "🔍 Testing API connectivity..."
RESPONSE=$(http -A veracode_hmac GET https://api.veracode.com/appsec/v1/applications/ 2>&1)

if echo "$RESPONSE" | grep -q "401\|Unauthorized"; then
    echo "❌ Authentication failed (401 Unauthorized)"
    echo "   Check your API credentials are correct"
    exit 1
elif echo "$RESPONSE" | grep -q "_embedded\|applications"; then
    echo "✅ API connectivity successful"
else
    echo "⚠️  Unexpected response:"
    echo "$RESPONSE" | head -20
fi
echo

# Run test query
echo "🚀 Running test query (last 7 days)..."

# Calculate dates
END_DATE=$(date +%Y-%m-%d)
START_DATE=$(date -v-7d +%Y-%m-%d)

echo "   Date range: $START_DATE to $END_DATE"
echo "   Command: python3 fetch_mitigated_findings.py --from $START_DATE --to $END_DATE --skip-annotations"
echo

python3 fetch_mitigated_findings.py --from "$START_DATE" --to "$END_DATE" --out ./out_test --skip-annotations --size 100 --poll-timeout 300

echo
echo "============================================================"
echo "✅ Integration test complete!"
echo "============================================================"
echo
echo "Output files created in ./out_test/:"
ls -lh ./out_test/ | tail -n +2
echo
echo "To include annotations (slower), re-run without --skip-annotations:"
echo "  python3 fetch_mitigated_findings.py --from $START_DATE --to $END_DATE --out ./out_test"
