"""
Database Module for Cube VoiceBot
Direct PostgreSQL connection via psycopg2 (replaces Supabase REST API).
All public function signatures are identical to the previous version.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

# ── Connection ────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://paluck_pw_voicebot:972ab47d4239@103.178.248.149:5432/paluck_pw_voicebot_db"
)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None

def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=DATABASE_URL,
        )
    return _pool


@contextmanager
def _conn():
    """Yield a connection from the pool, auto-commit or rollback."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _fetchall(sql: str, params=None) -> List[Dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def _fetchone(sql: str, params=None) -> Optional[Dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None


def _execute(sql: str, params=None) -> List[Dict]:
    """Execute a write statement and return RETURNING rows (if any)."""
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            try:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            except psycopg2.ProgrammingError:
                return []


def _j(value) -> Optional[str]:
    """Serialize a value to JSON string for JSONB columns."""
    return json.dumps(value) if value is not None else None


# ==================== DATABASE INITIALIZATION ====================

def init_database():
    """Connect to PostgreSQL and ensure all tables exist (idempotent)."""
    print("[DB] Connecting to PostgreSQL database...")
    try:
        _fetchone("SELECT 1 AS ok")
        print("[DB] Successfully connected to PostgreSQL!")
    except Exception as e:
        print(f"[DB] Warning: Could not connect: {e}")
        return

    # Run schema — CREATE TABLE IF NOT EXISTS is safe on every startup
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
        print("[DB] Schema applied — all tables verified/created.")
    except FileNotFoundError:
        print(f"[DB] Warning: Schema file not found at {schema_path}")
    except Exception as e:
        print(f"[DB] Warning: Schema apply failed: {e}")


# ==================== CALL MANAGEMENT ====================

def create_call(
    record_id: str,
    phone_number: str,
    customer_name: str = None,
    company_name: str = None,
    campaign_id: str = None,
    metadata: Dict[str, Any] = None,
    campaign_db_id: int = None
) -> int:
    cube_call_number = None
    if record_id and ":" in record_id:
        try:
            cube_call_number = int(record_id.split(":")[-1])
        except (ValueError, IndexError):
            pass

    rows = _execute(
        """
        INSERT INTO calls
            (record_id, cube_call_number, phone_number, customer_name,
             company_name, campaign_id, call_status, metadata, campaign_db_id)
        VALUES (%s, %s, %s, %s, %s, %s, 'initiated', %s, %s)
        RETURNING id
        """,
        (record_id, cube_call_number, phone_number, customer_name,
         company_name, campaign_id, _j(metadata), campaign_db_id),
    )
    call_id = rows[0]["id"] if rows else None
    print(f"[DB] Call created: #{call_id} | RecordID: {record_id} | Phone: {phone_number}")
    return call_id


def update_call_status(record_id: str, status: str, raw_status: str = None):
    if status in ('completed', 'failed', 'not_connected'):
        _execute(
            """
            UPDATE calls
            SET call_status = %s,
                call_ended_at = %s,
                cube_status_raw = COALESCE(%s, cube_status_raw)
            WHERE record_id = %s
            """,
            (status, datetime.utcnow().isoformat() + "Z", raw_status, record_id),
        )
    else:
        _execute(
            """
            UPDATE calls
            SET call_status = %s,
                cube_status_raw = COALESCE(%s, cube_status_raw)
            WHERE record_id = %s
            """,
            (status, raw_status, record_id),
        )
    print(f"[DB] Call status updated: {record_id} -> {status}")


def update_call_analysis(
    record_id: str,
    installation_status: str = None,
    installation_status_reason: str = None,
    disposition: str = None,
    disposition_reason: str = None,
    sentiment: str = None,
    call_summary: str = None,
):
    """Write post-call analysis results directly to the calls table.

    Each call has its own row here so data is never lost when the same lead
    is called multiple times (unlike lead_file_rows which gets overwritten).
    """
    _execute(
        """
        UPDATE calls
        SET installation_status        = COALESCE(%s, installation_status),
            installation_status_reason = COALESCE(%s, installation_status_reason),
            disposition                = COALESCE(%s, disposition),
            disposition_reason         = COALESCE(%s, disposition_reason),
            sentiment                  = COALESCE(%s, sentiment),
            call_summary               = COALESCE(%s, call_summary)
        WHERE record_id = %s
        """,
        (installation_status, installation_status_reason, disposition, disposition_reason, sentiment, call_summary, record_id),
    )
    print(f"[DB] Call analysis saved: {record_id} → status={installation_status}, disposition={disposition}")


