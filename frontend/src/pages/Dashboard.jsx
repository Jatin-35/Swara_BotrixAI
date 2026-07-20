import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import useAppStore from "../store/useAppStore";
import { fetchExportData } from "../utils/api";
import SessionsTable from "../components/SessionsTable";
import TranscriptsTable from "../components/TranscriptsTable";
import DashboardStats from "../components/DashboardStats";
import CallAnalytics from "../components/CallAnalytics";
import InsightsPanel from "../components/InsightsPanel";
import ThemeToggle from "../components/ThemeToggle";
import CustomDialer from "../components/CustomDialer";
import { Calendar, Download, RefreshCw, BarChart3 } from "lucide-react";


export default function Dashboard() {
  // Select state from the dashboard slice
  const {
    data,
    loading,
    error,
    dateFrom,
    dateTo,
    campaigns,
    selectedCampaignId,
    callScope
  } = useAppStore(state => state.dashboard);

  // Select actions from the root store
  const {
    setDashboardDateFrom,
    setDashboardDateTo,
    setDashboardSelectedCampaignId,
    setDashboardCallScope,
    fetchCampaignList,
    fetchDashboardData
  } = useAppStore(state => state);

  const [activeTab, setActiveTab] = useState("overview");
  const navigate = useNavigate();

  // Load data on mount ONLY if not already loaded (persisted)
  useEffect(() => {
    if (!data) {
      fetchDashboardData();
    }
    fetchCampaignList();
  }, []);

  const handleCampaignChange = (e) => {
    const value = e.target.value;
    setDashboardSelectedCampaignId(value ? Number(value) : null);
  };

  const handleFetch = () => {
    fetchDashboardData();
  };

  const handleLogout = () => {
    localStorage.removeItem("auth");
    navigate("/", { replace: true });
  };

  return (
    <div className="min-h-screen flex flex-col bg-gray-50 dark:bg-gray-900 transition-colors">
      {/* HEADER */}
      <div className="bg-white dark:bg-gray-800 shadow-sm border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">

            {/* LOGO + TITLE */}
            <div className="flex items-center space-x-3">
              <a href="https://www.botrixai.com/" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2">
                <img
                  src="/header_logo.png"
                  alt="Logo"
                  className="h-8 w-auto object-contain cursor-pointer"
                />
              </a>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                Outbound Announcement Analytics
              </h1>
            </div>

            {/* THEME + LOGOUT */}
            <div className="flex items-center space-x-3">
              <button
                onClick={() => navigate("/call-history")}
                className="
                  inline-flex items-center px-4 py-2 
                  text-sm font-medium 
                  text-green-700 dark:text-green-400 
                  bg-green-50 dark:bg-green-900/30 
                  border border-green-200 dark:border-green-700 
                  rounded-md 
                  hover:bg-green-100 dark:hover:bg-green-900/50 
                  focus:outline-none focus:ring-2 focus:ring-green-500 
                  transition-colors
                "
              >
                <svg className="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                </svg>
                Call History
              </button>
              <button
                onClick={() => navigate("/leads")}
                className="
                  inline-flex items-center px-4 py-2
                  text-sm font-medium
                  text-blue-700 dark:text-blue-400
                  bg-blue-50 dark:bg-blue-900/30
                  border border-blue-200 dark:border-blue-700
                  rounded-md
                  hover:bg-blue-100 dark:hover:bg-blue-900/50
                  focus:outline-none focus:ring-2 focus:ring-blue-500
                  transition-colors
                "
              >
                <svg className="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
                Follow Up Leads
              </button>
              <button
                onClick={() => navigate("/campaign")}
                className="
                  inline-flex items-center px-4 py-2
                  text-sm font-medium
                  text-purple-700 dark:text-purple-400
                  bg-purple-50 dark:bg-purple-900/30
                  border border-purple-200 dark:border-purple-700
                  rounded-md
                  hover:bg-purple-100 dark:hover:bg-purple-900/50
                  focus:outline-none focus:ring-2 focus:ring-purple-500
                  transition-colors
                "
              >
                <svg className="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z" />
                </svg>
                Campaign
              </button>
              <ThemeToggle />
              <button
                onClick={handleLogout}
                className="
                  px-4 py-2 text-sm font-medium 
                  text-gray-700 dark:text-gray-200 
                  bg-white dark:bg-gray-700 
                  border border-gray-300 dark:border-gray-600 
                  rounded-md 
                  hover:bg-gray-50 dark:hover:bg-gray-600 
                  focus:outline-none focus:ring-2 focus:ring-blue-500 
                  transition-colors
                "
              >
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

        {/* DATE FILTERS */}
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm p-6 mb-8 border border-gray-200 dark:border-gray-700">
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">

            {/* DATE PICKERS */}
            <div className="flex items-center space-x-4">
              <Calendar className="h-5 w-5 text-gray-400 dark:text-gray-500" />

              <div className="flex items-center space-x-3">

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    From
                  </label>
                  <input
                    type="date"
                    disabled={!!selectedCampaignId}
                    className="
                      border border-gray-300 dark:border-gray-600
                      rounded-md px-3 py-2 text-sm
                      bg-white dark:bg-gray-700
                      text-gray-900 dark:text-white
                      focus:outline-none focus:ring-2 focus:ring-blue-500
                      disabled:opacity-50 disabled:cursor-not-allowed
                    "
                    value={dateFrom}
                    onChange={(e) => setDashboardDateFrom(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    To
                  </label>
                  <input
                    type="date"
                    disabled={!!selectedCampaignId}
                    className="
                      border border-gray-300 dark:border-gray-600
                      rounded-md px-3 py-2 text-sm
                      bg-white dark:bg-gray-700
                      text-gray-900 dark:text-white
                      focus:outline-none focus:ring-2 focus:ring-blue-500
                      disabled:opacity-50 disabled:cursor-not-allowed
                    "
                    value={dateTo}
                    onChange={(e) => setDashboardDateTo(e.target.value)}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Call Type
                  </label>
                  <div className="inline-flex rounded-md border border-gray-300 dark:border-gray-600 overflow-hidden">
                    {[
                      { id: "both", label: "Both" },
                      { id: "campaign", label: "Campaign Only" },
                      { id: "normal", label: "Normal" },
                    ].map((opt, i) => (
                      <button
                        key={opt.id}
                        type="button"
                        disabled={!!selectedCampaignId}
                        onClick={() => setDashboardCallScope(opt.id)}
                        className={`
                          px-3 py-2 text-sm font-medium transition-colors
                          ${i > 0 ? "border-l border-gray-300 dark:border-gray-600" : ""}
                          ${callScope === opt.id
                            ? "bg-blue-600 text-white dark:bg-blue-500"
                            : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600"
                          }
                          disabled:opacity-50 disabled:cursor-not-allowed
                        `}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Campaign Run
                  </label>
                  <select
                    className="
                      border border-gray-300 dark:border-gray-600
                      rounded-md px-3 py-2 text-sm
                      bg-white dark:bg-gray-700
                      text-gray-900 dark:text-white
                      focus:outline-none focus:ring-2 focus:ring-blue-500
                      max-w-[220px]
                    "
                    value={selectedCampaignId ?? ""}
                    onChange={handleCampaignChange}
                  >
                    <option value="">All (date range)</option>
                    {campaigns.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name} — {c.started_at ? new Date(c.started_at).toLocaleDateString() : ""}
                      </option>
                    ))}
                  </select>
                </div>

              </div>
            </div>

            {/* FETCH BUTTON */}
            <div className="flex space-x-3">
              <button
                onClick={handleFetch}
                disabled={loading}
                className="
                  inline-flex items-center px-4 py-2 
                  border border-transparent 
                  text-sm font-medium rounded-md 
                  text-white 
                  bg-blue-600 hover:bg-blue-700 
                  dark:bg-blue-500 dark:hover:bg-blue-600 
                  focus:outline-none focus:ring-2 focus:ring-blue-500 
                  disabled:opacity-50 disabled:cursor-not-allowed 
                  transition-colors
                "
              >
                {loading ? (
                  <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Download className="h-4 w-4 mr-2" />
                )}
                {loading ? "Loading..." : "Fetch Data"}
              </button>
            </div>

          </div>
        </div>

        {/* LOADING */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="flex items-center space-x-3">
              <RefreshCw className="h-6 w-6 animate-spin text-blue-600 dark:text-blue-400" />
              <span className="text-lg text-gray-600 dark:text-gray-300">
                Loading analytics data...
              </span>
            </div>
          </div>
        )}

        {/* ERROR */}
        {error && !loading && (
          <div className="flex items-center justify-center py-12">
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 max-w-md">
              <div className="flex items-start space-x-3">
                <svg className="h-6 w-6 text-red-600 dark:text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                  <h3 className="text-sm font-medium text-red-800 dark:text-red-200">
                    Error loading data
                  </h3>
                  <p className="mt-1 text-sm text-red-700 dark:text-red-300">
                    {error}
                  </p>
                  <button
                    onClick={handleFetch}
                    className="mt-3 text-sm font-medium text-red-600 dark:text-red-400 hover:text-red-500 dark:hover:text-red-300"
                  >
                    Try again
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* CONTENT */}
        {data && !loading && !error && (
          <>
            <DashboardStats data={data} />

            <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm mb-8 border border-gray-200 dark:border-gray-700">

              <div className="border-b border-gray-200 dark:border-gray-700">
                <nav className="-mb-px flex space-x-8 px-6">

                  {[
                    { id: "overview", label: "Analytics Overview" },
                    { id: "insights", label: "Key Insights" },
                    { id: "sessions", label: "Call Sessions" },
                    { id: "transcripts", label: "Transcripts" }
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      className={`
                        py-4 px-1 border-b-2 font-medium text-sm transition-colors
                        ${activeTab === tab.id
                          ? "border-blue-500 text-blue-600 dark:text-blue-400"
                          : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:border-gray-300 dark:hover:border-gray-600"
                        }
                      `}
                    >
                      {tab.label}
                    </button>
                  ))}

                </nav>
              </div>

              <div className="p-6">
                {activeTab === "overview" && <CallAnalytics data={data} />}
                {activeTab === "insights" && <InsightsPanel data={data} />}
                {activeTab === "sessions" && (
                  <SessionsTable sessions={data.data.call_sessions} />
                )}
                {activeTab === "transcripts" && (
                  <TranscriptsTable transcripts={data.data.transcripts} />
                )}
              </div>
            </div>
          </>
        )}

        {/* EMPTY STATE */}
        {!data && !loading && (
          <div className="text-center py-12">
            <BarChart3 className="mx-auto h-12 w-12 text-gray-400 dark:text-gray-500" />
            <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">
              No data loaded
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
              Select a date range and click "Fetch Data" to view analytics
            </p>
          </div>
        )}

      </div>

      {/* FOOTER */}
      <footer className="w-full py-4 text-center border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="flex justify-center items-center space-x-2 text-gray-600 dark:text-gray-300 text-sm">
          <span>Powered by</span>
          <a href="https://www.botrixai.com/" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2">
            <img src="/botrixai_logo.png" className="h-10 object-contain dark:hidden" alt="BotrixAI Logo" />
            <img src="/botrixai_logo_dark.png" className="h-10 object-contain hidden dark:block" alt="BotrixAI Logo" />
          </a>
        </div>
      </footer>

    </div>
  );
}
