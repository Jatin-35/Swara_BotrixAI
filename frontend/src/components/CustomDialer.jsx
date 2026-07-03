import { useState } from "react";
import { makeCall } from "../utils/api";
import { Phone, User, Building2, ChevronDown, ChevronUp, Loader2 } from "lucide-react";

export default function CustomDialer() {
    const [isOpen, setIsOpen] = useState(false);
    const [calling, setCalling] = useState(false);
    const [message, setMessage] = useState(null);

    // Form fields
    const [phoneNumber, setPhoneNumber] = useState("");
    const [customerName, setCustomerName] = useState("");
    const [companyName, setCompanyName] = useState("");

    const handleCall = async (e) => {
        e.preventDefault();

        if (!phoneNumber.trim()) {
            setMessage({ type: "error", text: "Phone number is required" });
            return;
        }

        setCalling(true);
        setMessage(null);

        try {
            console.log(`📞 Custom dial: ${phoneNumber} (${customerName || 'Unknown'})`);
            const result = await makeCall(phoneNumber, customerName, companyName);

            // Log full response for debugging
            console.log('📋 Full API Response:', JSON.stringify(result, null, 2));

            if (result.success) {
                // Show full response including Cube response & VAD Status
                const cubeResponse = result.response || 'No Cube response';
                const vadStatus = result.vad_status
                    ? `🧠 VAD: ${result.vad_status.status === 'connected' ? '✅ Connected' : '❌ ' + (result.vad_status.status || 'Unknown')}`
                    : '';

                setMessage({
                    type: "success",
                    text: `✅ Call initiated! ID: ${result.record_id || 'N/A'}\n\n📞 Cube Response: ${cubeResponse}\n\n${vadStatus}`
                });
                setPhoneNumber("");
                setCustomerName("");
                setCompanyName("");
            } else {
                // Show detailed error
                const errorDetails = result.details || result.error || "Unknown error";
                setMessage({
                    type: "error",
                    text: `❌ Failed: ${result.error}\n\nDetails: ${errorDetails}`
                });
            }
        } catch (error) {
            console.error('❌ Call error:', error);
            setMessage({ type: "error", text: `Network Error: ${error.message}` });
        } finally {
            setCalling(false);
        }
    };

    return (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-sm mb-4 border border-gray-200 dark:border-gray-700 overflow-hidden">
            {/* HEADER */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
            >
                <div className="flex items-center space-x-2">
                    <Phone className="h-4 w-4 text-green-600 dark:text-green-400" />
                    <span className="font-medium text-gray-900 dark:text-white text-sm">
                        Custom Dialer
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                        - Make manual calls
                    </span>
                </div>
                {isOpen ? (
                    <ChevronUp className="h-4 w-4 text-gray-400" />
                ) : (
                    <ChevronDown className="h-4 w-4 text-gray-400" />
                )}
            </button>

            {/* FORM - Compact Inline Layout */}
            {isOpen && (
                <div className="px-4 pb-4 border-t border-gray-200 dark:border-gray-700">
                    <form onSubmit={handleCall} className="mt-3">
                        <div className="flex flex-wrap gap-2 items-end">
                            {/* Phone */}
                            <div className="flex-1 min-w-[150px]">
                                <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">
                                    Phone <span className="text-red-500">*</span>
                                </label>
                                <div className="relative">
                                    <Phone className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                                    <input
                                        type="tel"
                                        placeholder="919876543210"
                                        value={phoneNumber}
                                        onChange={(e) => setPhoneNumber(e.target.value)}
                                        className="w-full pl-7 pr-2 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-green-500"
                                        required
                                    />
                                </div>
                            </div>

                            {/* Name */}
                            <div className="flex-1 min-w-[120px]">
                                <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">
                                    Name
                                </label>
                                <div className="relative">
                                    <User className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                                    <input
                                        type="text"
                                        placeholder="Customer name"
                                        value={customerName}
                                        onChange={(e) => setCustomerName(e.target.value)}
                                        className="w-full pl-7 pr-2 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-blue-500"
                                    />
                                </div>
                            </div>

                            {/* Company */}
                            <div className="flex-1 min-w-[120px]">
                                <label className="text-xs text-gray-500 dark:text-gray-400 mb-1 block">
                                    Company
                                </label>
                                <div className="relative">
                                    <Building2 className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400" />
                                    <input
                                        type="text"
                                        placeholder="Company name"
                                        value={companyName}
                                        onChange={(e) => setCompanyName(e.target.value)}
                                        className="w-full pl-7 pr-2 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-blue-500"
                                    />
                                </div>
                            </div>

                            {/* Call Button */}
                            <button
                                type="submit"
                                disabled={calling || !phoneNumber.trim()}
                                className="px-4 py-2 text-sm font-medium rounded-md text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                            >
                                {calling ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <Phone className="h-4 w-4" />
                                )}
                                {calling ? "Calling..." : "Call"}
                            </button>
                        </div>

                        {/* Message - with full response display */}
                        {message && (
                            <div className={`mt-2 p-3 rounded text-xs whitespace-pre-wrap break-words max-h-40 overflow-y-auto ${message.type === "success"
                                ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-800"
                                : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800"
                                }`}>
                                {message.text}
                            </div>
                        )}
                    </form>
                </div>
            )}
        </div>
    );
}