# WhatsApp fallback DB helpers removed for Swara (no WhatsApp fallback).
# The `whatsapp_status` column on `calls` is left in place (harmless, unused).


# ──────────────────────────────────────────────────────────────────────────────
# Cube real-time call-status webhook (GET /getCallStatus)
# ──────────────────────────────────────────────────────────────────────────────

def mark_cube_connected(record_id: str):
    """Stamp cube_connected_at — Cube reported the customer picked up."""
    _execute(
        "UPDATE calls SET cube_connected_at=NOW() WHERE record_id=%s AND cube_connected_at IS NULL",
        (record_id,),
    )
    print(f"[DB] Cube webhook: Connected -> {record_id}")


def mark_cube_disconnected(record_id: str):
    """Stamp cube_disconnected_at — Cube reported the line closed."""
    _execute(
        "UPDATE calls SET cube_disconnected_at=NOW() WHERE record_id=%s AND cube_disconnected_at IS NULL",
        (record_id,),
    )
    print(f"[DB] Cube webhook: Disconnected -> {record_id}")


def get_cube_status_distribution(limit: int = 200) -> List[Dict[str, Any]]:
    """Distinct Status values /getCallStatus has received, with counts + last seen.
    Lets us review every real status string Cube sends in production."""
    return _fetchall(
        """
        SELECT details->>'status_raw' AS status_raw,
               COUNT(*) AS hits,
               MAX(timestamp) AS last_seen
        FROM console_logs
        WHERE message LIKE 'Cube call-status webhook:%%'
        GROUP BY details->>'status_raw'
        ORDER BY hits DESC
        LIMIT %s
        """,
        (limit,),
    )


def get_cube_call_flags(record_id: str) -> Optional[Dict[str, Any]]:
    """Return {connected_at, disconnected_at} for a call (None if not found)."""
    row = _fetchone(
        "SELECT cube_connected_at, cube_disconnected_at FROM calls WHERE record_id=%s",
        (record_id,),
    )
    if not row:
        return None
    return {
        "connected_at": row.get("cube_connected_at"),
        "disconnected_at": row.get("cube_disconnected_at"),
    }


def update_call_duration(record_id: str):
    call = _fetchone("SELECT call_initiated_at, call_ended_at FROM calls WHERE record_id=%s", (record_id,))
    if call and call.get("call_ended_at"):
        initiated = datetime.fromisoformat(str(call["call_initiated_at"]).replace("Z", "+00:00"))
        ended     = datetime.fromisoformat(str(call["call_ended_at"]).replace("Z", "+00:00"))
        duration  = int((ended - initiated).total_seconds())
        _execute(
            "UPDATE calls SET call_duration_seconds=%s WHERE record_id=%s",
            (duration, record_id),
        )
        print(f"[DB] Call duration calculated for {record_id}: {duration}s")
    else:
        print(f"[DB] WARNING: Cannot calculate duration: call_ended_at is missing for {record_id}")


def update_recording_url(record_id: str, recording_url: str, duration: int = None):
    if duration is not None:
        _execute(
            "UPDATE calls SET recording_url=%s, recording_duration_seconds=%s WHERE record_id=%s",
            (recording_url, duration, record_id),
        )
    else:
        _execute("UPDATE calls SET recording_url=%s WHERE record_id=%s", (recording_url, record_id))
    print(f"[DB] Recording URL updated for {record_id}" + (f" (duration: {duration}s)" if duration else ""))


def get_call_by_record_id(record_id: str) -> Optional[Dict[str, Any]]:
    return _fetchone("SELECT * FROM calls WHERE record_id=%s", (record_id,))


