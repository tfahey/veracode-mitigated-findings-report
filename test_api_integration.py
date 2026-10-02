#!/usr/bin/env python3
"""
Integration test script for real Veracode API testing.

This script will:
1. Validate API credentials
2. Test connectivity to Veracode API
3. Run a small query with recent date range
4. Verify output file generation
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime, timedelta


def check_credentials():
    """Verify Veracode API credentials are set."""
    key_id = os.getenv("VERACODE_API_KEY_ID")
    key_secret = os.getenv("VERACODE_API_KEY_SECRET")

    if not key_id or not key_secret:
        print("❌ Missing credentials!")
        print("\nSet these environment variables:")
        print("  export VERACODE_API_KEY_ID='your_key_id_here'")
        print("  export VERACODE_API_KEY_SECRET='your_key_secret_here'")
        return False

    print("✅ Credentials found")
    print(f"   API Key ID: {key_id[:8]}...{key_id[-4:]}")
    return True


def check_httpie_plugin():
    """Check if HTTPie and veracode_hmac plugin are available."""
    result = subprocess.run(["http", "--plugins"], capture_output=True, text=True)

    if result.returncode != 0:
        print("❌ HTTPie not working")
        return False

    if "veracode_hmac" not in result.stdout:
        print("⚠️  veracode_hmac plugin NOT installed")
        print("\nTo install, run one of these:")
        print("  1. Manual install: https://github.com/veracode/veracode-api-hmac-auth")
        print("  2. Or try: pip install --user httpie-plugin-veracode")
        print("\nWithout the plugin, the script cannot authenticate with Veracode API.")
        return False

    print("✅ HTTPie and veracode_hmac plugin ready")
    return True


def test_connectivity():
    """Test basic connectivity to Veracode API."""
    print("\n🔍 Testing API connectivity...")

    result = subprocess.run(
        ["http", "--body", "-A", "veracode_hmac", "GET", "https://api.veracode.com/appsec/v1/applications/"],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    if result.returncode != 0:
        if "401" in result.stderr or "Unauthorized" in result.stderr:
            print("❌ Authentication failed (401 Unauthorized)")
            print("   Check your API credentials are correct")
            return False
        else:
            print(f"❌ API connectivity failed:\n{result.stderr[:500]}")
            return False

    try:
        data = json.loads(result.stdout)
        if "_embedded" in data or "applications" in data:
            print("✅ API connectivity successful")
            return True
    except json.JSONDecodeError:
        pass

    print("⚠️  Unexpected response format")
    print(f"Response: {result.stdout[:200]}")
    return False


def run_test_query():
    """Run a small test query with the script."""
    print("\n🚀 Running test query (last 7 days)...")

    # Get date range: last 7 days
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    out_dir = Path("./out_test")
    out_dir.mkdir(exist_ok=True)

    cmd = [
        "python3",
        "fetch_mitigated_findings.py",
        "--from", start_date.isoformat(),
        "--to", end_date.isoformat(),
        "--out", str(out_dir),
        "--poll-timeout", "300",
        "--size", "100",
        "--skip-annotations",  # Skip for faster test
    ]

    print(f"   Date range: {start_date} to {end_date}")
    print(f"   Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"❌ Script failed:\n{result.stderr}")
        print(f"\nStdout:\n{result.stdout}")
        return False

    print(result.stdout)

    # Check output files
    json_file = out_dir / "mitigated_findings.json"
    jsonl_file = out_dir / "mitigated_findings.jsonl"
    xlsx_file = out_dir / "mitigated_findings.xlsx"

    all_exist = json_file.exists() and jsonl_file.exists() and xlsx_file.exists()

    if all_exist:
        print(f"\n✅ Output files generated:")
        print(f"   JSON : {json_file.stat().st_size:,} bytes")
        print(f"   JSONL: {jsonl_file.stat().st_size:,} bytes")
        print(f"   XLSX : {xlsx_file.stat().st_size:,} bytes")

        # Try to read JSON to verify it's valid
        try:
            with json_file.open() as f:
                data = json.load(f)
            print(f"   Items: {len(data)} findings")
            if data:
                print(f"\n   First finding (sample):")
                first = data[0]
                for key in list(first.keys())[:5]:
                    print(f"     {key}: {str(first[key])[:60]}")
        except Exception as e:
            print(f"   ⚠️  Could not parse JSON: {e}")

        return True
    else:
        print(f"❌ Output files not created:")
        print(f"   JSON : {json_file.exists()}")
        print(f"   JSONL: {jsonl_file.exists()}")
        print(f"   XLSX : {xlsx_file.exists()}")
        return False


def main():
    print("=" * 60)
    print("Veracode Mitigated Findings Report - Integration Test")
    print("=" * 60)

    checks = [
        ("API Credentials", check_credentials),
        ("HTTPie + Plugin", check_httpie_plugin),
        ("API Connectivity", test_connectivity),
        ("Test Query", run_test_query),
    ]

    results = {}
    for name, check_func in checks:
        print(f"\n[{name}]")
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"❌ Exception: {e}")
            results[name] = False

        if not results[name] and name != "Test Query":
            print(f"\n⛔ Stopping: {name} check failed")
            break

    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")

    all_passed = all(results.values())
    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed. See above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
