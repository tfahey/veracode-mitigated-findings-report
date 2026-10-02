#!/usr/bin/env python3
"""
Fetch mitigated findings closed during a time period and merge with annotation comments.

This script:
1. Calls Reporting API to retrieve mitigated findings closed in the specified time range
2. Calls Annotations API to pull comments and metadata for those findings
3. Merges annotation data with finding results
4. Outputs to Excel and JSON formats
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

BASE_URL = "https://api.veracode.com"
REPORT_POST_URL = f"{BASE_URL}/appsec/v1/analytics/report"
REPORT_GET_URL_T = f"{BASE_URL}/appsec/v1/analytics/report/{{rid}}?page={{page}}&size={{size}}"
REPORT_GET_META_T = f"{BASE_URL}/appsec/v1/analytics/report/{{rid}}"
ANNOTATIONS_URL_T = f"{BASE_URL}/appsec/v2/findings/{{finding_id}}/annotations"

warnings.simplefilter("ignore", UserWarning)

# Error handling
def die(msg: str, code: int = 2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)

def check_env():
    if not os.getenv("VERACODE_API_KEY_ID") or not os.getenv("VERACODE_API_KEY_SECRET"):
        die("Set VERACODE_API_KEY_ID and VERACODE_API_KEY_SECRET for HTTPie HMAC plugin.")
    if os.getenv("VERACODE_API_ID") or os.getenv("VERACODE_API_KEY"):
        print("WARN: Legacy VERACODE_API_ID/VERACODE_API_KEY are set; HTTPie uses *_KEY_ID/*_KEY_SECRET.",
              file=sys.stderr)

# HTTPie wrapper
def call_httpie(method: str, url: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cmd = ["http", "--body", "-A", "veracode_hmac", method, url]
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(body) if body is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        die("http(ie) is not installed. Install with `pip install httpie`.")
        return {}

    if proc.returncode != 0:
        if "Unauthorized" in proc.stderr or "401" in proc.stderr:
            die(f"HTTPie 401 Unauthorized. Verify VERACODE_API_KEY_ID/VERACODE_API_KEY_SECRET and tenant access.\n{proc.stderr}")
        die(f"HTTPie error:\n{proc.stderr}", code=proc.returncode)
        return {}

    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        die(f"JSON parse error from {method} {url}: {e}\nRaw (first 4KB):\n{out[:4096]}")
        return {}

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

# Extract helpers for varied response formats
def extract_report_id(post_json: Dict[str, Any]) -> str:
    rid = post_json.get("id")
    if not rid and isinstance(post_json.get("_embedded"), dict):
        rid = post_json["_embedded"].get("id")
    rid = str(rid) if rid else ""
    if not rid:
        die(f"POST returned no report id:\n{json.dumps(post_json, indent=2)[:2000]}")
    return rid

def current_status(meta_json: Dict[str, Any]) -> str:
    status = meta_json.get("status")
    if not status and isinstance(meta_json.get("_embedded"), dict):
        status = meta_json["_embedded"].get("status")
    return str(status or "")

def is_completed(meta_json: Dict[str, Any]) -> bool:
    if current_status(meta_json).upper() == "COMPLETED":
        return True
    drc = meta_json.get("date_report_completed")
    if not drc and isinstance(meta_json.get("_embedded"), dict):
        drc = meta_json["_embedded"].get("date_report_completed")
    return bool(drc)

def extract_items(page_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(page_json.get("content"), list):
        return page_json["content"]
    emb = page_json.get("_embedded")
    if isinstance(emb, dict):
        if isinstance(emb.get("items"), list):
            return emb["items"]
        if isinstance(emb.get("findings"), list):
            return emb["findings"]
    if isinstance(page_json.get("findings"), list):
        return page_json["findings"]
    if isinstance(page_json, list):
        return page_json
    return []

def hal_next(page_json: Dict[str, Any]) -> Optional[str]:
    links = page_json.get("_links")
    if isinstance(links, dict):
        nxt = links.get("next")
        if isinstance(nxt, dict):
            href = nxt.get("href")
            if isinstance(href, str) and href:
                return href if href.startswith("http") else (BASE_URL + href)
    return None

def _find_page_meta(payload: dict) -> dict:
    """Normalize pagination meta from multiple possible locations."""
    candidates = [
        payload.get("page"),
        payload.get("page_metadata"),
        (payload.get("_embedded") or {}).get("page"),
        (payload.get("_embedded") or {}).get("page_metadata"),
    ]
    for c in candidates:
        if not isinstance(c, dict):
            continue
        meta = {}
        if "number" in c:
            try: meta["number"] = int(c["number"])
            except Exception: pass
        if not meta.get("number") and "page_number" in c:
            try: meta["number"] = int(c["page_number"])
            except Exception: pass
        if "totalPages" in c:
            try: meta["total_pages"] = int(c["totalPages"])
            except Exception: pass
        if not meta.get("total_pages") and "total_pages" in c:
            try: meta["total_pages"] = int(c["total_pages"])
            except Exception: pass
        if "size" in c:
            try: meta["size"] = int(c["size"])
            except Exception: pass
        if "number" in meta and "total_pages" in meta:
            return meta
    return {}

def page_math_next(page_json: Dict[str, Any], rid: str, size: int, current_page: int) -> Optional[str]:
    meta = _find_page_meta(page_json)
    if not meta:
        return None
    num = meta.get("number", current_page)
    total_pages = meta.get("total_pages")
    if total_pages is None:
        return None
    if (num + 1) <= total_pages:
        return REPORT_GET_URL_T.format(rid=rid, page=(num + 1), size=size)
    return None

# Reporting API operations
def post_report(start_d: str, end_d: str, extra: Dict[str, Any]) -> str:
    """Create a findings report for the given time range."""
    body = {
        "report_type": "FINDINGS",
        "last_updated_start_date": f"{start_d} 00:00:00",
        "last_updated_end_date": f"{end_d} 23:59:59",
        "status": ["mitigated"],
    }
    body.update(extra or {})
    resp = call_httpie("POST", REPORT_POST_URL, body)
    return extract_report_id(resp)

def poll_ready(rid: str, max_wait_s: int = 600, interval_s: float = 2.0) -> None:
    """Poll report status until complete."""
    deadline = time.time() + max_wait_s
    last = ""
    while time.time() < deadline:
        meta = call_httpie("GET", REPORT_GET_META_T.format(rid=rid))
        st = (current_status(meta) or "UNKNOWN").upper()
        if st != last:
            print(f"  status: {st}")
            last = st
        if is_completed(meta):
            return
        time.sleep(interval_s)
    die(f"Report {rid} not ready within {max_wait_s}s")

def stream_report_items(rid: str, size: int) -> Iterable[Dict[str, Any]]:
    """Exhaustive pagination through report findings."""
    page_no = 0
    next_url = REPORT_GET_URL_T.format(rid=rid, page=page_no, size=size)

    while next_url:
        page = call_httpie("GET", next_url)
        items = extract_items(page)

        yield {"__PAGE_META__": {"page_no": page_no, "count": len(items)}}
        for it in items:
            yield it

        # Try HAL links first
        nxt = hal_next(page)
        if nxt:
            next_url = nxt
            page_no += 1
            continue

        # Try page metadata
        nxt = page_math_next(page, rid, size, current_page=page_no)
        if nxt:
            next_url = nxt
            page_no += 1
            continue

        # Length-based fallback
        if len(items) == size:
            page_no += 1
            next_url = REPORT_GET_URL_T.format(rid=rid, page=page_no, size=size)
            continue

        next_url = None

# Annotations API operations
def get_annotations(finding_id: str) -> List[Dict[str, Any]]:
    """Fetch annotations (comments) for a specific finding."""
    url = ANNOTATIONS_URL_T.format(finding_id=finding_id)
    resp = call_httpie("GET", url)

    annotations = []
    if isinstance(resp.get("_embedded"), dict):
        annotations = resp["_embedded"].get("annotations", [])
    elif isinstance(resp.get("annotations"), list):
        annotations = resp["annotations"]

    return annotations

def merge_annotations(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch and merge annotations into a finding."""
    finding_id = finding.get("finding_id")
    if finding_id is None or finding_id == "":
        finding["annotations"] = []
        finding["annotation_count"] = 0
        finding["last_comment"] = ""
        return finding

    try:
        annotations = get_annotations(finding_id)
        finding["annotations"] = annotations
        finding["annotation_count"] = len(annotations)

        if annotations:
            # Get most recent comment, falling back to first if no timestamps
            sorted_annot = sorted(annotations, key=lambda a: a.get("created_date") or "", reverse=True)
            finding["last_comment"] = sorted_annot[0].get("comment", "") if sorted_annot else ""
        else:
            finding["last_comment"] = ""
    except Exception as e:
        print(f"WARN: Failed to fetch annotations for finding {finding_id}: {e}", file=sys.stderr)
        finding["annotations"] = []
        finding["annotation_count"] = 0
        finding["last_comment"] = ""

    return finding

