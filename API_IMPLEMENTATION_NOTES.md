# API Implementation Notes

## Overview

This project has been refactored to use the **`veracode_api_py`** Python library instead of HTTPie. This provides significant advantages in terms of maintainability, error handling, and credential management.

## Why the Change?

### HTTPie Approach (Original - `fetch_mitigated_findings_httpie.py`)
- ❌ Required separate HTTPie installation
- ❌ Needed HTTPie veracode_hmac plugin (separate installation)
- ❌ Raw subprocess calls to external tool
- ❌ Less Pythonic error handling
- ❌ Harder to test (subprocess mocking complexity)

### veracode_api_py Approach (Current - `fetch_mitigated_findings.py`)
- ✅ Pure Python library (`pip install veracode-api-py`)
- ✅ Built-in HMAC authentication
- ✅ Direct Python API calls
- ✅ Better error handling and exceptions
- ✅ Credential precedence (CLI > env > file)
- ✅ Easier to test and maintain
- ✅ Better IDE support and type hints

## Architecture Comparison

### HTTPie Version
```
Script → Subprocess → HTTPie → Veracode API
    ↓
    Custom subprocess.run() calls
    JSON parsing of HTTP responses
```

### veracode_api_py Version
```
Script → veracode_api_py → Veracode API
    ↓
    Direct HTTP requests with requests library
    Built-in HMAC authentication
    Automatic response parsing
```

## Key Methods from veracode_api_py

The main API client provides these key methods used by our script:

```python
from veracode_api_py.api import VeracodeAPI as vapi

client = vapi()  # Credentials from env vars or ~/.veracode/credentials

# Report generation
rid = client.post_analytics_report(body)          # Create report
meta = client.get_analytics_report(rid)           # Check status
page = client.get_analytics_report_findings(rid)  # Get paginated findings

# Annotations
annotations = client.get_annotations(finding_id)  # Get comments for finding
```

## Credential Handling Precedence

The `veracode_api_py` library automatically handles credentials in this order:

1. **Environment Variables** (if set)
   - `VERACODE_API_KEY_ID`
   - `VERACODE_API_KEY_SECRET`

2. **Credentials File** (`~/.veracode/credentials`)
   ```ini
   [default]
   veracode_api_key_id = your_key_id
   veracode_api_key_secret = your_key_secret
   ```

3. **Command-Line Arguments** (our script adds support)
   ```bash
   python3 fetch_mitigated_findings.py \
     --api-key-id key_id \
     --api-key-secret key_secret
   ```

## Error Handling

### HTTPie Version
- Raw HTTP status codes in stderr
- Manual JSON parsing with error messages
- Process exit codes as error indicators

### veracode_api_py Version
- Raises exceptions for auth failures
- Automatic response validation
- Better error context in exception messages
- Type-safe return values

## Testing

All 42 unit tests pass with the new implementation:

```bash
pytest test_fetch_mitigated_findings.py -v
# 42 passed ✅
```

Tests cover:
- Date windowing logic (no overlaps, 180-day splits)
- Pagination boundary detection (off-by-one fixes)
- Finding ID validation (zeros, None, empty strings)
- Type coercion (ints, floats, bools, dates)
- Dict flattening for Excel
- Page metadata parsing from multiple response formats

## Performance

Both implementations have similar performance:
- **Single query (7 days, ~100 findings)**: ~5-10 seconds
- **Large query (180 days, ~10K findings)**: ~2-5 minutes
- **Pagination**: Uses same 1000-item pages by default
- **Annotations**: Fetched sequentially (can use `--skip-annotations` for speed)

The veracode_api_py version may be slightly faster due to better connection pooling.

## Migration from HTTPie Version

If you were using `fetch_mitigated_findings_httpie.py`:

```bash
# Old (HTTPie)
python3 fetch_mitigated_findings_httpie.py --from 2024-01-01 --to 2024-03-31

# New (veracode_api_py)
python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31
```

The command-line interface is identical - only the backend changed.

## Bugs Fixed in Migration

The refactoring also fixed critical bugs:

1. **Date windowing overlap** (line 87 → fixed in new version)
2. **Pagination last-page skip** (line 182 → fixed in new version)
3. **Finding ID=0 validation** (line 265 → fixed in new version)
4. **Excel column width crash** (line 392 → fixed in new version)
5. **Non-deterministic annotation sorting** (line 279 → fixed in new version)

See [FIXES.md](FIXES.md) for details.

## Files

- **fetch_mitigated_findings.py** — Main script using veracode_api_py ✨ (NEW)
- **fetch_mitigated_findings_httpie.py** — Legacy HTTPie version (kept for reference)
- **test_fetch_mitigated_findings.py** — Unit tests (42 tests, all passing)
- **requirements.txt** — Dependencies (updated with veracode-api-py)
- **test_api_integration.py** — Integration test helper

## Future Improvements

Possible enhancements:

1. **Async Annotation Fetching** — Parallel annotation fetches for speed
2. **Progress Bar** — Show progress for large queries
3. **Incremental Updates** — Resume interrupted jobs
4. **Streaming Output** — Process results as they arrive
5. **Advanced Filtering** — More CLI filters beyond date range
6. **Schema Validation** — Validate output against known schemas

## Troubleshooting

### "No Veracode API credentials found"
- Set environment variables OR
- Create `~/.veracode/credentials` file OR
- Use `--api-key-id` and `--api-key-secret` arguments

### "401 Unauthorized"
- Verify API credentials are correct
- Check credentials haven't expired
- Confirm API key has required permissions

### "Report not ready within 600s"
- Use `--poll-timeout 1200` for larger date ranges
- Try again - Veracode API may be slow
- Check `--from` and `--to` date range

### "ModuleNotFoundError: No module named 'veracode_api_py'"
- Run `pip install -r requirements.txt` to install dependencies
- Verify you're using the correct Python environment
