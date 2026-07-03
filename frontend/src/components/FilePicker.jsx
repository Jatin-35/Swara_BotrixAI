import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { Trash2, ChevronDown, RefreshCw } from "lucide-react";
import { deleteLeadFile } from "../utils/api";

// Upload-history label: "<date> (<day>) <time> · <name> · <rows>" pinned to IST
export function fileLabel(f) {
  if (!f) return "";
  const IST = "Asia/Kolkata";
  const d = new Date(f.uploaded_at);
  const date = d.toLocaleDateString("en-IN", { timeZone: IST });
  const time = d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: true });
  return `${date} (${f.day_of_week}) ${time} · ${f.original_name} · ${f.row_count} rows`;
}

/**
 * Custom file picker with a 🗑 per row (soft-delete). The open list is rendered
 * in a PORTAL and floats over the page — it never pushes other elements and is
 * never clipped by a scrollable modal (works identically on the Leads toolbar
 * and inside the Start-Campaign modal). Delete is confirmed by typing "delete";
 * the file is only hidden from the dropdown (kept in the DB).
 *
 *   files     : array of file objects
 *   value     : selected file id (number|null)
 *   onChange  : (id) => void          when a file is picked
 *   onDeleted : (deletedId) => void   after a successful soft-delete
 */
export default function FilePicker({ files, value, onChange, onDeleted, placeholder = "No files uploaded yet" }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);            // {top,left,width} for the floating list
  const [pending, setPending] = useState(null);    // file pending deletion
  const [text, setText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [err, setErr] = useState("");
  const btnRef = useRef(null);
  const panelRef = useRef(null);

  const selected = files.find(f => f.id === value) || null;

  // Position the floating list under the button; keep it aligned on scroll/resize.
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const r = btnRef.current?.getBoundingClientRect();
      if (r) setPos({ top: r.bottom + 4, left: r.left, width: r.width });
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  // Close on outside click (button and portal panel both count as "inside").
  useEffect(() => {
    function onDoc(e) {
      if (btnRef.current?.contains(e.target)) return;
      if (panelRef.current?.contains(e.target)) return;
      setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function doDelete() {
    if (!pending || text.trim().toLowerCase() !== "delete") return;
    setDeleting(true); setErr("");
    try {
      const res = await deleteLeadFile(pending.id);
      if (res.success) {
        const id = pending.id;
        const label = fileLabel(pending);
        setPending(null); setText(""); setOpen(false);
        onDeleted && onDeleted(id, label);
      } else {
        setErr(res.error || "Delete failed");
      }
    } catch (e) {
      setErr(e.message || "Delete failed");
    } finally { setDeleting(false); }
  }

  return (
    <>
      {/* selected value / toggle */}
      <button type="button" ref={btnRef} onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500">
        <span className="truncate text-left">{selected ? fileLabel(selected) : placeholder}</span>
        <ChevronDown className={`h-4 w-4 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {/* floating list (portal → never clipped, never pushes layout) */}
      {open && pos && createPortal(
        <div ref={panelRef}
          style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width, zIndex: 70 }}
          className="max-h-72 overflow-auto rounded-md border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 shadow-lg divide-y divide-gray-100 dark:divide-gray-600">
          {files.length === 0 && <div className="px-3 py-2 text-sm text-gray-400">{placeholder}</div>}
          {files.map(f => (
            <div key={f.id} title={fileLabel(f)}
              className={`flex items-center justify-between gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-600 ${f.id === value ? "bg-blue-50 dark:bg-blue-900/30" : ""}`}
              onClick={() => { onChange(f.id); setOpen(false); }}>
              <span className="truncate text-gray-800 dark:text-gray-100">{fileLabel(f)}</span>
              <button type="button" title="Remove this file from the list (data is kept)"
                onClick={e => { e.stopPropagation(); setErr(""); setText(""); setPending(f); setOpen(false); }}
                className="shrink-0 p-1 rounded text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30">
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}

      {/* type-to-confirm delete modal (portal → above everything) */}
      {pending && createPortal(
        <div className="fixed inset-0 z-[80] bg-black/50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h3 className="text-base font-bold text-gray-900 dark:text-white">Remove calling list?</h3>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              This removes <span className="font-semibold text-gray-900 dark:text-white break-words">{fileLabel(pending)}</span> from
              the dropdown. It stays in the database — campaign history, Excel downloads and all row data are kept — it just won't show in the list.
            </p>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Type <span className="font-mono font-semibold text-red-600 dark:text-red-400">delete</span> to confirm.
            </p>
            <input autoFocus value={text} placeholder="delete"
              onChange={e => setText(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") doDelete(); }}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500" />
            {err && <p className="text-xs text-red-600 dark:text-red-400">{err}</p>}
            <div className="flex gap-3">
              <button onClick={doDelete} disabled={deleting || text.trim().toLowerCase() !== "delete"}
                className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-sm rounded-md font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                {deleting ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />} Delete
              </button>
              <button onClick={() => { setPending(null); setText(""); setErr(""); }}
                className="flex-1 px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm rounded-md font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
                Cancel
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