def get_call_by_cube_number(cube_call_number: int) -> Optional[Dict[str, Any]]:
    return _fetchone("SELECT * FROM calls WHERE cube_call_number=%s", (cube_call_number,))


def get_call_id_by_record_id(record_id: str) -> Optional[int]:
    row = _fetchone("SELECT id FROM calls WHERE record_id=%s", (record_id,))
    return row["id"] if row else None


def get_call_by_duration_and_recency(duration_seconds: int, within_minutes: int = 5) -> Optional[Dict[str, Any]]:
    cutoff = (datetime.utcnow() - timedelta(minutes=within_minutes)).isoformat() + "Z"
    try:
        result = _fetchall(
            "SELECT * FROM calls WHERE call_initiated_at >= %s ORDER BY call_initiated_at DESC LIMIT 20",
            (cutoff,),
        )
    except Exception as e:
        print(f"[DB] WARNING: get_call_by_duration_and_recency query failed: {e}")
        return None

    TOLERANCE = 5
    for call in result:
        rec_dur = call.get("recording_duration_seconds") or call.get("call_duration_seconds")
        if rec_dur is not None and abs(int(rec_dur) - duration_seconds) <= TOLERANCE:
            print(f"[DB] Duration match: call {call['record_id']} "
                  f"(stored={rec_dur}s, webhook={duration_seconds}s, diff={abs(int(rec_dur)-duration_seconds)}s)")
            return call

    for call in result:
        if call.get("recording_url"):
            continue
        if call.get("call_ended_at"):
            print(f"[DB] Recency fallback match: call {call['record_id']} (no duration stored yet)")
            return call

    return None


def get_call_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    clean = ''.join(filter(str.isdigit, phone_number))
    query_phone = clean[-10:] if len(clean) >= 10 else clean
    return _fetchone(
        """
        SELECT * FROM calls
        WHERE phone_number ILIKE %s
          AND call_status IN ('initiated', 'connected')
        ORDER BY call_initiated_at DESC
        LIMIT 1
        """,
        (f"%{query_phone}%",),
    )


# ==================== CONVERSATION LOGGING ====================

def log_conversation(
    record_id: str,
    speaker: str,
    message: str,
    message_type: str = 'speech',
    metadata: Dict[str, Any] = None
):
    call_id = get_call_id_by_record_id(record_id)
    if not call_id:
        print(f"[DB] WARNING: Call not found for RecordID: {record_id}, creating placeholder")
        call_id = create_call(record_id, "unknown", "Unknown", None, None)

    _execute(
        """
        INSERT INTO conversation_logs (call_id, record_id, speaker, message, message_type, metadata)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (call_id, record_id, speaker, message, message_type, _j(metadata)),
    )
    print(f"[DB] [{speaker.upper()}]: {message[:50]}...")


def get_conversation(record_id: str) -> List[Dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM conversation_logs WHERE record_id=%s ORDER BY timestamp ASC",
        (record_id,),
    )


# ==================== CONSOLE LOGGING ====================

def log_console(
    message: str,
    log_level: str = 'INFO',
    record_id: str = None,
    details: Dict[str, Any] = None
):
    call_id = get_call_id_by_record_id(record_id) if record_id else None
    _execute(
        """
        INSERT INTO console_logs (call_id, record_id, log_level, message, details)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (call_id, record_id, log_level, message, _j(details)),
    )
    print(f"[DB] [{log_level}] {message[:100]}...")


# ==================== QUERY FUNCTIONS ====================

