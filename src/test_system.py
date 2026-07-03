"""
Full system test — run with:
  .venv/Scripts/python.exe src/test_system.py
"""
import sys, asyncio, uuid
sys.path.insert(0, 'src')

passed = []
failed = []

def ok(msg):   passed.append(msg);  print(f"  PASS  {msg}")
def fail(msg, err): failed.append(msg); print(f"  FAIL  {msg}: {err}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n1. MODULE IMPORTS")

try:
    import database as db
    ok("database")
except Exception as e: fail("database", e)

try:
    from campaign_manager import (
        campaign_manager, CampaignManager, CampaignRegistry,
        MAX_SIMULTANEOUS_CAMPAIGNS, RUNNING, PAUSED, IDLE
    )
    ok("campaign_manager")
except Exception as e: fail("campaign_manager", e)

try:
    from system_prompt import (
        POST_WARRANTY_PROMPT, KOEL_FOLLOWUP_PROMPT, FLOW_PROMPTS
    )
    # Backward-compat aliases no longer exported — use merged PALUCK_PROMPT names
    SCHEDULED_SERVICE_PROMPT = POST_WARRANTY_PROMPT
    WARRANTY_SERVICE_PROMPT  = POST_WARRANTY_PROMPT
    ok("system_prompt")
except Exception as e: fail("system_prompt", e)

try:
    from lead_knowledge import build_lead_context, BUSINESS_VERTICAL_KNOWLEDGE
    ok("lead_knowledge")
except Exception as e: fail("lead_knowledge", e)

try:
    from crm_api import CRMClient
    assert CRMClient().fetch_daily_leads() == []
    ok("crm_api (stub, returns empty)")
except Exception as e: fail("crm_api", e)

# ─────────────────────────────────────────────────────────────────────────────
# 2. DATABASE
# ─────────────────────────────────────────────────────────────────────────────
print("\n2. DATABASE")

try:
    row = db._fetchone("SELECT 1 AS ok")
    assert row["ok"] == 1
    ok("PostgreSQL connection live")
except Exception as e: fail("PostgreSQL connection", e)

try:
    tables = db._fetchall(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )
    names = {t["table_name"] for t in tables}
    for t in ["calls", "conversation_logs", "console_logs", "leads", "campaigns"]:
        assert t in names, f"Missing: {t}"
    ok(f"All 5 tables present: {sorted(names)}")
except Exception as e: fail("Tables", e)

try:
    rid = f"TEST_{uuid.uuid4().hex[:8]}"
    cid = db.create_call(record_id=rid, phone_number="9999900001",
                          customer_name="Test User", campaign_id="test_suite")
    assert cid
    call = db.get_call_by_record_id(rid)
    assert call["customer_name"] == "Test User"
    db.update_call_status(rid, "completed")
    db._execute("DELETE FROM calls WHERE record_id=%s", (rid,))
    ok(f"Call CRUD (id={cid})")
except Exception as e: fail("Call CRUD", e)

try:
    lid = db.create_or_update_lead("8888877778", name="Test Lead",
                                    lead_data={"product_name": "KirloStar DG"})
    assert lid > 0
    lead = db.get_lead_by_phone("8888877778")
    assert lead is not None
    db._execute("DELETE FROM leads WHERE phone_number=%s", ("8888877778",))
    ok(f"Lead CRUD (id={lid})")
except Exception as e: fail("Lead CRUD", e)

try:
    camps = db.get_campaign_history(limit=5)
    ok(f"Campaign history query ({len(camps)} records)")
except Exception as e: fail("Campaign history", e)

try:
    stats = db.get_call_stats()
    assert "total_calls" in stats
    ok(f"Call stats (total={stats['total_calls']})")
except Exception as e: fail("Call stats", e)

# ─────────────────────────────────────────────────────────────────────────────
# 3. SYSTEM PROMPT PLACEHOLDERS
# ─────────────────────────────────────────────────────────────────────────────
print("\n3. SYSTEM PROMPT PLACEHOLDERS")

# Merged prompt — check placeholders present in both flow sections
PW_REQUIRED = [
    "__CUSTOMER_NAME__", "__MACHINE_TYPE__", "__DG_CAPACITY__",
    "__INSTALL_LOCATION__", "__HELPLINE_NUMBER__", "__LAST_SERVICE_MONTH__",
]
KOEL_REQUIRED = [
    "__CUSTOMER_NAME__", "__MACHINE_TYPE__", "__MODEL_NUMBER__",
    "__ACCOUNT_NAME__", "__KOEL_STATUS__", "__PHONE_NUMBER__",
]