# Type coercion for Excel
ISO_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?$")
ISO_D_RE  = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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
            try: return int(s)
            except Exception: return s
        if looks_float(s):
            try: return float(s)
            except Exception: return s
        if ISO_DT_RE.match(s):
            try: return pd.to_datetime(s, utc=False)
            except Exception: return s
        if ISO_D_RE.match(s):
            try: return pd.to_datetime(s, utc=False)
            except Exception: return s
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
    json_path  = out_dir / "mitigated_findings.json"
    xlsx_path  = out_dir / "mitigated_findings.xlsx"

    # JSONL (items only)
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for obj in all_items:
            if "__PAGE_META__" in obj:
                continue
            jf.write(json.dumps(obj, ensure_ascii=False) + "\n")

    # JSON array
    arr = [o for o in all_items if "__PAGE_META__" not in o]
    json_path.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

    # XLSX
    if arr:
        rows = [flatten(o) for o in arr]
        df = pd.DataFrame(rows)

        # Column-wise type coercion heuristic
        for col in df.columns:
            s = df[col]
            if s.dtype == "O":
                sample = s.dropna().astype(str).head(500)
                iso_dt_hits = sample.str.match(ISO_DT_RE.pattern).mean() if len(sample) else 0.0
                iso_d_hits  = sample.str.match(ISO_D_RE .pattern).mean() if len(sample) else 0.0
                if iso_dt_hits >= 0.7 or iso_d_hits >= 0.7:
                    df[col] = pd.to_datetime(s, errors="coerce", utc=False)
                    continue
                num = pd.to_numeric(s, errors="coerce")
                if num.notna().sum() >= max(3, int(0.7 * len(s))):
                    df[col] = num

        with pd.ExcelWriter(
            xlsx_path, engine="xlsxwriter",
            datetime_format="yyyy-mm-dd hh:mm:ss", date_format="yyyy-mm-dd"
        ) as writer:
            chunk_size = 1000000
            num_chunks = (len(df) + chunk_size - 1) // chunk_size

            for i in range(num_chunks):
                start_row = i * chunk_size
                end_row = min((i + 1) * chunk_size, len(df))

                print(f"    Writing Excel chunk {i+1}: rows {start_row}-{end_row}")
                chunk_df = df.iloc[start_row:end_row]
                chunk_df.to_excel(writer, sheet_name=f'findings_{i+1}', index=False)

                ws = writer.sheets[f'findings_{i+1}']
                for j, col in enumerate(df.columns):
                    col_max = df[col].astype(str).map(len).max() or 0
                    max_len = min(80, max(len(str(col)), int(col_max)))
                    ws.set_column(j, j, max(10, max_len + 2))
    else:
        with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
            pd.DataFrame().to_excel(writer, index=False, sheet_name="findings")

    return jsonl_path, json_path, xlsx_path

