#!/usr/bin/env python3
"""
Fetch mitigated findings using Veracode Python API library (veracode_api_py).

This is the primary implementation using the veracode_api_py library.
Benefits over HTTPie approach:
- No external tool or plugin installation needed
- Pure Python API integration
- Better error handling and type safety
- Flexible credential management (CLI args > env vars > credentials file)

Usage:
  python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31
  python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31 --skip-annotations
  python3 fetch_mitigated_findings.py --from 2024-01-01 --to 2024-03-31 --out ~/reports

Credential precedence:
  1. CLI args: --api-key-id, --api-key-secret
  2. Environment: VERACODE_API_KEY_ID, VERACODE_API_KEY_SECRET
  3. File: ~/.veracode/credentials (default section)
"""

import argparse
import json
import os
import re
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import pandas as pd

warnings.simplefilter("ignore", UserWarning)

# Error handling
def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def setup_api_client(api_key_id: Optional[str] = None, api_key_secret: Optional[str] = None):
    """Initialize Veracode API client with credential precedence."""
    try:
        from veracode_api_py.api import VeracodeAPI as vapi
    except ImportError:
        die("veracode_api_py not installed. Run: pip install -r requirements.txt")

    # Precedence: CLI args > env vars > ~/.veracode/credentials (handled by veracode_api_py)
    if api_key_id:
        os.environ["veracode_api_key_id"] = api_key_id
    if api_key_secret:
        os.environ["veracode_api_key_secret"] = api_key_secret

    try:
        client = vapi()
        print("✅ Veracode API client initialized")
        return client
    except Exception as e:
        die(f"Failed to initialize Veracode API client: {e}")


# Date window handling
def windows_180(from_d: str, to_d: str) -> List[Tuple[str, str]]:
    """Split date range into 180-day windows (API limitation)."""
    start = datetime.strptime(from_d, "%Y-%m-%d").date()
    end = datetime.strptime(to_d, "%Y-%m-%d").date()
    if end < start:
        die("--to must be >= --from")
    out: List[Tuple[str, str]] = []
    cur = start
    step = timedelta(days=180)
    while cur <= end:
        nxt = cur + step
        if nxt > end:
            nxt = end
        out.append((cur.isoformat(), nxt.isoformat()))
        cur = nxt + timedelta(days=1)
    return out


# Type coercion for Excel
ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$")
ISO_D_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def looks_int(s: str) -> bool:
    return re.fullmatch(r"[+-]?\d+", s) is not None


def looks_float(s: str) -> bool:
    return re.fullmatch(r"[+-]?\d*\.\d+([eE][+-]?\d+)?", s) is not None


