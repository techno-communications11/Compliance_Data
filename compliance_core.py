r"""
=============================================================================
  TECHNO COMMUNICATIONS - COMPLIANCE DATA CORE  (web edition)
  -----------------------------------------------------------------
  A trimmed-down engine for the website. Does exactly two things:

     1. Pull the selected market sheets from Google (single market or ALL)
     2. Transpose them into ONE master CSV that the user can download

  This is a focused extract of the full Bulk Schedule Importer v4.1 —
  it deliberately drops the reports, Excel logs, anomaly detection and
  the interactive menu so the website stays fast and simple.

  Requires  credentials.json  in the SAME folder as this file.
=============================================================================
"""

import os
import re
import csv
import time
import threading
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import json
import gspread
from google.oauth2.service_account import Credentials


# ---- PATHS ------------------------------------------------------------------

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# Where we look for the Google service-account key, in order:
#   1. GOOGLE_CREDENTIALS_JSON env var  (paste the whole JSON — good for any host)
#   2. /etc/secrets/credentials.json    (Render "Secret File")
#   3. ./credentials.json               (local, next to this file)
_RENDER_SECRET_FILE = "/etc/secrets/credentials.json"

# All web-generated CSVs land here.
WEB_OUTPUT_DIR   = os.path.join(SCRIPT_DIR, "web_output")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


# ---- ALL MARKETS  (copied verbatim from the main importer) ------------------

ALL_SOURCE_SHEET_IDS = {
    "1Q3c4g9daK38vjDiyJVbdSSq-QI2xcj_pvU5Tm3reWO0": "Arizona",
    "1mS8s8JTvmNF_KqH9oA84TPS9IAzASCoGop9ucfDBvqQ": "Nashville",
    "1Nxh9CDC82bowvHvlIZzeEWn21rXeiXa90gPhdmt2uaY": "Denver",
    "1npCu5hMciAmlhrt2g-W7NPuY9VL8Z2QUO3xwH4f1fSQ": "Bay Area",
    "1AF7w-OyQCfKdTo1gQrcqbAl0jum5GDseRSmkoLEjIrY": "Memphis",
    "1hWnfffDdS94g7sR-68zAz06_OZXvZyH4EBdQimdLPKM": "Sacramento",
    "1Me551WSCNmgkdUJmyzhhj3hJHqMgjTybSiOkWe9XU_M": "San Diego",
    "1RlHBGRaX8hvysrbKZgYl0o7qMzWbI-UHjFS0Fc4I1Ec": "San Francisco",
    "1mJbmPp7k3kPJkMB2JYAe6LlFqhtMaljA1lxR46p1Njs": "Dallas",
    "1KLoiU24M3fRs9o3K0i9HGa06299pWX0GtnnQwKXnluk": "NC",
    "1JGFRvtzcBk4763VqEvJ-kle42hif992rrzw8ui6ZuQI": "El Paso",
    "1G78VBwjudt4jiurqMAZCeKag45PX-ASSKfhNXJuhyYQ": "North Bay Area",
    "1Ivuspo7CPhQRvAWBKgqHlv-PjrKg-jC1Qdw-KckqhrU": "East Bay Area",
    "1ODgdKafGbtPAXcP82jXRHsbmBM5GlP4MJsnB_iOOBXE": "Atlanta",
    "1d-XU7ykhzxdx8yU-GkjQeTsEJO45dikdy4pVcgfs68Y": "Portland",
    "1PmcE2vYU1ub4JxBJHklMx44nhtedsSpvSdjel58_re0": "Arkansas",
    "1RM_W40EjQg7K7ujVKOc5lCCCz0nzYMBzbZF17v3w7RU": "Kentucky",
    "1HnIoI8YN4uLwwkQEw5HY7aitlvmfSDsGJoXN_8Ul4YI": "Oklahoma",
    "1xWeJKXWeYVf9Ekq_Gj3oZi4flHi1dw7s9iQsybjeWWA": "Boston",
    "1dOdrnn6XaRBLu6WeK2hGpvqUA_0tZRn8bmt3R7unULo": "Charlotte",
    "1RbY9-cXhoMw-AS8Jl26bx-4pbilPf76i-aMINKlQWPE": "Miami",
    "1aJxTWlsIB3-oFp1-gSPvGY9WcDcAYieBWzZX3DcUfms": "Utah",
    "1oJ0kQLDUP92k-2MynLyLQYu8boIEEC9B5hSd5pGQYaY": "Philly",
    "1uKJakOLp80TAvEwfDO_sokL5raKv6bwMTgsnem2Pt-U": "Florida",
}

