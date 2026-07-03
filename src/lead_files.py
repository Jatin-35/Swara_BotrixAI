"""
lead_files.py — Faber Excel lead-list management.

Model:
  • The ORIGINAL uploaded .xlsx is saved untouched on disk (pristine) under
    lead_files/, named with date + weekday + original name for history.
  • Its rows are imported into the DB (lead_file_rows) — this is the editable
    "working copy" that Voice BOT calls and manual edits mutate.
  • Download returns EITHER the pristine original OR a freshly-exported xlsx
    built from the current working copy.

Public API:
  save_and_import(file_bytes, original_name, uploaded_by=None) -> dict
  list_files() -> list[dict]
  get_file(file_id) -> dict | None
  get_rows(file_id) -> list[dict]
  update_row(row_id, fields) -> dict | None
  set_row_call(row_id, call_status, called_by=None, record_id=None) -> dict | None
  apply_call_result(record_id, **fields) -> int          # writeback by call_record_id
  export_updated_xlsx(file_id) -> (bytes, filename)      # working copy → xlsx
  original_path(file_id) -> (path, filename) | None      # pristine original
"""

import io
import os
import re
from datetime import datetime, timezone, timedelta

import openpyxl

from database import _execute, _fetchall, _fetchone

# ── Storage location ──────────────────────────────────────────────────────────
# Pristine uploads live in <repo-root>/lead_files/  (sibling of src/)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(_BASE_DIR, "lead_files")

IST = timezone(timedelta(hours=5, minutes=30))

# ── Excel header → DB column mapping ──────────────────────────────────────────
# Matching is done on a normalised header (lower-cased, collapsed whitespace),
# so minor header variations (trailing spaces, case) still map correctly.
_HEADER_MAP = {
    "product name":           "product_name",
    "mobile":                 "mobile",
    "dealer name":            "dealer_name",
    "service request number": "service_request_number",
    "asc name":               "asc_name",
    "installation status":    "installation_status",
    "remarks":                "remarks",
    "sentiment":              "sentiment",
    "transcript":             "transcript",
    "summary of call":        "call_summary",
    "customer name":          "customer_name",
}

# Order used when exporting the working copy back to xlsx
_EXPORT_COLUMNS = [
    ("Product Name",           "product_name"),
    ("Mobile",                 "mobile"),
    ("Customer Name",          "customer_name"),
    ("Dealer Name",            "dealer_name"),
    ("Service request number", "service_request_number"),
    ("ASC Name",               "asc_name"),
    ("Installation Status",    "installation_status"),
    ("Remarks",                "remarks"),
    ("Sentiment",              "sentiment"),
    ("Transcript",             "transcript"),
    ("Summary of call",        "call_summary"),
    ("Disposition",            "disposition"),
]

# Columns a user is allowed to edit inline (others are read-only / system-managed)
EDITABLE_FIELDS = {
    "product_name", "mobile", "customer_name", "dealer_name", "service_request_number",
    "asc_name", "installation_status", "remarks", "sentiment",
    "transcript", "call_summary", "disposition",
}

# Fields the post-call writeback is allowed to set (disposition handled separately
# via apply_disposition because it also appends into remarks).
WRITEBACK_FIELDS = {
    "installation_status", "sentiment", "transcript", "call_summary",
}

# Canonical call dispositions — set on a row after a call (own column + appended
# into remarks).
DISPOSITIONS = [
    "Installation Completed",
    "Waiting For Technician",
    "Refused For Service",
    "Site Not Ready",
    "Customer will call back",
    "Language Barrier",
    "Damaged/Defective Product Received",
    "Complaint After Service",
    "Wrong Number",
    "No Response",
    "Other",
]
# Dispositions an LLM may assign to a CONNECTED call (No Response is reserved for
# not-connected / no-conversation outcomes and is set without an LLM).
CONNECTED_DISPOSITIONS = [d for d in DISPOSITIONS if d != "No Response"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm_header(h) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower())


def _clean_cell(v):
    """Normalise a cell value to a clean string (or None)."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)              # 9258838611.0 → 9258838611
    s = str(v).strip()
    return s or None


def _stamp_name(original_name: str, dt: datetime) -> str:
    """2026-06-23_Tuesday_Calling-data-20-Jun.xlsx"""
    base = os.path.basename(original_name)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base)      # non-safe runs → single dash
    safe = re.sub(r"-{2,}", "-", safe).strip("-")       # collapse repeated dashes
    return f"{dt.strftime('%Y-%m-%d')}_{dt.strftime('%A')}_{safe}"


def _ensure_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


# ── parse ─────────────────────────────────────────────────────────────────────

def parse_xlsx(path: str) -> list[dict]:
    """Read the first sheet; map header row → DB columns; return list of row dicts."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]

    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return []

    # Build {col_index: db_column} from the header row
    col_to_field = {}
    for idx, h in enumerate(header):
        field = _HEADER_MAP.get(_norm_header(h))
        if field:
            col_to_field[idx] = field

    out = []
    for raw in rows_iter:
        if raw is None or all(c is None or str(c).strip() == "" for c in raw):
            continue  # skip blank rows
        rec = {field: None for field in _HEADER_MAP.values()}
        for idx, field in col_to_field.items():
            if idx < len(raw):
                rec[field] = _clean_cell(raw[idx])
        out.append(rec)
    return out


