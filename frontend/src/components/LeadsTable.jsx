import { useState } from "react";
import { User, Phone, Tag, Building, Star, ChevronLeft, ChevronRight } from "lucide-react";

const ITEMS_PER_PAGE = 100;

export default function LeadsTable({ leads, onCallLead }) {
    const [searchTerm, setSearchTerm] = useState("");
    const [currentPage, setCurrentPage] = useState(1);
    const isInProgress = (status) => ['calling', 'initiated', 'initializing', 'initialized'].includes(status);

    if (!leads || leads.length === 0) {
        return (
            <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
                <User className="mx-auto h-12 w-12 text-gray-400" />
                <h3 className="mt-2 text-sm font-medium text-gray-900 dark:text-white">No pending leads</h3>
                <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
                    The leads queue is currently empty.
                </p>
            </div>
        );
    }

    // Search across ALL leads (not just current page)
    const filteredLeads = leads.filter(lead =>
        lead.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        lead.phone_number?.includes(searchTerm)
    );

    const totalPages = Math.ceil(filteredLeads.length / ITEMS_PER_PAGE);
    // Reset to page 1 when search changes would be handled via useEffect,
    // but clamping is enough here to avoid blank pages
    const safePage = Math.min(currentPage, totalPages || 1);
    const startIdx = (safePage - 1) * ITEMS_PER_PAGE;
    const pageLeads = filteredLeads.slice(startIdx, startIdx + ITEMS_PER_PAGE);

    function handleSearch(val) {
        setSearchTerm(val);
        setCurrentPage(1); // reset to page 1 on new search
    }

    // Build page number list — show at most 7 buttons with ellipsis
    function getPageNumbers() {
        if (totalPages <= 7) return Array.from({ length: totalPages }, (_, i) => i + 1);
        if (safePage <= 4) return [1, 2, 3, 4, 5, "...", totalPages];
        if (safePage >= totalPages - 3) return [1, "...", totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
        return [1, "...", safePage - 1, safePage, safePage + 1, "...", totalPages];
    }

    return (
        <div className="space-y-4">
            {/* Header row */}
            <div className="flex items-center justify-between">
                <div>
                    <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                        Fetched Leads Queue
                    </h3>
                    <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        Showing {filteredLeads.length === 0 ? 0 : startIdx + 1}–{Math.min(startIdx + ITEMS_PER_PAGE, filteredLeads.length)} of {filteredLeads.length} leads
                        {searchTerm && ` (filtered from ${leads.length})`}
                    </p>
                </div>
                <input
                    type="text"
                    placeholder="Search leads..."
                    className="pl-3 pr-4 py-2 border border-gray-300 dark:border-gray-600 rounded-md text-sm bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500 w-64"
                    value={searchTerm}
                    onChange={(e) => handleSearch(e.target.value)}
                />
            </div>

            {/* Table */}
            <div className="bg-white dark:bg-gray-900 shadow-sm rounded-lg border border-gray-200 dark:border-gray-700">
                <div className="overflow-auto">
                    <table className="min-w-[1200px] w-full divide-y divide-gray-200 dark:divide-gray-700">
                        <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0 z-10">
                            <tr>
                                <th className="w-48 max-w-[250px] px-3 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Lead</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Type</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Details</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Status</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">CRM Date</th>
                                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white dark:bg-gray-900 divide-y divide-gray-200 dark:divide-gray-700">
                            {pageLeads.map((lead) => (
                                <tr key={lead.id} className="hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                                    {/* LEAD */}
                                    <td className="px-3 py-3 w-48 max-w-[250px]">
                                        <div className="flex items-center">
                                            <User className="h-5 w-5 text-gray-400 dark:text-gray-500 flex-shrink-0" />
                                            <div className="ml-3 overflow-hidden">
                                                <div className="text-sm font-medium text-gray-900 dark:text-white truncate" title={lead.name}>
                                                    {lead.name}
                                                </div>
                                                <div className="text-sm text-gray-500 dark:text-gray-400 truncate" title={lead.phone_number}>
                                                    {lead.phone_number}
                                                </div>
                                            </div>
                                        </div>
                                    </td>

                                    {/* TYPE */}
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="flex flex-col space-y-1">
                                            {lead.details?.customer_type && (
                                                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">
                                                    {lead.details.customer_type}
                                                </span>
                                            )}
                                            {lead.details?.lead_type && (
                                                <span className="text-xs text-gray-500">
                                                    {lead.details.lead_type}
                                                </span>
                                            )}
                                        </div>
                                    </td>

                                    {/* DETAILS */}
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <div className="text-sm text-gray-500 dark:text-gray-400 space-y-1">
                                            {lead.details?.business_vertical && (
                                                <div className="flex items-center gap-1">
                                                    <Building className="h-3 w-3" />
                                                    {lead.details.business_vertical}
                                                </div>
                                            )}
                                            {lead.details?.business_segment && (
                                                <div className="flex items-center gap-1">
                                                    <Tag className="h-3 w-3 text-purple-500" />
                                                    <span className="text-purple-600 dark:text-purple-400">{lead.details.business_segment}</span>
                                                </div>
                                            )}
                                            {lead.details?.rating && (
                                                <div className="flex items-center gap-1">
                                                    <Star className="h-3 w-3 text-yellow-500" />
                                                    {lead.details.rating}
                                                </div>
                                            )}
                                        </div>
                                    </td>

                                    {/* STATUS */}
                                    <td className="px-6 py-4 whitespace-nowrap">
                                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium
                                            ${lead.status === 'pending' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300' :
                                                lead.status === 'calling' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 animate-pulse' :
                                                    ['initiated', 'initializing', 'initialized'].includes(lead.status) ? 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300 animate-pulse' :
                                                        lead.status === 'connected' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 animate-pulse' :
                                                            lead.status === 'completed' ? 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300' :
                                                                lead.status === 'not_connected' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' :
                                                                    'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                                            }`}>
                                            {lead.status === 'pending' && '⏳ PENDING'}
                                            {lead.status === 'calling' && '📲 CALLING...'}
                                            {['initiated', 'initializing', 'initialized'].includes(lead.status) && '📞 INITIATED'}
                                            {lead.status === 'connected' && '🟢 CONNECTED'}
                                            {lead.status === 'completed' && '✅ COMPLETED'}
                                            {lead.status === 'not_connected' && '❌ NOT CONNECTED'}
                                            {!['pending', 'calling', 'initiated', 'initializing', 'initialized', 'connected', 'completed', 'not_connected'].includes(lead.status) && (lead.status?.toUpperCase() || 'PENDING')}
                                        </span>
                                    </td>

                                    {/* CRM DATE */}
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                                        {lead.details?.date_created
                                            ? new Date(lead.details.date_created).toLocaleString()
                                            : new Date(lead.created_at).toLocaleString()
                                        }
                                    </td>

                                    {/* ACTIONS */}
                                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                                        <button
                                            onClick={() => onCallLead && onCallLead(lead)}
                                            disabled={isInProgress(lead.status)}
                                            className={`inline-flex min-w-[104px] justify-center items-center px-3 py-1.5 border border-transparent text-xs font-medium rounded-md
                                                ${lead.status === 'calling'
                                                    ? 'text-white bg-blue-500 dark:bg-blue-600 cursor-not-allowed animate-pulse'
                                                    : ['initiated', 'initializing', 'initialized'].includes(lead.status)
                                                        ? 'text-white bg-orange-500 dark:bg-orange-600 cursor-not-allowed'
                                                        : 'text-white bg-green-600 hover:bg-green-700 dark:bg-green-500 dark:hover:bg-green-600 cursor-pointer'
                                                } focus:outline-none focus:ring-2 focus:ring-green-500 transition-colors`}
                                        >
                                            <Phone className="h-3 w-3 mr-1" />
                                            {lead.status === 'calling' ? 'Calling...' :
                                                ['initiated', 'initializing', 'initialized'].includes(lead.status) ? 'Initiated...' :
                                                    lead.status === 'connected' ? 'Call Again' :
                                                        lead.status === 'completed' ? 'Call Again' :
                                                            lead.status === 'not_connected' ? 'Retry Call' :
                                                                'Call'}
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between px-1">
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                        Page {safePage} of {totalPages}
                    </p>
                    <div className="flex items-center gap-1">
                        {/* Prev */}
                        <button
                            onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                            disabled={safePage === 1}
                            className="p-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronLeft className="h-4 w-4" />
                        </button>

                        {/* Page numbers */}
                        {getPageNumbers().map((page, idx) =>
                            page === "..." ? (
                                <span key={`ellipsis-${idx}`} className="px-2 text-gray-400 text-sm select-none">…</span>
                            ) : (
                                <button
                                    key={page}
                                    onClick={() => setCurrentPage(page)}
                                    className={`min-w-[32px] h-8 px-2 rounded-md text-sm font-medium border transition-colors
                                        ${safePage === page
                                            ? 'bg-blue-600 text-white border-blue-600'
                                            : 'border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
                                        }`}
                                >
                                    {page}
                                </button>
                            )
                        )}

                        {/* Next */}
                        <button
                            onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                            disabled={safePage === totalPages}
                            className="p-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            <ChevronRight className="h-4 w-4" />
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