ALL_FOLDER_MARKETS = {
    "Houston": [
        "1nfNWfmOLuA7-I6ENF8p800vqd26M_Z7-",
    ],
    "Los Angeles": [
        "13oKNFiFtqxDl_OW8xVHiI2926SE7xq3S",  # 2026
        "1V7eqK7p4MYwqAWVCqyXmTYT3cZUVfRs3",  # 2025
        "16CR8rwvp19TiFn_8mXIWiuVG1PhzzOfi",  # 2024
    ],
}

HOUSTON_EXTRA_SHEET_IDS = [
    "1-3JettT94P5kOzZe3gKbyEKMwwopGapbhRpfguIJuRI",
]

MEMPHIS_EXTRA_SHEET_IDS = [
    "1YghqBwYSy7xvDgDn6_dxcyhRzx_Qi3Zn0xvmUP_BvNI",
]

ALL_MARKET_NAMES = sorted(
    list(ALL_SOURCE_SHEET_IDS.values()) + list(ALL_FOLDER_MARKETS.keys())
)


# ---- NORMALISER + DATE PARSING  (copied verbatim) ---------------------------

def normalize_cell(val):
    return (
        str(val)
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
        .strip()
    )


MONTH_MAP = {
    "january": 1,  "jan": 1,
    "february": 2, "feb": 2,
    "march": 3,    "mar": 3,
    "april": 4,    "apr": 4,
    "may": 5,
    "june": 6,     "jun": 6,
    "july": 7,     "jul": 7,
    "august": 8,   "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_date_str(s):
    s = s.strip()
    parts = s.split("/")
    if len(parts) < 3:
        return None
    try:
        m, d, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        return date(y, m, d)
    except Exception:
        return None


def derive_market_from_source(source_label):
    if not source_label:
        return ""
    first = source_label.split(" - ", 1)[0].strip()
    first = re.sub(r"\s*\([^)]*\)\s*", " ", first).strip()
    return first


def parse_name_date_range(name):
    # Pattern 1 - numeric
    m = re.search(
        r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*[-]\s*(\d{1,2}/\d{1,2}(?:/\d{2,4})?)",
        name
    )
    if m:
        s_str, e_str = m.group(1), m.group(2)
        s_date = parse_date_str(s_str) if len(s_str.split("/")) == 3 else None
        e_date = parse_date_str(e_str) if len(e_str.split("/")) == 3 else None

        if not e_date and s_date:
            gy = s_date.year
            em = int(e_str.split("/")[0])
            if s_date.month == 12 and em == 1:
                gy += 1
            try:
                p = e_str.split("/")
                e_date = date(gy, int(p[0]), int(p[1]))
            except Exception:
                pass

        if not s_date and e_date:
            gy = e_date.year
            sm = int(s_str.split("/")[0])
            if e_date.month == 1 and sm == 12:
                gy -= 1
            try:
                p = s_str.split("/")
                s_date = date(gy, int(p[0]), int(p[1]))
            except Exception:
                pass

        if s_date and e_date:
            if e_date < s_date:
                e_date = date(e_date.year + 1, e_date.month, e_date.day)
            return s_date, e_date

    # Pattern 2 - end date has NO month
    m = re.search(
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)\s+to\s+"
        r"(\d{1,2})(?:st|nd|rd|th)[,\s]+(\d{4})",
        name, re.IGNORECASE
    )
    if m:
        sm_ = MONTH_MAP.get(m.group(1).lower(), -1)
        sd  = int(m.group(2))
        ed  = int(m.group(3))
        yr  = int(m.group(4))
        if sm_ != -1:
            try:
                sy  = yr
                em_ = sm_
                ey  = yr
                if ed < sd:
                    em_ = sm_ + 1 if sm_ < 12 else 1
                    if sm_ == 12:
                        ey += 1
                return date(sy, sm_, sd), date(ey, em_, ed)
            except Exception:
                pass

    # Pattern 3 - year on BOTH dates
    m = re.search(
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)[,\s]+(\d{4})\s+to\s+"
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)[,\s]+(\d{4})",
        name, re.IGNORECASE
    )
    if m:
        sm_ = MONTH_MAP.get(m.group(1).lower(), -1)
        sd  = int(m.group(2))
        sy  = int(m.group(3))
        em_ = MONTH_MAP.get(m.group(4).lower(), -1)
        ed  = int(m.group(5))
        ey  = int(m.group(6))
        if sm_ != -1 and em_ != -1:
            try:
                return date(sy, sm_, sd), date(ey, em_, ed)
            except Exception:
                pass

    # Pattern 4 - year only at END
    m = re.search(
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)\s+to\s+"
        r"(\w+)\s+(\d{1,2})(?:st|nd|rd|th)[,\s]+(\d{4})",
        name, re.IGNORECASE
    )
    if m:
        sm_ = MONTH_MAP.get(m.group(1).lower(), -1)
        sd  = int(m.group(2))
        em_ = MONTH_MAP.get(m.group(3).lower(), -1)
        ed  = int(m.group(4))
        yr  = int(m.group(5))
        if sm_ != -1 and em_ != -1:
            sy, ey = yr, yr
            if sm_ == 12 and em_ == 1:
                ey = yr + 1
            elif em_ < sm_:
                ey = yr + 1
            try:
                return date(sy, sm_, sd), date(ey, em_, ed)
            except Exception:
                pass

    return None


