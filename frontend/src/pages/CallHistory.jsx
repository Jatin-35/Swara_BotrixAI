import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import useAppStore from "../store/useAppStore";
import { fetchExportData } from "../utils/api";
import ThemeToggle from "../components/ThemeToggle";
import CustomDialer from "../components/CustomDialer";
import { RefreshCw, ArrowLeft, Phone, Clock, User, FileText, PlayCircle, ChevronLeft, ChevronRight, Search } from "lucide-react";

const PAGE_SIZE = 25;

export default function CallHistory() {
    const {
        calls,
        loading,
        lastFetchedAt,
        nextRefreshAt
    } = useAppStore(state => state.callHistory);

    const {
        fetchCallHistory,
        resetCallHistoryCountdown
    } = useAppStore(state => state);

    const [selectedSessionId, setSelectedSessionId] = useState(null);
    const [secondsLeft, setSecondsLeft] = useState(30);
    const [search, setSearch] = useState("");
    const [page, setPage] = useState(1);
    const navigate = useNavigate();

    const selectedCall = selectedSessionId
        ? calls.find((c) => c.session_id === selectedSessionId) ?? null
        : null;

    const filtered = calls.filter(c =>
        !search ||
        c.caller_name?.toLowerCase().includes(search.toLowerCase()) ||
        c.phone_number?.includes(search)
    );
    const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
    const safePage   = Math.min(page, totalPages);
    const pageCalls  = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

    // Initial load + Persistent Auto-refresh Logic
    useEffect(() => {
        // 1. Load immediately if empty
        if (calls.length === 0) {
            fetchCallHistory();
        }

        // 2. Persistent timer loop
        const interval = setInterval(() => {
            const { nextRefreshAt, loading } = useAppStore.getState().callHistory;
            if (!nextRefreshAt) return;

            const now = Date.now();
            const diff = Math.ceil((nextRefreshAt - now) / 1000);
            setSecondsLeft(Math.max(0, diff));

            // Auto-refresh when time is up
            if (diff <= 0 && !loading && !document.hidden) {
                console.log("⏰ Persistent auto-refresh triggered");
                fetchCallHistory(true); // silent refresh
                resetCallHistoryCountdown();
            }
        }, 1000);

        return () => clearInterval(interval);
    }, []);

    const handleManualRefresh = () => {
        fetchCallHistory();
        resetCallHistoryCountdown();
    };

    const handleLogout = () => {
        localStorage.removeItem("auth");
        navigate("/login", { replace: true });
    };

    const viewTranscript = (call) => {
        setSelectedSessionId(call.session_id);
    };

    const closeModal = () => {
        setSelectedSessionId(null);
    };

    return (
        <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-900 transition-colors">
            {/* HEADER */}
            <div className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between items-center py-4">
                        <div className="flex items-center space-x-3">
                            <button
                                onClick={() => navigate("/dashboard")}
                                className="p-2 rounded-md text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:text-gray-400 dark:hover:text-gray-200 dark:hover:bg-gray-700 transition-colors"
                                title="Back to Dashboard"
                            >
                                <ArrowLeft className="h-5 w-5" />
                            </button>
                            <a href="https://www.ailifebot.com/" className="flex items-center gap-2">
                                <img src="/logo.png" alt="AI LifeBOT Logo" className="h-8 w-auto object-contain cursor-pointer" />
                            </a>
                            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                                Call History & Transcriptions
                            </h1>
                        </div>

                        <div className="flex items-center space-x-3">
                            <ThemeToggle />
                            <button onClick={handleLogout} className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500 transition-colors">
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* MAIN CONTENT */}
            <div className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full">
                {/* CUSTOM DIALER */}
                <CustomDialer />

                <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm p-6 mb-8 border border-gray-200 dark:border-gray-700">
                    <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
                        <div className="flex items-center space-x-4">
                            <Phone className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                            <div>
                                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                                    All Call Records
                                </h2>
                                <p className="text-sm text-gray-500 dark:text-gray-400">
                                    View transcriptions, recordings, and call details
                                </p>
                            </div>
                        </div>

                        <button
                            onClick={handleManualRefresh}
                            disabled={loading}
                            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
                            {loading ? "Refreshing..." : `Refresh (${secondsLeft}s)`}
                        </button>
                    </div>
                </div>

                {/* SEARCH */}
                <div className="mb-4 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
                    <input
                        type="text"
                        placeholder="Search by name or phone…"
                        value={search}
                        onChange={e => { setSearch(e.target.value); setPage(1); }}
                        className="w-full pl-9 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                </div>

                {/* CALLS TABLE */}
                <div className="bg-white dark:bg-gray-900 shadow-sm rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
                    <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                            <thead className="bg-gray-50 dark:bg-gray-800">
                                <tr>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                        Date & Time
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                        Contact
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                        Duration
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                        Status
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider w-48">
                                        Install / Disposition
                                    </th>
                                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                                        Actions
                                    </th>
                                </tr>
                            </thead>
                            <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                                {pageCalls.length === 0 && !loading && (
                                    <tr>
                                        <td colSpan="7" className="px-6 py-12 text-center text-gray-500 dark:text-gray-400">
                                            {search ? "No results match your search." : "No call records found"}
                                        </td>
                                    </tr>
                                )}
                                {pageCalls.map((call) => (
                                    <tr key={call.session_id} className="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex items-center gap-2">
                                                <Clock className="h-4 w-4 text-gray-400 shrink-0" />
                                                {call.started_at ? (
                                                    <div className="text-sm text-gray-900 dark:text-white">
                                                        <div>{new Date(call.started_at).toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: '2-digit', year: 'numeric' })},</div>
                                                        <div className="text-xs text-gray-500 dark:text-gray-400">{new Date(call.started_at).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true }).toUpperCase()}</div>
                                                    </div>
                                                ) : (
                                                    <div className="text-sm text-gray-900 dark:text-white">N/A</div>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 max-w-[260px]">
                                            <div className="flex items-start gap-2">
                                                <User className="h-4 w-4 text-gray-400 mt-0.5 shrink-0" />
                                                <div className="min-w-0">
                                                    <div className="text-sm font-medium text-gray-900 dark:text-white break-words line-clamp-3">
                                                        {call.caller_name || "Unknown"}
                                                    </div>
                                                    <div className="text-sm text-gray-500 dark:text-gray-400 whitespace-nowrap">
                                                        {call.phone_number}
                                                    </div>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                            {call.call_duration_seconds ? `${Math.floor(call.call_duration_seconds / 60)}m ${call.call_duration_seconds % 60}s` : call.recording_duration_seconds ? `${Math.floor(call.recording_duration_seconds / 60)}m ${call.recording_duration_seconds % 60}s` : "N/A"}
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap">
                                            <div className="flex flex-col items-start gap-1">
                                                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${call.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' :
                                                        call.status === 'not_connected' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' :
                                                            call.status === 'in_progress' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300' :
                                                                call.status === 'initiated' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300' :
                                                                    'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                                                    }`}>
                                                    {call.status === 'not_connected' ? (call.cube_status_raw ? `No Answer: ${call.cube_status_raw}` : 'No Answer') : call.status?.toUpperCase() || 'COMPLETED'}
                                                </span>
                                                {call.campaign_db_id && (
                                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300" title={`Called via campaign #${call.campaign_db_id}`}>
                                                        📢 Campaign
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        {/* INSTALL STATUS + DISPOSITION COLUMN — fixed width so long text never shifts other columns */}
                                        <td className="px-6 py-4 w-48 max-w-[12rem]">
                                            <div className="flex flex-col gap-0.5">
                                                {call.installation_status && (
                                                    <span className="text-xs text-gray-500 dark:text-gray-400 break-words" title="Installation status from the Swara calling list">
                                                        Install: <span className="font-medium text-gray-700 dark:text-gray-200">{call.installation_status}</span>
                                                    </span>
                                                )}
                                                {call.disposition && (
                                                    <span className="text-xs text-gray-500 dark:text-gray-400 break-words" title="Call disposition">
                                                        Disposition: <span className="font-medium text-blue-700 dark:text-blue-300">{call.disposition}</span>
                                                    </span>
                                                )}
                                                {!call.installation_status && !call.disposition && (
                                                    <span className="text-xs text-gray-400 dark:text-gray-500">—</span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium space-x-2">
                                            <button
                                                onClick={() => viewTranscript(call)}
                                                className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-900 dark:text-blue-400 dark:hover:text-blue-300"
                                            >
                                                <FileText className="h-4 w-4" />
                                                Transcript
                                            </button>
                                            {call.recording_url && (
                                                <a
                                                    href={call.recording_url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="inline-flex items-center gap-1 text-green-600 hover:text-green-900 dark:text-green-400 dark:hover:text-green-300"
                                                    title={call.recording_duration_seconds ? `Recording duration: ${Math.floor(call.recording_duration_seconds / 60)}m ${call.recording_duration_seconds % 60}s` : 'Play recording'}
                                                >
                                                    <PlayCircle className="h-4 w-4" />
                                                    Recording
                                                    {call.recording_duration_seconds && (
                                                        <span className="text-xs ml-1">
                                                            ({Math.floor(call.recording_duration_seconds / 60)}m {call.recording_duration_seconds % 60}s)
                                                        </span>
                                                    )}
                                                </a>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                {/* PAGINATION */}
                {totalPages > 1 && (
                    <div className="flex items-center justify-between mt-4">
                        <p className="text-sm text-gray-500 dark:text-gray-400">
                            Showing {(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length} calls
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

            {/* TRANSCRIPT MODAL */}
            {selectedCall && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50" onClick={closeModal}>
                    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] overflow-hidden" onClick={(e) => e.stopPropagation()}>
                        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                                Call Transcript - {selectedCall.caller_name || "Unknown"}
                            </h3>
                            <button
                                onClick={closeModal}
                                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                            >
                                ✕
                            </button>
                        </div>
                        <div className="px-6 py-4 overflow-y-auto max-h-[60vh]">
                            <div className="space-y-4">
                                <div className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                                    <p><strong>Date:</strong> {selectedCall.started_at ? new Date(selectedCall.started_at).toLocaleString() : 'N/A'}</p>
                                    <p><strong>Phone:</strong> {selectedCall.phone_number}</p>
                                    <p><strong>Duration:</strong> {(() => { const secs = selectedCall.call_duration_seconds ?? selectedCall.recording_duration_seconds ?? selectedCall.duration_seconds; if (!secs) return "N/A"; return `${Math.floor(secs / 60)}m ${secs % 60}s`; })()}</p>
                                    <p><strong>Status:</strong> {selectedCall.status?.toUpperCase() || 'N/A'}</p>
                                    {selectedCall.caller_name && <p><strong>Name:</strong> {selectedCall.caller_name}</p>}
                                    {selectedCall.firm_name && <p><strong>Company:</strong> {selectedCall.firm_name}</p>}
                                    {selectedCall.installation_status && <p><strong>Installation:</strong> {selectedCall.installation_status}</p>}
                                    {selectedCall.disposition && <p><strong>Disposition:</strong> {selectedCall.disposition}</p>}
                                    {selectedCall.recording_url && (
                                        <p>
                                            <strong>Recording:</strong>{' '}
                                            <a
                                                href={selectedCall.recording_url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-green-600 hover:text-green-900 dark:text-green-400 dark:hover:text-green-300 inline-flex items-center gap-1"
                                            >
                                                <PlayCircle className="h-4 w-4" />
                                                Play Recording
                                                {selectedCall.recording_duration_seconds && (
                                                    <span className="text-xs ml-1">
                                                        ({Math.floor(selectedCall.recording_duration_seconds / 60)}m {selectedCall.recording_duration_seconds % 60}s)
                                                    </span>
                                                )}
                                            </a>
                                        </p>
                                    )}
                                </div>
                                <div className="bg-gray-50 dark:bg-gray-900 rounded-lg p-4">
                                    <pre className="whitespace-pre-wrap text-sm text-gray-900 dark:text-white font-mono">
                                        {selectedCall.transcript || "No transcript available"}
                                    </pre>
                                </div>
                            </div>
                        </div>
                        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
                            <button
                                onClick={closeModal}
                                className="px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded-md hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* FOOTER */}
            <footer className="w-full py-4 text-center border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
                <div className="flex justify-center items-center space-x-2 text-gray-600 dark:text-gray-300 text-sm">
                    <span>Powered by</span>
                    <a href="https://www.ailifebot.com/" className="flex items-center gap-2">
                        <img src="/ailifebot_logo.png" className="h-5 object-contain" alt="AI LifeBOT Logo" />
                    </a>
                </div>
            </footer>
        </div>
    );
}
