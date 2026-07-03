import { Phone, Users, Clock, CheckCircle, XCircle, PhoneIncoming, PhoneOutgoing, FileText } from "lucide-react";

export default function DashboardStats({ data }) {
  // Safe destructuring with defaults
  if (!data || !data.summary) {
    return (
      <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-4 mb-8">
        <p className="text-sm text-yellow-800 dark:text-yellow-200">
          ⚠️ No summary data available
        </p>
      </div>
    );
  }

  const summary = data.summary || {};

  const formatDuration = (seconds) => {
    const totalSeconds = Math.floor(seconds || 0);
    const mins = Math.floor(totalSeconds / 60);
    const secs = String(totalSeconds % 60).padStart(2, "0");
    return `${mins}m ${secs}s`;
  };


  const formatPercentage = (value) => {
    return `${(value || 0).toFixed(1)}%`;
  };

  const stats = [
    {
      name: "Total Calls",
      value: summary.total_calls || 0,
      icon: Phone,
      color: "bg-blue-500",
    },
    {
      name: "Unique Callers",
      value: summary.unique_callers || 0,
      icon: Users,
      color: "bg-green-500",
    },
    {
      name: "Inbound Calls",
      value: summary.inbound_calls || 0,
      icon: PhoneIncoming,
      color: "bg-emerald-500",
    },
    {
      name: "Outbound Calls",
      value: summary.outbound_calls || 0,
      icon: PhoneOutgoing,
      color: "bg-cyan-500",
    },
    {
      name: "Completed Calls",
      value: summary.completed_calls || 0,
      icon: CheckCircle,
      color: "bg-green-600",
    },
    {
      name: "Failed Calls",
      value: summary.failed_calls || 0,
      icon: XCircle,
      color: "bg-red-500",
    },
    {
      name: "Avg Call Duration",
      value: formatDuration(summary.avg_duration_seconds),
      icon: Clock,
      color: "bg-purple-500",
    },
    {
      name: "Total Transcripts",
      value: (data?.data?.total_transcripts) || 0,
      icon: FileText,
      color: "bg-pink-500",
    }
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <div
            key={stat.name}
            className="
              bg-white dark:bg-gray-800 
              rounded-lg shadow-sm 
              p-6 
              border border-gray-200 dark:border-gray-700 
              transition-colors
            "
          >
            <div className="flex items-center">
              <div className={`${stat.color} rounded-lg p-3`}>
                <Icon className="h-6 w-6 text-white" />
              </div>

              <div className="ml-4 flex-1">
                <p className="text-sm font-medium text-gray-600 dark:text-gray-400">
                  {stat.name}
                </p>
                <p className="text-2xl font-semibold text-gray-900 dark:text-white">
                  {stat.value}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