_CELL_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"),
    re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|"
        r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?[,\s]+(\d{4})\b",
        re.IGNORECASE
    ),
    re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(january|february|march|april|may|june|july|august|september|"
        r"october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"\s+(\d{4})\b",
        re.IGNORECASE
    ),
]


def _try_parse_cell_date(cell_str):
    s = cell_str.strip()
    if not s:
        return None

    for pat in _CELL_DATE_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        groups = m.groups()

        if re.match(r"\d", groups[0]):
            try:
                mo, dy, yr = int(groups[0]), int(groups[1]), int(groups[2])
                if yr < 100:
                    yr += 2000
                return date(yr, mo, dy)
            except Exception:
                continue

        month_name = groups[0].lower()
        mo = MONTH_MAP.get(month_name, -1)
        if mo == -1:
            mo = MONTH_MAP.get(groups[1].lower(), -1)
            if mo == -1:
                continue
            try:
                dy = int(groups[0])
                yr = int(groups[2])
                return date(yr, mo, dy)
            except Exception:
                continue

        try:
            dy = int(groups[1])
            yr = int(groups[2])
            return date(yr, mo, dy)
        except Exception:
            continue

    try:
        serial = int(float(s))
        if 40000 < serial < 60000:
            base = date(1899, 12, 30)
            return base + timedelta(days=serial)
    except Exception:
        pass

    return None


def extract_dates_from_sheet_row2(data):
    if len(data) < 2:
        return None
    date_row = data[1]
    found = []
    for cell in date_row[2:]:
        d = _try_parse_cell_date(str(cell))
        if d:
            found.append(d)
    if not found:
        return None
    return min(found), max(found)


# ---- GOOGLE API HELPERS -----------------------------------------------------