# ── save + import ─────────────────────────────────────────────────────────────

def save_and_import(file_bytes: bytes, original_name: str, uploaded_by: str = None) -> dict:
    """Persist the pristine xlsx, parse it, and import rows into the working copy."""
    _ensure_dir()
    now = datetime.now(IST)
    stored_name = _stamp_name(original_name, now)
    stored_path = os.path.join(UPLOAD_DIR, stored_name)

    # If a same-stamp file already exists (re-upload same day), suffix it
    if os.path.exists(stored_path):
        root, ext = os.path.splitext(stored_name)
        stored_name = f"{root}_{now.strftime('%H%M%S')}{ext}"
        stored_path = os.path.join(UPLOAD_DIR, stored_name)

    # 1. Write the PRISTINE original untouched
    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    # 2. Parse rows from the saved file
    rows = parse_xlsx(stored_path)

    # 3. Index the file
    file_rows = _execute(
        """
        INSERT INTO lead_files
            (original_name, stored_name, stored_path, day_of_week, row_count, uploaded_by, active)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE)
        RETURNING id
        """,
        (original_name, stored_name, stored_path, now.strftime("%A"), len(rows), uploaded_by),
    )
    file_id = file_rows[0]["id"]

    # 4. Import rows (working copy)
    for i, rec in enumerate(rows):
        _execute(
            """
            INSERT INTO lead_file_rows
                (file_id, row_index, product_name, mobile, customer_name, dealer_name,
                 service_request_number, asc_name, installation_status,
                 remarks, sentiment, transcript, call_summary, call_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
            """,
            (file_id, i, rec["product_name"], rec["mobile"], rec["customer_name"], rec["dealer_name"],
             rec["service_request_number"], rec["asc_name"], rec["installation_status"],
             rec["remarks"], rec["sentiment"], rec["transcript"], rec["call_summary"]),
        )

    print(f"[lead_files] Imported '{original_name}' -> file_id={file_id}, {len(rows)} rows, stored='{stored_name}'")
    return get_file(file_id)


# ── queries ───────────────────────────────────────────────────────────────────

def list_files() -> list[dict]:
    return _fetchall(
        """
        SELECT id, original_name, stored_name, day_of_week, row_count,
               uploaded_by, uploaded_at, active
        FROM lead_files
        WHERE active = TRUE
        ORDER BY uploaded_at DESC
        """
    )


def get_file(file_id: int) -> dict | None:
    return _fetchone("SELECT * FROM lead_files WHERE id = %s", (file_id,))


def file_label(f: dict) -> str:
    """Same label the UI dropdown shows: '<date> (<day>) <time> · <name> · <rows>' (IST)."""
    if not f:
        return "?"
    date_s = time_s = "?"
    ua = f.get("uploaded_at")
    if ua is not None:
        try:
            if getattr(ua, "tzinfo", None) is None:
                ua = ua.replace(tzinfo=timezone.utc)
            ist = ua.astimezone(IST)
            date_s = f"{ist.day}/{ist.month}/{ist.year}"
            time_s = ist.strftime("%I:%M %p").replace("AM", "am").replace("PM", "pm")
        except Exception:
            pass
    return f"{date_s} ({f.get('day_of_week','')}) {time_s} · {f.get('original_name','')} · {f.get('row_count','')} rows"


def soft_delete_file(file_id: int) -> bool:
    """Hide a file from the upload-history dropdown (active=FALSE).

    Reversible, non-destructive: campaign history, Excel downloads, and all
    lead_file_rows stay intact — only list_files() (the dropdown) filters on active.
    """
    rows = _execute("UPDATE lead_files SET active = FALSE WHERE id = %s RETURNING id", (file_id,))
    return bool(rows)


def get_rows(file_id: int) -> list[dict]:
    # LEFT JOIN the latest linked call so the UI can show a "Campaign" badge
    # when the row's most recent call was fired by an automated campaign.
    return _fetchall(
        """
        SELECT r.*, c.campaign_db_id AS campaign_db_id
        FROM lead_file_rows r
        LEFT JOIN calls c ON c.record_id = r.call_record_id
        WHERE r.file_id = %s
        ORDER BY r.row_index ASC
        """,
        (file_id,),
    )


def get_row(row_id: int) -> dict | None:
    return _fetchone("SELECT * FROM lead_file_rows WHERE id = %s", (row_id,))