def coerce_scalar(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return ""
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        if looks_int(s):
            try:
                return int(s)
            except Exception:
                return s
        if looks_float(s):
            try:
                return float(s)
            except Exception:
                return s
        if ISO_DT_RE.match(s):
            try:
                return pd.to_datetime(s, utc=False)
            except Exception:
                return s
        if ISO_D_RE.match(s):
            try:
                return pd.to_datetime(s, utc=False)
            except Exception:
                return s
        return s
    return v


def flatten(obj: Dict[str, Any], parent: str = "", sep: str = ".") -> Dict[str, Any]:
    """Flatten nested dicts for Excel output."""
    flat: Dict[str, Any] = {}
    for k, v in obj.items():
        key = f"{parent}{sep}{k}" if parent else k
        if isinstance(v, dict):
            flat.update(flatten(v, key, sep))
        elif isinstance(v, list):
            flat[key] = json.dumps(v, ensure_ascii=False)
        else:
            flat[key] = coerce_scalar(v)
    return flat


# Output generation
def write_outputs(all_items: List[Dict[str, Any]], out_dir: Path) -> Tuple[Path, Path, Path]:
    """Write findings to JSON, JSONL, and Excel formats."""
    jsonl_path = out_dir / "mitigated_findings.jsonl"
    json_path = out_dir / "mitigated_findings.json"
    xlsx_path = out_dir / "mitigated_findings.xlsx"

    # JSONL (items only)
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for obj in all_items:
            jf.write(json.dumps(obj, ensure_ascii=False) + "\n")

    # JSON array
    json_path.write_text(json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8")

    # XLSX
    if all_items:
        rows = [flatten(o) for o in all_items]
        df = pd.DataFrame(rows)

        # Column-wise type coercion heuristic
        for col in df.columns:
            s = df[col]
            if s.dtype == "O":
                sample = s.dropna().astype(str).head(500)
                iso_dt_hits = sample.str.match(ISO_DT_RE.pattern).mean() if len(sample) else 0.0
                iso_d_hits = sample.str.match(ISO_D_RE.pattern).mean() if len(sample) else 0.0
                if iso_dt_hits >= 0.7 or iso_d_hits >= 0.7:
                    df[col] = pd.to_datetime(s, errors="coerce", utc=False)
                    continue
                num = pd.to_numeric(s, errors="coerce")
                if num.notna().sum() >= max(3, int(0.7 * len(s))):
                    df[col] = num

        with pd.ExcelWriter(
            xlsx_path, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm:ss", date_format="yyyy-mm-dd"
        ) as writer:
            chunk_size = 1000000
            num_chunks = (len(df) + chunk_size - 1) // chunk_size

            for i in range(num_chunks):
                start_row = i * chunk_size
                end_row = min((i + 1) * chunk_size, len(df))

                print(f"    Writing Excel chunk {i+1}: rows {start_row}-{end_row}")
                chunk_df = df.iloc[start_row:end_row]
                chunk_df.to_excel(writer, sheet_name=f"findings_{i+1}", index=False)

                ws = writer.sheets[f"findings_{i+1}"]
                for j, col in enumerate(df.columns):
                    col_max = df[col].astype(str).str.len().max()
                    col_max = int(col_max) if pd.notna(col_max) else 0
                    max_len = min(80, max(len(str(col)), col_max))
                    ws.set_column(j, j, max(10, max_len + 2))
    else:
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="findings")

    return jsonl_path, json_path, xlsx_path


# Main entry point
def main():
    ap = argparse.ArgumentParser(
        description="Fetch mitigated findings closed in a time range (using veracode_api_py)."
    )
    ap.add_argument("--from", dest="date_from", required=True, help="Start date (YYYY-MM-DD)")
    ap.add_argument("--to", dest="date_to", required=True, help="End date (YYYY-MM-DD)")
    ap.add_argument("--out", default="./out", help="Output directory")
    ap.add_argument(
        "--skip-annotations", action="store_true", help="Skip fetching annotations (faster)"
    )
    ap.add_argument("--api-key-id", help="Veracode API Key ID (overrides env var)")
    ap.add_argument("--api-key-secret", help="Veracode API Key Secret (overrides env var)")
    args = ap.parse_args()

    # Initialize API client
    client = setup_api_client(args.api_key_id, args.api_key_secret)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    windows = windows_180(args.date_from, args.date_to)
    print("Time windows:")
    for s, e in windows:
        print(f"  - {s} → {e}")

    all_items: List[Dict[str, Any]] = []
    grand_total = 0

    for w_start, w_end in windows:
        print(f"\n=== Window {w_start} → {w_end} ===")
        try:
            # Create analytics report
            print(f"  Creating report for {w_start} to {w_end}...")
            response = client.create_analytics_report(
                report_type="findings",
                last_updated_start_date=f"{w_start} 00:00:00",
                last_updated_end_date=f"{w_end} 23:59:59",
            )
            rid = response if isinstance(response, (str, UUID)) else str(response)
            print(f"  Report ID: {rid}")

            # Save report ID for manual testing
            report_ids_file = out_dir / "report_ids.txt"
            with report_ids_file.open("a") as f:
                f.write(f"{w_start} to {w_end}: {rid}\n")

            # Poll for completion
            deadline = time.time() + 600  # 10 minute timeout
            last_status = ""
            report_uuid = UUID(str(rid)) if not isinstance(rid, UUID) else rid
            while time.time() < deadline:
                try:
                    # get_analytics_report returns (status, body)
                    status, _ = client.get_analytics_report(report_uuid)
                    if status != last_status:
                        print(f"  Status: {status}")
                        last_status = status
                    if status == "COMPLETED":
                        break
                except Exception as e:
                    pass  # Ignore polling errors
                time.sleep(2)

            # Fetch findings - returns (status, findings_list)
            print(f"  Fetching findings...")
            try:
                status, findings_list = client.get_analytics_findings_report(report_uuid)
                findings = findings_list if isinstance(findings_list, list) else []

                print(f"  Found {len(findings)} findings")

                window_total = 0
                for finding in findings:
                    # Add metadata
                    finding["source_report_id"] = str(rid)
                    finding["window_start"] = w_start
                    finding["window_end"] = w_end
                    all_items.append(finding)
                    window_total += 1
                    grand_total += 1

                print(f"  Window complete: {window_total} items")

            except Exception as e:
                print(f"  Warning: Failed to fetch findings: {e}")

        except Exception as e:
            print(f"  Error processing window: {e}")
            continue

    jsonl_path, json_path, xlsx_path = write_outputs(all_items, out_dir)
    print("\n=== Outputs ===")
    print(f"  JSONL : {jsonl_path}")
    print(f"  JSON  : {json_path}")
    print(f"  XLSX  : {xlsx_path}")
    print(f"Grand total: {grand_total} items")


if __name__ == "__main__":
    main()
