import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import ThemeToggle from "../components/ThemeToggle";
import FilePicker from "../components/FilePicker";
import {
  Play, Pause, Square, Phone, PhoneOff, Clock,
  CheckCircle, XCircle, AlertCircle, Loader2,
  Upload, ChevronLeft, ChevronDown, ChevronUp, RefreshCw, UserPlus, List, Download
} from "lucide-react";
import {
  campaignStart, campaignPause, campaignResume, campaignStop,
  campaignAddLead, campaignStatus, campaignHistory,
  campaignLeadsRich,
  uploadLeadFile, listLeadFiles, leadFileDownloadUrl
} from "../utils/api";

const STATE_CFG = {
  idle:      { color: "text-gray-500",   bg: "bg-gray-100  dark:bg-gray-700",   label: "Idle"      },
  running:   { color: "text-green-600",  bg: "bg-green-100 dark:bg-green-900",  label: "Running"   },
  paused:    { color: "text-yellow-600", bg: "bg-yellow-100 dark:bg-yellow-900",label: "Paused"    },
  stopped:   { color: "text-red-600",    bg: "bg-red-100   dark:bg-red-900",    label: "Stopped"   },
  completed: { color: "text-blue-600",   bg: "bg-blue-100  dark:bg-blue-900",   label: "Completed" },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function Badge({ state }) {
  const cfg = STATE_CFG[state] ?? STATE_CFG.idle;
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold ${cfg.bg} ${cfg.color}`}>
      {state === "running" && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
      {cfg.label}
    </span>
  );
}

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-4 flex items-center gap-3">
      <div className={`p-2 rounded-lg bg-gray-50 dark:bg-gray-700 ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
        <p className={`text-xl font-bold ${color}`}>{value ?? "—"}</p>
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const map = {
    completed:     { bg: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",     Icon: CheckCircle },
    failed:        { bg: "bg-red-100   dark:bg-red-900   text-red-700   dark:text-red-300",        Icon: XCircle    },
    no_answer:     { bg: "bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300",  Icon: AlertCircle },
    not_connected: { bg: "bg-red-100   dark:bg-red-900   text-red-700   dark:text-red-300",        Icon: PhoneOff   },
    initiated:     { bg: "bg-blue-100  dark:bg-blue-900  text-blue-700  dark:text-blue-300",       Icon: Phone      },
    calling:       { bg: "bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300",  Icon: Phone      },
    pending:       { bg: "bg-gray-100  dark:bg-gray-700  text-gray-600  dark:text-gray-400",       Icon: Clock      },
    retry_pending: { bg: "bg-orange-100 dark:bg-orange-900 text-orange-700 dark:text-orange-300",  Icon: AlertCircle },
    running:       { bg: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",      Icon: Play       },
    paused:        { bg: "bg-yellow-100 dark:bg-yellow-900 text-yellow-700 dark:text-yellow-300",  Icon: Pause      },
    stopped:       { bg: "bg-red-100   dark:bg-red-900   text-red-700   dark:text-red-300",        Icon: Square     },
  };
  const cfg = map[status] ?? { bg: "bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400", Icon: Clock };
  const { Icon } = cfg;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.bg}`}>
      <Icon size={10} />
      {status ?? "unknown"}
    </span>
  );
}

function LeadsTable({ leads }) {
  if (!leads || leads.length === 0) return (
    <div className="py-8 text-center text-sm text-gray-400">No lead data available.</div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 dark:bg-gray-700 text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          <tr>
            <th className="px-3 py-2 text-left w-8">#</th>
            <th className="px-3 py-2 text-left">Name</th>
            <th className="px-3 py-2 text-left">Phone</th>
            <th className="px-3 py-2 text-left">Status</th>
            <th className="px-3 py-2 text-center">Attempt</th>
            <th className="px-3 py-2 text-left">Called At</th>
            <th className="px-3 py-2 text-left">Error / Note</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
          {leads.map(lead => (
            <tr key={lead.index} className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
              <td className="px-3 py-2 text-gray-400">{lead.index}</td>
              <td className="px-3 py-2 font-medium text-gray-900 dark:text-white max-w-[180px] truncate">{lead.name}</td>
              <td className="px-3 py-2 text-gray-600 dark:text-gray-300 whitespace-nowrap">{lead.phone}</td>
              <td className="px-3 py-2"><StatusPill status={lead.status} /></td>
              <td className="px-3 py-2 text-center text-gray-500">{(lead.attempt ?? 0) + 1}</td>
              <td className="px-3 py-2 text-gray-500 whitespace-nowrap">
                {lead.call_started_at ? new Date(lead.call_started_at).toLocaleTimeString() : "—"}
              </td>
              <td className="px-3 py-2 text-gray-400 max-w-[200px] truncate" title={lead.error}>{lead.error || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Rich Leads-style table — mirrors the /leads page, fed by /leads-rich ──────
function RichLeadsTable({ leads }) {
  if (!leads || leads.length === 0) return (
    <div className="py-8 text-center text-sm text-gray-400">No lead data available.</div>
  );
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-gray-50 dark:bg-gray-700 text-gray-500 dark:text-gray-400 uppercase tracking-wider">
          <tr>
            <th className="px-3 py-2 text-left w-8">#</th>
            <th className="px-3 py-2 text-left">Customer</th>
            <th className="px-3 py-2 text-left">Disposition</th>
            <th className="px-3 py-2 text-left">Sentiment</th>
            <th className="px-3 py-2 text-left">Call Status</th>
            <th className="px-3 py-2 text-center">Attempt</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
          {leads.map(l => (
            <tr key={l.index} className="hover:bg-gray-50 dark:hover:bg-gray-700/40 align-top">
              <td className="px-3 py-2 text-gray-400">{l.index}</td>
              <td className="px-3 py-2 min-w-[140px]">
                <div className="font-medium text-gray-900 dark:text-white break-words">{l.name || "—"}</div>
                <div className="text-gray-500 dark:text-gray-400 whitespace-nowrap">{l.phone || "—"}</div>
              </td>
              <td className="px-3 py-2 font-medium text-blue-700 dark:text-blue-300 break-words max-w-[160px]">{l.disposition || "—"}</td>
              <td className="px-3 py-2 text-gray-600 dark:text-gray-300">{l.sentiment || "—"}</td>
              <td className="px-3 py-2">{l.call_status ? <StatusPill status={l.call_status} /> : <span className="text-gray-400">—</span>}</td>
              <td className="px-3 py-2 text-center text-gray-500">{(l.attempt ?? 0) + 1}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Extract the lead_file_id a campaign ran on — for the Updated-Excel download
// (same export the Leads page uses). filters_used may be a JSON string or object.
function campaignLeadFileId(c) {
  const f = c?.filters_used;
  if (!f) return null;
  try {
    const obj = typeof f === "string" ? JSON.parse(f) : f;
    return obj?.lead_file_id ?? null;
  } catch { return null; }
}

// Auto campaign name = "<date> (<day>) <time> - <sheet name>"
// e.g. "2/7/2026 (Wednesday) 3:45 PM - Test Data"
function autoCampaignName(fileName) {
  const now = new Date();
  const IST = "Asia/Kolkata";
  const dateStr = now.toLocaleDateString("en-IN", { timeZone: IST });
  const day = now.toLocaleDateString("en-IN", { timeZone: IST, weekday: "long" });
  const timeStr = now.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: true });
  const clean = (fileName || "").replace(/\.xlsx?$/i, "").trim();
  return `${dateStr} (${day}) ${timeStr} - ${clean}`;
}

// ── CSV parser — supports Kirloskar Excel format + simple phone/name/product/price ──
function parseCsvLeads(text) {
  // Split respecting quoted fields (addresses contain commas)
  function splitCsvLine(line) {
    const cols = [];
    let cur = "", inQuote = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') { inQuote = !inQuote; }
      else if (ch === ',' && !inQuote) { cols.push(cur.trim()); cur = ""; }
      else { cur += ch; }
    }
    cols.push(cur.trim());
    return cols;
  }

  const lines = text.trim().split("\n").filter(Boolean);
  if (lines.length === 0) return [];

  const firstRow = splitCsvLine(lines[0]).map(c => c.toLowerCase().trim());

  // Header detection — include Kirloskar Excel header words
  const hasHeader = firstRow.some(c =>
    ["phone", "phone_number", "mobile", "name", "customer name", "contact phone number",
     "product", "price", "account name", "asset number", "rating", "branch id"].includes(c)
  );

  // Column aliases → internal field names
  const COL_MAP = {
    phone_number:     ["contact phone number", "phone_number", "phone", "mobile", "contact", "number"],
    name:             ["customer name", "name", "customer_name", "customer"],
    account_name:     ["account name", "account_name", "company"],
    asset_number:     ["asset number", "asset_number", "model number", "model_number"],
    location:         ["installation site address", "installation_site_address", "address", "location", "install location"],
    machine_type:     ["product", "machine_type", "product_name", "item"],
    dg_capacity:      ["rating", "dg_capacity", "capacity", "kva"],
    agreement_expiry: ["agreement expiry date", "agreement_expiry_date", "warranty expiry date", "warranty_expiry_date", "agreement expiry", "warranty expiry", "agreement_expiry", "warranty"],
    last_service_month: ["last service date", "last_service_date", "last_service_month", "last service"],
    service_due_date: ["service due date", "service_due_date", "due date", "next service"],
    branch_id:        ["branch id", "branch_id", "branch"],
  };

  let headers = null;
  let dataLines = lines;

  if (hasHeader) {
    headers = firstRow;
    dataLines = lines.slice(1);
  }

  return dataLines.map(line => {
    const cols = splitCsvLine(line);

    if (!headers) {
      // No header — assume: phone [, name [, product [, price]]]
      return {
        phone_number: cols[0] || "",
        name:         cols[1] || "",
        lead_data: {
          machine_type: cols[2] || "",
          dg_capacity:  cols[3] || "",
        },
      };
    }

    // Map header names to values
    const row = {};
    headers.forEach((h, i) => { row[h] = cols[i] || ""; });

    const get = (aliases) => {
      for (const a of aliases) if (row[a] !== undefined && row[a] !== "") return row[a];
      return "";
    };

    // Normalize phone: strip spaces/dashes, keep last 10 digits
    let phone = get(COL_MAP.phone_number).replace(/[\s\-().+]/g, "");
    if (phone.length > 10) phone = phone.slice(-10);

    // Build location: strip internal quotes/newlines from multi-part address
    const loc = get(COL_MAP.location).replace(/["\n\r]+/g, " ").replace(/\s+/g, " ").trim();

    return {
      phone_number: phone,
      name:         get(COL_MAP.name),
      lead_data: {
        account_name:       get(COL_MAP.account_name),
        machine_type:       get(COL_MAP.machine_type) || "Genset",
        dg_capacity:        get(COL_MAP.dg_capacity) ? get(COL_MAP.dg_capacity) + " kVA" : "",
        location:           loc,
        location_full:      loc,
        agreement_expiry:   get(COL_MAP.agreement_expiry),
        warranty_expiry:    get(COL_MAP.agreement_expiry),
        last_service_month: get(COL_MAP.last_service_month),
        service_due_date:   get(COL_MAP.service_due_date),
        model_number:       get(COL_MAP.asset_number),
        branch_id:          get(COL_MAP.branch_id),
        flow_type:          "POST_WARRANTY",
      },
    };
  }).filter(l => l.phone_number && l.phone_number.length >= 10);
}

// ── Main component ────────────────────────────────────────────────────────────

export default function Campaign() {
  const navigate = useNavigate();
  const [status,  setStatus]  = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [toast,   setToast]   = useState(null);
  const [tab,     setTab]     = useState("live");
  const pollRef     = useRef(null);
  const leadsRef    = useRef(null);

  // Per-lead tracking
  const [leadsLog,      setLeadsLog]      = useState([]);
  const [expandedId,    setExpandedId]    = useState(null);
  const [expandedLeads, setExpandedLeads] = useState({});

  // Start-campaign form
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: "",
    delay_seconds: 120,
    max_concurrent: 2,
  });
  const [csvFile,    setCsvFile]    = useState(null);
  const [parsedLeads, setParsedLeads] = useState([]);
  const [csvPreview,  setCsvPreview]  = useState([]);

  // Excel-based lead source (mirrors the Leads page)
  const [leadFiles,     setLeadFiles]     = useState([]);
  const [selectedFileId, setSelectedFileId] = useState("");
  const [uploadingExcel, setUploadingExcel] = useState(false);

  const loadLeadFiles = useCallback(async () => {
    try {
      const data = await listLeadFiles();
      const files = data.files ?? data ?? [];
      setLeadFiles(files);
      if (files.length && !selectedFileId) {
        setSelectedFileId(String(files[0].id));
        setForm(f => ({ ...f, name: autoCampaignName(files[0].original_name) }));
      }
    } catch { /* silent */ }
  }, [selectedFileId]);

  // Add-lead modal
  const [showAddLead, setShowAddLead] = useState(false);
  const [addLeadForm, setAddLeadForm] = useState({
    phone_number: "", name: "", product_name: "", price: ""
  });

  const showToast = (msg, type = "success") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3500);
  };

  const loadStatus = useCallback(async () => {
    try { setStatus(await campaignStatus()); } catch { /* silent */ }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const data = await campaignHistory();
      setHistory(data.campaigns ?? []);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      await Promise.all([loadStatus(), loadHistory()]);
      setLoading(false);
    })();
  }, []);

  // Poll every 3s while active
  useEffect(() => {
    const active = status?.state === "running" || status?.state === "paused";
    if (active) {
      pollRef.current = setInterval(() => { loadStatus(); }, 3000);
    }
    return () => clearInterval(pollRef.current);
  }, [status?.state]);

  // Poll per-lead log every 3s when active
  useEffect(() => {
    const cid = status?.campaign_id;
    const active = status?.state === "running" || status?.state === "paused";
    if (!cid || !active) return;
    const fetch = async () => {
      try {
        const data = await campaignLeadsRich(cid);
        if (data.success) setLeadsLog(data.leads ?? []);
      } catch {}
    };
    fetch();
    leadsRef.current = setInterval(fetch, 3000);
    return () => clearInterval(leadsRef.current);
  }, [status?.campaign_id, status?.state]);

  // Fetch leads for completed/stopped campaign once
  useEffect(() => {
    const cid = status?.campaign_id;
    const done = status?.state === "completed" || status?.state === "stopped";
    if (!cid || !done || leadsLog.length > 0) return;
    campaignLeadsRich(cid).then(d => { if (d.success) setLeadsLog(d.leads ?? []); }).catch(() => {});
  }, [status?.state]);

  const toggleExpandHistory = async (id) => {
    if (expandedId === id) { setExpandedId(null); return; }
    setExpandedId(id);
    if (!(id in expandedLeads)) {
      try {
        const data = await campaignLeadsRich(id);
        // null = fetched but not available; array = fetched with leads
        setExpandedLeads(prev => ({ ...prev, [id]: data.success ? (data.leads ?? []) : null }));
      } catch {
        setExpandedLeads(prev => ({ ...prev, [id]: null }));
      }
    }
  };

  // CSV handling
  const handleCsvChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setCsvFile(file);
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target.result;
      const leads = parseCsvLeads(text);
      setParsedLeads(leads);
      // Preview: first 5 raw lines
      setCsvPreview(text.trim().split("\n").slice(0, 6).map(l => l.split(",")));
    };
    reader.readAsText(file);
  };

  const handleExcelUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingExcel(true);
    try {
      const res = await uploadLeadFile(file);
      if (res.success && res.file) {
        showToast(`Uploaded "${res.file.original_name}" — ${res.file.row_count} rows`);
        await loadLeadFiles();
        setSelectedFileId(String(res.file.id));
        setForm(f => ({ ...f, name: autoCampaignName(res.file.original_name) }));
      } else {
        showToast(res.error || "Upload failed", "error");
      }
    } catch (err) {
      showToast(err.message || "Upload failed", "error");
    } finally { setUploadingExcel(false); e.target.value = ""; }
  };

  const handleStart = async () => {
    if (!selectedFileId) { showToast("Please select or upload a Swara Excel calling list", "error"); return; }
    setActionLoading(true);
    try {
      await campaignStart({
        name:           form.name || `Campaign ${new Date().toLocaleDateString("en-IN")}`,
        lead_file_id:   Number(selectedFileId),
        delay_seconds:  Number(form.delay_seconds),
        max_concurrent: Number(form.max_concurrent),
        filters:        {},
      });
      showToast("Campaign started!");
      setShowForm(false);
      await loadStatus();
    } catch (e) {
      showToast(e.message || "Failed to start", "error");
    } finally { setActionLoading(false); }
  };

  const handleAction = async (action) => {
    setActionLoading(true);
    try {
      if (action === "pause")  await campaignPause();
      if (action === "resume") await campaignResume();
      if (action === "stop")   await campaignStop();
      showToast(`Campaign ${action}d`);
      await loadStatus();
      if (action === "stop") await loadHistory();
    } catch (e) { showToast(e.message || `Failed`, "error"); }
    finally { setActionLoading(false); }
  };

  const handleAddLead = async () => {
    if (!addLeadForm.phone_number) { showToast("Phone number is required", "error"); return; }
    setActionLoading(true);
    try {
      const payload = {
        phone_number: addLeadForm.phone_number,
        name:         addLeadForm.name,
        lead_data: {
          product_name: addLeadForm.product_name,
          price:        addLeadForm.price,
        },
      };
      const res = await campaignAddLead(payload);
      if (res.success) {
        showToast("Lead added to campaign queue!");
        setShowAddLead(false);
        setAddLeadForm({ phone_number: "", name: "", product_name: "", price: "" });
        await loadStatus();
      } else {
        showToast(res.error || "Failed to add lead", "error");
      }
    } catch (e) { showToast(e.message || "Failed", "error"); }
    finally { setActionLoading(false); }
  };

  const state    = status?.state ?? "idle";
  const isActive = state === "running" || state === "paused";
  const progress = status?.total > 0
    ? Math.round(((status.called + status.failed) / status.total) * 100)
    : 0;

  return (
    <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-900 transition-colors">

      {/* HEADER */}
      <div className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center gap-3">
              <button onClick={() => navigate("/dashboard")} className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300">
                <ChevronLeft size={20} />
              </button>
              <div>
                <h1 className="text-lg font-bold text-gray-900 dark:text-white">Campaign Manager</h1>
                <p className="text-xs text-gray-500 dark:text-gray-400">Swara The Fashion Street</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button onClick={() => { loadStatus(); loadHistory(); }} className="p-2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-300" title="Refresh">
                <RefreshCw size={16} />
              </button>
              <ThemeToggle />
              <button onClick={() => { localStorage.removeItem("auth"); navigate("/login", { replace: true }); }}
                className="text-sm text-red-500 hover:text-red-700 font-medium">Logout</button>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6 w-full">

        {/* Toast */}
        {toast && (
          <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-white text-sm font-medium
            ${toast.type === "error" ? "bg-red-500" : "bg-green-500"}`}>
            {toast.msg}
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-48">
            <Loader2 className="animate-spin text-gray-400" size={32} />
          </div>
        ) : (<>

          {/* STATUS CARD */}
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <h2 className="text-base font-semibold text-gray-900 dark:text-white">
                    {status?.campaign_name || "No active campaign"}
                  </h2>
                  <Badge state={state} />
                </div>
                {status?.current_lead && (
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Calling: <span className="font-medium text-gray-700 dark:text-gray-300">
                      {status.current_lead.name || "—"} ({status.current_lead.phone})
                    </span>
                  </p>
                )}
              </div>

              {/* CONTROLS */}
              <div className="flex flex-wrap gap-2">
                {!isActive && (
                  <button onClick={() => { setShowForm(true); loadLeadFiles(); }} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <Play size={14} /> Start Campaign
                  </button>
                )}
                {state === "running" && (<>
                  <button onClick={() => setShowAddLead(true)} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <UserPlus size={14} /> Add Lead
                  </button>
                  <button onClick={() => handleAction("pause")} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-yellow-500 hover:bg-yellow-600 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <Pause size={14} /> Pause
                  </button>
                </>)}
                {state === "paused" && (<>
                  <button onClick={() => setShowAddLead(true)} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <UserPlus size={14} /> Add Lead
                  </button>
                  <button onClick={() => handleAction("resume")} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <Play size={14} /> Resume
                  </button>
                </>)}
                {isActive && (
                  <button onClick={() => handleAction("stop")} disabled={actionLoading}
                    className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                    <Square size={14} /> Stop
                  </button>
                )}
                {actionLoading && <Loader2 className="animate-spin text-gray-400 my-auto" size={18} />}
              </div>
            </div>

            {/* PROGRESS BAR */}
            {(status?.total ?? 0) > 0 && (
              <div className="mt-5">
                <div className="flex justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
                  <span>{(status.called ?? 0) + (status.failed ?? 0)} / {status.total} processed</span>
                  <span>{progress}%</span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
                  <div className="bg-green-500 h-2 rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}
          </div>

          {/* STAT CARDS */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <StatCard icon={Phone}       label="Total Leads"  value={status?.total}     color="text-blue-600" />
            <StatCard icon={CheckCircle} label="Called"       value={status?.called}    color="text-green-600" />
            <StatCard icon={XCircle}     label="Failed"       value={status?.failed}    color="text-red-500" />
            <StatCard icon={Clock}       label="Remaining"    value={status?.remaining} color="text-yellow-600" />
          </div>

          {/* TABS */}
          <div className="border-b border-gray-200 dark:border-gray-700">
            <nav className="flex gap-6">
              {[["live","Live Status"], ["history","Campaign History"]].map(([key, label]) => (
                <button key={key} onClick={() => setTab(key)}
                  className={`pb-3 text-sm font-medium border-b-2 transition-colors ${
                    tab === key
                      ? "border-blue-500 text-blue-600 dark:text-blue-400"
                      : "border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                  }`}>
                  {label}
                </button>
              ))}
            </nav>
          </div>

          {/* TAB CONTENT */}
          {tab === "live" && (
            <div className="space-y-4">
              {/* Campaign info grid */}
              <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
                <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                  <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Current Campaign Info</h2>
                  <div className="flex items-center gap-2">
                    {status?.lead_file_id && (
                      <a href={leadFileDownloadUrl(status.lead_file_id, "updated", `${status.campaign_name || "campaign"} updated`)} download
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/50 transition-colors">
                        <Download size={12} /> Updated Excel
                      </a>
                    )}
                  </div>
                </div>
                <div className="p-6 grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Campaign Name</p>
                    <p className="font-medium text-gray-900 dark:text-white">{status?.campaign_name || "—"}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Delay Between Calls</p>
                    <p className="font-medium text-gray-900 dark:text-white">{status?.delay_seconds != null ? `${status.delay_seconds}s` : "—"}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Max Concurrent</p>
                    <p className="font-medium text-gray-900 dark:text-white">{status?.max_concurrent ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Started At</p>
                    <p className="font-medium text-gray-900 dark:text-white">
                      {status?.started_at ? new Date(status.started_at).toLocaleString() : "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Skipped (invalid nos.)</p>
                    <p className="font-medium text-gray-900 dark:text-white">{status?.skipped ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-gray-400 text-xs mb-1">Campaign ID</p>
                    <p className="font-medium text-gray-500 dark:text-gray-400 font-mono text-xs">{status?.campaign_id ?? "—"}</p>
                  </div>
                </div>
              </div>

              {/* Per-lead table */}
              {leadsLog.length > 0 && (
                <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700">
                  <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
                      Lead-by-Lead Status
                      <span className="ml-2 text-xs font-normal text-gray-400">
                        {leadsLog.filter(l => (l.dispatch_status ?? l.status) === "initiated").length} initiated ·{" "}
                        {leadsLog.filter(l => (l.dispatch_status ?? l.status) === "failed").length} failed ·{" "}
                        {leadsLog.filter(l => (l.dispatch_status ?? l.status) === "pending").length} pending
                      </span>
                    </h2>
                    {isActive && <span className="flex items-center gap-1 text-xs text-green-500"><span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" /> Live</span>}
                  </div>
                  <RichLeadsTable leads={leadsLog} />
                </div>
              )}
            </div>
          )}

          {tab === "history" && (
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Past Campaigns</h2>
              </div>
              {history.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                  <List size={32} className="mb-2" />
                  <p className="text-sm">No campaigns yet</p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100 dark:divide-gray-700">
                  {history.map((c, i) => (
                    <div key={c.id ?? i}>
                      {/* Summary row */}
                      <div className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{c.name || "—"}</p>
                          <p className="text-xs text-gray-400">
                            {c.started_at ? new Date(c.started_at).toLocaleString() : "—"}
                            {c.completed_at ? ` → ${new Date(c.completed_at).toLocaleString()}` : ""}
                          </p>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <StatusPill status={c.state} />
                          <span className="text-xs text-gray-500">{c.total ?? 0} leads</span>
                          <span className="text-xs text-green-600 font-medium">{c.called ?? 0} called</span>
                          {(c.failed ?? 0) > 0 && <span className="text-xs text-red-500 font-medium">{c.failed} failed</span>}
                          {campaignLeadFileId(c) && (
                            <a href={leadFileDownloadUrl(campaignLeadFileId(c), "updated", `${c.name || "campaign"} updated`)} download
                              className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/50 transition-colors"
                              title="Download updated Excel">
                              <Download size={11} /> Excel
                            </a>
                          )}
                          <button onClick={() => toggleExpandHistory(c.id)}
                            className="p-1 rounded text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
                            {expandedId === c.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                          </button>
                        </div>
                      </div>
                      {/* Expanded per-lead table */}
                      {expandedId === c.id && (
                        <div className="bg-gray-50 dark:bg-gray-900 border-t border-gray-100 dark:border-gray-700">
                          {!(c.id in expandedLeads)
                            ? <div className="py-6 text-center text-xs text-gray-400"><Loader2 className="animate-spin inline mr-1" size={12} />Loading lead details…</div>
                            : expandedLeads[c.id] === null
                            ? <div className="py-6 text-center text-xs text-gray-400">Lead details unavailable — server was restarted after this campaign ran.</div>
                            : <RichLeadsTable leads={expandedLeads[c.id]} />
                          }
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>)}

        {/* ── START CAMPAIGN MODAL ─────────────────────────────────────── */}
        {showForm && (
          <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
              <h3 className="text-base font-bold text-gray-900 dark:text-white">Start New Campaign</h3>

              {/* Campaign Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Campaign Name</label>
                <input type="text" value={form.name} placeholder={`Campaign ${new Date().toLocaleDateString("en-IN")}`}
                  onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              {/* Swara Excel calling list — pick existing or upload new */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Calling List (Swara Excel)
                  <span className="ml-1 text-gray-400 font-normal text-xs">— same format as the Leads page</span>
                </label>
                <FilePicker
                  files={leadFiles}
                  value={selectedFileId ? Number(selectedFileId) : null}
                  onChange={id => {
                    setSelectedFileId(String(id));
                    const f = leadFiles.find(x => x.id === id);
                    if (f) setForm(prev => ({ ...prev, name: autoCampaignName(f.original_name) }));
                  }}
                  onDeleted={(id, label) => {
                    setLeadFiles(prev => prev.filter(f => f.id !== id));
                    if (String(id) === String(selectedFileId)) setSelectedFileId("");
                    showToast(`Deleted: ${label}`);
                  }}
                  placeholder="No files uploaded yet — upload one below"
                />

                <label className="mt-2 flex items-center gap-2 cursor-pointer border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-3 hover:border-blue-400 transition-colors">
                  {uploadingExcel ? <Loader2 size={16} className="text-gray-400 animate-spin" /> : <Upload size={16} className="text-gray-400" />}
                  <span className="text-sm text-gray-500 dark:text-gray-400">
                    {uploadingExcel ? "Uploading…" : "Upload a new Excel (.xlsx)"}
                  </span>
                  <input type="file" accept=".xlsx,.xls" className="hidden" onChange={handleExcelUpload} disabled={uploadingExcel} />
                </label>

                <div className="mt-2 bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3 text-xs text-blue-700 dark:text-blue-300">
                  The campaign calls each row of the selected list automatically. Results
                  (disposition, sentiment, summary) are written back live and the
                  updated Excel can be downloaded after the run.
                </div>
              </div>

              {/* Delay + Concurrency */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Delay between calls (s)</label>
                  <select value={form.delay_seconds}
                    onChange={e => setForm(f => ({ ...f, delay_seconds: Number(e.target.value) }))}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                    {Array.from({ length: 7 }, (_, i) => 120 + i * 10).map(s => (
                      <option key={s} value={s}>{s}s</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Max concurrent calls</label>
                  <select value={form.max_concurrent}
                    onChange={e => setForm(f => ({ ...f, max_concurrent: Number(e.target.value) }))}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value={2}>2 — Standard</option>
                    <option value={3}>3 — High</option>
                    <option value={4}>4 — Max</option>
                  </select>
                </div>
              </div>

              <div className="flex gap-3 pt-1">
                <button onClick={handleStart} disabled={actionLoading || !selectedFileId}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                  {actionLoading ? <Loader2 className="animate-spin" size={14} /> : <Play size={14} />}
                  Start Campaign
                </button>
                <button onClick={() => setShowForm(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm rounded-lg font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── ADD LEAD MODAL ───────────────────────────────────────────── */}
        {showAddLead && (
          <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center p-4">
            <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
              <h3 className="text-base font-bold text-gray-900 dark:text-white">Add Lead to Campaign</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                This lead will be added to the end of the current campaign queue.
              </p>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Phone Number <span className="text-red-500">*</span></label>
                <input type="tel" value={addLeadForm.phone_number} placeholder="9876543210"
                  onChange={e => setAddLeadForm(f => ({ ...f, phone_number: e.target.value }))}
                  className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Customer Name</label>
                <input type="text" value={addLeadForm.name} placeholder="Ramesh Kumar"
                  onChange={e => setAddLeadForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Product Name</label>
                  <input type="text" value={addLeadForm.product_name} placeholder="KirloStar DG"
                    onChange={e => setAddLeadForm(f => ({ ...f, product_name: e.target.value }))}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Price (₹)</label>
                  <input type="text" value={addLeadForm.price} placeholder="45000"
                    onChange={e => setAddLeadForm(f => ({ ...f, price: e.target.value }))}
                    className="w-full border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>

              <div className="flex gap-3 pt-1">
                <button onClick={handleAddLead} disabled={actionLoading}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg font-medium disabled:opacity-60 transition-colors">
                  {actionLoading ? <Loader2 className="animate-spin" size={14} /> : <UserPlus size={14} />}
                  Add to Queue
                </button>
                <button onClick={() => setShowAddLead(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm rounded-lg font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