def get_row_by_record(record_id: str) -> dict | None:
    """Find the lead-file row linked to a Cube call record_id (None if not a lead-file call)."""
    if not record_id:
        return None
    return _fetchone("SELECT * FROM lead_file_rows WHERE call_record_id = %s", (record_id,))


# ── mutate working copy ───────────────────────────────────────────────────────

def update_row(row_id: int, fields: dict) -> dict | None:
    """Manual inline edit. Only EDITABLE_FIELDS are accepted."""
    sets, vals = [], []
    for k, v in fields.items():
        if k in EDITABLE_FIELDS:
            sets.append(f"{k} = %s")
            vals.append(v)
    if not sets:
        return get_row(row_id)
    sets.append("updated_at = NOW()")
    vals.append(row_id)
    _execute(f"UPDATE lead_file_rows SET {', '.join(sets)} WHERE id = %s", vals)
    return get_row(row_id)


def set_row_call(row_id: int, call_status: str, called_by: str = None, record_id: str = None) -> dict | None:
    """Mark a row's calling state (e.g. called_by='VoiceBOT', record_id=<cube record>)."""
    sets = ["call_status = %s", "updated_at = NOW()"]
    vals = [call_status]
    if called_by is not None:
        sets.append("called_by = %s"); vals.append(called_by)
    if record_id is not None:
        sets.append("call_record_id = %s"); vals.append(record_id)
    vals.append(row_id)
    _execute(f"UPDATE lead_file_rows SET {', '.join(sets)} WHERE id = %s", vals)
    return get_row(row_id)


def apply_disposition(record_id: str, disposition: str) -> int:
    """Set the call disposition on the row linked to this Cube record_id.

    Writes the `disposition` column AND appends it to `remarks`
    ("<original> | <disposition>"). Idempotent — if a disposition is already
    set for the row, it is left as-is (no duplicate append).
    """
    row = get_row_by_record(record_id)
    if not row:
        return 0
    if row.get("disposition"):
        return 0  # already dispositioned — don't append twice
    orig = (row.get("remarks") or "").strip()
    new_remarks = f"{orig} | {disposition}" if orig else disposition
    _execute(
        "UPDATE lead_file_rows SET disposition=%s, remarks=%s, updated_at=NOW() WHERE id=%s",
        (disposition, new_remarks, row["id"]),
    )
    print(f"[lead_files] disposition '{disposition}' -> row {row['id']} (record {record_id})")
    return 1


def mark_not_connected(record_id: str) -> int:
    """Flip the linked row's call_status to 'not_connected' (a terminal state).

    Not-connected calls never reach apply_call_result (no conversation happened),
    so without this the row's call_status would stay stuck at 'initiated' even
    though the call is over. Guarded so it never downgrades a call that actually
    connected ('called').
    """
    rows = _execute(
        """
        UPDATE lead_file_rows SET call_status='not_connected', updated_at=NOW()
        WHERE call_record_id=%s AND call_status <> 'called'
        RETURNING id
        """,
        (record_id,),
    )
    if rows:
        print(f"[lead_files] call_status -> 'not_connected' for row {rows[0]['id']} (record {record_id})")
    return len(rows)


def apply_call_result(record_id: str, **fields) -> int:
    """Post-call writeback: update the row linked to this Cube record_id.
    Only WRITEBACK_FIELDS are applied; also flips call_status → 'called'."""
    sets, vals = ["call_status = 'called'", "updated_at = NOW()"], []
    for k, v in fields.items():
        if k in WRITEBACK_FIELDS and v is not None:
            sets.append(f"{k} = %s")
            vals.append(v)
    vals.append(record_id)
    rows = _execute(
        f"UPDATE lead_file_rows SET {', '.join(sets)} WHERE call_record_id = %s RETURNING id",
        vals,
    )
    if rows:
        print(f"[lead_files] Writeback applied to row {rows[0]['id']} (record {record_id})")
    return len(rows)


# ── export working copy → xlsx ────────────────────────────────────────────────

def export_updated_xlsx(file_id: int) -> tuple[bytes, str] | None:
    """Build a fresh xlsx from the current working copy (DB rows)."""
    f = get_file(file_id)
    if not f:
        return None
    rows = get_rows(file_id)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append([h for h, _ in _EXPORT_COLUMNS])
    for r in rows:
        ws.append([r.get(field) for _, field in _EXPORT_COLUMNS])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    base = os.path.splitext(f["original_name"])[0]
    base = re.sub(r"(_UPDATED)+$", "", base, flags=re.IGNORECASE)  # avoid _UPDATED_UPDATED
    filename = f"{base}_UPDATED.xlsx"
    return buf.read(), filename


def original_path(file_id: int) -> tuple[str, str] | None:
    """Return (disk path, download filename) for the PRISTINE original."""
    f = get_file(file_id)
    if not f or not os.path.exists(f["stored_path"]):
        return None
    return f["stored_path"], f["original_name"]
