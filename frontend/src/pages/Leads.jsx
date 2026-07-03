import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
    listLeadFiles, getLeadFileRows, updateLeadRow, uploadLeadFile,
    leadFileDownloadUrl, makeCall,
} from "../utils/api";
import ThemeToggle from "../components/ThemeToggle";
import FilePicker from "../components/FilePicker";
import {
    ArrowLeft, RefreshCw, Phone, Search, ChevronLeft, ChevronRight,
    Upload, Download, FileSpreadsheet, Pencil, Check, X,
} from "lucide-react";

const PAGE_SIZE = 50;
const DEFAULT_TOLL_FREE = "1800 209 3484";

const STATUS_COLOR = {
    pending:   "bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300",
    calling:   "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
    initiated: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300",
    called:    "bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
    failed:    "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
    not_connected: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
};

const SENTIMENT_COLOR = {
    happy:   "text-green-600 dark:text-green-400",
    neutral: "text-gray-500 dark:text-gray-400",
    irate:   "text-red-600 dark:text-red-400",
    angry:   "text-red-600 dark:text-red-400",
};

// Fields editable inline (Voice BOT also writes these back post-call)
const EDIT_FIELDS = ["installation_status", "remarks", "sentiment", "disposition"];

// Standardized call dispositions (set after a call; also appended into Remarks)
const DISPOSITIONS = [
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
];

