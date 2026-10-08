# Veracode Mitigated Findings Report

Fetch mitigated findings closed during a specified time period from the Veracode Reporting API, merge with annotation comments from the Annotations API, and generate Excel/JSON reports.

## Features

- **Reporting API Integration**: Fetches mitigated findings filtered by `last_updated` date range
- **Annotations API Integration**: Automatically pulls comments and metadata for each finding
- **Automatic Windowing**: Handles 180-day windows automatically (API limitation)
- **Multiple Output Formats**: JSON, JSONL, and Excel outputs
- **Robust Pagination**: Handles HAL links, page metadata, and length-based fallbacks
- **Type Coercion**: Intelligently converts strings to dates, numbers, booleans in Excel
- **Python API Library**: Uses `veracode_api_py` for cleaner authentication and error handling

## Prerequisites

- Python 3.7+
- Veracode API credentials in one of:
  - Environment variables: `VERACODE_API_KEY_ID` and `VERACODE_API_KEY_SECRET`
  - Credentials file: `~/.veracode/credentials`
  - Command-line arguments: `--api-key-id` and `--api-key-secret`

## Setup

```bash
git clone <repo>
cd veracode-mitigated-findings-report
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Credential Setup

Choose one method:

**Option 1: Environment Variables (Recommended for CI/CD)**
```bash
export VERACODE_API_KEY_ID="your_key_id"
export VERACODE_API_KEY_SECRET="your_key_secret"
python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31
```

**Option 2: Credentials File (Recommended for Local Development)**
```bash
# Create ~/.veracode/credentials (first time only)
# Then run without environment variables:
python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31
```

**Option 3: Command-Line Arguments**
```bash
python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31 \
  --api-key-id your_key_id \
  --api-key-secret your_key_secret
```

## Usage

### Recommended: HTTPie Version

```bash
# Basic usage: fetch mitigated findings from Jan 1 to Jun 30, 2024
./fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30

# Skip annotations (faster if only need findings)
./fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30 --skip-annotations

# Custom output directory
./fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30 --out ~/reports

# Larger page size (trades memory for fewer API calls)
./fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30 --size 2000

# Longer timeout for large date ranges
./fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30 --poll-timeout 1200
```

### Alternative: veracode_api_py Version

⚠️ **Note:** Currently only retrieves the first page of results. Use HTTPie version for complete data.

```bash
./fetch_mitigated_findings.py --from 2024-01-01 --to 2024-06-30 [--api-key-id KEY --api-key-secret SECRET]
```

### Arguments (Both Versions)

- `--from` (required): Start date in YYYY-MM-DD format
- `--to` (required): End date in YYYY-MM-DD format
- `--out`: Output directory (default: `./out`)
- `--size`: Page size for findings pagination (default: 1000)
- `--skip-annotations`: Skip fetching annotations (faster)
- `--poll-timeout`: Max seconds to wait for report completion (default: 600)
- `--poll-interval`: Seconds between status polls (default: 2.0)
- `--sleep`: Pause before polling report (default: 0.5) — HTTPie version only

**HTTPie-specific:**
- `--api-key-id`: Veracode API Key ID (uses env var or credentials file if not provided)
- `--api-key-secret`: Veracode API Key Secret (uses env var or credentials file if not provided)

## Output Files

In the output directory:

- `mitigated_findings.xlsx` - Excel workbook with findings and annotations
- `mitigated_findings.json` - Complete JSON array
- `mitigated_findings.jsonl` - Newline-delimited JSON (one finding per line)

## Data Included

Each finding row contains:

- **Finding Fields**: id, app_name, cwe_id, severity, issue_type, etc.
- **Mitigation Fields**: mitigation_status, mitigation_date, resolved_date, etc.
- **Annotation Fields**: annotations (JSON array), annotation_count, last_comment
- **Report Metadata**: source_report_id, window_start, window_end

## Notes

- The script filters for `status: ["mitigated"]` by default
- Annotations are fetched sequentially (can be slow for large finding sets)
- Consider `--skip-annotations` if only interested in finding metadata
- Date range is automatically split into 180-day windows per Veracode API limits
- Flattened JSON fields (nested objects) are serialized as JSON strings in Excel

## Implementation

### ⭐ Recommended: HTTPie Version (Production Ready)

**`fetch_mitigated_findings_httpie.py`** — HTTPie-based implementation

This is the **recommended production implementation** because:
- ✅ **Complete Results**: Retrieves ALL findings across all pages
- ✅ **Proven Pagination**: Robust pagination handling for large result sets
- ✅ **Well-Tested**: Real API integration tested with production Veracode credentials
- ✅ **Simple Setup**: Requires only HTTPie installation

```bash
export VERACODE_API_KEY_ID="your_key_id"
export VERACODE_API_KEY_SECRET="your_key_secret"
python3 fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-06-30
```

### Alternative: veracode_api_py Version

**`fetch_mitigated_findings.py`** — Pure Python library implementation

This version uses the `veracode_api_py` library for:
- Clean Python API client interface
- Automatic HMAC authentication
- Flexible credential management
- Better error handling

**⚠️ Known Limitation**: Currently only retrieves the first page of results (pagination needs fixing)

Use this version once the pagination issue is resolved, or if you prefer pure-Python implementation without HTTPie.

```bash
# Will retrieve first page only (pagination fix needed)
python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-06-30
```