for ph in PW_REQUIRED:
    try:
        assert ph in POST_WARRANTY_PROMPT
        ok(f"{ph} in POST_WARRANTY")
    except: fail(f"{ph} in POST_WARRANTY", "MISSING")

for ph in KOEL_REQUIRED:
    try:
        assert ph in KOEL_FOLLOWUP_PROMPT
        ok(f"{ph} in KOEL_FOLLOWUP")
    except: fail(f"{ph} in KOEL_FOLLOWUP", "MISSING")

# Full replacement test — no placeholder should survive
try:
    sample = {
        "__CUSTOMER_NAME__":    "Ramesh Kumar",
        "__MACHINE_TYPE__":     "Genset",
        "__DG_CAPACITY__":      "62.5 KVA",
        "__INSTALL_LOCATION__": "Noida",
        "__LAST_SERVICE_MONTH__": "October 2025",
        "__HELPLINE_NUMBER__":  "+91 8130102683",
        "__ACCOUNT_NAME__":     "Kumar Enterprises",
        "__MODEL_NUMBER__":     "KG1-62.5-VS",
        "__KOEL_STATUS__":      "Follow-up",
        "__PHONE_NUMBER__":     "9876543210",
        "__FLOW_TYPE__":        "POST_WARRANTY",
        "__INSTALL_LOCATION_FULL__": "Plot A-10, Sector 3, Noida",
        "__AGREEMENT_EXPIRY__": "Oct 2025",
        "__WARRANTY_EXPIRY__":  "May 2026",
        "__SERVICE_DUE_DATE__": "April 2026",
        "__INSTALLATION_DATE__": "Jan 2023",
    }
    for flow_name, prompt in FLOW_PROMPTS.items():
        p = prompt
        for k, v in sample.items():
            p = p.replace(k, v)
        leftover = [ph for ph in sample if ph in p]
        assert not leftover, f"{flow_name}: unreplaced {leftover}"
        assert "Ramesh Kumar" in p
        ok(f"Full replacement — {flow_name}: no leftover placeholders")
except Exception as e: fail("Placeholder replacement", e)

# ─────────────────────────────────────────────────────────────────────────────
# 4. CAMPAIGN MANAGER
# ─────────────────────────────────────────────────────────────────────────────
print("\n4. CAMPAIGN MANAGER")

try:
    assert MAX_SIMULTANEOUS_CAMPAIGNS == 2
    ok(f"MAX_SIMULTANEOUS_CAMPAIGNS = {MAX_SIMULTANEOUS_CAMPAIGNS}")
except Exception as e: fail("MAX_SIMULTANEOUS_CAMPAIGNS", e)

try:
    assert isinstance(campaign_manager, CampaignRegistry)
    ok("campaign_manager is CampaignRegistry singleton")
except Exception as e: fail("campaign_manager type", e)

try:
    s = campaign_manager.get_status()
    assert s["state"] == IDLE
    assert s["max_campaigns"] == 2
    assert s["active_campaigns"] == 0
    assert s["pending_campaigns"] == 0
    ok("get_status() idle: state=idle, active=0, pending=0, max=2")
except Exception as e: fail("get_status idle", e)

try:
    assert not campaign_manager.pause()["success"]
    assert not campaign_manager.stop()["success"]
    assert not campaign_manager.resume()["success"]
    ok("pause/stop/resume return error when idle")
except Exception as e: fail("Controls when idle", e)

try:
    r = asyncio.run(campaign_manager.add_lead({"phone_number": "9876543210"}))
    assert not r["success"]
    ok("add_lead returns error when no active campaign")
except Exception as e: fail("add_lead idle", e)

try:
    mgr = CampaignManager()
    assert mgr.retry_on_busy is True
    assert mgr.retry_on_no_answer is True
    assert mgr.retry_delay_seconds == 60
    assert mgr.max_concurrent == 2
    ok("CampaignManager retry defaults: busy=True, no_answer=True, delay=60s, max_concurrent=2")
except Exception as e: fail("Retry defaults", e)

try:
    assert campaign_manager.get_all_status() == []
    ok("get_all_status() empty list when no campaigns started")