def get_all_calls(limit: int = 50, offset: int = 0, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
    where, params = [], []
    if start_date:
        where.append("call_initiated_at >= %s"); params.append(start_date)
    if end_date:
        where.append("call_initiated_at <= %s"); params.append(f"{end_date}T23:59:59")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params += [limit, offset]
    return _fetchall(
        f"SELECT * FROM calls {clause} ORDER BY call_initiated_at DESC LIMIT %s OFFSET %s",
        params,
    )


def get_recent_calls(limit: int = 10) -> List[Dict[str, Any]]:
    return get_all_calls(limit=limit, offset=0)


def get_latest_calls_for_phones(phone_numbers: List[str]) -> Dict[str, Dict[str, Any]]:
    if not phone_numbers:
        return {}

    cleaned = []
    for p in phone_numbers:
        digits = ''.join(filter(str.isdigit, p))
        cleaned.append(digits[-10:] if len(digits) >= 10 else digits)

    try:
        rows = _fetchall(
            f"""
            SELECT DISTINCT ON (phone_number) *
            FROM calls
            WHERE phone_number = ANY(%s)
            ORDER BY phone_number, call_initiated_at DESC
            """,
            (cleaned,),
        )
    except Exception as e:
        print(f"[DB] WARNING: Batch call fetch failed: {e}")
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        raw = row.get("phone_number", "")
        digits = ''.join(filter(str.isdigit, raw))
        key = digits[-10:] if len(digits) >= 10 else digits
        if key not in result:
            result[key] = row
    return result


def search_calls(phone_number: str = None, customer_name: str = None) -> List[Dict[str, Any]]:
    where, params = [], []
    if phone_number:
        where.append("phone_number ILIKE %s"); params.append(f"%{phone_number}%")
    if customer_name:
        where.append("customer_name ILIKE %s"); params.append(f"%{customer_name}%")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return _fetchall(f"SELECT * FROM calls {clause} ORDER BY call_initiated_at DESC", params)


def update_conversation_record_id(old_record_id: str, new_record_id: str) -> bool:
    try:
        new_call_id = get_call_id_by_record_id(new_record_id)
        old_call_id = get_call_id_by_record_id(old_record_id)
        if new_call_id and old_call_id:
            _execute(
                "UPDATE conversation_logs SET record_id=%s, call_id=%s WHERE record_id=%s",
                (new_record_id, new_call_id, old_record_id),
            )
            print(f"[DB] Migrated conversation logs: {old_record_id} ({old_call_id}) -> {new_record_id} ({new_call_id})")
        else:
            _execute(
                "UPDATE conversation_logs SET record_id=%s WHERE record_id=%s",
                (new_record_id, old_record_id),
            )
            print(f"[DB] Migrated conversation logs: {old_record_id} -> {new_record_id} (call_id not updated)")
        return True
    except Exception as e:
        print(f"[DB] Error migrating conversation logs: {e}")
        return False


# ==================== LEAD MANAGEMENT ====================

def add_lead(lead_data: Dict[str, Any]) -> int:
    phone = lead_data.get('phone_number')
    name  = lead_data.get('name')
    if not phone:
        print("[DB] WARNING: Skipping lead without phone number")
        return -1
    rows = _execute(
        "INSERT INTO leads (phone_number, name, lead_data, status) VALUES (%s, %s, %s, 'pending') RETURNING id",
        (phone, name, _j(lead_data)),
    )
    return rows[0]["id"] if rows else -1


def get_pending_leads(limit: int = 10) -> List[Dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM leads WHERE status='pending' ORDER BY created_at ASC LIMIT %s",
        (limit,),
    )


def update_lead_status(lead_id: int, status: str):
    _execute("UPDATE leads SET status=%s WHERE id=%s", (status, lead_id))


def update_all_leads_by_phone(phone_number: str, status: str) -> int:
    clean = ''.join(filter(str.isdigit, phone_number or ''))
    if len(clean) >= 10:
        clean = clean[-10:]
    if not clean:
        print(f"[DB] update_all_leads_by_phone: invalid phone '{phone_number}'")
        return 0
    try:
        rows = _execute(
            "UPDATE leads SET status=%s WHERE phone_number=%s RETURNING id",
            (status, clean),
        )
        count = len(rows)
        print(f"[DB] update_all_leads_by_phone: {clean} -> '{status}' ({count} rows)")
        return count
    except Exception as e:
        print(f"[DB] ERROR update_all_leads_by_phone({clean}): {e}")
        return 0


def create_or_update_lead(phone_number: str, name: str = None, lead_data: Dict[str, Any] = None) -> int:
    if not phone_number:
        print("[DB] WARNING: Cannot create lead without phone number")
        return -1

    clean = ''.join(filter(str.isdigit, phone_number))
    if len(clean) >= 10:
        clean = clean[-10:]

    existing = get_lead_by_phone(clean)
    if existing:
        lead_id        = existing['id']
        current_status = existing.get('status', 'pending')
        sets, vals     = [], []

        if name:
            sets.append("name=%s"); vals.append(name)
        if lead_data:
            existing_data = existing.get('lead_data') or {}
            if isinstance(existing_data, dict):
                preserved = existing_data.get('date_created')
                existing_data.update(lead_data)
                if preserved:
                    existing_data['date_created'] = preserved
            else:
                existing_data = lead_data
            sets.append("lead_data=%s"); vals.append(_j(existing_data))

        if current_status == 'initiated':
            sets.append("status=%s"); vals.append("not_connected")
            print(f"[DB] Resetting stale 'initiated' → 'not_connected' for lead {lead_id} ({clean})")

        if sets:
            vals.append(lead_id)
            _execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=%s", vals)
        print(f"[DB] Updated existing lead: ID={lead_id}, Phone={clean}")
        return lead_id
    else:
        rows = _execute(
            "INSERT INTO leads (phone_number, name, lead_data, status) VALUES (%s, %s, %s, 'pending') RETURNING id",
            (clean, name or (lead_data.get('name') if lead_data else None), _j(lead_data or {})),
        )
        lead_id = rows[0]["id"] if rows else -1
        print(f"[DB] Created new lead: ID={lead_id}, Phone={clean}")
        return lead_id


def batch_upsert_leads(leads: List[Dict[str, Any]]) -> Dict[str, int]:
    if not leads:
        return {'created': 0, 'updated': 0, 'skipped': 0}

    cleaned, skipped = [], 0
    for lead in leads:
        digits = ''.join(filter(str.isdigit, str(lead.get('phone_number', ''))))
        clean  = digits[-10:] if len(digits) >= 10 else digits
        if not clean:
            skipped += 1
            continue
        cleaned.append({'raw': lead, 'phone': clean})

    if not cleaned:
        return {'created': 0, 'updated': 0, 'skipped': skipped}

    phone_list = [c['phone'] for c in cleaned]

    try:
        existing_rows = _fetchall(
            "SELECT id, phone_number, status FROM leads WHERE phone_number = ANY(%s)",
            (phone_list,),
        )
    except Exception as e:
        print(f"[DB] ERROR: Could not fetch existing leads batch: {e}")
        existing_rows = []

    existing_phones, stale_ids = set(), []
    for row in existing_rows:
        p   = ''.join(filter(str.isdigit, row.get('phone_number', '')))
        key = p[-10:] if len(p) >= 10 else p
        existing_phones.add(key)
        if row.get('status') == 'initiated':
            stale_ids.append(row['id'])

    # Batch insert new leads
    new_rows = [
        (c['phone'], c['raw'].get('name'), _j(c['raw']), 'pending')
        for c in cleaned if c['phone'] not in existing_phones
    ]
    created = 0
    if new_rows:
        try:
            with _conn() as conn:
                with conn.cursor() as cur:
                    psycopg2.extras.execute_values(
                        cur,
                        "INSERT INTO leads (phone_number, name, lead_data, status) VALUES %s",
                        new_rows,
                    )
            created = len(new_rows)
            print(f"[DB] Batch inserted {created} new leads.")
        except Exception as e:
            print(f"[DB] ERROR: Batch insert failed: {e}")

    # Reset stale leads
    updated = 0
    if stale_ids:
        try:
            _execute(
                "UPDATE leads SET status='not_connected' WHERE id = ANY(%s)",
                (stale_ids,),
            )
            updated = len(stale_ids)
            print(f"[DB] Reset {updated} stale 'initiated' → 'not_connected'.")
        except Exception as e:
            print(f"[DB] WARNING: Could not reset stale statuses: {e}")

    existing_count = len(existing_phones.intersection(set(phone_list)))
    print(f"[DB] batch_upsert_leads: {created} created, {existing_count} existing, {updated} status-reset, {skipped} skipped.")
    return {'created': created, 'updated': updated, 'skipped': skipped}


def get_all_leads(limit: int = 100, offset: int = 0, date_filter: str = None) -> List[Dict[str, Any]]:
    if date_filter:
        return _fetchall(
            """
            SELECT * FROM leads
            WHERE lead_data->>'date_created' LIKE %s
            ORDER BY created_at DESC LIMIT %s OFFSET %s
            """,
            (f"{date_filter}%", limit, offset),
        )
    return _fetchall(
        "SELECT * FROM leads ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
    )


def get_lead_by_phone(phone_number: str) -> Optional[Dict[str, Any]]:
    clean = ''.join(filter(str.isdigit, phone_number))
    query = clean[-10:] if len(clean) >= 10 else clean
    return _fetchone(
        "SELECT * FROM leads WHERE phone_number ILIKE %s ORDER BY created_at DESC LIMIT 1",
        (f"%{query}%",),
    )


def get_all_transcripts(limit: int = 100, start_date: str = None, end_date: str = None) -> List[Dict[str, Any]]:
    where, params = [], []
    if start_date:
        where.append("call_initiated_at >= %s"); params.append(start_date)
    if end_date:
        where.append("call_initiated_at <= %s"); params.append(f"{end_date}T23:59:59")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)

    calls_result = _fetchall(
        f"SELECT * FROM calls {clause} ORDER BY call_initiated_at DESC LIMIT %s",
        params,
    )

    transcripts = []
    for call in calls_result:
        entries = _fetchall(
            "SELECT * FROM conversation_logs WHERE record_id=%s ORDER BY timestamp ASC",
            (call['record_id'],),
        )
        if not entries:
            continue
        lines = [
            f"{'Agent' if e['speaker'] == 'bot' else 'User'}: {e['message']}"
            for e in entries
        ]
        transcript_text = "\n".join(lines)
        if transcript_text:
            transcripts.append({
                'call_id':       call['record_id'],
                'phone_number':  call['phone_number'],
                'customer_name': call['customer_name'],
                'transcript':    transcript_text,
                'created_at':    call['call_initiated_at'],
            })
    return transcripts