export default function Leads() {
    const navigate = useNavigate();
    const fileInputRef = useRef(null);

    const [files, setFiles]           = useState([]);
    const [activeFileId, setActiveId] = useState(null);
    const [rows, setRows]             = useState([]);
    const [loading, setLoading]       = useState(false);
    const [uploading, setUploading]   = useState(false);
    const [search, setSearch]         = useState("");
    const [page, setPage]             = useState(1);
    const [msg, setMsg]               = useState(null);

    // inline edit state: { rowId, draft:{field:value} }
    const [edit, setEdit] = useState(null);

    const activeFile = files.find(f => f.id === activeFileId) || null;

    // ── load history on mount ────────────────────────────────────────────────
    useEffect(() => { loadFiles(); }, []);

    // auto-dismiss the toast after a few seconds
    useEffect(() => {
        if (!msg) return;
        const t = setTimeout(() => setMsg(null), 3500);
        return () => clearTimeout(t);
    }, [msg]);

    async function loadFiles(selectId) {
        try {
            const res = await listLeadFiles();
            if (res.success) {
                setFiles(res.files);
                const pick = selectId ?? res.files[0]?.id ?? null;
                if (pick) { setActiveId(pick); loadRows(pick); }
                else { setActiveId(null); setRows([]); }
            }
        } catch (e) { console.error("loadFiles", e); }
    }

    async function loadRows(fileId) {
        setLoading(true);
        try {
            const res = await getLeadFileRows(fileId);
            if (res.success) { setRows(res.rows); setPage(1); }
        } catch (e) { console.error("loadRows", e); }
        finally { setLoading(false); }
    }

    function switchFile(id) {
        setActiveId(id);
        setSearch("");
        loadRows(id);
    }

    // ── upload ───────────────────────────────────────────────────────────────
    function pickFile() { fileInputRef.current?.click(); }

    async function onFileChosen(e) {
        const file = e.target.files?.[0];
        e.target.value = "";                       // allow re-uploading same name
        if (!file) return;
        setUploading(true);
        setMsg(null);
        try {
            const res = await uploadLeadFile(file, localStorage.getItem("auth_user") || "web");
            if (res.success) {
                setMsg({ type: "success", text: `Uploaded "${res.file.original_name}" — ${res.file.row_count} rows` });
                await loadFiles(res.file.id);       // select the new file
            } else {
                setMsg({ type: "error", text: res.error || "Upload failed" });
            }
        } catch (err) {
            setMsg({ type: "error", text: err.message });
        } finally {
            setUploading(false);
        }
    }

    function download(version) {
        if (!activeFileId) return;
        window.open(leadFileDownloadUrl(activeFileId, version), "_blank");
    }

    // ── inline edit ──────────────────────────────────────────────────────────
    function startEdit(row) {
        setEdit({
            rowId: row.id,
            draft: Object.fromEntries(EDIT_FIELDS.map(f => [f, row[f] ?? ""])),
        });
    }
    function cancelEdit() { setEdit(null); }

    async function saveEdit() {
        if (!edit) return;
        try {
            const res = await updateLeadRow(edit.rowId, edit.draft);
            if (res.success) {
                setRows(prev => prev.map(r => r.id === edit.rowId ? res.row : r));
                setEdit(null);
            }
        } catch (e) { console.error("saveEdit", e); }
    }

    // ── call ─────────────────────────────────────────────────────────────────
    async function handleCall(row) {
        const phone = (row.mobile || "").trim();
        if (!phone) { alert("No mobile number on this row"); return; }

        setRows(prev => prev.map(r =>
            r.id === row.id ? { ...r, call_status: "calling", called_by: "VoiceBOT" } : r
        ));
        try {
            const leadData = {
                flow_type:        "FABER_INSTALL_FOLLOWUP",
                product:          row.product_name || "product",
                dealer_name:      row.dealer_name || "the dealer",
                toll_free:        DEFAULT_TOLL_FREE,
                customer_name:    row.customer_name || "",
                lead_file_row_id: row.id,            // backend links call → row for writeback
            };
            const result = await makeCall(phone, row.customer_name || "", "", leadData);
            const newStatus = result.success ? "initiated" : "failed";
            setRows(prev => prev.map(r =>
                r.id === row.id ? { ...r, call_status: newStatus } : r
            ));
        } catch (e) {
            setRows(prev => prev.map(r =>
                r.id === row.id ? { ...r, call_status: "failed" } : r
            ));
        }
    }

    // ── derived ──────────────────────────────────────────────────────────────
    const filtered = rows.filter(r =>
        !search ||
        r.product_name?.toLowerCase().includes(search.toLowerCase()) ||
        r.customer_name?.toLowerCase().includes(search.toLowerCase()) ||
        r.dealer_name?.toLowerCase().includes(search.toLowerCase()) ||
        r.mobile?.includes(search) ||
        r.service_request_number?.toLowerCase().includes(search.toLowerCase())
    );
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const safePage   = Math.min(page, totalPages);
    const pageRows   = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

    const counts = {
        total:   rows.length,
        pending: rows.filter(r => (r.call_status || "pending") === "pending").length,
        called:  rows.filter(r => r.call_status === "called").length,
        voicebot: rows.filter(r => r.called_by === "VoiceBOT").length,
    };


    return (
        <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-900 transition-colors">
            {/* HEADER */}
            <div className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
                <div className="max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between items-center py-4">
                        <div className="flex items-center space-x-3">
                            <button onClick={() => navigate("/dashboard")}
                                className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-200 dark:hover:bg-gray-700 transition-colors">
                                <ArrowLeft className="h-5 w-5" />
                            </button>
                            <img src="/logo.png" alt="Logo" className="h-8 w-auto object-contain" />
                            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Swara Calling Leads</h1>
                            {rows.length > 0 && (
                                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300">
                                    {counts.total} rows · {counts.pending} pending
                                </span>
                            )}
                        </div>
                        <div className="flex items-center space-x-3">
                            <ThemeToggle />
                            <button onClick={() => { localStorage.removeItem("auth"); navigate("/login", { replace: true }); }}
                                className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors">
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex-1 max-w-[1800px] mx-auto px-4 sm:px-6 lg:px-8 py-6 w-full">

                {/* KPI CARDS */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
                    {[
                        ["Total Rows", counts.total, "text-gray-900 dark:text-white"],
                        ["Pending", counts.pending, "text-blue-600 dark:text-blue-400"],
                        ["Called", counts.called, "text-green-600 dark:text-green-400"],
                        ["Voice BOT", counts.voicebot, "text-red-600 dark:text-red-400"],
                    ].map(([label, val, color]) => (
                        <div key={label} className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 p-4">
                            <p className="text-xs text-gray-500 dark:text-gray-400 uppercase tracking-wider">{label}</p>
                            <p className={`text-2xl font-bold mt-1 ${color}`}>{val}</p>
                        </div>
                    ))}
                </div>

                {/* TOOLBAR */}
                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm p-4 mb-6 border border-gray-200 dark:border-gray-700">
                    <div className="flex flex-wrap gap-3 items-end">
                        {/* file history selector */}
                        <div className="flex-1 min-w-[260px]">
                            <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">Calling List (upload history)</label>
                            <FilePicker
                                files={files}
                                value={activeFileId}
                                onChange={id => switchFile(id)}
                                onDeleted={(id, label) => {
                                    loadFiles(id === activeFileId ? undefined : activeFileId);
                                    setMsg({ type: "success", text: `Deleted: ${label}` });
                                }}
                            />
                        </div>

                        {/* hidden file input + upload */}
                        <input ref={fileInputRef} type="file" accept=".xlsx,.xls" onChange={onFileChosen} className="hidden" />
                        <button onClick={pickFile} disabled={uploading}
                            className="inline-flex items-center px-4 py-2 text-sm font-medium rounded-md text-white bg-red-600 hover:bg-red-700 disabled:opacity-50 transition-colors">
                            <Upload className={`h-4 w-4 mr-2 ${uploading ? "animate-pulse" : ""}`} />
                            {uploading ? "Uploading…" : "Upload Excel"}
                        </button>

                        <button onClick={() => download("original")} disabled={!activeFileId}
                            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors"
                            title="Download the pristine uploaded file">
                            <Download className="h-4 w-4 mr-1.5" /> Original
                        </button>
                        <button onClick={() => download("updated")} disabled={!activeFileId}
                            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 transition-colors"
                            title="Download the working copy with all updates">
                            <FileSpreadsheet className="h-4 w-4 mr-1.5" /> Updated
                        </button>
                        <button onClick={() => activeFileId && loadRows(activeFileId)} disabled={loading || !activeFileId}
                            className="inline-flex items-center px-3 py-2 text-sm font-medium rounded-md text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 transition-colors">
                            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                        </button>
                    </div>
                </div>

                {/* SEARCH */}
                <div className="mb-4 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <input type="text" placeholder="Search by product, dealer, mobile or service request…" value={search}
                        onChange={e => { setSearch(e.target.value); setPage(1); }}
                        className="w-full pl-9 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500" />
                </div>

                {/* TABLE */}
                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                    {loading ? (
                        <div className="py-16 text-center text-gray-500 dark:text-gray-400">Loading…</div>
                    ) : pageRows.length === 0 ? (
                        <div className="py-16 text-center">
                            <FileSpreadsheet className="mx-auto h-10 w-10 text-gray-400 mb-2" />
                            <p className="text-sm text-gray-500 dark:text-gray-400">
                                {rows.length === 0 ? "No rows. Upload an Excel calling list to begin." : "No results match your search."}
                            </p>
                        </div>
                    ) : (
                        <div>
                            <table className="w-full table-fixed divide-y divide-gray-200 dark:divide-gray-700">
                                <colgroup>
                                    <col className="w-[7%]" />  {/* Product */}
                                    <col className="w-[8%]" />  {/* Customer (name + mobile stacked) */}
                                    <col className="w-[8%]" />  {/* Dealer */}
                                    <col className="w-[9%]" />  {/* Service Req # */}
                                    <col className="w-[12%]" /> {/* ASC */}
                                    <col className="w-[8%]" />  {/* Installation Status */}
                                    <col className="w-[13%]" /> {/* Remarks */}
                                    <col className="w-[6%]" />  {/* Sentiment */}
                                    <col className="w-[13%]" /> {/* Disposition */}
                                    <col className="w-[7%]" />  {/* Call Status */}
                                    <col className="w-[9%]" />  {/* Actions */}
                                </colgroup>
                                <thead className="bg-gray-50 dark:bg-gray-900">
                                    <tr>
                                        {["Product","Customer","Dealer","Service Req #","ASC","Installation Status","Remarks","Sentiment","Disposition","Call Status","Actions"].map(h => (
                                            <th key={h} className="px-2 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider overflow-hidden">
                                                {h === "Installation Status" ? (<>Installation<br />Status</>) : <span className="truncate block">{h}</span>}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                                    {pageRows.map(row => {
                                        const editing = edit?.rowId === row.id;
                                        return (
                                            <tr key={row.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/40 transition-colors align-top">
                                                <td className="px-2 py-3 text-sm font-medium text-gray-900 dark:text-white truncate" title={row.product_name}>{row.product_name || "—"}</td>
                                                {/* Customer — name above, mobile below (bold + visible) */}
                                                <td className="px-2 py-3 break-words">
                                                    <div className="text-sm font-medium text-gray-900 dark:text-white break-words" title={row.customer_name}>{row.customer_name || "—"}</div>
                                                    <div className="text-sm font-bold text-gray-900 dark:text-white">{row.mobile || "—"}</div>
                                                </td>
                                                <td className="px-2 py-3 text-base text-gray-700 dark:text-gray-200 break-words" title={row.dealer_name}>{row.dealer_name || "—"}</td>
                                                <td className="px-2 py-3 text-base font-mono text-gray-700 dark:text-gray-200 break-words" title={row.service_request_number}>{row.service_request_number || "—"}</td>
                                                <td className="px-2 py-3 text-base text-gray-700 dark:text-gray-200 break-words">{row.asc_name || "—"}</td>

                                                {/* Installation Status */}
                                                <td className="px-2 py-3 text-sm text-gray-900 dark:text-white break-words">
                                                    {editing ? (
                                                        <input value={edit.draft.installation_status}
                                                            onChange={e => setEdit({ ...edit, draft: { ...edit.draft, installation_status: e.target.value } })}
                                                            className="w-full px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700" />
                                                    ) : (row.installation_status || "—")}
                                                </td>

                                                {/* Remarks */}
                                                <td className="px-2 py-3 text-sm text-gray-600 dark:text-gray-300 break-words">
                                                    {editing ? (
                                                        <input value={edit.draft.remarks}
                                                            onChange={e => setEdit({ ...edit, draft: { ...edit.draft, remarks: e.target.value } })}
                                                            className="w-full px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700" />
                                                    ) : <span className="break-words">{row.remarks || "—"}</span>}
                                                </td>

                                                {/* Sentiment */}
                                                <td className="px-2 py-3 text-sm truncate">
                                                    {editing ? (
                                                        <input value={edit.draft.sentiment}
                                                            onChange={e => setEdit({ ...edit, draft: { ...edit.draft, sentiment: e.target.value } })}
                                                            className="w-24 px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700" />
                                                    ) : (
                                                        <span className={`font-medium ${SENTIMENT_COLOR[(row.sentiment || "").toLowerCase()] || "text-gray-500 dark:text-gray-400"}`}>
                                                            {row.sentiment || "—"}
                                                        </span>
                                                    )}
                                                </td>

                                                {/* Disposition — fixed width via colgroup, wraps instead of overflowing/shifting other columns */}
                                                <td className="px-2 py-3 text-sm break-words">
                                                    {editing ? (
                                                        <select value={edit.draft.disposition || ""}
                                                            onChange={e => setEdit({ ...edit, draft: { ...edit.draft, disposition: e.target.value } })}
                                                            className="w-full px-2 py-1 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-700">
                                                            <option value="">—</option>
                                                            {DISPOSITIONS.map(d => <option key={d} value={d}>{d}</option>)}
                                                        </select>
                                                    ) : (
                                                        row.disposition
                                                            ? <span className="font-medium text-blue-700 dark:text-blue-300 break-words">{row.disposition}</span>
                                                            : <span className="text-gray-400 dark:text-gray-500">—</span>
                                                    )}
                                                </td>

                                                {/* Call status */}
                                                <td className="px-2 py-3 truncate">
                                                    <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLOR[row.call_status] || STATUS_COLOR.pending}`}>
                                                        {row.call_status || "pending"}
                                                    </span>
                                                    {row.called_by === "VoiceBOT" && (
                                                        <div className="text-[10px] text-red-500 dark:text-red-400 mt-0.5">Voice BOT</div>
                                                    )}
                                                    {row.campaign_db_id && (
                                                        <div className="text-[10px] text-purple-600 dark:text-purple-400 mt-0.5" title={`Called via campaign #${row.campaign_db_id}`}>📢 Campaign</div>
                                                    )}
                                                </td>

                                                {/* Actions */}
                                                <td className="px-2 py-3">
                                                    <div className="flex flex-wrap items-center gap-1">
                                                        {editing ? (
                                                            <>
                                                                <button onClick={saveEdit} title="Save"
                                                                    className="p-1.5 rounded text-green-600 hover:bg-green-50 dark:hover:bg-green-900/30"><Check className="h-4 w-4" /></button>
                                                                <button onClick={cancelEdit} title="Cancel"
                                                                    className="p-1.5 rounded text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700"><X className="h-4 w-4" /></button>
                                                            </>
                                                        ) : (
                                                            <>
                                                                <button onClick={() => handleCall(row)}
                                                                    disabled={["calling", "initiated", "connected"].includes(row.call_status) || !row.mobile}
                                                                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                                                                    <Phone className="h-3 w-3" />
                                                                    {row.call_status === "calling" ? "Calling…" :
                                                                        row.call_status === "initiated" ? "Initiated" :
                                                                            row.call_status === "connected" ? "Connected…" :
                                                                                ["completed", "not_connected"].includes(row.call_status) ? "Retry Call" :
                                                                                    "Call"}
                                                                </button>
                                                                <button onClick={() => startEdit(row)} title="Edit row"
                                                                    className="p-1.5 rounded text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700"><Pencil className="h-4 w-4" /></button>
                                                            </>
                                                        )}
                                                    </div>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>

                {/* PAGINATION */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-4">
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                            Showing {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length}
                        </p>
                        <div className="flex items-center gap-2">
                            <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage === 1}
                                className="p-1.5 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                                <ChevronLeft className="h-4 w-4" />
                            </button>
                            <span className="text-sm text-gray-700 dark:text-gray-300">{safePage} / {totalPages}</span>
                            <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage === totalPages}
                                className="p-1.5 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
                                <ChevronRight className="h-4 w-4" />
                            </button>
                        </div>
                    </div>
                )}
            </div>

            <footer className="w-full py-4 text-center border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                <div className="flex justify-center items-center space-x-2 text-gray-600 dark:text-gray-300 text-sm">
                    <span>Powered by</span>
                    <a href="https://www.botrixai.com/" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2">
                        <img src="/botrixai_logo.png" className="h-10 object-contain dark:hidden" alt="BotrixAI" />
                        <img src="/botrixai_logo_dark.png" className="h-10 object-contain hidden dark:block" alt="BotrixAI" />
                    </a>
                </div>
            </footer>

            {/* Floating toast — fixed overlay, never affects page layout */}
            {msg && (
                <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg text-white text-sm font-medium max-w-sm
                    ${msg.type === "error" ? "bg-red-500" : "bg-green-500"}`}>
                    {msg.text}
                </div>
            )}
        </div>
    );
}
