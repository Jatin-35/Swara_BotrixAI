"""
PALUCK Technologies — Koel Follow-Up Leads
Fetches records from the Koel Follow-Up API and persists them in PostgreSQL.
"""
import urllib.request
import json
from database import _execute, _fetchall

KOEL_API_URL = "http://122.176.132.162:8082/paluckreport/servlet/GetKoelFollowUpApi"

# ── Schema ────────────────────────────────────────────────────────────────────

def ensure_koel_table():
    _execute("""
        CREATE TABLE IF NOT EXISTS koel_followup_leads (
            id               SERIAL PRIMARY KEY,
            docket_id        VARCHAR(50) UNIQUE NOT NULL,
            segment          VARCHAR(50),
            follow_up_date   VARCHAR(100),
            voc              TEXT,
            instance_no      VARCHAR(50),
            koel_status      VARCHAR(255),
            account_name     VARCHAR(255),
            customer_name    VARCHAR(255),
            rating           VARCHAR(20),
            contact_no       VARCHAR(50),
            warranty_expiry  VARCHAR(100),
            genset_type      VARCHAR(100),
            model_number     VARCHAR(100),
            submit_date      VARCHAR(100),
            call_status      VARCHAR(50) DEFAULT 'pending',
            sdate            DATE,
            edate            DATE,
            synced_at        TIMESTAMPTZ DEFAULT NOW(),
            created_at       TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    # Widen contact_no if it was previously created as VARCHAR(20)
    try:
        _execute("ALTER TABLE koel_followup_leads ALTER COLUMN contact_no TYPE VARCHAR(50)")
    except Exception:
        pass
    # Add campaign_name column if not already present
    try:
        _execute("ALTER TABLE koel_followup_leads ADD COLUMN IF NOT EXISTS campaign_name VARCHAR(255)")
    except Exception:
        pass
    # Add is_interested flag for leads where customer expressed interest
    try:
        _execute("ALTER TABLE koel_followup_leads ADD COLUMN IF NOT EXISTS is_interested BOOLEAN DEFAULT FALSE")
    except Exception:
        pass

# ── Koel API ──────────────────────────────────────────────────────────────────

def fetch_from_koel(sdate: str, edate: str, seg: str = "MM") -> list:
    url = f"{KOEL_API_URL}?SDate={sdate}&EDate={edate}&seg={seg}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read().decode())

# ── DB operations ─────────────────────────────────────────────────────────────

def upsert_koel_leads(records: list, sdate: str, edate: str) -> dict:
    if not records:
        return {"created": 0, "updated": 0, "total": 0}

    rows = []
    for r in records:
        docket_id = str(r.get("DocketId", "")).strip()
        if not docket_id:
            continue
        rows.append((
            docket_id,
            r.get("Segment"),
            r.get("FollowUpDate"),
            r.get("Voc"),
            r.get("Instace"),
            r.get("Status"),
            r.get("AccountName"),
            r.get("CustomerName"),
            r.get("Rating"),
            (r.get("ContactNo") or "").strip()[:50],
            r.get("WarrantyExpiryDate"),
            r.get("GensetType"),
            r.get("ModelNumber"),
            r.get("SubmitRequestDate"),
            sdate,
            edate,
        ))

    if not rows:
        return {"created": 0, "updated": 0, "total": 0}

    # Single batch upsert — fast regardless of record count
    from psycopg2.extras import execute_values
    import database as _db
    with _db._conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO koel_followup_leads
                    (docket_id, segment, follow_up_date, voc, instance_no,
                     koel_status, account_name, customer_name, rating, contact_no,
                     warranty_expiry, genset_type, model_number, submit_date,
                     sdate, edate)
                VALUES %s
                ON CONFLICT (docket_id) DO UPDATE SET
                    segment        = EXCLUDED.segment,
                    follow_up_date = EXCLUDED.follow_up_date,
                    voc            = EXCLUDED.voc,
                    instance_no    = EXCLUDED.instance_no,
                    koel_status    = EXCLUDED.koel_status,
                    account_name   = EXCLUDED.account_name,
                    customer_name  = EXCLUDED.customer_name,
                    rating         = EXCLUDED.rating,
                    contact_no     = EXCLUDED.contact_no,
                    warranty_expiry= EXCLUDED.warranty_expiry,
                    genset_type    = EXCLUDED.genset_type,
                    model_number   = EXCLUDED.model_number,
                    submit_date    = EXCLUDED.submit_date,
                    sdate          = EXCLUDED.sdate,
                    edate          = EXCLUDED.edate,
                    synced_at      = NOW()
            """, rows)

    return {"created": len(rows), "updated": 0, "total": len(rows)}


def get_koel_leads(sdate: str = None, edate: str = None, seg: str = None) -> list:
    filters = []
    params = []
    if sdate:
        filters.append("sdate >= %s"); params.append(sdate)
    if edate:
        filters.append("edate <= %s"); params.append(edate)
    if seg:
        filters.append("segment = %s"); params.append(seg)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    return _fetchall(
        f"SELECT * FROM koel_followup_leads {where} ORDER BY follow_up_date ASC, id DESC",
        tuple(params)
    )


def update_koel_call_status(docket_id: str, call_status: str, campaign_name: str = None):
    if campaign_name is not None:
        _execute(
            "UPDATE koel_followup_leads SET call_status = %s, campaign_name = %s WHERE docket_id = %s",
            (call_status, campaign_name, docket_id)
        )
    else:
        _execute(
            "UPDATE koel_followup_leads SET call_status = %s WHERE docket_id = %s",
            (call_status, docket_id)
        )


def update_koel_interest(docket_id: str):
    _execute(
        "UPDATE koel_followup_leads SET is_interested = TRUE WHERE docket_id = %s",
        (docket_id,)
    )


def get_interested_koel_leads() -> list:
    return _fetchall(
        "SELECT * FROM koel_followup_leads WHERE is_interested = TRUE ORDER BY follow_up_date ASC, id DESC"
    )


def sync_koel_leads(sdate: str, edate: str, seg: str = "MM") -> dict:
    ensure_koel_table()
    records = fetch_from_koel(sdate, edate, seg)
    result = upsert_koel_leads(records, sdate, edate)
    print(f"[Koel] Synced {sdate} to {edate} seg={seg}: {result}")
    return result