except Exception as e: fail("get_all_status empty", e)

# ─────────────────────────────────────────────────────────────────────────────
# 5. LEAD KNOWLEDGE
# ─────────────────────────────────────────────────────────────────────────────
print("\n5. LEAD KNOWLEDGE")

try:
    assert "PALUCK Technologies" in BUSINESS_VERTICAL_KNOWLEDGE
    assert "OPG Mobility" not in BUSINESS_VERTICAL_KNOWLEDGE
    ok("OPG Mobility removed; PALUCK Technologies present")
except Exception as e: fail("Business vertical cleanup", e)

try:
    ctx = build_lead_context(
        {"product_name": "KirloStar DG", "price": "45000"},
        "Ramesh Kumar"
    )
    assert "Ramesh Kumar" in ctx
    assert "KirloStar DG" in ctx
    ok("build_lead_context includes name + product")
except Exception as e: fail("build_lead_context", e)

# ─────────────────────────────────────────────────────────────────────────────
# 6. KOEL LEADS
# ─────────────────────────────────────────────────────────────────────────────
print("\n6. KOEL LEADS")

try:
    from koel_leads import ensure_koel_table, fetch_from_koel, sync_koel_leads, get_koel_leads, update_koel_call_status
    ok("koel_leads imports")
except Exception as e: fail("koel_leads imports", e)

try:
    ensure_koel_table()
    ok("ensure_koel_table (koel_followup_leads exists)")
except Exception as e: fail("ensure_koel_table", e)

try:
    records = fetch_from_koel("2026-04-01", "2026-04-01", "MM")
    assert isinstance(records, list)
    assert len(records) > 0
    first = records[0]
    assert "DocketId" in first
    assert "ContactNo" in first
    assert "CustomerName" in first
    ok(f"fetch_from_koel => {len(records)} records, fields OK")
except Exception as e: fail("fetch_from_koel", e)

try:
    result = sync_koel_leads("2026-04-01", "2026-04-01", "MM")
    assert "total" in result
    assert result["total"] > 0
    ok(f"sync_koel_leads => {result}")
except Exception as e: fail("sync_koel_leads", e)

try:
    rows = get_koel_leads("2026-04-01", "2026-04-01", "MM")
    assert len(rows) > 0
    row = rows[0]
    assert "docket_id" in row
    assert "contact_no" in row
    assert "call_status" in row
    ok(f"get_koel_leads => {len(rows)} rows from DB")
except Exception as e: fail("get_koel_leads", e)

try:
    rows = get_koel_leads("2026-04-01", "2026-04-01", "MM")
    test_docket = rows[0]["docket_id"]
    update_koel_call_status(test_docket, "pending")
    ok(f"update_koel_call_status docket={test_docket}")
except Exception as e: fail("update_koel_call_status", e)

# ─────────────────────────────────────────────────────────────────────────────
# 7. LIVE SERVER ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
print("\n6. LIVE SERVER ENDPOINTS (localhost:8040)")
import urllib.request, json as _json

BASE = "http://localhost:8040"

def get(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=8) as r:
            return _json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}

def post(path, body=None):
    try:
        data = _json.dumps(body or {}).encode()
        req = urllib.request.Request(f"{BASE}{path}", data=data,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return _json.loads(r.read())
    except Exception as e:
        return {"__error__": str(e)}

endpoints = [
    ("GET",  "/api/campaign/status",  None),
    ("GET",  "/api/campaign/history", None),
    ("GET",  "/api/campaign/all",     None),
    ("GET",  "/api/export?start_date=2026-01-01&end_date=2026-04-30", None),
    ("GET",  "/health",               None),
    ("POST", "/api/webhook/recording", {"record_id": "TEST_PING", "recording_url": "https://example.com/test.mp3", "duration": 0}),
]

for method, path, body in endpoints:
    r = get(path) if method == "GET" else post(path, body)
    if "__error__" in r:
        fail(f"{method} {path}", r["__error__"])
    else:
        ok(f"{method} {path} => {list(r.keys())[:4]}")

# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print()
print("=" * 60)
print(f"RESULTS: {len(passed)} passed  |  {len(failed)} failed")
if failed:
    print("\nFAILED:")
    for f in failed:
        print(f"  - {f}")
else:
    print("ALL TESTS PASSED")
