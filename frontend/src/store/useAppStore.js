/**
 * Global Zustand store — persists data across page navigation.
 *
 * Why: Each page (Dashboard, CallHistory, Leads) previously used local
 * useState, which gets destroyed when React unmounts the component on
 * navigation. This store lives outside the component tree so data
 * survives route changes.
 *
 * Slices:
 *  - dashboard  → fetched analytics data + date range
 *  - callHistory → call list + auto-refresh metadata
 *  - leads      → leads list + sync state
 */

import { create } from "zustand";
import { fetchExportData, fetchLeads, refreshLeads, campaignHistory } from "../utils/api";

const useAppStore = create((set, get) => ({

    // ─────────────────────────────────────────────
    // DASHBOARD SLICE
    // ─────────────────────────────────────────────
    dashboard: {
        data: null,
        loading: false,
        error: null,
        dateFrom: (() => {
            const today = new Date();
            const start = new Date(today.getFullYear(), today.getMonth(), 1);
            return start.toISOString().split("T")[0];
        })(),
        dateTo: new Date().toISOString().split("T")[0],
        lastFetchedAt: null,
        campaigns: [],
        selectedCampaignId: null,
    },

    setDashboardDateFrom: (dateFrom) =>
        set((s) => ({ dashboard: { ...s.dashboard, dateFrom } })),

    setDashboardDateTo: (dateTo) =>
        set((s) => ({ dashboard: { ...s.dashboard, dateTo } })),

    // Selecting a campaign overrides the date range for the next fetch; clearing
    // it (null) reverts to date-range mode.
    setDashboardSelectedCampaignId: (selectedCampaignId) =>
        set((s) => ({ dashboard: { ...s.dashboard, selectedCampaignId } })),

    fetchCampaignList: async () => {
        try {
            const result = await campaignHistory();
            if (result?.campaigns) {
                set((s) => ({ dashboard: { ...s.dashboard, campaigns: result.campaigns } }));
            }
        } catch (err) {
            console.error("❌ fetchCampaignList error:", err);
        }
    },

    fetchDashboardData: async () => {
        const { dashboard } = get();
        console.log("🚀 fetchDashboardData started", {
            from: dashboard.dateFrom,
            to: dashboard.dateTo,
            campaignId: dashboard.selectedCampaignId
        });

        set((s) => ({ dashboard: { ...s.dashboard, loading: true, error: null } }));
        try {
            const result = await fetchExportData(dashboard.dateFrom, dashboard.dateTo, dashboard.selectedCampaignId);
            console.log("✅ fetchDashboardData result:", result);

            if (!result) throw new Error("No data returned from server");

            set((s) => ({
                dashboard: {
                    ...s.dashboard,
                    data: result,
                    loading: false,
                    lastFetchedAt: Date.now(),
                },
            }));
        } catch (err) {
            console.error("❌ fetchDashboardData error:", err);
            set((s) => ({
                dashboard: {
                    ...s.dashboard,
                    loading: false,
                    error: err.message || "Failed to fetch data",
                    data: null,
                },
            }));
        }
    },

    // ─────────────────────────────────────────────
    // CALL HISTORY SLICE
    // ─────────────────────────────────────────────
    callHistory: {
        calls: [],
        loading: false,
        lastFetchedAt: null,
        // Timestamp for next refresh
        nextRefreshAt: Date.now() + 30000,
    },

    fetchCallHistory: async (silent = false) => {
        if (!silent) {
            set((s) => ({ callHistory: { ...s.callHistory, loading: true } }));
        }
        try {
            const result = await fetchExportData("2020-01-01", "2030-12-31");
            if (result?.data?.call_sessions) {
                const transcripts = result.data.transcripts || [];
                const transcriptMap = {};
                transcripts.forEach((t) => { transcriptMap[t.call_id] = t.transcript; });

                const callsWithTranscripts = result.data.call_sessions.map((call) => ({
                    ...call,
                    transcript: transcriptMap[call.session_id] || null,
                }));

                set((s) => ({
                    callHistory: {
                        ...s.callHistory,
                        calls: callsWithTranscripts,
                        loading: false,
                        lastFetchedAt: Date.now(),
                        nextRefreshAt: Date.now() + 30000,
                    },
                }));
            } else {
                set((s) => ({ callHistory: { ...s.callHistory, loading: false } }));
            }
        } catch (err) {
            console.error("Error fetching call history:", err);
            set((s) => ({ callHistory: { ...s.callHistory, loading: false } }));
        }
    },

    resetCallHistoryCountdown: () => {
        set((s) => ({ callHistory: { ...s.callHistory, nextRefreshAt: Date.now() + 30000 } }));
    },

    // ─────────────────────────────────────────────
    // LEADS SLICE
    // ─────────────────────────────────────────────
    leads: {
        items: [],
        loading: false,
        syncing: false,
        autoRefreshing: false,
        lastRefresh: null,
        syncDate: "",
        // Restore last-used date filter from localStorage (survives page refresh)
        activeFilterDate: localStorage.getItem('leads_activeFilterDate') || null,
    },

    setLeadsSyncDate: (syncDate) =>
        set((s) => ({ leads: { ...s.leads, syncDate } })),

    // Optimistic update for a single lead's status (e.g. 'calling' → 'initiated')
    updateLeadStatus: (leadId, status) =>
        set((s) => ({
            leads: {
                ...s.leads,
                items: s.leads.items.map((l) =>
                    l.id === leadId ? { ...l, status } : l
                ),
            },
        })),

    fetchLeadsData: async (isAutoRefresh = false, dateFilter = undefined) => {
        const { leads } = get();
        // Resolve which date filter to use
        const filterToUse =
            dateFilter === undefined ? leads.activeFilterDate : dateFilter;

        if (isAutoRefresh) {
            set((s) => ({ leads: { ...s.leads, autoRefreshing: true } }));
        } else {
            set((s) => ({ leads: { ...s.leads, loading: true } }));
        }

        try {
            const result = await fetchLeads(filterToUse);
            if (result.success) {
                // Preserve any leads currently in an active state that the server
                // response omitted (e.g. date-filter race condition during a call).
                // Once the server returns them with a real status they will be updated.
                const currentItems = get().leads.items;
                const serverIds = new Set(result.leads.map((l) => String(l.id)));
                const activeStatuses = ['calling', 'initiated', 'connected'];
                const orphanedActive = currentItems.filter(
                    (l) => activeStatuses.includes(l.status) && !serverIds.has(String(l.id))
                );
                const mergedLeads = orphanedActive.length > 0
                    ? [...result.leads, ...orphanedActive]
                    : result.leads;

                set((s) => ({
                    leads: {
                        ...s.leads,
                        items: mergedLeads,
                        loading: false,
                        autoRefreshing: false,
                        lastRefresh: new Date(),
                    },
                }));
            } else {
                set((s) => ({
                    leads: { ...s.leads, loading: false, autoRefreshing: false },
                }));
            }
        } catch (err) {
            console.error("Error fetching leads:", err);
            set((s) => ({
                leads: { ...s.leads, loading: false, autoRefreshing: false },
            }));
        }
    },

    syncLeadsFromCRM: async () => {
        const { leads, fetchLeadsData } = get();
        const dateToSync = leads.syncDate;
        if (!dateToSync) return;

        set((s) => ({ leads: { ...s.leads, syncing: true } }));
        try {
            const result = await refreshLeads(dateToSync);
            if (result.success) {
                set((s) => ({
                    leads: {
                        ...s.leads,
                        syncing: false,
                        activeFilterDate: dateToSync,
                    },
                }));
                // Persist so auto-refresh survives page reload
                localStorage.setItem('leads_activeFilterDate', dateToSync);
                await fetchLeadsData(false, dateToSync);
            } else {
                set((s) => ({ leads: { ...s.leads, syncing: false } }));
                alert(`Sync failed: ${result.error}`);
            }
        } catch (err) {
            set((s) => ({ leads: { ...s.leads, syncing: false } }));
            alert(`Error: ${err.message}`);
        }
    },
}));

export default useAppStore;