def _load_credentials():
    """Load the Google service-account credentials from env var, Render
    secret file, or a local credentials.json — whichever is available."""
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    for path in (_RENDER_SECRET_FILE, CREDENTIALS_FILE):
        if os.path.exists(path):
            return Credentials.from_service_account_file(path, scopes=SCOPES)

    raise FileNotFoundError(
        "No Google credentials found. Either set the GOOGLE_CREDENTIALS_JSON "
        "environment variable, add a Render Secret File named credentials.json, "
        "or place credentials.json next to compliance_core.py (local use)."
    )


def credentials_available():
    if os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip():
        return True
    return any(os.path.exists(p) for p in (_RENDER_SECRET_FILE, CREDENTIALS_FILE))


def get_gc():
    return gspread.authorize(_load_credentials())


def get_drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_load_credentials())


def get_sheets_in_folder(drive_service, folder_id):
    results, page_token = [], None
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/vnd.google-apps.spreadsheet' "
        "and trashed=false"
    )
    while True:
        resp = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name)",
            pageToken=page_token
        ).execute()
        results.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return results


def with_retry(fn, max_retries=8):
    delay = 5
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            err = str(e)
            is_quota = "429" in err or "Quota exceeded" in err
            is_conn  = (
                "ConnectionResetError" in err
                or "Connection aborted" in err
                or "RemoteDisconnected" in err
            )
            if (is_quota or is_conn) and attempt < max_retries - 1:
                wait = delay if is_quota else 10
                time.sleep(wait)
                if is_quota:
                    delay = min(delay * 2, 300)
            else:
                raise


# ---- IMPORT (in memory — no per-sheet CSVs, no logging) ---------------------

SKIP_SHEET_NAMES_SET = {"import log", "sheet1", "transposed"}
SKIP_ROW_LABELS      = {"name", "clockin", "clockout", "store name",
                        "comments", "storename"}


def _import_single_spreadsheet(gc, spreadsheet_id, market_name, range_start,
                               range_end, use_content_dates=False,
                               spreadsheet_display_name=None):
    imported     = []
    display_name = spreadsheet_display_name or market_name

    wb         = with_retry(lambda: gc.open_by_key(spreadsheet_id))
    worksheets = with_retry(lambda: wb.worksheets())

    for ws in worksheets:
        sheet_name = ws.title
        if sheet_name.lower() in SKIP_SHEET_NAMES_SET:
            continue

        if use_content_dates:
            try:
                data = with_retry(lambda w=ws: w.get_all_values())
            except Exception:
                continue

            content_range = extract_dates_from_sheet_row2(data)
            if content_range:
                s, e = content_range
                in_range = s <= range_end and e >= range_start
            else:
                parsed = parse_name_date_range(sheet_name)
                if parsed:
                    s, e = parsed
                    in_range = s <= range_end and e >= range_start
                else:
                    in_range = False
        else:
            parsed = parse_name_date_range(sheet_name)
            if not parsed:
                continue
            s, e = parsed
            in_range = s <= range_end and e >= range_start
            if not in_range:
                continue
            try:
                data = with_retry(lambda w=ws: w.get_all_values())
            except Exception:
                continue

        if not in_range:
            continue

        data = [[normalize_cell(cell) for cell in row] for row in data]
        imported.append({
            "market":       market_name,
            "display_name": display_name,
            "sheet":        sheet_name,
            "data":         data,
        })
        time.sleep(0.4)

    return imported


def import_from_spreadsheet(gc, spreadsheet_id, market_name, range_start,
                            range_end, results_list, use_content_dates=False,
                            spreadsheet_display_name=None):
    display_name = spreadsheet_display_name or market_name
    for attempt in (1, 2):
        try:
            imported = _import_single_spreadsheet(
                gc, spreadsheet_id, market_name, range_start, range_end,
                use_content_dates, spreadsheet_display_name
            )
            results_list.extend(imported)
            return
        except Exception:
            if attempt == 1:
                time.sleep(15)
            # else: give up silently for this one sheet