# Main entry point
def main():
    check_env()

    ap = argparse.ArgumentParser(
        description="Fetch mitigated findings closed in a time range and merge with annotations."
    )
    ap.add_argument("--from", dest="date_from", required=True, help="Start date (YYYY-MM-DD)")
    ap.add_argument("--to", dest="date_to", required=True, help="End date (YYYY-MM-DD)")
    ap.add_argument("--size", type=int, default=1000, help="Page size for findings pagination")
    ap.add_argument("--out", default="./out", help="Output directory")
    ap.add_argument("--skip-annotations", action="store_true",
                    help="Skip fetching annotations (faster but less data)")
    ap.add_argument("--sleep", type=float, default=0.5, help="Pause after POST before polling")
    ap.add_argument("--poll-timeout", type=int, default=600, help="Seconds to wait for report completion")
    ap.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval in seconds")
    args = ap.parse_args()

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
        rid = post_report(w_start, w_end, {})
        print(f"  report id: {rid}")

        if args.sleep > 0:
            time.sleep(args.sleep)

        poll_ready(rid, max_wait_s=args.poll_timeout, interval_s=args.poll_interval)

        window_total = 0
        for obj in stream_report_items(rid, args.size):
            if "__PAGE_META__" in obj:
                meta = obj["__PAGE_META__"]
                print(f"    page {meta['page_no']}: {meta['count']} items  (window_total={window_total}, grand_total={grand_total})")
                continue

            # Merge annotations if not skipped
            if not args.skip_annotations:
                obj = merge_annotations(obj)

            stamped = dict(obj)
            stamped["source_report_id"] = rid
            stamped["window_start"] = w_start
            stamped["window_end"] = w_end

            all_items.append(stamped)
            window_total += 1
            grand_total += 1

        print(f"  window complete: {window_total} items")

    jsonl_path, json_path, xlsx_path = write_outputs(all_items, out_dir)
    print("\n=== Outputs ===")
    print(f"  JSONL : {jsonl_path}")
    print(f"  JSON  : {json_path}")
    print(f"  XLSX  : {xlsx_path}")
    print(f"Grand total: {grand_total} items")

if __name__ == "__main__":
    main()