def get_call_stats(start_date: str = None, end_date: str = None) -> Dict[str, Any]:
    where, params = [], []
    if start_date:
        where.append("call_initiated_at >= %s"); params.append(start_date)
    if end_date:
        where.append("call_initiated_at <= %s"); params.append(f"{end_date}T23:59:59")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    all_calls = _fetchall(f"SELECT call_status, call_duration_seconds FROM calls {clause}", params)
    total = len(all_calls)

    status_counts: Dict[str, int] = {}
    for c in all_calls:
        s = c.get('call_status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1

    durations = [c['call_duration_seconds'] for c in all_calls if c.get('call_duration_seconds')]
    avg_duration = sum(durations) / len(durations) if durations else 0

    return {
        'total_calls':              total,
        'status_breakdown':         status_counts,
        'average_duration_seconds': round(avg_duration, 2),
    }


# ==================== CAMPAIGN MANAGEMENT ====================

def create_campaign(
    name: str,
    filters: Dict,
    total: int,
    delay_seconds: int,
    max_concurrent: int,
) -> Optional[int]:
    rows = _execute(
        """
        INSERT INTO campaigns
            (name, state, total, called, failed, skipped, remaining,
             filters_used, delay_seconds, max_concurrent, started_at)
        VALUES (%s, 'running', %s, 0, 0, 0, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (name, total, total, json.dumps(filters), delay_seconds,
         max_concurrent, datetime.now(timezone.utc).isoformat()),
    )
    return rows[0]["id"] if rows else None


def update_campaign_progress(
    campaign_id: int,
    called: int,
    failed: int,
    skipped: int,
    remaining: int,
    state: str,
) -> None:
    if state in ("completed", "stopped"):
        _execute(
            """
            UPDATE campaigns
            SET called=%s, failed=%s, skipped=%s, remaining=%s, state=%s, completed_at=%s
            WHERE id=%s
            """,
            (called, failed, skipped, remaining, state,
             datetime.now(timezone.utc).isoformat(), campaign_id),
        )
    else:
        _execute(
            "UPDATE campaigns SET called=%s, failed=%s, skipped=%s, remaining=%s, state=%s WHERE id=%s",
            (called, failed, skipped, remaining, state, campaign_id),
        )


def get_campaign(campaign_id: int) -> Optional[Dict[str, Any]]:
    return _fetchone("SELECT * FROM campaigns WHERE id=%s", (campaign_id,))


def get_campaign_history(limit: int = 20) -> List[Dict[str, Any]]:
    return _fetchall(
        "SELECT * FROM campaigns ORDER BY started_at DESC LIMIT %s",
        (limit,),
    )


def upsert_campaign_lead(
    campaign_id: int,
    phone: str,
    name: str,
    attempt: int,
    status: str,
    call_started_at: Optional[str] = None,
    call_completed_at: Optional[str] = None,
    error: Optional[str] = None,
    record_id: Optional[str] = None,
    lead_file_row_id: Optional[int] = None,
) -> None:
    """Insert or update a per-lead outcome row keyed on (campaign_id, phone, attempt)."""
    _execute(
        """
        INSERT INTO campaign_leads
            (campaign_id, phone, name, attempt, status, call_started_at, call_completed_at, error,
             record_id, lead_file_row_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (campaign_id, phone, attempt)
        DO UPDATE SET
            name              = EXCLUDED.name,
            status            = EXCLUDED.status,
            call_started_at   = COALESCE(EXCLUDED.call_started_at, campaign_leads.call_started_at),
            call_completed_at = COALESCE(EXCLUDED.call_completed_at, campaign_leads.call_completed_at),
            error             = EXCLUDED.error,
            record_id         = COALESCE(EXCLUDED.record_id, campaign_leads.record_id),
            lead_file_row_id  = COALESCE(EXCLUDED.lead_file_row_id, campaign_leads.lead_file_row_id),
            updated_at        = NOW()
        """,
        (campaign_id, phone, name, attempt, status,
         call_started_at, call_completed_at, error, record_id, lead_file_row_id),
    )


def get_campaign_leads(campaign_id: int) -> List[Dict[str, Any]]:
    """Return all per-lead rows for a campaign, ordered by id."""
    return _fetchall(
        "SELECT * FROM campaign_leads WHERE campaign_id=%s ORDER BY id",
        (campaign_id,),
    )


def get_campaign_leads_enriched(campaign_id: int) -> List[Dict[str, Any]]:
    """Per-lead campaign rows joined to their rich Excel row (lead_file_rows).

    Post-call analysis writes disposition / installation_status / sentiment /
    call_status back to lead_file_rows, so this single LEFT JOIN surfaces the
    real, live post-call outcome alongside the campaign's own dispatch status —
    everything the campaign table needs to look like the Leads page.
    """
    return _fetchall(
        """
        SELECT
            cl.id                AS campaign_lead_id,
            cl.phone, cl.name, cl.attempt, cl.status AS dispatch_status,
            cl.error, cl.record_id, cl.lead_file_row_id,
            cl.call_started_at, cl.call_completed_at,
            r.product_name, r.dealer_name, r.service_request_number,
            r.asc_name, r.customer_name, r.remarks,
            r.installation_status, r.disposition, r.sentiment,
            r.call_status        AS row_call_status
        FROM campaign_leads cl
        LEFT JOIN lead_file_rows r ON r.id = cl.lead_file_row_id
        WHERE cl.campaign_id = %s
        ORDER BY cl.id
        """,
        (campaign_id,),
    )


def update_campaign_lead_outcome(
    phone: str,
    outcome: str,
    conclusion: str,
) -> None:
    """Set outcome + conclusion on the most recent campaign_lead row for a phone number."""
    _execute(
        """
        UPDATE campaign_leads
        SET outcome = %s, conclusion = %s, updated_at = NOW()
        WHERE id = (
            SELECT id FROM campaign_leads
            WHERE phone = %s
            ORDER BY id DESC
            LIMIT 1
        )
        """,
        (outcome, conclusion, phone),
    )


# ==================== INITIALIZATION ====================

try:
    init_database()
except Exception as e:
    print(f"[DB] ERROR: Error initializing database: {e}")