# ---- TRANSPOSE (build the master CSV) ---------------------------------------

def transpose_sheet_data(data, source_label, market=""):
    output_rows = []
    if len(data) < 2:
        return output_rows

    if not market:
        market = derive_market_from_source(source_label)

    header_row  = data[0]
    date_row    = data[1]
    day_columns = []

    for ci in range(2, len(header_row)):
        dv = normalize_cell(header_row[ci])
        dt = normalize_cell(date_row[ci]) if ci < len(date_row) else ""
        if dv:
            day_columns.append({"day": dv, "date": dt, "col": ci})

    if not day_columns:
        return output_rows

    i = 2
    while i < len(data):
        emp_row  = data[i]
        name_val = normalize_cell(emp_row[0]) if emp_row else ""
        ntid_val = normalize_cell(emp_row[1]) if len(emp_row) > 1 else ""

        if not name_val or name_val.lower() in SKIP_ROW_LABELS:
            i += 1
            continue

        def safe_row(off):
            idx = i + off
            return data[idx] if idx < len(data) else []

        ci_row = safe_row(1)
        co_row = safe_row(2)
        st_row = safe_row(3)
        cm_row = safe_row(4)

        for col_info in day_columns:
            c = col_info["col"]

            def cell(row, col=c):
                return normalize_cell(row[col]) if col < len(row) else ""

            output_rows.append([
                ntid_val, name_val,
                col_info["day"], col_info["date"],
                cell(emp_row), cell(ci_row), cell(co_row),
                cell(st_row),  cell(cm_row), source_label,
            ])

        i += 5

    return output_rows


def transpose_all_results(all_results, output_path):
    header = ["NTID", "Name", "Day", "Date", "Schedule",
              "ClockIn", "ClockOut", "Store Name", "Comments", "Source Sheet"]
    collected = []

    for item in all_results:
        if item["sheet"].lower() in SKIP_SHEET_NAMES_SET:
            continue
        source_label = f"{item['display_name']} - {item['sheet']}"
        market       = item.get("market") or derive_market_from_source(source_label)
        rows         = transpose_sheet_data(item["data"], source_label, market)
        if rows:
            collected.extend(rows)

    # Sort oldest -> newest; unparseable/blank dates pushed to the end.
    def _date_key(r):
        d = _try_parse_cell_date(r[3]) if len(r) > 3 else None
        return (0, d) if d is not None else (1, date.max)

    collected.sort(key=_date_key)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for r in collected:
            writer.writerow(r[:10])

    return len(collected)


# ---- PUBLIC ENTRY POINT (called by the website) -----------------------------

def _safe(s):
    return re.sub(r'[\\/*?:"<>|]+', "_", str(s)).strip("_ ") or "market"


def generate_compliance_csv(selected_markets, range_start, range_end,
                            on_progress=None):
    """
    Pull the given markets between range_start / range_end and write a single
    master CSV. Returns dict: {csv_path, filename, sheets, rows, markets}.

    on_progress(pct:int, message:str) is called as work advances (optional).
    """
    def prog(pct, msg):
        if on_progress:
            try:
                on_progress(int(pct), msg)
            except Exception:
                pass

    if not credentials_available():
        raise FileNotFoundError(
            "No Google credentials found. Set GOOGLE_CREDENTIALS_JSON, add a "
            "Render Secret File named credentials.json, or place credentials.json "
            "next to compliance_core.py (local use)."
        )

    # Normalise selection
    if isinstance(selected_markets, str):
        selected_markets = [selected_markets]
    if any(str(m).strip().upper() == "ALL" for m in selected_markets):
        selected_markets = list(ALL_MARKET_NAMES)
    selected_markets = [m for m in selected_markets if m in ALL_MARKET_NAMES]
    if not selected_markets:
        raise ValueError("No valid market selected.")

    os.makedirs(WEB_OUTPUT_DIR, exist_ok=True)

    prog(4, "Authenticating with Google…")
    gc            = get_gc()
    drive_service = get_drive_service()

    source_ids     = {k: v for k, v in ALL_SOURCE_SHEET_IDS.items()
                      if v in selected_markets}
    folder_markets = {k: v for k, v in ALL_FOLDER_MARKETS.items()
                      if k in selected_markets}

    # ---- build the task list ----
    tasks = [
        {"spreadsheet_id": sid, "market_name": mname,
         "use_content_dates": False}
        for sid, mname in source_ids.items()
    ]

    if "Houston" in selected_markets:
        for extra_id in HOUSTON_EXTRA_SHEET_IDS:
            tasks.append({
                "spreadsheet_id":           extra_id,
                "market_name":              "Houston",
                "spreadsheet_display_name": f"Houston (extra) - {extra_id[:12]}",
                "use_content_dates":        False,
            })

    if "Memphis" in selected_markets:
        for extra_id in MEMPHIS_EXTRA_SHEET_IDS:
            tasks.append({
                "spreadsheet_id":           extra_id,
                "market_name":              "Memphis",
                "spreadsheet_display_name": f"Memphis (extra) - {extra_id[:12]}",
                "use_content_dates":        False,
            })

    prog(10, "Scanning market folders…")
    for market_name, folder_ids in folder_markets.items():
        if isinstance(folder_ids, str):
            folder_ids = [folder_ids]
        for folder_id in folder_ids:
            try:
                files = get_sheets_in_folder(drive_service, folder_id)
                for f in files:
                    parsed = parse_name_date_range(f["name"])
                    if parsed:
                        s, e = parsed
                        if not (s <= range_end and e >= range_start):
                            continue
                    tasks.append({
                        "spreadsheet_id":           f["id"],
                        "market_name":              market_name,
                        "spreadsheet_display_name": f"{market_name} - {f['name']}",
                        "use_content_dates":        True,
                    })
            except Exception:
                pass

    total_tasks = max(1, len(tasks))
    prog(16, f"Pulling sheets… (0 / {total_tasks})")

    all_results  = []
    results_lock = threading.Lock()
    done_counter = {"n": 0}

    def run_task(task):
        local = []
        import_from_spreadsheet(
            gc=gc,
            spreadsheet_id=task["spreadsheet_id"],
            market_name=task["market_name"],
            range_start=range_start,
            range_end=range_end,
            results_list=local,
            use_content_dates=task.get("use_content_dates", False),
            spreadsheet_display_name=task.get("spreadsheet_display_name"),
        )
        with results_lock:
            all_results.extend(local)
            done_counter["n"] += 1
            n = done_counter["n"]
        # 16% -> 88% across the pull phase
        pct = 16 + int(72 * n / total_tasks)
        prog(pct, f"Pulling sheets… ({n} / {total_tasks})")

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(run_task, t): t for t in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass

    if not all_results:
        raise RuntimeError(
            "No sheets matched. Check the date range and that the service "
            "account has access to the selected market(s)."
        )

    prog(92, "Building compliance CSV…")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(selected_markets) == len(ALL_MARKET_NAMES):
        label = "AllMarkets"
    elif len(selected_markets) == 1:
        label = _safe(selected_markets[0])
    else:
        label = f"{len(selected_markets)}markets"

    filename = (f"compliance_{label}_"
                f"{range_start.strftime('%Y-%m-%d')}_to_"
                f"{range_end.strftime('%Y-%m-%d')}_{stamp}.csv")
    csv_path = os.path.join(WEB_OUTPUT_DIR, filename)

    row_count = transpose_all_results(all_results, csv_path)

    prog(100, "Done")
    return {
        "csv_path": csv_path,
        "filename": filename,
        "sheets":   len(all_results),
        "rows":     row_count,
        "markets":  selected_markets,
    }
